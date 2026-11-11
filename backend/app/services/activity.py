"""Write entries to the Activity log (what the AI and the guard did, and why)."""

import json
import logging
from datetime import date

from sqlmodel import Session, select

from app.models import AgentAction


def already_logged(session: Session, user_id: int, dedupe_key: str) -> bool:
    return session.exec(
        select(AgentAction).where(AgentAction.user_id == user_id, AgentAction.dedupe_key == dedupe_key)
    ).first() is not None


def log_action(
    session: Session,
    *,
    user_id: int,
    kind: str,
    title: str,
    message: str = "",
    on_date: date | None = None,
    allowed: bool | None = None,
    reason: str | None = None,
    bill_id: int | None = None,
    payment_id: int | None = None,
    dedupe_key: str | None = None,
    details: dict | None = None,
) -> AgentAction:
    if dedupe_key:
        existing = session.exec(
            select(AgentAction).where(AgentAction.user_id == user_id, AgentAction.dedupe_key == dedupe_key)
        ).first()
        if existing:
            return existing
    action = AgentAction(
        user_id=user_id,
        kind=kind,
        title=title,
        message=message,
        on_date=on_date,
        allowed=allowed,
        reason=reason,
        bill_id=bill_id,
        payment_id=payment_id,
        dedupe_key=dedupe_key,
        details_json=json.dumps(details, default=str) if details else None,
    )
    session.add(action)
    session.commit()
    session.refresh(action)
    try:
        from app.services.notify import notify_action

        notify_action(session, action)
    except Exception:  # alerts are extra; they must never break a payment or the daily check
        logging.getLogger("kharcha.notify").exception("Couldn't queue an alert")
    return action
