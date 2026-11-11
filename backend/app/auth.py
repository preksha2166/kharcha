"""Logins: "Log in with PayPal" (OpenID Connect) plus our own session tokens.

Flow (the React app drives it):
1. The app makes a random `state`, keeps it, and asks us for PayPal's login URL.
2. PayPal sends the student back to FRONTEND_URL/auth/paypal/return?code=...&state=...
3. The app checks `state`, then sends us the code. We swap it for an access token, read the
   student's PayPal id and email, find or create their Kharcha account, and return a session token.

We store only a SHA-256 hash of each session token. In mock mode (no PayPal keys) the login is
simulated, like the rest of the PayPal integration.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlmodel import Session, select

from app.config import settings
from app.models import AuthSession, Budget, User
from app.paypal.client import PayPalError, is_mock

SESSION_DAYS = 30
SCOPES = "openid profile email"
MOCK_CODE = "MOCK-LOGIN"
# A starting point for new students; they change these on the Spending page.
STARTER_BUDGETS = [("Groceries", 60.0), ("Transport", 10.0), ("Eating out", 25.0), ("Fun", 15.0)]


def redirect_uri() -> str:
    """Must match the Return URL set for "Log in with PayPal" in the PayPal app settings."""
    return f"{settings.frontend_url}/auth/paypal/return"


def login_url(state: str) -> str:
    if is_mock():
        return f"{redirect_uri()}?{urlencode({'code': MOCK_CODE, 'state': state})}"
    params = {
        "flowEntry": "static",
        "client_id": settings.paypal_client_id,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": redirect_uri(),
        "state": state,
    }
    return f"{settings.paypal_web_url}/connect?{urlencode(params)}"


def paypal_identity(code: str) -> dict:
    """Swap the login code for the student's PayPal id, email and first name."""
    if is_mock():
        if code != MOCK_CODE:
            raise PayPalError(400, "Unknown mock login code")
        return {"id": "mock-student", "email": "student@example.com", "name": "Student"}

    token = httpx.post(
        f"{settings.paypal_base_url}/v1/oauth2/token",
        auth=(settings.paypal_client_id, settings.paypal_client_secret),
        data={"grant_type": "authorization_code", "code": code},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if token.status_code != 200:
        body = _json(token)
        raise PayPalError(token.status_code, body.get("error_description") or body.get("message")
                          or "PayPal didn't accept the login code. Please try again.")
    access = token.json()["access_token"]
    info = httpx.get(
        f"{settings.paypal_base_url}/v1/identity/oauth2/userinfo",
        params={"schema": "paypalv1.1"},
        headers={"Authorization": f"Bearer {access}", "Accept": "application/json"},
        timeout=30,
    )
    if info.status_code != 200:
        body = _json(info)
        raise PayPalError(info.status_code, body.get("message") or "Couldn't read your PayPal profile.")
    return parse_userinfo(info.json())


def parse_userinfo(body: dict) -> dict:
    """PayPal's userinfo comes in two shapes (paypalv1.1 and openid); accept both."""
    emails = body.get("emails") or []
    primary = next((e for e in emails if e.get("primary")), emails[0] if emails else None)
    email = (primary or {}).get("value") or body.get("email")
    pid = body.get("payer_id") or body.get("user_id") or body.get("sub")
    name = body.get("given_name") or (body.get("name") or "").split(" ")[0] or "Student"
    if not pid:
        raise PayPalError(502, "PayPal didn't send an account id.")
    return {"id": str(pid), "email": email, "name": name}


def find_or_create_user(session: Session, identity: dict) -> tuple[User, bool]:
    user = session.exec(select(User).where(User.paypal_login_id == identity["id"])).first()
    if user:
        if identity.get("email") and not user.email:
            user.email = identity["email"]
            session.add(user)
            session.commit()
        return user, False
    user = User(name=identity.get("name") or "Student", email=identity.get("email"), paypal_login_id=identity["id"],
                current_money=0.0, timezone=settings.student_timezone)
    session.add(user)
    session.commit()
    session.refresh(user)
    for category, limit in STARTER_BUDGETS:
        session.add(Budget(user_id=user.id, category=category, weekly_limit=limit))
    session.commit()
    return user, True


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(user_id=user.id, token_hash=_hash(token),
                            expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)))
    session.commit()
    return token


def user_for_token(session: Session, token: str) -> User | None:
    row = session.exec(select(AuthSession).where(AuthSession.token_hash == _hash(token))).first()
    if row is None:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        session.delete(row)
        session.commit()
        return None
    return session.get(User, row.user_id)


def end_session(session: Session, token: str) -> None:
    row = session.exec(select(AuthSession).where(AuthSession.token_hash == _hash(token))).first()
    if row:
        session.delete(row)
        session.commit()


def _json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {}
