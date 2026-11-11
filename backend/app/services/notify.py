"""Alerts outside the app, both free:

- Phone / browser notifications (Web Push). The student taps "Turn on" once; their browser gives us a
  subscription. VAPID keys come from .env, or are made once and saved in the database.
- Email, through any SMTP account (for example a Gmail app password or a free Brevo account).

Sending happens on a small background thread, so a slow email server never slows the app down.
"""

import base64
import json
import logging
import smtplib
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlmodel import Session, select

from app.clock import get_state
from app.config import settings
from app.models import AgentAction, PushSubscription, User

log = logging.getLogger("kharcha.notify")

# Which Activity entries also go to the phone / email. Weekly dream set-asides ("dreams:" keys) stay in the app.
ALERT_KINDS = {"payment", "block", "approval", "nudge", "dream"}
QUIET_KEYS = ("dreams:",)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kharcha-notify")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def vapid_keys(session: Session) -> tuple[str, str]:
    """(public key the browser needs, private key we sign with)."""
    if settings.vapid_public_key and settings.vapid_private_key:
        return settings.vapid_public_key, settings.vapid_private_key
    state = get_state(session)
    if not state.vapid_private_key or not state.vapid_public_key:
        key = ec.generate_private_key(ec.SECP256R1())
        state.vapid_private_key = _b64url(key.private_numbers().private_value.to_bytes(32, "big"))
        state.vapid_public_key = _b64url(key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        session.add(state)
        session.commit()
    return state.vapid_public_key, state.vapid_private_key


def wants_alert(action: AgentAction) -> bool:
    if action.kind not in ALERT_KINDS:
        return False
    return not (action.dedupe_key or "").startswith(QUIET_KEYS)


def notify_action(session: Session, action: AgentAction) -> None:
    """Called for every new Activity entry. Sends it on if it matters and the student turned alerts on."""
    if not wants_alert(action):
        return
    user = session.get(User, action.user_id)
    if user is None:
        return
    send(session, user, title=action.title, body=action.message, url="/activity")


def send(session: Session, user: User, *, title: str, body: str, url: str = "/") -> dict:
    """Queue a push to every device of this student, and an email if they turned it on."""
    subs = session.exec(select(PushSubscription).where(PushSubscription.user_id == user.id)).all()
    email_to = user.email if (user.notify_email and user.email and settings.email_enabled) else None
    if not subs and not email_to:
        return {"push": 0, "email": False}
    public, private = vapid_keys(session) if subs else ("", "")
    targets = [{"id": s.id, "endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}} for s in subs]
    payload = {"title": title[:120], "body": (body or "")[:300], "url": url}
    _pool.submit(_deliver, targets, private, payload, email_to)
    return {"push": len(targets), "email": bool(email_to)}


def _deliver(targets: list[dict], private_key: str, payload: dict, email_to: str | None) -> None:
    gone: list[int] = []
    for t in targets:
        try:
            _push(t, private_key, payload)
        except _Gone:
            gone.append(t["id"])
        except Exception as exc:  # one bad device must not stop the others
            log.warning("Push failed: %s", exc)
    if gone:
        _forget(gone)
    if email_to:
        try:
            send_email(email_to, f"Kharcha: {payload['title']}", f"{payload['body']}\n\nOpen Kharcha: {settings.frontend_url}{payload['url']}")
        except Exception as exc:
            log.warning("Email failed: %s", exc)


class _Gone(Exception):
    """The browser unsubscribed (HTTP 404/410): forget this device."""


def _push(target: dict, private_key: str, payload: dict) -> None:
    from pywebpush import WebPushException, webpush

    try:
        webpush(subscription_info={"endpoint": target["endpoint"], "keys": target["keys"]}, data=json.dumps(payload),
                vapid_private_key=private_key, vapid_claims={"sub": settings.vapid_subject}, ttl=24 * 3600, timeout=15)
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            raise _Gone() from exc
        raise


def _forget(ids: list[int]) -> None:
    from app.db import engine

    with Session(engine) as session:
        for sub_id in ids:
            sub = session.get(PushSubscription, sub_id)
            if sub:
                session.delete(sub)
        session.commit()


def send_email(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if settings.smtp_port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        server.starttls()
    with server:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
