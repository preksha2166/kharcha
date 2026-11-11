"""When bills are due and when money arrives."""

from dataclasses import dataclass
from datetime import date, timedelta

from app.finance.dates import add_months, monthly_due_date, period_key


@dataclass(frozen=True)
class BillSpec:
    """The parts of a bill the math needs (kept separate from the DB model for easy testing)."""

    id: int
    name: str
    amount: float
    recurrence: str  # monthly | once
    start_date: date
    due_day: int | None = None
    due_date: date | None = None
    grace_days: int = 0
    late_fee: float = 0.0


@dataclass(frozen=True)
class IncomeSpec:
    id: int
    label: str
    amount: float
    start_date: date
    recurrence: str = "monthly"  # once | monthly | biweekly
    last_received: date | None = None


@dataclass(frozen=True)
class DueItem:
    bill: BillSpec
    period: str
    due: date


def bill_period(bill: BillSpec, due: date) -> str:
    return "once" if bill.recurrence == "once" else period_key(due)


def due_items(bill: BillSpec, today: date, horizon_end: date, paid_periods: set[str]) -> list[DueItem]:
    """Unpaid due dates from the bill's start up to horizon_end (overdue ones included)."""
    if bill.recurrence == "once":
        if bill.due_date is None or "once" in paid_periods:
            return []
        return [DueItem(bill, "once", bill.due_date)] if bill.due_date <= horizon_end else []

    if bill.due_day is None:
        return []
    items: list[DueItem] = []
    # Look back 2 months for anything overdue, then forward to the horizon.
    cursor = add_months(today, -2, day=1)
    while True:
        due = monthly_due_date(cursor.year, cursor.month, bill.due_day)
        if due > horizon_end:
            break
        period = period_key(due)
        if due >= bill.start_date and period not in paid_periods:
            items.append(DueItem(bill, period, due))
        cursor = add_months(cursor, 1, day=1)
    return items


def income_occurrences(income: IncomeSpec, today: date, horizon_end: date) -> list[date]:
    """Expected arrival dates from today to horizon_end that haven't been received yet."""
    dates: list[date] = []
    if income.recurrence == "once":
        candidates = [income.start_date]
    elif income.recurrence == "biweekly":
        candidates = []
        d = income.start_date
        while d <= horizon_end:
            candidates.append(d)
            d += timedelta(days=14)
    else:  # monthly
        candidates = []
        i = 0
        while True:
            d = add_months(income.start_date, i)
            if d > horizon_end:
                break
            candidates.append(d)
            i += 1
    for d in candidates:
        if d < today or d > horizon_end:
            continue
        if income.last_received is not None and d <= income.last_received:
            continue
        dates.append(d)
    return dates
