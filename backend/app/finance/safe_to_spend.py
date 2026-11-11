"""'Safe to spend today': the most you can spend per day without missing a bill.

For every future day d, the money you'll have before discretionary spending is
B(d) = money now + income up to d - bills up to d - loan set-aside up to d - dream savings.
(Money already saved for dreams, what Kharcha will set aside for them, and the student's
safety cushion aren't spendable.)
Spending s per day keeps you above zero on day d only if s * (days so far) <= B(d).
So the safe daily amount is the smallest B(d) / days-so-far over the horizon.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.finance.forecast import Flow


@dataclass(frozen=True)
class SafeToSpend:
    per_day: float
    horizon_days: int
    tightest_day: date  # the day that limits how much you can spend
    money_now: float
    income_in_horizon: float
    bills_in_horizon: float
    loan_set_aside_in_horizon: float
    dreams_saved: float
    dreams_in_horizon: float
    cushion: float
    shortfall: float  # > 0 when bills can't be covered even with zero spending
    first_short_day: date | None


def safe_to_spend(
    *,
    money_now: float,
    today: date,
    incomes: list[Flow],
    outflows: list[Flow],
    loan_set_aside_monthly: float = 0.0,
    dreams_saved: float = 0.0,
    dreams_per_week: float = 0.0,
    cushion: float = 0.0,
    horizon_days: int = 30,
) -> SafeToSpend:
    loan_per_day = loan_set_aside_monthly / 30.0
    dreams_per_day = dreams_per_week / 7.0
    per_day_reserve = loan_per_day + dreams_per_day
    cumulative = money_now - dreams_saved - cushion
    best = None
    tightest = today
    min_b = None
    first_short = None
    total_in = total_out = 0.0

    for i in range(horizon_days):
        d = today + timedelta(days=i)
        day_in = sum(f.amount for f in incomes if f.on == d)
        day_out = sum(f.amount for f in outflows if f.on == d)
        total_in += day_in
        total_out += day_out
        cumulative += day_in - day_out - per_day_reserve
        if min_b is None or cumulative < min_b:
            min_b = cumulative
        if cumulative < 0 and first_short is None:
            first_short = d
        per_day = cumulative / (i + 1)
        if best is None or per_day < best:
            best = per_day
            tightest = d

    best = best if best is not None else 0.0
    shortfall = -min_b if (min_b is not None and min_b < 0) else 0.0
    return SafeToSpend(
        per_day=round(max(0.0, best), 2),
        horizon_days=horizon_days,
        tightest_day=tightest,
        money_now=round(money_now, 2),
        income_in_horizon=round(total_in, 2),
        bills_in_horizon=round(total_out, 2),
        loan_set_aside_in_horizon=round(loan_per_day * horizon_days, 2),
        dreams_saved=round(dreams_saved, 2),
        dreams_in_horizon=round(dreams_per_day * horizon_days, 2),
        cushion=round(cushion, 2),
        shortfall=round(shortfall, 2),
        first_short_day=first_short,
    )
