from datetime import date, timedelta

import pytest

from app.finance.forecast import Flow
from app.finance.loan import LoanSpec, analyze, compare, emi
from app.finance.safe_to_spend import safe_to_spend
from app.finance.schedule import BillSpec, IncomeSpec, due_items, income_occurrences

TODAY = date(2026, 11, 5)


def test_emi_matches_standard_formula():
    # 1,00,000 at 12% for 12 months -> 8,884.88 (well-known reference value)
    assert emi(100_000, 12, 12) == pytest.approx(8884.88, abs=0.01)
    assert emi(1200, 0, 12) == 100


def test_paying_interest_during_study_saves_money():
    loan = LoanSpec(principal=4_000_000, annual_rate=10.5, interest_type="simple",
                    disbursed_date=date(2025, 8, 1), repayment_start=date(2027, 11, 1), term_months=120)
    base = analyze(loan, TODAY)
    assert base.study_months_total == 27
    assert base.interest_by_repayment_start == pytest.approx(4_000_000 * 0.105 * 27 / 12)
    c = compare(loan, TODAY, 10_000)
    assert c["savings"] > 0
    assert c["scenario"].monthly_payment < base.monthly_payment
    assert base.balance_points[0]["balance"] == 4_000_000


def test_safe_to_spend_spreads_money_until_bills_are_covered():
    incomes = [Flow(TODAY + timedelta(days=9), 800, "home")]
    outflows = [Flow(TODAY + timedelta(days=9), 1200, "rent")]
    s = safe_to_spend(money_now=1100, today=TODAY, incomes=incomes, outflows=outflows, horizon_days=30)
    # After day 9 there is 700 left for 30 days -> about $23/day.
    assert s.per_day == pytest.approx(700 / 30, abs=0.01)
    assert s.shortfall == 0


def test_safe_to_spend_reports_shortfall():
    outflows = [Flow(TODAY + timedelta(days=3), 1500, "rent")]
    s = safe_to_spend(money_now=1000, today=TODAY, incomes=[], outflows=outflows, horizon_days=10)
    assert s.per_day == 0
    assert s.shortfall == 500
    assert s.first_short_day == TODAY + timedelta(days=3)


def test_monthly_bill_due_dates_and_paid_periods():
    bill = BillSpec(id=1, name="Rent", amount=1200, recurrence="monthly", start_date=date(2026, 11, 12), due_day=12)
    items = due_items(bill, TODAY, TODAY + timedelta(days=60), paid_periods=set())
    assert [i.due for i in items] == [date(2026, 11, 12), date(2026, 12, 12)]
    items = due_items(bill, TODAY, TODAY + timedelta(days=60), paid_periods={"2026-11"})
    assert [i.period for i in items] == ["2026-12"]


def test_due_day_31_clamps_to_short_months():
    bill = BillSpec(id=1, name="Rent", amount=1, recurrence="monthly", start_date=date(2027, 1, 31), due_day=31)
    items = due_items(bill, date(2027, 1, 20), date(2027, 3, 31), set())
    assert [i.due for i in items] == [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)]


def test_income_skips_already_received():
    inc = IncomeSpec(id=1, label="home", amount=800, start_date=date(2026, 11, 14), recurrence="monthly",
                     last_received=date(2026, 11, 14))
    assert income_occurrences(inc, date(2026, 11, 14), date(2026, 12, 31)) == [date(2026, 12, 14)]
