"""Education loan math: interest during studies, monthly payment after, what-if scenarios.

Many education loans (for example from Indian lenders) charge interest during the study
period ("moratorium") and add it to the loan when repayment starts. Paying some or all of
that interest while studying lowers the total cost.
"""

from dataclasses import dataclass, field
from datetime import date

from app.finance.dates import add_months, months_between


@dataclass(frozen=True)
class LoanSpec:
    principal: float
    annual_rate: float  # percent
    interest_type: str  # simple | compound (during the study period)
    disbursed_date: date
    repayment_start: date
    term_months: int
    currency: str = "INR"


@dataclass(frozen=True)
class LoanResult:
    study_months_total: int
    study_months_left: int
    interest_accrued_so_far: float
    interest_by_repayment_start: float  # if nothing is paid during studies
    paid_during_study: float
    balance_at_repayment_start: float
    monthly_payment: float  # EMI after studies
    total_interest: float
    total_paid: float
    balance_points: list[dict] = field(default_factory=list)  # [{month, balance}] for the chart


def emi(principal: float, annual_rate: float, months: int) -> float:
    """Standard loan payment formula."""
    if months <= 0:
        return 0.0
    r = annual_rate / 100 / 12
    if r == 0:
        return principal / months
    factor = (1 + r) ** months
    return principal * r * factor / (factor - 1)


def _study_interest(principal: float, annual_rate: float, interest_type: str, months: int) -> float:
    r = annual_rate / 100
    if interest_type == "compound":
        return principal * ((1 + r / 12) ** months - 1)
    return principal * r * months / 12


def analyze(loan: LoanSpec, today: date, monthly_payment_during_study: float = 0.0) -> LoanResult:
    """Full picture, optionally with a fixed monthly payment toward interest while studying."""
    total_study = months_between(loan.disbursed_date, loan.repayment_start)
    elapsed = min(total_study, months_between(loan.disbursed_date, today))
    left = max(0, total_study - elapsed)

    accrued_so_far = _study_interest(loan.principal, loan.annual_rate, loan.interest_type, elapsed)
    interest_by_start = _study_interest(loan.principal, loan.annual_rate, loan.interest_type, total_study)

    # Payments from now until repayment starts reduce the interest that gets added to the loan.
    # (Simplification: payments go to interest first, and only up to the interest owed.)
    paid = min(monthly_payment_during_study * left, interest_by_start)
    unpaid_interest = max(0.0, interest_by_start - paid)
    balance_at_start = loan.principal + unpaid_interest

    payment = emi(balance_at_start, loan.annual_rate, loan.term_months)
    total_paid = paid + payment * loan.term_months
    total_interest = total_paid - loan.principal

    # Chart: balance at each month from disbursement to the end of repayment.
    points: list[dict] = []
    monthly_interest = interest_by_start / total_study if total_study else 0.0
    monthly_paydown = paid / left if left else 0.0
    bal = loan.principal
    for m in range(total_study + 1):
        when = add_months(loan.disbursed_date, m)
        points.append({"month": when.isoformat(), "balance": round(bal, 2)})
        bal += monthly_interest
        if m >= elapsed:
            bal -= monthly_paydown
    bal = balance_at_start
    r = loan.annual_rate / 100 / 12
    for m in range(1, loan.term_months + 1):
        bal = bal * (1 + r) - payment
        when = add_months(loan.repayment_start, m)
        if m % 3 == 0 or m == loan.term_months:  # every 3 months keeps the chart light
            points.append({"month": when.isoformat(), "balance": round(max(0.0, bal), 2)})

    return LoanResult(
        study_months_total=total_study,
        study_months_left=left,
        interest_accrued_so_far=round(accrued_so_far, 2),
        interest_by_repayment_start=round(interest_by_start, 2),
        paid_during_study=round(paid, 2),
        balance_at_repayment_start=round(balance_at_start, 2),
        monthly_payment=round(payment, 2),
        total_interest=round(total_interest, 2),
        total_paid=round(total_paid, 2),
        balance_points=points,
    )


def compare(loan: LoanSpec, today: date, monthly_payment_during_study: float) -> dict:
    """Baseline (pay nothing while studying) vs. paying a fixed amount each month."""
    base = analyze(loan, today, 0.0)
    plan = analyze(loan, today, monthly_payment_during_study)
    return {
        "baseline": base,
        "scenario": plan,
        "savings": round(base.total_paid - plan.total_paid, 2),
        "monthly_payment_drop": round(base.monthly_payment - plan.monthly_payment, 2),
    }
