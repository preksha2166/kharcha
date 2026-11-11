"""Builds one consistent picture of the student's money: bill plans, forecast, dreams, safe-to-spend."""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlmodel import Session, select

from app.finance.dreams import DreamPlan, DreamSpec, Room, plan_dreams, room_per_week
from app.finance.forecast import DayPoint, Flow, closing_on, forecast
from app.finance.safe_to_spend import SafeToSpend, safe_to_spend
from app.finance.schedule import BillSpec, IncomeSpec, due_items, income_occurrences
from app.finance.timing import PaymentPlan, plan_payment
from app.guard.mandates import MandateSpec
from app.models import Bill, Budget, Dream, IncomeEvent, Mandate, Payment, User

HORIZON_DAYS = 60
SAFE_HORIZON_DAYS = 30
# Bill planning looks this far past the horizon, so a bill due near the end can still "see"
# money that arrives during its grace period (e.g. rent due on day 60, money from home on day 62).
PLAN_BUFFER_DAYS = 31
PAID_STATUSES = {"completed", "processing"}
# Dreams whose money counts as saved (a proposed dream isn't saved yet; a bought one is spent).
SAVING_STATUSES = {"active", "paused", "reached"}


@dataclass
class PlannedItem:
    bill: Bill
    period: str
    due: date
    plan: PaymentPlan
    mandate: Mandate | None
    pending_payment: Payment | None  # waiting for the student's approval


@dataclass
class DreamsState:
    rows: list[Dream] = field(default_factory=list)  # saving dreams, most important first
    plans: dict[int, DreamPlan] = field(default_factory=dict)
    room: Room = field(default_factory=lambda: Room(0.0, None))
    saved_total: float = 0.0
    per_week: float = 0.0  # set aside this Monday, all dreams together
    weekly_surplus: float = 0.0  # normal spare money per week (regular income minus regular costs)
    cushion: float = 0.0  # the student's safety cushion (never planned to be spent)


@dataclass
class Snapshot:
    today: date
    user: User
    items: list[PlannedItem]  # every unpaid occurrence in the horizon, in due-date order
    current: dict[int, PlannedItem]  # the next unpaid occurrence per bill
    points: list[DayPoint]
    safe: SafeToSpend
    daily_spend: float
    incomes: list[Flow]
    outflows: list[Flow]
    dreams: DreamsState


def _minus(value: float | None, amount: float) -> float | None:
    return None if value is None else value - amount


def bill_spec(b: Bill) -> BillSpec:
    return BillSpec(
        id=b.id, name=b.name, amount=b.amount, recurrence=b.recurrence, start_date=b.start_date,
        due_day=b.due_day, due_date=b.due_date, grace_days=b.grace_days, late_fee=b.late_fee,
    )


def mandate_spec(m: Mandate | None) -> MandateSpec | None:
    if m is None:
        return None
    return MandateSpec(
        payee_paypal_email=m.payee_paypal_email, max_amount=m.max_amount,
        earliest_days_before_due=m.earliest_days_before_due, latest_days_after_due=m.latest_days_after_due,
        valid_until=m.valid_until, paused=m.paused,
    )


def due_for_period(bill: Bill, period: str) -> date | None:
    if bill.recurrence == "once":
        return bill.due_date
    if bill.due_day is None:
        return None
    from app.finance.dates import monthly_due_date

    year, month = (int(x) for x in period.split("-"))
    return monthly_due_date(year, month, bill.due_day)


def active_mandate(session: Session, bill_id: int) -> Mandate | None:
    return session.exec(
        select(Mandate).where(Mandate.bill_id == bill_id).order_by(Mandate.id.desc())
    ).first()


def paid_periods(session: Session, bill_id: int) -> set[str]:
    rows = session.exec(select(Payment).where(Payment.bill_id == bill_id)).all()
    return {p.period for p in rows if p.status in PAID_STATUSES}


def daily_spend_for(session: Session, user_id: int) -> float:
    budgets = session.exec(select(Budget).where(Budget.user_id == user_id)).all()
    return round(sum(b.weekly_limit for b in budgets) / 7.0, 2)


def income_flows(session: Session, user_id: int, today: date, horizon_end: date) -> list[Flow]:
    flows: list[Flow] = []
    for ev in session.exec(select(IncomeEvent).where(IncomeEvent.user_id == user_id)).all():
        spec = IncomeSpec(ev.id, ev.label, ev.amount, ev.start_date, ev.recurrence, ev.last_received)
        flows += [Flow(d, ev.amount, ev.label) for d in income_occurrences(spec, today, horizon_end)]
    return flows


def dream_spec(d: Dream) -> DreamSpec:
    return DreamSpec(id=d.id, name=d.name, target=d.target_amount, saved=d.saved_amount, target_date=d.target_date,
                     priority=d.priority, paused=d.status == "paused")


def saving_dreams(session: Session, user_id: int) -> list[Dream]:
    rows = session.exec(select(Dream).where(Dream.user_id == user_id, Dream.status.in_(SAVING_STATUSES))).all()
    return sorted(rows, key=lambda d: (d.priority, d.id))


def short_bill_text(items: list["PlannedItem"]) -> str | None:
    """The first bill that's short or late, in words. Dreams wait while one exists (bills first)."""
    for it in items:
        if it.plan.status == "late":
            return f"{it.bill.name} is past its due date"
        if it.plan.status == "short":
            when = it.due.strftime("%b %d").replace(" 0", " ")
            return f"{it.bill.name} on {when} is about ${math.ceil(it.plan.shortfall):,} short"
    return None


def tight_because(items: list["PlannedItem"], until: date | None) -> str | None:
    """The big bill behind a tight stretch: the largest one paid in the week before its tightest day."""
    if until is None:
        return None
    near = [i for i in items if 0 <= (until - i.plan.pay_on).days <= 6]
    return max(near, key=lambda i: i.bill.amount).bill.name if near else None


def weekly_surplus(session: Session, user: User) -> float:
    """Normal spare money per week: regular income minus regular bills, weekly budgets and the loan
    set-aside. One-time money and one-time bills aren't counted (the 60-day forecast has them)."""
    per_week = 0.0
    for ev in session.exec(select(IncomeEvent).where(IncomeEvent.user_id == user.id)).all():
        if ev.recurrence == "monthly":
            per_week += ev.amount * 12 / 52
        elif ev.recurrence == "biweekly":
            per_week += ev.amount / 2
    for b in session.exec(select(Bill).where(Bill.user_id == user.id, Bill.active == True)).all():  # noqa: E712
        if b.recurrence == "monthly":
            per_week -= b.amount * 12 / 52
    per_week -= sum(b.weekly_limit for b in session.exec(select(Budget).where(Budget.user_id == user.id)).all())
    per_week -= user.loan_set_aside_monthly * 12 / 52
    return round(per_week, 2)


def dreams_state(session: Session, user: User, today: date, points: list[DayPoint], items: list["PlannedItem"],
                 extra: Dream | None = None) -> DreamsState:
    """Room for dreams and each dream's plan. `extra` previews a proposed dream at the lowest priority."""
    rows = saving_dreams(session, user.id)
    saved_total = round(sum(d.saved_amount for d in rows), 2)
    surplus = weekly_surplus(session, user)
    cushion = max(0.0, user.safety_cushion or 0.0)
    room = room_per_week(today=today, closings=[p.closing - cushion for p in points], saved_total=saved_total,
                         reserve_per_day=user.loan_set_aside_monthly / 30.0, short_bill=short_bill_text(items),
                         weekly_surplus=surplus)
    specs = [dream_spec(d) for d in rows]
    if extra is not None:
        specs.append(DreamSpec(id=extra.id, name=extra.name, target=extra.target_amount, saved=extra.saved_amount,
                               target_date=extra.target_date, priority=10_000))
    plans = {p.id: p for p in plan_dreams(specs, room, today)}
    per_week = sum(p.per_week for p in plans.values() if extra is None or p.id != extra.id)
    return DreamsState(rows, plans, room, saved_total, per_week, surplus, cushion)


def build_snapshot(session: Session, user: User, today: date) -> Snapshot:
    horizon_end = today + timedelta(days=HORIZON_DAYS - 1)
    daily_spend = daily_spend_for(session, user.id)
    incomes = income_flows(session, user.id, today, horizon_end + timedelta(days=PLAN_BUFFER_DAYS))

    bills = session.exec(select(Bill).where(Bill.user_id == user.id, Bill.active == True)).all()  # noqa: E712
    occurrences = []
    mandates: dict[int, Mandate | None] = {}
    pending: dict[tuple[int, str], Payment] = {}
    for b in bills:
        mandates[b.id] = active_mandate(session, b.id)
        for occ in due_items(bill_spec(b), today, horizon_end, paid_periods(session, b.id)):
            occurrences.append((occ.due, b, occ.period))
        for p in session.exec(
            select(Payment).where(Payment.bill_id == b.id, Payment.status == "needs_approval")
        ).all():
            pending[(b.id, p.period)] = p
    occurrences.sort(key=lambda x: (x[0], x[1].id))
    cushion = max(0.0, user.safety_cushion or 0.0)  # bills are planned so this much always stays

    outflows: list[Flow] = []
    items: list[PlannedItem] = []
    for due, bill, period in occurrences:
        points = forecast(user.current_money, today, HORIZON_DAYS + PLAN_BUFFER_DAYS, incomes, outflows, daily_spend)
        mandate = mandates.get(bill.id)
        latest = due + timedelta(days=mandate.latest_days_after_due) if (mandate and not mandate.paused) else None
        plan = plan_payment(
            today=today,
            due=due,
            amount=bill.amount,
            grace_days=bill.grace_days,
            late_fee=bill.late_fee,
            available_on=lambda d, pts=points: _minus(closing_on(pts, d), cushion),
            latest_allowed=latest,
            transfer_days=user.transfer_days_from_home,
        )
        outflows.append(Flow(plan.pay_on, bill.amount, bill.name))
        items.append(PlannedItem(bill, period, due, plan, mandate, pending.get((bill.id, period))))

    points = forecast(user.current_money, today, HORIZON_DAYS, incomes, outflows, daily_spend)
    dreams = dreams_state(session, user, today, points, items)
    safe = safe_to_spend(
        money_now=user.current_money,
        today=today,
        incomes=incomes,
        outflows=outflows,
        loan_set_aside_monthly=user.loan_set_aside_monthly,
        dreams_saved=dreams.saved_total,
        dreams_per_week=dreams.per_week,
        cushion=cushion,
        horizon_days=SAFE_HORIZON_DAYS,
    )
    current: dict[int, PlannedItem] = {}
    for it in items:
        current.setdefault(it.bill.id, it)
    return Snapshot(today, user, items, current, points, safe, daily_spend, incomes, outflows, dreams)
