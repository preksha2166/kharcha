from datetime import date, timedelta

from app.finance.timing import plan_payment

TODAY = date(2026, 11, 5)
DUE = date(2026, 11, 12)


def balances(mapping: dict[int, float], default: float):
    """available_on(d) built from {days after TODAY: money}."""
    def available(d: date):
        offset = (d - TODAY).days
        best = default
        for k in sorted(mapping):
            if offset >= k:
                best = mapping[k]
        return best
    return available


def test_pays_on_due_date_when_money_is_there():
    plan = plan_payment(today=TODAY, due=DUE, amount=1200, grace_days=4, late_fee=75,
                        available_on=balances({}, 1500))
    assert plan.status == "ready"
    assert plan.pay_on == DUE
    assert plan.shortfall == 0


def test_waits_for_money_inside_grace_period():
    # Money from home lands 2 days after the due date.
    plan = plan_payment(today=TODAY, due=DUE, amount=1200, grace_days=4, late_fee=75,
                        available_on=balances({9: 1700}, 1000))
    assert plan.status == "waiting_for_money"
    assert plan.pay_on == DUE + timedelta(days=2)
    assert plan.pay_on <= plan.last_free_day


def test_short_when_money_arrives_too_late():
    plan = plan_payment(today=TODAY, due=DUE, amount=1200, grace_days=4, late_fee=75,
                        available_on=balances({20: 2000}, 900), transfer_days=4)
    assert plan.status == "short"
    assert plan.shortfall == 300
    assert plan.transfer_by == DUE - timedelta(days=4)
    assert plan.pay_on == DUE + timedelta(days=4)


def test_mandate_window_limits_waiting():
    # Grace is 4 days, but the student only allowed paying up to 1 day late.
    plan = plan_payment(today=TODAY, due=DUE, amount=1200, grace_days=4, late_fee=75,
                        available_on=balances({9: 1700}, 1000), latest_allowed=DUE + timedelta(days=1))
    assert plan.status == "short"


def test_late_after_grace_period():
    plan = plan_payment(today=DUE + timedelta(days=6), due=DUE, amount=1200, grace_days=4, late_fee=75,
                        available_on=lambda d: 1300)
    assert plan.status == "late"
