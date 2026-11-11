"""Day-by-day money forecast."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Flow:
    on: date
    amount: float  # positive number; direction comes from which list it is in
    label: str


@dataclass(frozen=True)
class DayPoint:
    day: date
    opening: float
    income: float
    bills: float
    spending: float
    closing: float


def forecast(
    start_money: float,
    today: date,
    days: int,
    incomes: list[Flow],
    outflows: list[Flow],
    daily_spend: float,
) -> list[DayPoint]:
    """Balance for `days` days starting today. Spending is spread evenly per day."""
    income_by_day: dict[date, float] = defaultdict(float)
    out_by_day: dict[date, float] = defaultdict(float)
    for f in incomes:
        income_by_day[f.on] += f.amount
    for f in outflows:
        out_by_day[f.on] += f.amount

    points: list[DayPoint] = []
    balance = start_money
    for i in range(days):
        d = today + timedelta(days=i)
        opening = balance
        balance = opening + income_by_day[d] - out_by_day[d] - daily_spend
        points.append(
            DayPoint(
                day=d,
                opening=round(opening, 2),
                income=round(income_by_day[d], 2),
                bills=round(out_by_day[d], 2),
                spending=round(daily_spend, 2),
                closing=round(balance, 2),
            )
        )
    return points


def closing_on(points: list[DayPoint], d: date) -> float | None:
    for p in points:
        if p.day == d:
            return p.closing
    return None
