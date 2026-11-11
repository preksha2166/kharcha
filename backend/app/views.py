"""Turn database rows and snapshots into the JSON the React app reads."""

import json
import math
from datetime import date

from sqlmodel import Session, select

from app.ai.client import enabled as ai_enabled
from app.clock import get_state
from app.config import settings
from app.finance.budget import SpendItem, weekly_status
from app.finance.dreams import DreamPlan, next_save_day, plan_dreams, room_per_week
from app.finance.loan import LoanSpec, analyze
from app.models import AgentAction, Bill, Budget, Dream, IncomeEvent, Loan, Payment, Transaction, User
from app.services.planner import PlannedItem, Snapshot, active_mandate, dream_spec, short_bill_text, tight_because


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def mode(session: Session) -> dict:
    return {
        "paypal": settings.paypal_mode,
        "ai": "on" if ai_enabled() else "off",
        "demo": settings.demo_mode,
        "demo_offset_days": get_state(session).demo_offset_days,
        "fx_inr_per_usd": settings.fx_inr_per_usd,
        "paypal_fee_percent": settings.paypal_fee_percent,
        "paypal_fee_fixed": settings.paypal_fee_fixed,
    }


def user_view(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "is_demo": u.is_demo,
        "logged_in_with_paypal": bool(u.paypal_login_id),
        "safety_cushion": u.safety_cushion,
        "balance_checked_on": iso(u.balance_checked_on),
        "notify_email": u.notify_email,
        "current_money": u.current_money,
        "transfer_days_from_home": u.transfer_days_from_home,
        "loan_set_aside_monthly": u.loan_set_aside_monthly,
        "paypal_connected": bool(u.paypal_vault_id),
        "paypal_payer_email": u.paypal_payer_email,
        "paypal_connected_mock": u.paypal_connected_mock,
    }


def mandate_view(m) -> dict | None:
    if m is None:
        return None
    return {
        "id": m.id,
        "max_amount": m.max_amount,
        "payee_paypal_email": m.payee_paypal_email,
        "earliest_days_before_due": m.earliest_days_before_due,
        "latest_days_after_due": m.latest_days_after_due,
        "valid_until": iso(m.valid_until),
        "paused": m.paused,
    }


def bill_base(b: Bill) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "category": b.category,
        "payee_name": b.payee_name,
        "payee_paypal_email": b.payee_paypal_email,
        "amount": b.amount,
        "currency": b.currency,
        "recurrence": b.recurrence,
        "due_day": b.due_day,
        "due_date": iso(b.due_date),
        "grace_days": b.grace_days,
        "late_fee": b.late_fee,
        "pay_mode": b.pay_mode,
        "paypal_fee": paypal_fee(b.amount),
    }


def paypal_fee(amount: float) -> float:
    """Estimated PayPal fee on a payment of `amount` (taken from what the receiver gets)."""
    return round(amount * settings.paypal_fee_percent / 100 + settings.paypal_fee_fixed, 2)


def planned_view(item: PlannedItem, today: date) -> dict:
    p = item.plan
    return {
        **bill_base(item.bill),
        "period": item.period,
        "due": iso(item.due),
        "days_to_due": (item.due - today).days,
        "pay_on": iso(p.pay_on),
        "status": p.status,
        "reason": p.reason,
        "last_free_day": iso(p.last_free_day),
        "shortfall": p.shortfall,
        "transfer_by": iso(p.transfer_by),
        "autopay": mandate_view(item.mandate),
        "pending_payment_id": item.pending_payment.id if item.pending_payment else None,
        "pay_today": item.bill.pay_mode == "remind" and today >= p.pay_on,
    }


def payment_view(p: Payment) -> dict:
    return {
        "id": p.id,
        "bill_id": p.bill_id,
        "period": p.period,
        "amount": p.amount,
        "status": p.status,
        "trigger": p.trigger,
        "paypal_order_id": p.paypal_order_id,
        "paypal_capture_id": p.paypal_capture_id,
        "payout_batch_id": p.payout_batch_id,
        "payout_status": p.payout_status,
        "mock": p.mock,
        "failure_reason": p.failure_reason,
        "paid_on": iso(p.paid_on),
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def action_view(a: AgentAction) -> dict:
    return {
        "id": a.id,
        "at": a.at.isoformat() if a.at else None,
        "on_date": iso(a.on_date),
        "kind": a.kind,
        "title": a.title,
        "message": a.message,
        "allowed": a.allowed,
        "reason": a.reason,
        "bill_id": a.bill_id,
        "payment_id": a.payment_id,
        "details": json.loads(a.details_json) if a.details_json else None,
    }


def bills_view(session: Session, snap: Snapshot) -> list[dict]:
    """Every active bill: its next unpaid occurrence, or 'paid' if nothing is open."""
    out = []
    bills = session.exec(select(Bill).where(Bill.user_id == snap.user.id, Bill.active == True)).all()  # noqa: E712
    for b in bills:
        item = snap.current.get(b.id)
        if item:
            out.append(planned_view(item, snap.today))
            continue
        last = session.exec(
            select(Payment).where(Payment.bill_id == b.id, Payment.status == "completed").order_by(Payment.id.desc())
        ).first()
        out.append({
            **bill_base(b), "status": "paid", "period": last.period if last else None, "due": None,
            "days_to_due": None, "pay_on": None, "reason": "All caught up.", "last_free_day": None, "shortfall": 0,
            "transfer_by": None, "autopay": mandate_view(active_mandate(session, b.id)), "pending_payment_id": None,
            "pay_today": False,
        })
    out.sort(key=lambda x: (x["due"] is None, x["due"] or ""))
    return out


def budgets_view(session: Session, user_id: int, today: date) -> list[dict]:
    limits = {b.category: b.weekly_limit for b in session.exec(select(Budget).where(Budget.user_id == user_id)).all()}
    txs = session.exec(select(Transaction).where(Transaction.user_id == user_id)).all()
    return [s.__dict__ for s in weekly_status(limits, [SpendItem(t.date, t.category, t.amount) for t in txs], today)]


def loan_spec(loan: Loan) -> LoanSpec:
    return LoanSpec(loan.principal, loan.annual_rate, loan.interest_type, loan.disbursed_date,
                    loan.repayment_start, loan.term_months, loan.currency)


def loan_card(session: Session, user_id: int, today: date) -> dict | None:
    loan = session.exec(select(Loan).where(Loan.user_id == user_id)).first()
    if not loan:
        return None
    r = analyze(loan_spec(loan), today)
    return {
        "id": loan.id,
        "lender": loan.lender,
        "currency": loan.currency,
        "principal": loan.principal,
        "annual_rate": loan.annual_rate,
        "repayment_start": iso(loan.repayment_start),
        "study_months_left": r.study_months_left,
        "interest_accrued_so_far": r.interest_accrued_so_far,
        "monthly_payment": r.monthly_payment,
        "monthly_payment_usd": round(r.monthly_payment / settings.fx_inr_per_usd, 2) if loan.currency == "INR" else r.monthly_payment,
    }


def dream_view(d: Dream, plan: DreamPlan | None) -> dict:
    left = round(max(0.0, d.target_amount - d.saved_amount), 2)
    return {
        "id": d.id,
        "name": d.name,
        "emoji": d.emoji,
        "target_amount": d.target_amount,
        "saved_amount": d.saved_amount,
        "target_date": iso(d.target_date),
        "priority": d.priority,
        "status": d.status,  # proposed | active | paused | reached | bought
        "left": plan.left if plan else left,
        "percent": plan.percent if plan else (round(min(100.0, 100 * d.saved_amount / d.target_amount), 1) if d.target_amount else 0.0),
        "per_week": plan.per_week if plan else 0.0,
        "later_per_week": plan.later_per_week if plan else None,
        "starts_on": iso(plan.starts_on) if plan else None,
        "needed_per_week": plan.needed_per_week if plan else None,
        "ready_on": iso(plan.ready_on) if plan else None,
        "plan_status": plan.status if plan else d.status,
        "reason": plan.reason if plan else "",
        "bought_on": iso(d.bought_on),
        "bought_price": d.bought_price,
    }


def _want_categories(session: Session, user_id: int) -> set[str]:
    """Budget categories that are mostly wants (eating out, fun), judged from past spending."""
    votes: dict[str, int] = {}
    for t in session.exec(select(Transaction).where(Transaction.user_id == user_id)).all():
        if t.is_need is not None:
            votes[t.category] = votes.get(t.category, 0) + (-1 if t.is_need else 1)
    return {c for c, v in votes.items() if v > 0}


def make_room(session: Session, snap: Snapshot) -> list[dict]:
    """'Lower this budget and your dreams get it': one suggestion per want budget, with the new ready date."""
    state = snap.dreams
    waiting = [d for d in state.rows if d.status == "active" and state.plans.get(d.id)
               and state.plans[d.id].status in {"behind", "no_room", "saving", "starts_later"}]
    if state.room.blocked_by or not waiting:
        return []
    wants = _want_categories(session, snap.user.id)
    out = []
    for b in session.exec(select(Budget).where(Budget.user_id == snap.user.id)).all():
        if b.category not in wants or b.weekly_limit < 10:
            continue
        new_limit = math.floor(b.weekly_limit * 0.6 / 5) * 5
        gain = b.weekly_limit - new_limit
        if gain < 5:
            continue
        closings = [p.closing - state.cushion + gain / 7 * (i + 1) for i, p in enumerate(snap.points)]
        room = room_per_week(today=snap.today, closings=closings, saved_total=state.saved_total,
                             reserve_per_day=snap.user.loan_set_aside_monthly / 30.0, short_bill=short_bill_text(snap.items),
                             weekly_surplus=state.weekly_surplus + gain)
        plans = {p.id: p for p in plan_dreams([dream_spec(d) for d in state.rows], room, snap.today)}
        first = waiting[0]
        before, after = state.plans[first.id], plans[first.id]
        if after.ready_on == before.ready_on and after.status == before.status:
            continue
        out.append({
            "category": b.category, "from": b.weekly_limit, "to": new_limit, "gain_per_week": gain,
            "room_after": room.later_per_week if room.later_per_week is not None else room.per_week, "dream": first.name, "ready_before": iso(before.ready_on),
            "ready_after": iso(after.ready_on), "status_after": after.status,
        })
    return out


def dreams_view(session: Session, snap: Snapshot) -> dict:
    state = snap.dreams
    bought = session.exec(select(Dream).where(Dream.user_id == snap.user.id, Dream.status == "bought")
                          .order_by(Dream.bought_on.desc(), Dream.id.desc()).limit(5)).all()
    return {
        "room": {"per_week": state.room.per_week, "blocked_by": state.room.blocked_by,
                 "later_per_week": state.room.later_per_week, "later_from": iso(state.room.later_from),
                 "tight_until": iso(state.room.tight_until), "tight_because": tight_because(snap.items, snap.dreams.room.tight_until)},
        "weekly_surplus": state.weekly_surplus,
        "monthly_surplus": round(state.weekly_surplus * 52 / 12, 2),
        "saved_total": state.saved_total,
        "per_week": state.per_week,
        "next_save_day": iso(next_save_day(snap.today)),
        "dreams": [dream_view(d, state.plans.get(d.id)) for d in state.rows],
        "bought": [dream_view(d, None) for d in bought],
        "make_room": make_room(session, snap),
    }


def setup_steps(session: Session, user: User) -> dict:
    """For a new student: the few things Kharcha needs before its plans mean anything."""
    has_income = session.exec(select(IncomeEvent.id).where(IncomeEvent.user_id == user.id)).first() is not None
    has_bill = session.exec(select(Bill.id).where(Bill.user_id == user.id)).first() is not None
    steps = {
        "money": user.balance_checked_on is not None,
        "income": has_income,
        "bills": has_bill,
        "paypal": bool(user.paypal_vault_id),
    }
    return {**steps, "done": steps["money"] and steps["income"] and steps["bills"]}


def balance_check_due(user: User, today: date) -> bool:
    return user.balance_checked_on is None or (today - user.balance_checked_on).days >= 7


def dashboard(session: Session, snap: Snapshot) -> dict:
    s = snap.safe
    bills = bills_view(session, snap)
    # The first short bill is the real problem; later ones are short *because* of it,
    # so they're flagged as knock-on alerts and the UI groups them under the first.
    alerts = []
    for i in snap.items:
        if i.plan.status in {"short", "late"}:
            alerts.append({
                "bill_id": i.bill.id, "name": i.bill.name, "due": iso(i.due), "period": i.period,
                "status": i.plan.status, "shortfall": i.plan.shortfall, "transfer_by": iso(i.plan.transfer_by),
                "reason": i.plan.reason, "knock_on": bool(alerts),
            })
    approvals = [b for b in bills if b.get("pending_payment_id")]
    pay_yourself = [b for b in bills if b.get("pay_today")]
    recent = session.exec(
        select(AgentAction).where(AgentAction.user_id == snap.user.id).order_by(AgentAction.id.desc()).limit(8)
    ).all()
    return {
        "today": iso(snap.today),
        "mode": mode(session),
        "user": user_view(snap.user),
        "balance_check_due": balance_check_due(snap.user, snap.today),
        "safe_to_spend": {
            "per_day": s.per_day,
            "horizon_days": s.horizon_days,
            "tightest_day": iso(s.tightest_day),
            "money_now": s.money_now,
            "income_in_horizon": s.income_in_horizon,
            "bills_in_horizon": s.bills_in_horizon,
            "loan_set_aside_in_horizon": s.loan_set_aside_in_horizon,
            "dreams_saved": s.dreams_saved,
            "dreams_in_horizon": s.dreams_in_horizon,
            "dreams_per_week": snap.dreams.per_week,
            "cushion": s.cushion,
            "shortfall": s.shortfall,
            "first_short_day": iso(s.first_short_day),
            "planned_daily_spend": snap.daily_spend,
        },
        "bills": bills,
        "alerts": alerts,
        "approvals": approvals,
        "pay_yourself": pay_yourself,
        "setup": setup_steps(session, snap.user),
        "budgets": budgets_view(session, snap.user.id, snap.today),
        "loan": loan_card(session, snap.user.id, snap.today),
        "dreams": dreams_view(session, snap),
        "forecast": [{"day": iso(p.day), "closing": p.closing, "income": p.income, "bills": p.bills} for p in snap.points],
        "recent_activity": [action_view(a) for a in recent],
    }
