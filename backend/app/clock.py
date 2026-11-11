"""The app's idea of 'today'. In demo mode the date can be moved forward."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session

from app.config import settings
from app.models import AppState


def real_today() -> date:
    return datetime.now(ZoneInfo(settings.student_timezone)).date()


def get_state(session: Session) -> AppState:
    state = session.get(AppState, 1)
    if state is None:
        state = AppState(id=1, demo_offset_days=0)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def today(session: Session) -> date:
    return real_today() + timedelta(days=get_state(session).demo_offset_days)
