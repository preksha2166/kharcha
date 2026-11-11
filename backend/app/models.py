"""Database tables. See ARCHITECTURE.md section 6."""

from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppState(SQLModel, table=True):
    """Single row (id=1). Holds the demo clock offset."""

    id: int = Field(default=1, primary_key=True)
    demo_offset_days: int = 0
    seeded_on: Optional[date] = None
    # Web push keys, made on first start when VAPID_* aren't set in .env.
    vapid_private_key: Optional[str] = None
    vapid_public_key: Optional[str] = None


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: Optional[str] = None  # from Log in with PayPal; used for email alerts
    paypal_login_id: Optional[str] = Field(default=None, index=True)  # PayPal account id from Log in with PayPal
    is_demo: bool = False  # the seeded demo student (used without logging in, in demo mode)
    timezone: str = "America/Los_Angeles"
    current_money: float = 0.0  # student-entered (PayPal doesn't let apps read a personal balance)
    balance_checked_on: Optional[date] = None  # last time the student confirmed their balance
    safety_cushion: float = 50.0  # Kharcha never plans to leave less than this
    last_check_on: Optional[date] = None  # last day the daily check ran (for catching up missed days)
    notify_email: bool = False  # send alerts by email too
    created_at: datetime = Field(default_factory=utcnow)
    transfer_days_from_home: int = 4  # how long money from home takes to arrive
    loan_set_aside_monthly: float = 0.0  # USD the student wants to reserve for the loan each month
    paypal_vault_id: Optional[str] = None  # PayPal payment token id (saved PayPal)
    paypal_customer_id: Optional[str] = None
    paypal_payer_email: Optional[str] = None
    paypal_connected_mock: bool = False


class IncomeEvent(SQLModel, table=True):
    """Money the student expects: money from home, campus job pay."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    label: str
    amount: float
    start_date: date
    recurrence: str = "monthly"  # once | monthly | biweekly
    last_received: Optional[date] = None


class Bill(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str
    category: str = "other"  # rent | tuition | transit | phone | other
    payee_name: str
    payee_paypal_email: str
    amount: float
    currency: str = "USD"
    recurrence: str = "monthly"  # monthly | once
    due_day: Optional[int] = None  # monthly bills: day of month (1-28)
    due_date: Optional[date] = None  # one-time bills
    start_date: date  # first due date the app tracks
    grace_days: int = 0  # days after the due date with no late fee
    late_fee: float = 0.0
    document_id: Optional[int] = Field(default=None, foreign_key="document.id")
    active: bool = True
    # remind: Kharcha tells you the best day and you pay it yourself (free).
    # paypal: Kharcha pays with your saved PayPal, inside your autopay limits.
    pay_mode: str = "paypal"


class Mandate(SQLModel, table=True):
    """The student's one-time permission: 'pay this payee up to $X in this window'."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    bill_id: int = Field(foreign_key="bill.id")
    payee_paypal_email: str
    max_amount: float
    earliest_days_before_due: int = 3
    latest_days_after_due: int = 0  # set to the grace period so smart timing can wait for money
    valid_until: date
    paused: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Payment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    bill_id: int = Field(foreign_key="bill.id")
    mandate_id: Optional[int] = Field(default=None, foreign_key="mandate.id")
    period: str  # "2026-12" for monthly bills, "once" for one-time bills
    amount: float
    status: str  # needs_approval | processing | completed | failed | blocked
    trigger: str = "autopay"  # autopay | manual | agent
    paypal_order_id: Optional[str] = None
    paypal_capture_id: Optional[str] = None
    payout_batch_id: Optional[str] = None
    payout_status: Optional[str] = None
    request_id: Optional[str] = None
    mock: bool = False
    failure_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    paid_on: Optional[date] = None  # demo-clock date the payment completed


class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    date: date
    merchant: str
    category: str = "Other"
    amount: float
    source: str = "seed"  # kharcha | csv | seed | manual
    is_need: Optional[bool] = None
    counted_in_balance: bool = False  # True if it lowered current_money (newer than the last balance check)


class Budget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    category: str
    weekly_limit: float


class Loan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    lender: str
    principal: float
    currency: str = "INR"
    annual_rate: float  # percent, e.g. 10.5
    interest_type: str = "simple"  # simple | compound (during the study period)
    disbursed_date: date
    repayment_start: date
    term_months: int
    document_id: Optional[int] = Field(default=None, foreign_key="document.id")


class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    kind: str = "other"  # lease | fee_notice | loan_letter | other
    filename: str
    uploaded_at: datetime = Field(default_factory=utcnow)
    extracted_json: Optional[str] = None
    status: str = "review"  # review | confirmed
    mock: bool = False


class AgentAction(SQLModel, table=True):
    """Everything the AI and the guard did, shown in the Activity log."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    at: datetime = Field(default_factory=utcnow)
    on_date: Optional[date] = None  # demo-clock date
    kind: str  # nudge | proposal | payment | block | approval | income | chat | info | dream
    title: str
    message: str = ""
    allowed: Optional[bool] = None
    reason: Optional[str] = None
    bill_id: Optional[int] = None
    payment_id: Optional[int] = None
    dedupe_key: Optional[str] = Field(default=None, index=True)
    details_json: Optional[str] = None


class Dream(SQLModel, table=True):
    """Something the student is saving for. The money stays in their account, marked as saved."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str
    emoji: str = "⭐"
    target_amount: float
    saved_amount: float = 0.0
    target_date: Optional[date] = None  # None: "whenever there's room"
    priority: int = 1  # 1 = most important
    status: str = "active"  # proposed | active | paused | reached | bought
    created_at: datetime = Field(default_factory=utcnow)
    last_saved_on: Optional[date] = None  # demo-clock date of the last weekly set-aside
    bought_on: Optional[date] = None
    bought_price: Optional[float] = None


class AuthSession(SQLModel, table=True):
    """A login. The browser keeps the token; we only store its SHA-256 hash."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime


class PushSubscription(SQLModel, table=True):
    """A phone or browser that gets Kharcha's alerts (Web Push)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    endpoint: str = Field(unique=True)
    p256dh: str
    auth: str
    created_at: datetime = Field(default_factory=utcnow)
