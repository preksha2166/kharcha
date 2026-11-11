"""The daily check: update payout status, receive expected income, warn about bills, run autopay on the right day,
then set money aside for dreams on Mondays.

Safe to run many times per day: income uses last_received, nudges use dedupe keys,
and payments refuse to pay a period twice.
"""

from datetime import date, timedelta

from sqlmodel import Session, select

from app.ai.nudges import write_nudge
from app.finance.budget import SpendItem, weekly_status
from app.finance.dates import week_start
from app.finance.schedule import IncomeSpec, income_occurrences
from app.models import Budget, IncomeEvent, Transaction, User
from app.services.activity import already_logged, log_action
from app.services.autopay import pay_bill, refresh_payouts
from app.services.dreams import run_dreams
from app.services.planner import build_snapshot


def _d(d: date | None) -> str | None:
    return d.strftime("%a %b %d").replace(" 0", " ") if d else None


def receive_income(session: Session, user: User, day: date) -> None:
    for ev in session.exec(select(IncomeEvent).where(IncomeEvent.user_id == user.id)).all():
        spec = IncomeSpec(ev.id, ev.label, ev.amount, ev.start_date, ev.recurrence, ev.last_received)
        if day in income_occurrences(spec, day, day):
            user.current_money = round(user.current_money + ev.amount, 2)
            ev.last_received = day
            session.add_all([user, ev])
            session.commit()
            msg, _ = write_nudge("income", {"label": ev.label, "amount": ev.amount})
            log_action(session, user_id=user.id, kind="income", on_date=day, title=f"{ev.label}: +${ev.amount:,.0f}",
                       message=msg, dedupe_key=f"income:{ev.id}:{day.isoformat()}")


def bill_facts(item, day: date) -> dict:
    plan = item.plan
    return {
        "bill": item.bill.name,
        "payee": item.bill.payee_name,
        "amount": item.bill.amount,
        "due": _d(item.due),
        "days_to_due": (item.due - day).days,
        "status": plan.status,
        "pay_on": _d(plan.pay_on),
        "last_free_day": _d(plan.last_free_day),
        "late_fee": item.bill.late_fee,
        "shortfall": plan.shortfall,
        "transfer_by": _d(plan.transfer_by),
        "autopay_on": bool(item.mandate and not item.mandate.paused),
        "pay_mode": item.bill.pay_mode,
    }


def _money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


def remind_to_pay(session: Session, user: User, item, day: date) -> None:
    """'Remind me' bills: tell the student today is the day (and again on the last day with no late fee)."""
    bill, plan = item.bill, item.plan
    key = f"{bill.id}:{item.period}"
    how = (f"Pay {bill.payee_name} the way you usually do, or tap 'Pay with PayPal' in Kharcha. "
           "Then tap 'I paid it' so your plan stays right.")
    if plan.status == "short":
        first = (f"Pay {bill.name} today: {_money(bill.amount)}",
                 f"You're about {_money(plan.shortfall)} short. Pay what you can and ask family for the rest, "
                 f"so you avoid the {_money(bill.late_fee)} late fee. {how}")
    elif plan.status == "late":
        first = (f"{bill.name} is late: pay as soon as you can",
                 f"It's past the no-late-fee period, so a {_money(bill.late_fee)} late fee may apply. {how}")
    else:
        later = f", and it's before the late fee starts after {_d(plan.last_free_day)}" if plan.last_free_day > item.due else ""
        first = (f"Pay {bill.name} today: {_money(bill.amount)}",
                 f"Today is the best day: your money is there{later}. {how}")
    log_action(session, user_id=user.id, kind="nudge", on_date=day, bill_id=bill.id, title=first[0], message=first[1],
               reason=plan.reason, dedupe_key=f"remind:{key}")
    if day == plan.last_free_day and day > plan.pay_on and bill.late_fee > 0:
        log_action(session, user_id=user.id, kind="nudge", on_date=day, bill_id=bill.id,
                   title=f"Last day to pay {bill.name} without a late fee",
                   message=f"After today a {_money(bill.late_fee)} late fee may apply. {how}",
                   dedupe_key=f"remind-last:{key}")


def run_daily_check(session: Session, user: User, day: date) -> None:
    refresh_payouts(session, user, day)
    receive_income(session, user, day)
    snap = build_snapshot(session, user, day)

    for item in list(snap.current.values()):
        days_to_due = (item.due - day).days
        key = f"{item.bill.id}:{item.period}"

        if days_to_due <= 7 and not already_logged(session, user.id, f"due7:{key}"):
            facts = bill_facts(item, day)
            msg, by_ai = write_nudge("due_soon", facts)
            log_action(session, user_id=user.id, kind="nudge", on_date=day, bill_id=item.bill.id,
                       title=f"{item.bill.name} due {facts['due']}", message=msg, reason=item.plan.reason,
                       dedupe_key=f"due7:{key}", details={**facts, "written_by_ai": by_ai})
        elif (
            item.plan.status == "short"
            and item.plan.transfer_by
            and (item.plan.transfer_by - day).days <= 7
            and not already_logged(session, user.id, f"short:{key}")
        ):
            facts = bill_facts(item, day)
            msg, by_ai = write_nudge("due_soon", facts)
            log_action(session, user_id=user.id, kind="nudge", on_date=day, bill_id=item.bill.id,
                       title=f"Heads-up: {item.bill.name} on {facts['due']}", message=msg, reason=item.plan.reason,
                       dedupe_key=f"short:{key}", details={**facts, "written_by_ai": by_ai})

        if day >= item.plan.pay_on and item.pending_payment is None:
            if item.bill.pay_mode == "remind":
                remind_to_pay(session, user, item, day)
            else:
                pay_bill(session, user=user, bill=item.bill, period=item.period, due=item.due, today=day, trigger="autopay")
                session.refresh(user)

    # Budget coach: one nudge per category per week when 80%+ is used.
    limits = {b.category: b.weekly_limit for b in session.exec(select(Budget).where(Budget.user_id == user.id)).all()}
    txs = session.exec(select(Transaction).where(Transaction.user_id == user.id)).all()
    for st in weekly_status(limits, [SpendItem(t.date, t.category, t.amount) for t in txs], day):
        dedupe = f"budget:{st.category}:{week_start(day).isoformat()}"
        if st.status in {"close", "over"} and not already_logged(session, user.id, dedupe):
            facts = {"category": st.category, "spent": st.spent, "limit": st.weekly_limit, "percent": st.percent,
                     "safe_to_spend_per_day": snap.safe.per_day}
            msg, by_ai = write_nudge("budget", facts)
            log_action(session, user_id=user.id, kind="nudge", on_date=day, title=f"{st.category} budget at {st.percent:.0f}%",
                       message=msg, dedupe_key=dedupe, details={**facts, "written_by_ai": by_ai})

    # Dreams last, after today's bills: bills first, dreams second.
    run_dreams(session, user, day)

    session.refresh(user)
    user.last_check_on = max(day, user.last_check_on or day)
    session.add(user)
    session.commit()


MAX_CATCH_UP_DAYS = 31


def catch_up(session: Session, user: User, today: date) -> int:
    """Run the daily check for every day missed since the last run (say the server was asleep on
    payday), then for today. Each day is safe to repeat. Returns how many days were checked."""
    last = user.last_check_on
    if last is None or last >= today:
        start = today
    else:
        start = max(last + timedelta(days=1), today - timedelta(days=MAX_CATCH_UP_DAYS - 1))
    day = start
    while day <= today:
        run_daily_check(session, user, day)
        session.refresh(user)
        day += timedelta(days=1)
    return (today - start).days + 1


def check_all_users(session: Session, today: date) -> dict:
    """The hourly job and the wake-up URL both call this."""
    users = session.exec(select(User)).all()
    days = sum(catch_up(session, u, today) for u in users)
    return {"users": len(users), "days_checked": days}
