"""Demo student "Riya". All dates are relative to the day the demo is seeded, so the story always works:

- Rent $1,200 is due in 7 days (grace period 4 days, $75 late fee).
- She has $1,100 now. Money from home ($800) arrives 2 days AFTER the due date.
- Bank autopay would fail on the due date. Kharcha waits and pays on day 9, inside the grace period.
- A campus job pays $560 every two weeks (20 hours a week at $14), starting the day after rent is paid.
- Spring fee $2,400 is due in ~45 days and she'll be short, so Kharcha warns her early.

Names are made up on purpose (hackathon rule: no third-party trademarks in the demo).
"""

from datetime import date, timedelta

from sqlmodel import Session, select

from app.config import settings
from app.finance.budget import rule_category
from app.finance.dates import add_months
from app.models import AppState, Bill, Budget, IncomeEvent, Loan, Mandate, Transaction, User


def seed_demo(session: Session, today: date) -> User:
    existing = get_demo_user(session)
    if existing:
        return existing

    user = User(
        name="Riya",
        is_demo=True,
        current_money=1100.0,
        balance_checked_on=today,
        transfer_days_from_home=4,
        loan_set_aside_monthly=50.0,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    rent_due = today + timedelta(days=7)
    rent = Bill(
        user_id=user.id, name="Rent", category="rent", payee_name="Maple Apartments",
        payee_paypal_email=settings.demo_landlord_email, amount=1200.0, recurrence="monthly",
        due_day=rent_due.day, start_date=rent_due, grace_days=4, late_fee=75.0,
    )
    phone_due = today + timedelta(days=12)
    phone = Bill(
        user_id=user.id, name="Phone plan", category="phone", payee_name="Bright Mobile",
        payee_paypal_email=settings.demo_landlord_email, amount=25.0, recurrence="monthly",
        due_day=phone_due.day, start_date=phone_due, grace_days=0, late_fee=5.0,
    )
    transit_due = today + timedelta(days=18)
    transit = Bill(
        user_id=user.id, name="Transit pass", category="transit", payee_name="City Transit Card",
        payee_paypal_email=settings.demo_landlord_email, amount=50.0, recurrence="monthly",
        due_day=transit_due.day, start_date=transit_due, grace_days=0, late_fee=0.0,
    )
    fee_due = today + timedelta(days=45)
    tuition = Bill(
        user_id=user.id, name="Spring term fee", category="tuition", payee_name="State University",
        payee_paypal_email=settings.demo_college_email, amount=2400.0, recurrence="once",
        due_date=fee_due, start_date=fee_due, grace_days=0, late_fee=100.0,
        pay_mode="remind",  # paid on the college portal: Kharcha reminds, the student pays (free)
    )
    session.add_all([rent, phone, transit, tuition])
    session.commit()
    for b in (rent, phone, transit, tuition):
        session.refresh(b)

    # Autopay permissions. Rent has a limit of $1,250 and may wait through the grace period.
    session.add_all([
        Mandate(user_id=user.id, bill_id=rent.id, payee_paypal_email=rent.payee_paypal_email, max_amount=1250.0,
                earliest_days_before_due=3, latest_days_after_due=rent.grace_days,
                valid_until=add_months(today, 7)),
        Mandate(user_id=user.id, bill_id=phone.id, payee_paypal_email=phone.payee_paypal_email, max_amount=40.0,
                earliest_days_before_due=3, latest_days_after_due=0, valid_until=add_months(today, 12)),
        Mandate(user_id=user.id, bill_id=transit.id, payee_paypal_email=transit.payee_paypal_email, max_amount=60.0,
                earliest_days_before_due=3, latest_days_after_due=0, valid_until=add_months(today, 12)),
        # No mandate for the spring fee: it's in "remind me" mode (pay on the college portal).
    ])

    session.add(IncomeEvent(user_id=user.id, label="Money from home", amount=800.0,
                            start_date=rent_due + timedelta(days=2), recurrence="monthly"))
    # On-campus job (F-1 students can work on campus). First paycheck lands after rent is paid.
    session.add(IncomeEvent(user_id=user.id, label="Campus job paycheck", amount=560.0,
                            start_date=today + timedelta(days=10), recurrence="biweekly"))

    for category, limit in [("Groceries", 60.0), ("Transport", 10.0), ("Eating out", 25.0), ("Fun", 15.0)]:
        session.add(Budget(user_id=user.id, category=category, weekly_limit=limit))

    # Last three weeks of spending (fixed, so the demo looks the same every time).
    spend = [
        (20, "Green Grocer", 24.80), (19, "Corner Cafe", 5.50), (18, "City Transit Card top-up", 10.00),
        (17, "QuickBite Delivery", 16.90), (16, "Green Grocer", 19.35), (15, "StreamBox subscription", 9.99),
        (13, "Campus Bookstore", 34.00), (12, "Green Grocer", 27.10), (11, "Corner Cafe", 5.50),
        (10, "QuickBite Delivery", 21.40), (9, "Movie night", 12.00), (8, "Green Grocer", 22.65),
        (6, "QuickBite Delivery", 18.20), (5, "Corner Cafe", 5.50), (4, "Green Grocer", 18.90),
        (3, "City Transit Card top-up", 10.00), (2, "Corner Cafe", 6.25), (0, "QuickBite Delivery", 18.40),
        (0, "Green Grocer", 21.30),
    ]
    for days_ago, merchant, amount in spend:
        category, need = rule_category(merchant)
        session.add(Transaction(user_id=user.id, date=today - timedelta(days=days_ago), merchant=merchant,
                                category=category, amount=amount, source="seed", is_need=need))

    session.add(Loan(
        user_id=user.id, lender="Shiksha Bank (demo)", principal=4_000_000.0, currency="INR", annual_rate=10.5,
        interest_type="simple", disbursed_date=add_months(today, -15, day=1),
        repayment_start=add_months(today, 12, day=1), term_months=120,
    ))

    state = session.get(AppState, 1) or AppState(id=1)
    state.demo_offset_days = 0
    state.seeded_on = today
    session.add(state)
    session.commit()
    session.refresh(user)
    return user


def get_demo_user(session: Session) -> User | None:
    return session.exec(select(User).where(User.is_demo == True).order_by(User.id)).first()  # noqa: E712
