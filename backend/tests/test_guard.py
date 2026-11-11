from datetime import date

from app.guard.mandates import MandateSpec, check_payment

DUE = date(2026, 12, 1)
LANDLORD = "landlord@example.com"
MANDATE = MandateSpec(payee_paypal_email=LANDLORD, max_amount=1250, earliest_days_before_due=3,
                      latest_days_after_due=4, valid_until=date(2027, 5, 31))


def check(**overrides):
    args = dict(bill_payee_email=LANDLORD, amount=1200, pay_date=DUE, due_date=DUE, mandate=MANDATE,
                already_paid=False, has_saved_paypal=True, money_available=2000, user_approved=False)
    args.update(overrides)
    return check_payment(**args)


def test_allows_payment_inside_all_limits():
    d = check()
    assert d.allowed and d.code == "ok"


def test_blocks_amount_above_limit():
    d = check(amount=1400)
    assert not d.allowed and d.code == "within_limit"
    assert "$1,400" in d.reason and "$1,250" in d.reason


def test_blocks_changed_payee():
    # e.g. a document tried to sneak in a different payee
    d = check(bill_payee_email="someone-else@example.com")
    assert not d.allowed and d.code == "payee_matches"


def test_blocks_outside_window():
    assert check(pay_date=date(2026, 12, 6)).code == "in_window"
    assert check(pay_date=date(2026, 11, 27)).code == "in_window"
    assert check(pay_date=date(2026, 11, 28)).allowed


def test_blocks_paused_or_missing_mandate():
    paused = MandateSpec(**{**MANDATE.__dict__, "paused": True})
    assert check(mandate=paused).code == "mandate_active"
    assert check(mandate=None).code == "mandate_active"


def test_blocks_expired_mandate():
    expired = MandateSpec(**{**MANDATE.__dict__, "valid_until": date(2026, 11, 30)})
    assert check(mandate=expired).code == "not_expired"


def test_safety_rules():
    assert check(has_saved_paypal=False).code == "saved_paypal"
    assert check(already_paid=True).code == "not_already_paid"
    assert check(money_available=900).code == "no_overdraft"


def test_user_approval_skips_limits_but_not_safety():
    assert check(amount=1400, user_approved=True).allowed
    assert check(mandate=None, user_approved=True).allowed
    assert not check(already_paid=True, user_approved=True).allowed
    assert not check(has_saved_paypal=False, user_approved=True).allowed
