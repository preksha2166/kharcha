"""Smart timing: pick the best day to pay a bill.

Bank autopay pays on the due date even if your money arrives two days later, so you
overdraw or the payment fails. Kharcha looks at the forecast: if the money lands
inside the no-late-fee grace period, it waits and pays then, with no fee and no overdraft.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class PaymentPlan:
    pay_on: date
    status: str  # ready | waiting_for_money | short | late
    reason: str
    last_free_day: date  # last day with no late fee
    shortfall: float  # 0 when the money is there
    transfer_by: date | None  # when to start a transfer from home if short


def _fmt(d: date) -> str:
    return d.strftime("%b %d").replace(" 0", " ")


def plan_payment(
    *,
    today: date,
    due: date,
    amount: float,
    grace_days: int,
    late_fee: float,
    available_on: Callable[[date], float | None],
    latest_allowed: date | None = None,
    transfer_days: int = 4,
) -> PaymentPlan:
    """available_on(d) = money projected at the end of day d *before* paying this bill."""
    last_free_day = due + timedelta(days=grace_days)
    window_end = last_free_day if latest_allowed is None else min(last_free_day, latest_allowed)

    # Already past the grace period: pay as soon as possible, a late fee applies.
    if today > last_free_day:
        money = available_on(today)
        short = max(0.0, amount - (money or 0.0))
        return PaymentPlan(
            pay_on=today,
            status="late",
            reason=f"Past the grace period ({_fmt(last_free_day)}). A late fee of ${late_fee:,.0f} may apply.",
            last_free_day=last_free_day,
            shortfall=round(short, 2),
            transfer_by=None,
        )

    start = max(today, due)
    best_seen = None
    d = start
    while d <= window_end:
        money = available_on(d)
        if money is not None:
            best_seen = money if best_seen is None else max(best_seen, money)
            if money >= amount:
                if d == due or d < due:
                    return PaymentPlan(d, "ready", f"Enough money on the due date ({_fmt(due)}).", last_free_day, 0.0, None)
                return PaymentPlan(
                    pay_on=d,
                    status="waiting_for_money",
                    reason=(
                        f"Not enough money on {_fmt(due)}, but your expected money arrives by {_fmt(d)}. "
                        f"Paying on {_fmt(d)} is still inside the no-late-fee period (until {_fmt(last_free_day)})."
                    ),
                    last_free_day=last_free_day,
                    shortfall=0.0,
                    transfer_by=None,
                )
        d += timedelta(days=1)

    # No day in the window has enough money.
    shortfall = amount - (best_seen if best_seen is not None else 0.0)
    transfer_by = max(today, due - timedelta(days=transfer_days))
    return PaymentPlan(
        pay_on=window_end,
        status="short",
        reason=(
            f"You'll be about ${shortfall:,.0f} short even by {_fmt(window_end)}. "
            f"Start a transfer from home by {_fmt(transfer_by)} to avoid a ${late_fee:,.0f} late fee."
        ),
        last_free_day=last_free_day,
        shortfall=round(shortfall, 2),
        transfer_by=transfer_by,
    )
