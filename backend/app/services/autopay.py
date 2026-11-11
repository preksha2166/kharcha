"""Paying a bill: guard check -> charge saved PayPal (Orders) -> pay the payee (Payouts) -> log.

The AI never calls this with user_approved=True. Only a human tap in the UI does.
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from app.guard.mandates import Decision, check_payment
from app.models import Bill, Payment, User
from app.paypal import orders, payouts
from app.paypal.client import PayPalError, is_mock
from app.services.activity import log_action
from app.services.planner import PAID_STATUSES, active_mandate, mandate_spec


log = logging.getLogger("kharcha.autopay")

# Payout statuses that can still change, so Kharcha keeps asking PayPal about them.
PAYOUT_WAITING = {"PENDING", "PROCESSING", "NEW", "ONHOLD", "UNCLAIMED"}
# Final statuses that mean the payee did NOT get the money.
PAYOUT_PROBLEMS = {"FAILED", "RETURNED", "BLOCKED", "DENIED", "REFUNDED", "REVERSED", "CANCELED"}


@dataclass
class PayResult:
    payment: Payment
    decision: Decision


def _money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


def _attempt_number(session: Session, bill_id: int, period: str) -> int:
    rows = session.exec(select(Payment).where(Payment.bill_id == bill_id, Payment.period == period)).all()
    return len(rows) + 1


def request_approval(
    session: Session, *, user: User, bill: Bill, period: str, due: date, today: date,
    trigger: str, decision: Decision, note: str = "",
) -> Payment:
    """Create (or reuse) a 'needs your approval' payment the student can tap to approve."""
    existing = session.exec(
        select(Payment).where(
            Payment.bill_id == bill.id, Payment.period == period, Payment.status == "needs_approval"
        )
    ).first()
    if existing:
        return existing
    payment = Payment(
        user_id=user.id, bill_id=bill.id, period=period, amount=bill.amount,
        status="needs_approval", trigger=trigger, failure_reason=decision.reason,
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)
    log_action(
        session, user_id=user.id, kind="approval", on_date=today, bill_id=bill.id, payment_id=payment.id,
        title=f"Needs your OK: {bill.name} {_money(bill.amount)}",
        message=note or decision.reason, allowed=False, reason=decision.reason,
        dedupe_key=f"approval:{bill.id}:{period}", details=decision.as_dict(),
    )
    return payment


def pay_bill(
    session: Session,
    *,
    user: User,
    bill: Bill,
    period: str,
    due: date,
    today: date,
    trigger: str = "autopay",  # autopay | manual | agent
    user_approved: bool = False,
    payment: Payment | None = None,  # an existing needs_approval payment being approved
) -> PayResult:
    mandate = active_mandate(session, bill.id)
    already = any(
        p.status in PAID_STATUSES
        for p in session.exec(select(Payment).where(Payment.bill_id == bill.id, Payment.period == period)).all()
    )
    decision = check_payment(
        bill_payee_email=bill.payee_paypal_email,
        amount=bill.amount,
        pay_date=today,
        due_date=due,
        mandate=mandate_spec(mandate),
        already_paid=already,
        has_saved_paypal=bool(user.paypal_vault_id),
        money_available=user.current_money,
        cushion=user.safety_cushion,
        user_approved=user_approved,
    )

    if not decision.allowed:
        # Safety rules (no PayPal, already paid) can't be fixed by approving.
        fixable = decision.code in {"mandate_active", "within_limit", "in_window", "not_expired", "no_overdraft", "payee_matches"}
        if fixable and not user_approved:
            p = request_approval(session, user=user, bill=bill, period=period, due=due, today=today,
                                 trigger=trigger, decision=decision)
            log_action(
                session, user_id=user.id, kind="block", on_date=today, bill_id=bill.id, payment_id=p.id,
                title=f"Guard blocked {bill.name} {_money(bill.amount)}", message=decision.reason,
                allowed=False, reason=decision.reason, dedupe_key=f"block:{bill.id}:{period}:{decision.code}",
                details=decision.as_dict(),
            )
            return PayResult(p, decision)
        blocked = payment or Payment(user_id=user.id, bill_id=bill.id, period=period, amount=bill.amount,
                                     status="blocked", trigger=trigger)
        blocked.status = "blocked"
        blocked.failure_reason = decision.reason
        session.add(blocked)
        session.commit()
        session.refresh(blocked)
        log_action(session, user_id=user.id, kind="block", on_date=today, bill_id=bill.id, payment_id=blocked.id,
                   title=f"Can't pay {bill.name}", message=decision.reason, allowed=False, reason=decision.reason,
                   details=decision.as_dict())
        return PayResult(blocked, decision)

    attempt = _attempt_number(session, bill.id, period)
    request_id = f"kharcha-{bill.id}-{period}-{attempt}"
    if payment is None:
        payment = Payment(user_id=user.id, bill_id=bill.id, period=period, amount=bill.amount, trigger=trigger, status="processing")
    payment.status = "processing"
    payment.mandate_id = mandate.id if mandate else None
    payment.request_id = request_id
    payment.mock = is_mock()
    payment.failure_reason = None
    session.add(payment)
    session.commit()
    session.refresh(payment)

    try:
        charge = orders.charge_saved_paypal(
            vault_id=user.paypal_vault_id,
            amount=bill.amount,
            currency=bill.currency,
            description=f"{bill.name} ({period})",
            reference_id=f"bill-{bill.id}-{period}",
            request_id=request_id,
        )
        payment.paypal_order_id = charge["order_id"]
        payment.paypal_capture_id = charge["capture_id"]
        if charge["status"] != "COMPLETED":
            raise PayPalError(402, f"Charge not completed (status {charge['status']})")

        payout = payouts.send_payout(
            receiver_email=bill.payee_paypal_email,
            amount=bill.amount,
            currency=bill.currency,
            note=f"{bill.name} for {period}, paid by {user.name} via Kharcha",
            sender_batch_id=f"{request_id}-payout",
        )
        payment.payout_batch_id = payout["batch_id"]
        payment.payout_status = payout["batch_status"]
        payment.status = "completed"
        payment.paid_on = today
        user.current_money = round(user.current_money - bill.amount, 2)
        session.add(user)
    except PayPalError as exc:
        payment.status = "failed"
        payment.failure_reason = str(exc)
    session.add(payment)
    session.commit()
    session.refresh(payment)

    if payment.status == "completed":
        how = "you approved it" if user_approved else "it was inside your autopay limits"
        log_action(
            session, user_id=user.id, kind="payment", on_date=today, bill_id=bill.id, payment_id=payment.id,
            title=f"Paid {bill.name} {_money(bill.amount)} to {bill.payee_name}",
            message=f"Paid with your saved PayPal because {how}." + (" (MOCK PayPal)" if payment.mock else ""),
            allowed=True, reason=decision.reason, details={**decision.as_dict(), "order_id": payment.paypal_order_id,
                                                         "payout_batch_id": payment.payout_batch_id},
        )
    else:
        log_action(
            session, user_id=user.id, kind="block", on_date=today, bill_id=bill.id, payment_id=payment.id,
            title=f"PayPal payment failed: {bill.name}", message=payment.failure_reason or "Unknown error",
            allowed=False, reason=payment.failure_reason,
        )
    return PayResult(payment, decision)


def refresh_payouts(session: Session, user: User, today: date) -> None:
    """Ask PayPal how each unfinished payout is doing. Webhooks do this for a deployed app,
    but PayPal can't reach a laptop, so the daily check asks instead."""
    waiting = session.exec(select(Payment).where(
        Payment.user_id == user.id,
        Payment.payout_batch_id.is_not(None),
        Payment.payout_status.in_(PAYOUT_WAITING),
    )).all()
    for payment in waiting:
        try:
            result = payouts.get_payout(payment.payout_batch_id)
        except Exception as exc:  # network or API errors must never break the daily check
            log.warning("Couldn't check payout %s: %s", payment.payout_batch_id, exc)
            continue
        status = result.get("item_status") or result.get("batch_status")
        if not status or status == payment.payout_status:
            continue

        payment.payout_status = status
        bill = session.get(Bill, payment.bill_id)
        payee = bill.payee_name if bill else "The payee"
        what = bill.name if bill else "this bill"
        if status in PAYOUT_PROBLEMS:
            payment.failure_reason = f"PayPal couldn't deliver the money to {payee} (status {status})."
        session.add(payment)
        session.commit()

        common = dict(user_id=user.id, on_date=today, bill_id=payment.bill_id, payment_id=payment.id,
                      dedupe_key=f"payout:{payment.id}:{status}", details={"payout_batch_id": payment.payout_batch_id,
                                                                            "payout_status": status})
        if status == "SUCCESS":
            log_action(session, kind="payment", title=f"{payee} received {_money(payment.amount)}",
                       message=f"PayPal confirmed the money for {what} reached {payee}.", **common)
        elif status in PAYOUT_PROBLEMS:
            log_action(session, kind="block", title=f"{payee} didn't get the money for {what}",
                       message=payment.failure_reason + " Check the payee's PayPal email on the Bills page.",
                       allowed=False, reason=payment.failure_reason, **common)
        elif status == "UNCLAIMED":
            log_action(session, kind="info", title=f"{payee} hasn't claimed {_money(payment.amount)} yet",
                       message="That email has no PayPal account yet. PayPal returns the money if it isn't "
                               "claimed within 30 days.", **common)
