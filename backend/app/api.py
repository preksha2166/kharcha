"""HTTP API for the React app. See ARCHITECTURE.md section 7."""

import hmac
import json
import logging
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app import auth, clock
from app.ai import agent
from app.ai.client import AIFailed, AIRefused, AIUnavailable
from app.ai.extract import extract_document
from app.config import settings
from app.db import get_session, reset_db
from app.finance.budget import rule_category
from app.finance.csv_import import CsvError, parse_bank_csv
from app.finance.dates import add_months
from app.finance.loan import compare
from app.models import (AgentAction, Bill, Budget, Document, Dream, IncomeEvent, Loan, Mandate, Payment,
                        PushSubscription, Transaction, User)
from app.paypal import orders, vault, webhooks
from app.paypal.client import PayPalError, is_mock
from app.seed.demo_data import get_demo_user, seed_demo
from app.services.activity import log_action
from app.services import notify
from app.services.autopay import pay_bill
from app.services.daily import check_all_users, run_daily_check
from app.services.planner import build_snapshot, dreams_state, due_for_period, saving_dreams
from app import views

log = logging.getLogger("kharcha.api")
router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header[7:].strip() or None


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """The logged-in student. In demo mode, visitors who aren't logged in get the demo student."""
    token = _bearer(request)
    if token:
        user = auth.user_for_token(session, token)
        if user is None:
            raise HTTPException(401, "Your login has expired. Please log in again.")
        return user
    if settings.demo_mode:
        return get_demo_user(session) or seed_demo(session, clock.today(session))
    raise HTTPException(401, "Please log in.")


# ---------- login (Log in with PayPal) ----------

class LoginStartIn(BaseModel):
    state: str = Field(min_length=16, max_length=128)


class LoginFinishIn(BaseModel):
    code: str = Field(min_length=1, max_length=2000)


@router.get("/auth/config")
def auth_config():
    return {"demo_mode": settings.demo_mode, "mock": is_mock(), "redirect_uri": auth.redirect_uri()}


@router.post("/auth/paypal/start")
def login_start(body: LoginStartIn):
    """The PayPal login page URL. The app keeps `state` and checks it when PayPal sends the student back."""
    return {"url": auth.login_url(body.state)}


@router.post("/auth/paypal/finish")
def login_finish(body: LoginFinishIn, session: Session = Depends(get_session)):
    try:
        identity = auth.paypal_identity(body.code)
    except PayPalError as exc:
        raise HTTPException(400, f"PayPal login didn't work: {exc}") from exc
    except Exception as exc:  # network errors
        raise HTTPException(502, "Couldn't reach PayPal to finish logging in. Please try again.") from exc
    user, created = auth.find_or_create_user(session, identity)
    token = auth.start_session(session, user)
    if created:
        log_action(session, user_id=user.id, kind="info", on_date=clock.today(session), title="Welcome to Kharcha",
                   message="Start with three things: your money now, the money you get, and your bills.")
    return {"token": token, "new_user": created, "user": views.user_view(user)}


@router.post("/auth/logout")
def logout(request: Request, session: Session = Depends(get_session)):
    token = _bearer(request)
    if token:
        auth.end_session(session, token)
    return {"ok": True}


@router.get("/me")
def me(request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)):
    return {**views.user_view(user), "logged_in": _bearer(request) is not None}


# ---------- alerts: phone notifications and email ----------

class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: PushKeys


class PushRemoveIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)


def _alerts_view(session: Session, user: User) -> dict:
    devices = session.exec(select(PushSubscription).where(PushSubscription.user_id == user.id)).all()
    return {
        "push_public_key": notify.vapid_keys(session)[0],
        "push_devices": len(devices),
        "email": user.email,
        "notify_email": user.notify_email,
        "email_ready": settings.email_enabled,
    }


@router.get("/alerts")
def get_alerts(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return _alerts_view(session, user)


@router.post("/alerts/push")
def add_push_device(body: PushIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """The browser's push subscription after the student taps 'Turn on'."""
    if not body.endpoint.startswith("https://"):
        raise HTTPException(400, "That isn't a push subscription.")
    sub = session.exec(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)).first()
    if sub is None:
        sub = PushSubscription(user_id=user.id, endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth)
    else:
        sub.user_id, sub.p256dh, sub.auth = user.id, body.keys.p256dh, body.keys.auth
    session.add(sub)
    session.commit()
    return _alerts_view(session, user)


@router.post("/alerts/push/remove")
def remove_push_device(body: PushRemoveIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    sub = session.exec(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint,
                                                      PushSubscription.user_id == user.id)).first()
    if sub:
        session.delete(sub)
        session.commit()
    return _alerts_view(session, user)


@router.post("/alerts/test")
def test_alert(session: Session = Depends(get_session), user: User = Depends(current_user)):
    sent = notify.send(session, user, title="Kharcha alerts are on",
                       body="This is a test. You'll get alerts like 'Rent is due in 7 days' here.", url="/")
    if not sent["push"] and not sent["email"]:
        raise HTTPException(400, "Turn on phone alerts or email first.")
    return sent


# ---------- wake-up URL for a free timer service (e.g. cron-job.org) ----------

@router.api_route("/cron/daily-check", methods=["GET", "POST"])
def cron_daily_check(request: Request, key: str = "", session: Session = Depends(get_session)):
    """Free hosting sleeps when nobody visits. A free timer calls this every hour: it wakes the server
    and runs the daily check for every student, catching up any days that were missed."""
    given = request.headers.get("x-cron-secret") or key
    if not settings.cron_secret or not hmac.compare_digest(given.encode(), settings.cron_secret.encode()):
        raise HTTPException(403, "Wrong or missing key. Set CRON_SECRET and pass it as ?key= or X-Cron-Secret.")
    return {"ok": True, **check_all_users(session, clock.today(session))}


# ---------- health & dashboard ----------

@router.get("/health")
def health(session: Session = Depends(get_session)):
    return {"ok": True, "mode": views.mode(session)}


@router.get("/dashboard")
def dashboard(session: Session = Depends(get_session), user: User = Depends(current_user)):
    today = clock.today(session)
    return views.dashboard(session, build_snapshot(session, user, today))


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    current_money: float | None = None
    transfer_days_from_home: int | None = Field(default=None, ge=0, le=30)
    loan_set_aside_monthly: float | None = Field(default=None, ge=0)
    safety_cushion: float | None = Field(default=None, ge=0, le=10_000)
    email: str | None = Field(default=None, max_length=200)
    notify_email: bool | None = None


@router.patch("/user")
def update_user(body: UserUpdate, session: Session = Depends(get_session), user: User = Depends(current_user)):
    changes = body.model_dump(exclude_none=True)
    if "email" in changes:
        changes["email"] = changes["email"].strip() or None
        if changes["email"] and "@" not in changes["email"]:
            raise HTTPException(400, "That doesn't look like an email address.")
    if "current_money" in changes:
        user.balance_checked_on = clock.today(session)
    for k, v in changes.items():
        setattr(user, k, v)
    session.add(user)
    session.commit()
    return views.user_view(user)


class BalanceIn(BaseModel):
    current_money: float = Field(ge=-1_000_000, le=10_000_000)


@router.post("/user/balance")
def confirm_balance(body: BalanceIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """The weekly check-in: 'Is your balance still about $X?' Yes keeps it; a new number replaces it."""
    today = clock.today(session)
    old = user.current_money
    user.current_money = round(body.current_money, 2)
    user.balance_checked_on = today
    session.add(user)
    session.commit()
    diff = round(user.current_money - old, 2)
    if abs(diff) >= 0.01:
        sign = "+" if diff > 0 else "-"
        log_action(session, user_id=user.id, kind="info", on_date=today,
                   title=f"Balance updated: ${user.current_money:,.2f}",
                   message=f"You corrected it by {sign}${abs(diff):,.2f}. Every plan now uses the new number.")
    return views.user_view(user)


# ---------- bills & autopay permissions ----------

@router.get("/bills")
def list_bills(session: Session = Depends(get_session), user: User = Depends(current_user)):
    today = clock.today(session)
    return views.bills_view(session, build_snapshot(session, user, today))


class BillIn(BaseModel):
    name: str
    category: str = "other"
    payee_name: str
    payee_paypal_email: str
    amount: float = Field(gt=0)
    currency: str = "USD"
    recurrence: str = Field(pattern="^(monthly|once)$")
    due_day: int | None = Field(default=None, ge=1, le=31)
    due_date: date | None = None
    grace_days: int = Field(default=0, ge=0, le=31)
    late_fee: float = Field(default=0, ge=0)
    document_id: int | None = None
    pay_mode: str = Field(default="remind", pattern="^(remind|paypal)$")


def _create_bill(session: Session, user: User, body: BillIn, today: date) -> Bill:
    if body.recurrence == "monthly" and not body.due_day:
        raise HTTPException(400, "Monthly bills need due_day")
    if body.recurrence == "once" and not body.due_date:
        raise HTTPException(400, "One-time bills need due_date")
    if body.recurrence == "monthly":
        from app.finance.dates import monthly_due_date

        first = monthly_due_date(today.year, today.month, body.due_day)
        if first < today - timedelta(days=body.grace_days):
            first = add_months(first, 1, day=body.due_day)
        start = first
    else:
        start = body.due_date
    bill = Bill(user_id=user.id, start_date=start, **body.model_dump())
    session.add(bill)
    session.commit()
    session.refresh(bill)
    return bill


@router.post("/bills")
def create_bill(body: BillIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    bill = _create_bill(session, user, body, clock.today(session))
    return views.bill_base(bill)


class BillPatch(BaseModel):
    amount: float | None = Field(default=None, gt=0)
    payee_paypal_email: str | None = None
    payee_name: str | None = None
    grace_days: int | None = Field(default=None, ge=0, le=31)
    late_fee: float | None = Field(default=None, ge=0)
    active: bool | None = None
    pay_mode: str | None = Field(default=None, pattern="^(remind|paypal)$")


@router.patch("/bills/{bill_id}")
def patch_bill(bill_id: int, body: BillPatch, session: Session = Depends(get_session),
               user: User = Depends(current_user)):
    bill = _own_bill(session, user, bill_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(bill, k, v)
    session.add(bill)
    session.commit()
    return views.bill_base(bill)


def _own_bill(session: Session, user: User, bill_id: int) -> Bill:
    bill = session.get(Bill, bill_id)
    if not bill or bill.user_id != user.id:
        raise HTTPException(404, "Bill not found")
    return bill


class MandateIn(BaseModel):
    max_amount: float = Field(gt=0)
    earliest_days_before_due: int = Field(default=3, ge=0, le=15)
    latest_days_after_due: int | None = Field(default=None, ge=0, le=31)  # default: the bill's grace period
    valid_months: int = Field(default=6, ge=1, le=24)


@router.post("/bills/{bill_id}/mandate")
def set_mandate(bill_id: int, body: MandateIn, session: Session = Depends(get_session),
                user: User = Depends(current_user)):
    """The student sets (or replaces) the autopay permission for a bill. Only the student can do this."""
    bill = _own_bill(session, user, bill_id)
    today = clock.today(session)
    m = Mandate(
        user_id=user.id, bill_id=bill.id, payee_paypal_email=bill.payee_paypal_email, max_amount=body.max_amount,
        earliest_days_before_due=body.earliest_days_before_due,
        latest_days_after_due=bill.grace_days if body.latest_days_after_due is None else body.latest_days_after_due,
        valid_until=add_months(today, body.valid_months),
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    log_action(session, user_id=user.id, kind="info", on_date=today, bill_id=bill.id,
               title=f"Autopay set for {bill.name}",
               message=f"Up to ${m.max_amount:,.0f} to {bill.payee_name}, until {m.valid_until.isoformat()}.")
    return views.mandate_view(m)


class MandatePatch(BaseModel):
    paused: bool


@router.patch("/mandates/{mandate_id}")
def pause_mandate(mandate_id: int, body: MandatePatch, session: Session = Depends(get_session),
                  user: User = Depends(current_user)):
    m = session.get(Mandate, mandate_id)
    if not m or m.user_id != user.id:
        raise HTTPException(404, "Permission not found")
    m.paused = body.paused
    session.add(m)
    session.commit()
    return views.mandate_view(m)


# ---------- payments ----------

@router.post("/bills/{bill_id}/pay")
def pay_now(bill_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """The student taps 'Pay now'. Counts as their approval; safety rules still apply."""
    bill = _own_bill(session, user, bill_id)
    today = clock.today(session)
    item = build_snapshot(session, user, today).current.get(bill.id)
    if not item:
        raise HTTPException(400, "Nothing is due for this bill right now")
    result = pay_bill(session, user=user, bill=bill, period=item.period, due=item.due, today=today,
                      trigger="manual", user_approved=True, payment=item.pending_payment)
    return {"payment": views.payment_view(result.payment), "guard": result.decision.as_dict()}


class PaidIn(BaseModel):
    amount: float | None = Field(default=None, gt=0)


def _current_item(session: Session, user: User, bill: Bill):
    item = build_snapshot(session, user, clock.today(session)).current.get(bill.id)
    if not item:
        raise HTTPException(400, "Nothing is due for this bill right now.")
    return item


@router.post("/bills/{bill_id}/paid")
def mark_paid(bill_id: int, body: PaidIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """'I paid it': the student paid it themselves (bank, college portal, cash). Free, no PayPal."""
    bill = _own_bill(session, user, bill_id)
    item = _current_item(session, user, bill)
    today = clock.today(session)
    amount = round(body.amount or bill.amount, 2)
    if item.pending_payment is not None:
        item.pending_payment.status = "blocked"
        item.pending_payment.failure_reason = "You paid it yourself."
        session.add(item.pending_payment)
    p = Payment(user_id=user.id, bill_id=bill.id, period=item.period, amount=amount, status="completed",
                trigger="self", paid_on=today)
    user.current_money = round(user.current_money - amount, 2)
    session.add_all([p, user])
    session.commit()
    session.refresh(p)
    log_action(session, user_id=user.id, kind="payment", on_date=today, bill_id=bill.id, payment_id=p.id,
               title=f"You paid {bill.name} ${amount:,.0f} to {bill.payee_name}",
               message="Marked as paid by you. Kharcha took it out of your money and moved on to the next one.",
               allowed=True)
    return {"payment": views.payment_view(p), "current_money": user.current_money}


@router.post("/bills/{bill_id}/checkout")
def start_checkout(bill_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """'Pay with PayPal': a one-time payment the student approves on PayPal, straight to the payee."""
    bill = _own_bill(session, user, bill_id)
    item = _current_item(session, user, bill)
    if not bill.payee_paypal_email:
        raise HTTPException(400, "Add the payee's PayPal email to this bill first.")
    try:
        co = orders.create_checkout(
            amount=bill.amount, currency=bill.currency, payee_email=bill.payee_paypal_email,
            description=f"{bill.name} ({item.period})", reference_id=f"bill-{bill.id}-{item.period}",
            return_url=f"{settings.frontend_url}/paypal/paid", cancel_url=f"{settings.frontend_url}/paypal/paid?cancelled=1",
            request_id=f"kharcha-checkout-{bill.id}-{item.period}-{uuid.uuid4().hex[:8]}",
        )
    except PayPalError as exc:
        raise HTTPException(502, str(exc)) from exc
    p = Payment(user_id=user.id, bill_id=bill.id, period=item.period, amount=bill.amount, status="checkout",
                trigger="checkout", paypal_order_id=co["order_id"], mock=co["mock"])
    session.add(p)
    session.commit()
    return {"approve_url": co["approve_url"], "order_id": co["order_id"], "payment_id": p.id, "mock": co["mock"]}


class CheckoutIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)


def _checkout_payment(session: Session, user: User, order_id: str) -> Payment:
    p = session.exec(select(Payment).where(Payment.paypal_order_id == order_id, Payment.user_id == user.id)).first()
    if not p:
        raise HTTPException(404, "Payment not found")
    return p


@router.post("/payments/checkout/capture")
def finish_checkout(body: CheckoutIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """The student approved on PayPal and came back: take the payment (it goes straight to the payee)."""
    p = _checkout_payment(session, user, body.order_id)
    bill = session.get(Bill, p.bill_id)
    if p.status == "completed":
        return {"payment": views.payment_view(p), "current_money": user.current_money}
    if p.status != "checkout":
        raise HTTPException(400, f"This payment is {p.status}.")
    today = clock.today(session)
    try:
        cap = orders.capture_checkout(body.order_id, request_id=f"kharcha-capture-{body.order_id}")
    except PayPalError as exc:
        p.status, p.failure_reason = "failed", str(exc)
        session.add(p)
        session.commit()
        raise HTTPException(502, str(exc)) from exc
    if cap["status"] != "COMPLETED":
        p.status, p.failure_reason = "failed", f"PayPal says the payment is {cap['status']}."
        session.add(p)
        session.commit()
        raise HTTPException(402, p.failure_reason)
    p.status, p.paypal_capture_id, p.paid_on = "completed", cap["capture_id"], today
    user.current_money = round(user.current_money - p.amount, 2)
    session.add_all([p, user])
    session.commit()
    session.refresh(p)
    log_action(session, user_id=user.id, kind="payment", on_date=today, bill_id=bill.id, payment_id=p.id,
               title=f"Paid {bill.name} ${p.amount:,.0f} straight to {bill.payee_name}",
               message="You approved it on PayPal, and PayPal sent it directly to them. Kharcha never held the money."
               + (" (MOCK PayPal)" if p.mock else ""),
               allowed=True, details={"order_id": p.paypal_order_id, "capture_id": p.paypal_capture_id})
    return {"payment": views.payment_view(p), "current_money": user.current_money}


@router.post("/payments/checkout/cancel")
def cancel_checkout(body: CheckoutIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    p = _checkout_payment(session, user, body.order_id)
    if p.status == "checkout":
        p.status, p.failure_reason = "blocked", "You cancelled on PayPal."
        session.add(p)
        session.commit()
    return {"ok": True}


@router.post("/payments/{payment_id}/approve")
def approve_payment(payment_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    p = session.get(Payment, payment_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Payment not found")
    if p.status != "needs_approval":
        raise HTTPException(400, f"Payment is {p.status}, not waiting for approval")
    bill = session.get(Bill, p.bill_id)
    due = due_for_period(bill, p.period)
    today = clock.today(session)
    result = pay_bill(session, user=user, bill=bill, period=p.period, due=due, today=today,
                      trigger="manual", user_approved=True, payment=p)
    return {"payment": views.payment_view(result.payment), "guard": result.decision.as_dict()}


@router.post("/payments/{payment_id}/decline")
def decline_payment(payment_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    p = session.get(Payment, payment_id)
    if not p or p.user_id != user.id or p.status != "needs_approval":
        raise HTTPException(404, "No approval request with that id")
    p.status = "blocked"
    p.failure_reason = "You declined this payment."
    session.add(p)
    session.commit()
    log_action(session, user_id=user.id, kind="block", on_date=clock.today(session), bill_id=p.bill_id,
               payment_id=p.id, title="You declined a payment", message=p.failure_reason, allowed=False)
    return views.payment_view(p)


@router.get("/payments")
def list_payments(session: Session = Depends(get_session), user: User = Depends(current_user)):
    rows = session.exec(select(Payment).where(Payment.user_id == user.id).order_by(Payment.id.desc())).all()
    return [views.payment_view(p) for p in rows]


# ---------- PayPal connect (Vault) & webhooks ----------

class SetupTokenIn(BaseModel):
    return_path: str = "/paypal/return"
    cancel_path: str = "/paypal/cancel"


@router.post("/paypal/setup-token")
def paypal_setup_token(body: SetupTokenIn, user: User = Depends(current_user)):
    try:
        st = vault.create_setup_token(
            return_url=f"{settings.frontend_url}{body.return_path}",
            cancel_url=f"{settings.frontend_url}{body.cancel_path}",
            request_id=f"kharcha-setup-{user.id}-{uuid.uuid4().hex[:8]}",
        )
    except PayPalError as exc:
        raise HTTPException(502, str(exc)) from exc
    return st


class PaymentTokenIn(BaseModel):
    setup_token_id: str


@router.post("/paypal/payment-token")
def paypal_payment_token(body: PaymentTokenIn, session: Session = Depends(get_session),
                         user: User = Depends(current_user)):
    try:
        pt = vault.create_payment_token(setup_token_id=body.setup_token_id,
                                        request_id=f"kharcha-token-{body.setup_token_id}")
    except PayPalError as exc:
        raise HTTPException(502, str(exc)) from exc
    user.paypal_vault_id = pt["id"]
    user.paypal_customer_id = pt["customer_id"]
    user.paypal_payer_email = pt["payer_email"]
    user.paypal_connected_mock = pt["mock"]
    session.add(user)
    session.commit()
    log_action(session, user_id=user.id, kind="info", on_date=clock.today(session), title="PayPal connected",
               message="Your PayPal is saved. Kharcha can now pay bills inside the limits you set."
               + (" (MOCK PayPal)" if pt["mock"] else ""))
    return views.user_view(user)


@router.post("/paypal/disconnect")
def paypal_disconnect(session: Session = Depends(get_session), user: User = Depends(current_user)):
    user.paypal_vault_id = None
    user.paypal_customer_id = None
    user.paypal_payer_email = None
    user.paypal_connected_mock = False
    session.add(user)
    session.commit()
    return views.user_view(user)


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, session: Session = Depends(get_session)):
    event = await request.json()
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        if not webhooks.verify(headers, event):
            raise HTTPException(400, "Webhook signature not verified")
    except PayPalError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"result": webhooks.handle_event(session, event)}


# ---------- documents (AI extraction) ----------

@router.post("/documents")
async def upload_document(file: UploadFile = File(...), kind: str = Form("auto"),
                          session: Session = Depends(get_session), user: User = Depends(current_user)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 20 MB")
    mime = file.content_type or "application/octet-stream"
    name = file.filename or "document"
    if name.lower().endswith(".pdf"):
        mime = "application/pdf"
    try:
        extracted, mock = extract_document(data, mime, name, clock.today(session))
    except AIRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except AIFailed as exc:
        raise HTTPException(502, str(exc)) from exc
    doc = Document(user_id=user.id, kind=extracted.get("document_type", kind), filename=name,
                   extracted_json=json.dumps(extracted), mock=mock)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    log_action(session, user_id=user.id, kind="info", on_date=clock.today(session),
               title=f"Read {name}", message=extracted.get("summary", ""),
               details={"document_id": doc.id, "mock": mock, "warnings": extracted.get("warnings", [])})
    return {"id": doc.id, "filename": name, "mock": mock, "extraction": extracted}


class ConfirmBill(BaseModel):
    bill: BillIn
    autopay_max_amount: float | None = Field(default=None, gt=0)


class ConfirmLoan(BaseModel):
    lender: str
    principal: float = Field(gt=0)
    currency: str = "INR"
    annual_rate: float = Field(gt=0, lt=50)
    interest_type: str = Field(default="simple", pattern="^(simple|compound)$")
    disbursed_date: date
    repayment_start: date
    term_months: int = Field(gt=0, le=360)


class ConfirmIn(BaseModel):
    bill: ConfirmBill | None = None
    loan: ConfirmLoan | None = None


@router.post("/documents/{doc_id}/confirm")
def confirm_document(doc_id: int, body: ConfirmIn, session: Session = Depends(get_session),
                     user: User = Depends(current_user)):
    """The student has checked (and maybe fixed) every field. Only now do we create anything."""
    doc = session.get(Document, doc_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(404, "Document not found")
    today = clock.today(session)
    out: dict = {}
    if body.bill:
        b = body.bill.bill.model_copy(update={"document_id": doc.id})
        bill = _create_bill(session, user, b, today)
        out["bill"] = views.bill_base(bill)
        if body.bill.autopay_max_amount:
            out["autopay"] = set_mandate(bill.id, MandateIn(max_amount=body.bill.autopay_max_amount), session, user)
    if body.loan:
        for old in session.exec(select(Loan).where(Loan.user_id == user.id)).all():
            session.delete(old)
        loan = Loan(user_id=user.id, document_id=doc.id, **body.loan.model_dump())
        session.add(loan)
        session.commit()
        out["loan"] = views.loan_card(session, user.id, today)
    doc.status = "confirmed"
    session.add(doc)
    session.commit()
    return out


# ---------- spending & budgets ----------

@router.get("/transactions")
def list_transactions(days: int = 60, session: Session = Depends(get_session), user: User = Depends(current_user)):
    today = clock.today(session)
    start = today - timedelta(days=days)
    rows = session.exec(select(Transaction).where(Transaction.user_id == user.id, Transaction.date >= start)
                        .order_by(Transaction.date.desc(), Transaction.id.desc())).all()
    return [_tx_view(t) for t in rows]


class TransactionIn(BaseModel):
    merchant: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0, le=100_000)
    spent_on: date | None = None
    category: str | None = Field(default=None, max_length=40)
    is_need: bool | None = None


def _counts_toward_balance(user: User, on: date, *, from_bank_file: bool) -> bool:
    """Spending lowers your money unless it happened before your last balance check (then your
    balance already includes it). A bank file's rows from the check day itself are already in it too."""
    if user.balance_checked_on is None:
        return True
    return on > user.balance_checked_on if from_bank_file else on >= user.balance_checked_on


def _add_spending(session: Session, user: User, *, on: date, merchant: str, amount: float, source: str,
                  category: str | None = None, is_need: bool | None = None) -> Transaction:
    rule_cat, rule_need = rule_category(merchant)
    counted = _counts_toward_balance(user, on, from_bank_file=source == "csv")
    t = Transaction(user_id=user.id, date=on, merchant=merchant.strip(), category=category or rule_cat,
                    amount=round(amount, 2), source=source, is_need=rule_need if is_need is None else is_need,
                    counted_in_balance=counted)
    if counted:
        user.current_money = round(user.current_money - t.amount, 2)
        session.add(user)
    session.add(t)
    return t


def _tx_view(t: Transaction) -> dict:
    return {"id": t.id, "date": t.date.isoformat(), "merchant": t.merchant, "category": t.category,
            "amount": t.amount, "source": t.source, "is_need": t.is_need, "counted_in_balance": t.counted_in_balance}


@router.post("/transactions")
def add_transaction(body: TransactionIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Spending the student types in. It lowers their money right away, so every plan stays right."""
    today = clock.today(session)
    on = body.spent_on or today
    if on > today:
        raise HTTPException(400, "Spending can't be in the future.")
    t = _add_spending(session, user, on=on, merchant=body.merchant, amount=body.amount, source="manual",
                      category=body.category, is_need=body.is_need)
    session.commit()
    session.refresh(t)
    return {"transaction": _tx_view(t), "current_money": user.current_money}


MAX_CSV_BYTES = 2 * 1024 * 1024


@router.post("/transactions/import")
async def import_transactions(file: UploadFile = File(...), session: Session = Depends(get_session),
                              user: User = Depends(current_user)):
    """A bank's CSV export. Rows already imported are skipped, so importing twice is safe."""
    data = await file.read()
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(413, "The file is larger than 2 MB.")
    try:
        parsed = parse_bank_csv(data)
    except CsvError as exc:
        raise HTTPException(400, str(exc)) from exc
    today = clock.today(session)
    have = {(t.date, t.merchant.lower(), round(t.amount, 2)) for t in session.exec(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.source == "csv")).all()}
    before = user.current_money
    added = duplicates = future = 0
    for row in parsed.rows:
        key = (row.on, row.merchant.lower(), row.amount)
        if row.on > today:
            future += 1
            continue
        if key in have:
            duplicates += 1
            continue
        have.add(key)
        _add_spending(session, user, on=row.on, merchant=row.merchant, amount=row.amount, source="csv")
        added += 1
    session.commit()
    change = round(user.current_money - before, 2)
    if added:
        log_action(session, user_id=user.id, kind="info", on_date=today, title=f"Imported {added} purchases",
                   message=(f"Your money went down by ${-change:,.2f} for spending after your last balance check."
                            if change < 0 else "They were all from before your last balance check, so your balance stays."))
    return {"added": added, "duplicates": duplicates, "skipped_income": parsed.skipped_income,
            "skipped_unreadable": parsed.skipped_bad + future, "money_change": change, "current_money": user.current_money}


@router.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    t = session.get(Transaction, tx_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "Transaction not found")
    if t.source not in {"manual", "csv"}:
        raise HTTPException(400, "Only spending you added or imported can be deleted.")
    if t.counted_in_balance:
        user.current_money = round(user.current_money + t.amount, 2)
        session.add(user)
    session.delete(t)
    session.commit()
    return {"ok": True, "current_money": user.current_money}


class TransactionPatch(BaseModel):
    category: str | None = None
    is_need: bool | None = None


@router.patch("/transactions/{tx_id}")
def patch_transaction(tx_id: int, body: TransactionPatch, session: Session = Depends(get_session),
                      user: User = Depends(current_user)):
    t = session.get(Transaction, tx_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "Transaction not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    session.add(t)
    session.commit()
    return {"id": t.id, "category": t.category, "is_need": t.is_need}


class BudgetIn(BaseModel):
    category: str
    weekly_limit: float = Field(ge=0)


@router.put("/budgets")
def put_budgets(body: list[BudgetIn], session: Session = Depends(get_session), user: User = Depends(current_user)):
    for old in session.exec(select(Budget).where(Budget.user_id == user.id)).all():
        session.delete(old)
    for b in body:
        session.add(Budget(user_id=user.id, category=b.category, weekly_limit=b.weekly_limit))
    session.commit()
    return views.budgets_view(session, user.id, clock.today(session))


# ---------- loan ----------

@router.get("/loan")
def get_loan(session: Session = Depends(get_session), user: User = Depends(current_user)):
    today = clock.today(session)
    loan = session.exec(select(Loan).where(Loan.user_id == user.id)).first()
    if not loan:
        return None
    from app.finance.loan import analyze

    r = analyze(views.loan_spec(loan), today)
    return {**views.loan_card(session, user.id, today), "analysis": r.__dict__,
            "disbursed_date": loan.disbursed_date.isoformat(), "term_months": loan.term_months,
            "interest_type": loan.interest_type}


class ScenarioIn(BaseModel):
    monthly_payment: float = Field(ge=0)


@router.post("/loan/scenario")
def loan_scenario(body: ScenarioIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    loan = session.exec(select(Loan).where(Loan.user_id == user.id)).first()
    if not loan:
        raise HTTPException(404, "No loan on file")
    c = compare(views.loan_spec(loan), clock.today(session), body.monthly_payment)
    return {"baseline": c["baseline"].__dict__, "scenario": c["scenario"].__dict__, "savings": c["savings"],
            "monthly_payment_drop": c["monthly_payment_drop"], "currency": loan.currency,
            "fx_inr_per_usd": settings.fx_inr_per_usd}


# ---------- dreams (saving for things you want) ----------

class DreamIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    target_amount: float = Field(gt=0, le=1_000_000)
    target_date: date | None = None
    emoji: str | None = Field(default=None, max_length=8)
    saved_amount: float = Field(default=0, ge=0)


class DreamPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    target_amount: float | None = Field(default=None, gt=0, le=1_000_000)
    target_date: date | None = None
    emoji: str | None = Field(default=None, max_length=8)
    saved_amount: float | None = Field(default=None, ge=0)
    paused: bool | None = None


class MoveIn(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


class BoughtIn(BaseModel):
    price: float | None = Field(default=None, gt=0)


def _dream(session: Session, user: User, dream_id: int) -> Dream:
    d = session.get(Dream, dream_id)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "Dream not found")
    return d


def _check_saved(session: Session, user: User, saved: float, skip_id: int | None = None) -> None:
    """You can't mark more money as saved than you have."""
    others = sum(d.saved_amount for d in saving_dreams(session, user.id) if d.id != skip_id)
    if saved > 0 and others + saved > user.current_money + 0.005:
        free = max(0.0, user.current_money - others)
        raise HTTPException(400, f"You have ${user.current_money:,.0f} and ${others:,.0f} is already saved for other "
                                 f"dreams, so at most ${free:,.0f} more can be marked as saved.")


def _next_priority(session: Session, user: User) -> int:
    return max([d.priority for d in saving_dreams(session, user.id)], default=0) + 1


def _set_reached(d: Dream) -> None:
    if d.status in {"active", "reached"}:
        d.status = "reached" if d.saved_amount >= d.target_amount else "active"


def _dreams_out(session: Session, user: User) -> dict:
    return views.dreams_view(session, build_snapshot(session, user, clock.today(session)))


def _log_new_dream(session: Session, user: User, d: Dream) -> None:
    log_action(session, user_id=user.id, kind="dream", on_date=clock.today(session), title=f"New dream: {d.emoji} {d.name}",
               message=f"Saving for {d.name} (${d.target_amount:,.0f}). Kharcha sets money aside every Monday from what's spare.")


def create_dream(session: Session, user: User, body: DreamIn, *, status: str = "active") -> Dream:
    today = clock.today(session)
    if body.target_date and body.target_date <= today:
        raise HTTPException(400, "Pick a date in the future (or leave it empty).")
    saved = min(body.saved_amount, body.target_amount)
    _check_saved(session, user, saved)
    d = Dream(user_id=user.id, name=body.name.strip(), emoji=(body.emoji or "").strip() or "⭐",
              target_amount=round(body.target_amount, 2), saved_amount=round(saved, 2), target_date=body.target_date,
              priority=_next_priority(session, user), status=status)
    _set_reached(d)
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


@router.get("/dreams")
def list_dreams(session: Session = Depends(get_session), user: User = Depends(current_user)):
    return _dreams_out(session, user)


@router.post("/dreams")
def add_dream(body: DreamIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    d = create_dream(session, user, body)
    _log_new_dream(session, user, d)
    return _dreams_out(session, user)


@router.patch("/dreams/{dream_id}")
def edit_dream(dream_id: int, body: DreamPatch, session: Session = Depends(get_session), user: User = Depends(current_user)):
    d = _dream(session, user, dream_id)
    if d.status == "bought":
        raise HTTPException(400, "This dream is already bought.")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("target_date") and changes["target_date"] <= clock.today(session):
        raise HTTPException(400, "Pick a date in the future (or leave it empty).")
    if changes.get("saved_amount") is not None:
        _check_saved(session, user, changes["saved_amount"], skip_id=d.id)
    paused = changes.pop("paused", None)
    for k, v in changes.items():
        if v is None and k != "target_date":
            continue  # only the date can be cleared
        setattr(d, k, v.strip() if isinstance(v, str) else v)
    d.saved_amount = round(min(d.saved_amount, d.target_amount), 2)
    if paused is True and d.status in {"active", "reached"}:
        d.status = "paused"
    elif paused is False and d.status == "paused":
        d.status = "active"
    _set_reached(d)
    session.add(d)
    session.commit()
    return _dreams_out(session, user)


@router.post("/dreams/{dream_id}/confirm")
def confirm_dream(dream_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """The student taps 'Save dream' on a suggestion from Ask Kharcha."""
    d = _dream(session, user, dream_id)
    if d.status != "proposed":
        raise HTTPException(400, "This dream is already saved.")
    _check_saved(session, user, d.saved_amount, skip_id=d.id)
    d.priority = _next_priority(session, user)  # before it counts as saving, so its own placeholder isn't the max
    d.status = "active"
    _set_reached(d)
    session.add(d)
    session.commit()
    _log_new_dream(session, user, d)
    return _dreams_out(session, user)


@router.post("/dreams/{dream_id}/move")
def move_dream(dream_id: int, body: MoveIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    rows = saving_dreams(session, user.id)
    ids = [d.id for d in rows]
    if dream_id not in ids:
        raise HTTPException(404, "Dream not found")
    i = ids.index(dream_id)
    j = i - 1 if body.direction == "up" else i + 1
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
    for n, d in enumerate(rows, start=1):
        d.priority = n
        session.add(d)
    session.commit()
    return _dreams_out(session, user)


@router.post("/dreams/{dream_id}/bought")
def dream_bought(dream_id: int, body: BoughtIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """The student bought it: the money leaves their account and the dream is done."""
    d = _dream(session, user, dream_id)
    if d.status not in {"active", "paused", "reached"}:
        raise HTTPException(400, "Only a saved dream can be marked as bought.")
    price = round(body.price or d.target_amount, 2)
    if price > user.current_money + 0.005:
        raise HTTPException(400, f"That's more than the ${user.current_money:,.0f} Kharcha thinks you have.")
    today = clock.today(session)
    user.current_money = round(user.current_money - price, 2)
    d.status, d.bought_on, d.bought_price = "bought", today, price
    session.add_all([user, d])
    session.commit()
    extra = price - d.saved_amount
    note = f" It cost ${extra:,.0f} more than you'd saved, so that came from your spending money." if extra > 0.5 else ""
    log_action(session, user_id=user.id, kind="dream", on_date=today, title=f"Dream come true: {d.emoji} {d.name}",
               message=f"You bought {d.name} for ${price:,.0f}.{note}", details={"price": price, "saved": d.saved_amount})
    return _dreams_out(session, user)


@router.delete("/dreams/{dream_id}")
def delete_dream(dream_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    d = _dream(session, user, dream_id)
    was_saving = d.status in {"active", "paused", "reached"} and d.saved_amount > 0
    name, saved = d.name, d.saved_amount
    session.delete(d)
    session.commit()
    if was_saving:
        log_action(session, user_id=user.id, kind="dream", on_date=clock.today(session), title=f"Removed dream: {name}",
                   message=f"The ${saved:,.0f} saved for it is back in your spending money.")
    return _dreams_out(session, user)


# ---------- expected money (e.g. a transfer you asked family for) ----------

class ExpectedMoneyIn(BaseModel):
    label: str = Field(default="Transfer from home", min_length=1, max_length=60)
    amount: float = Field(gt=0, le=1_000_000)
    arrives_on: date  # the (next) day it arrives
    recurrence: str = Field(default="once", pattern="^(once|monthly|biweekly)$")


def _income_view(ev: IncomeEvent) -> dict:
    return {"id": ev.id, "label": ev.label, "amount": ev.amount, "recurrence": ev.recurrence,
            "arrives_on": ev.start_date.isoformat(), "last_received": ev.last_received.isoformat() if ev.last_received else None}


@router.get("/incomes")
def list_incomes(session: Session = Depends(get_session), user: User = Depends(current_user)):
    rows = session.exec(select(IncomeEvent).where(IncomeEvent.user_id == user.id).order_by(IncomeEvent.id)).all()
    return [_income_view(ev) for ev in rows]


@router.post("/incomes")
def add_expected_money(body: ExpectedMoneyIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Money the student expects: once (a transfer they asked family for) or regular (money from home,
    a paycheck), so the plan and the bills-first check can count on it."""
    today = clock.today(session)
    if body.arrives_on < today:
        raise HTTPException(400, "Pick today or a later date.")
    label = body.label.strip()
    ev = IncomeEvent(user_id=user.id, label=label, amount=round(body.amount, 2), start_date=body.arrives_on,
                     recurrence=body.recurrence)
    session.add(ev)
    session.commit()
    session.refresh(ev)
    when = body.arrives_on.strftime("%b %d").replace(" 0", " ")
    every = {"monthly": " every month", "biweekly": " every two weeks"}.get(body.recurrence, "")
    log_action(session, user_id=user.id, kind="info", on_date=today, title=f"Expecting {label}: +${body.amount:,.0f}{every}",
               message=f"Kharcha now plans with this money, starting {when}.")
    return _income_view(ev)


@router.delete("/incomes/{income_id}")
def delete_income(income_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    ev = session.get(IncomeEvent, income_id)
    if not ev or ev.user_id != user.id:
        raise HTTPException(404, "Income not found")
    session.delete(ev)
    session.commit()
    return {"ok": True}


# ---------- chat (agent) & activity ----------

class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


@router.post("/chat")
def chat(body: ChatIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    if body.messages[-1].role != "user":
        raise HTTPException(400, "Last message must be from the user")
    today = clock.today(session)
    try:
        result = agent.chat(session, user, today, [m.model_dump() for m in body.messages])
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except AIFailed as exc:
        raise HTTPException(502, str(exc)) from exc
    log_action(session, user_id=user.id, kind="chat", on_date=today, title="Ask Kharcha",
               message=result["reply"][:500], details={"question": body.messages[-1].content[:500],
                                                       "tools_used": result["tools_used"]})
    result["dream_proposals"] = _dream_proposals(session, user, today, result.get("dream_ids", []))
    return result


def _dream_proposals(session: Session, user: User, today: date, ids: list[int]) -> list[dict]:
    """Suggested dreams from the chat, each with Kharcha's plan, for the 'Save dream' cards."""
    out = []
    snap = build_snapshot(session, user, today) if ids else None
    for dream_id in ids:
        d = session.get(Dream, dream_id)
        if d and d.user_id == user.id and d.status == "proposed":
            state = dreams_state(session, user, today, snap.points, snap.items, extra=d)
            out.append(views.dream_view(d, state.plans.get(d.id)))
    return out


@router.get("/activity")
def activity(limit: int = 100, session: Session = Depends(get_session), user: User = Depends(current_user)):
    rows = session.exec(select(AgentAction).where(AgentAction.user_id == user.id)
                        .order_by(AgentAction.id.desc()).limit(min(limit, 500))).all()
    return [views.action_view(a) for a in rows]


# ---------- demo clock ----------

class AdvanceIn(BaseModel):
    days: int = Field(default=1, ge=1, le=60)


def _require_demo():
    if not settings.demo_mode:
        raise HTTPException(403, "Demo mode is off")


@router.post("/demo/advance-days")
def advance_days(body: AdvanceIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Move the demo clock forward one day at a time, running the daily check for each day."""
    _require_demo()
    state = clock.get_state(session)
    before = session.exec(select(AgentAction.id).where(AgentAction.user_id == user.id)
                          .order_by(AgentAction.id.desc())).first() or 0
    for _ in range(body.days):
        state.demo_offset_days += 1
        session.add(state)
        session.commit()
        run_daily_check(session, user, clock.today(session))
        session.refresh(user)
    new = session.exec(select(AgentAction).where(AgentAction.user_id == user.id, AgentAction.id > before)
                       .order_by(AgentAction.id)).all()
    return {"today": clock.today(session).isoformat(), "new_activity": [views.action_view(a) for a in new]}


@router.post("/demo/run-check")
def run_check(session: Session = Depends(get_session), user: User = Depends(current_user)):
    _require_demo()
    run_daily_check(session, user, clock.today(session))
    return {"ok": True}


@router.post("/demo/reset")
def demo_reset(session: Session = Depends(get_session)):
    _require_demo()
    session.close()
    reset_db()
    from app.db import engine

    with Session(engine) as fresh:
        user = seed_demo(fresh, clock.real_today())
        run_daily_check(fresh, user, clock.today(fresh))
    return {"ok": True}
