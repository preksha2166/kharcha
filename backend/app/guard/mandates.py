"""Mandate checks. A mandate is the student's one-time permission, for example:
"Pay Maple Apartments up to $1,250 once a month, from 3 days before the due date
until the end of the grace period, until May 2027."

Two modes:
- autonomous (autopay or agent): every rule applies.
- user_approved (the student tapped "Approve"): the limit and window rules are
  skipped, because the human decided. The safety rules (saved PayPal, no double payment,
  known payee) still apply.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class MandateSpec:
    payee_paypal_email: str
    max_amount: float
    earliest_days_before_due: int
    latest_days_after_due: int
    valid_until: date
    paused: bool = False


@dataclass(frozen=True)
class Check:
    rule: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str  # "ok" or the first failed rule
    reason: str  # one human-readable sentence
    checks: list[Check] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "checks": [c.__dict__ for c in self.checks],
        }


def _money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


def check_payment(
    *,
    bill_payee_email: str,
    amount: float,
    pay_date: date,
    due_date: date,
    mandate: MandateSpec | None,
    already_paid: bool,
    has_saved_paypal: bool,
    money_available: float | None,
    user_approved: bool = False,
    cushion: float = 0.0,
) -> Decision:
    checks: list[Check] = []

    checks.append(Check(
        "saved_paypal", has_saved_paypal,
        "PayPal is connected." if has_saved_paypal else "PayPal isn't connected yet. Connect it once to allow payments.",
    ))
    checks.append(Check(
        "not_already_paid", not already_paid,
        "No other payment for this bill this period." if not already_paid else "This bill is already paid (or being paid) for this period.",
    ))
    checks.append(Check(
        "known_payee", bool(bill_payee_email),
        "Payee has a PayPal email." if bill_payee_email else "The bill has no payee PayPal email.",
    ))

    if not user_approved:
        has_mandate = mandate is not None and not mandate.paused
        if mandate is None:
            detail = "No autopay permission for this bill. You'll be asked to approve."
        elif mandate.paused:
            detail = "Autopay is paused for this bill."
        else:
            detail = "Autopay permission is active."
        checks.append(Check("mandate_active", has_mandate, detail))

        if mandate is not None:
            payee_ok = mandate.payee_paypal_email.strip().lower() == bill_payee_email.strip().lower()
            checks.append(Check(
                "payee_matches", payee_ok,
                "Payee matches your permission." if payee_ok
                else f"Payee changed to {bill_payee_email}, but you only allowed {mandate.payee_paypal_email}.",
            ))
            amount_ok = amount <= mandate.max_amount + 1e-9
            checks.append(Check(
                "within_limit", amount_ok,
                f"{_money(amount)} is within your {_money(mandate.max_amount)} limit." if amount_ok
                else f"{_money(amount)} is above your {_money(mandate.max_amount)} limit.",
            ))
            earliest = due_date - timedelta(days=mandate.earliest_days_before_due)
            latest = due_date + timedelta(days=mandate.latest_days_after_due)
            window_ok = earliest <= pay_date <= latest
            checks.append(Check(
                "in_window", window_ok,
                f"Paying on {pay_date.isoformat()} is inside your allowed window." if window_ok
                else f"{pay_date.isoformat()} is outside your allowed window ({earliest.isoformat()} to {latest.isoformat()}).",
            ))
            valid_ok = pay_date <= mandate.valid_until
            checks.append(Check(
                "not_expired", valid_ok,
                "Permission hasn't expired." if valid_ok else f"Permission expired on {mandate.valid_until.isoformat()}.",
            ))

        if money_available is not None:
            enough = money_available - cushion + 1e-9 >= amount
            if enough:
                detail = "You have enough money for this payment" + (
                    f", and your {_money(cushion)} safety cushion stays." if cushion > 0 else ".")
            elif money_available + 1e-9 >= amount:
                detail = (f"You have {_money(money_available)}, so paying {_money(amount)} would leave less than your "
                          f"{_money(cushion)} safety cushion. Kharcha won't do that without asking.")
            else:
                detail = (f"You have {_money(money_available)}, so paying {_money(amount)} would overdraw you. "
                          "Kharcha won't do that without asking.")
            checks.append(Check("no_overdraft", enough, detail))

    failed = next((c for c in checks if not c.ok), None)
    if failed is None:
        reason = "Approved by you." if user_approved else "All autopay rules passed."
        return Decision(True, "ok", reason, checks)
    return Decision(False, failed.rule, f"Blocked: {failed.detail}", checks)
