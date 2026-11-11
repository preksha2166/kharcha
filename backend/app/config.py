"""App settings, read once from environment variables (and backend/.env if present)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _str(name: str, default: str) -> str:
    """A blank value counts as unset (hosts like Render can create a variable you left empty)."""
    return (os.getenv(name) or "").strip() or default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    paypal_client_id: str
    paypal_client_secret: str
    paypal_base_url: str
    paypal_webhook_id: str
    demo_landlord_email: str
    demo_college_email: str
    gemini_api_key: str
    ai_model: str
    database_url: str
    demo_mode: bool
    frontend_url: str
    fx_inr_per_usd: float
    student_timezone: str
    paypal_fee_percent: float  # estimate shown to the student; check PayPal's fee page for your country
    paypal_fee_fixed: float
    cron_secret: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    vapid_public_key: str
    vapid_private_key: str
    vapid_subject: str

    @property
    def paypal_mode(self) -> str:
        """'sandbox' when credentials are set, otherwise 'mock' (fake responses)."""
        return "sandbox" if self.paypal_client_id and self.paypal_client_secret else "mock"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def paypal_web_url(self) -> str:
        """Where people log in to PayPal (sandbox or live), matching the API base URL."""
        return "https://www.sandbox.paypal.com" if "sandbox" in self.paypal_base_url else "https://www.paypal.com"

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


def _database_url(raw: str) -> str:
    """Neon/Render/Supabase give 'postgres://' or 'postgresql://' URLs; SQLAlchemy needs the psycopg driver name."""
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    return raw


def load_settings() -> Settings:
    return Settings(
        paypal_client_id=os.getenv("PAYPAL_CLIENT_ID", "").strip(),
        paypal_client_secret=os.getenv("PAYPAL_CLIENT_SECRET", "").strip(),
        paypal_base_url=_str("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"),
        paypal_webhook_id=os.getenv("PAYPAL_WEBHOOK_ID", "").strip(),
        demo_landlord_email=os.getenv("DEMO_LANDLORD_EMAIL", "").strip() or "landlord@example.com",
        demo_college_email=os.getenv("DEMO_COLLEGE_EMAIL", "").strip() or "college@example.com",
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        ai_model=os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.6-flash",
        database_url=_database_url(_str("DATABASE_URL", "sqlite:///./kharcha.db")),
        demo_mode=_bool("DEMO_MODE", True),
        frontend_url=_str("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
        fx_inr_per_usd=float(os.getenv("FX_INR_PER_USD", "88") or 88),
        student_timezone=_str("STUDENT_TIMEZONE", "America/Los_Angeles"),
        paypal_fee_percent=float(os.getenv("PAYPAL_FEE_PERCENT", "3.49") or 3.49),
        paypal_fee_fixed=float(os.getenv("PAYPAL_FEE_FIXED", "0.49") or 0.49),
        cron_secret=os.getenv("CRON_SECRET", "").strip(),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587") or 587),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        vapid_public_key=os.getenv("VAPID_PUBLIC_KEY", "").strip(),
        vapid_private_key=os.getenv("VAPID_PRIVATE_KEY", "").strip(),
        vapid_subject=os.getenv("VAPID_SUBJECT", "").strip() or "mailto:kharcha-demo@example.com",
    )


settings = load_settings()
