"""Dreams in the daily check: bills first, set money aside every Monday, celebrate progress.

Nothing moves between accounts. "Saved" means Kharcha keeps that money out of safe-to-spend.
"""

from datetime import date

from sqlmodel import Session

from app.ai.nudges import write_nudge
from app.finance.dreams import SAVE_WEEKDAY
from app.models import Dream, User
from app.services.activity import already_logged, log_action
from app.services.planner import DreamsState, build_snapshot, saving_dreams, tight_because

MILESTONES = (25, 50, 75)


def _money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


def _day(d: date | None) -> str | None:
    return d.strftime("%a %b %d").replace(" 0", " ") if d else None


def _percent(d: Dream) -> float:
    return 100 * d.saved_amount / d.target_amount if d.target_amount > 0 else 100.0


def on_hold_reason(state: DreamsState, because: str | None) -> str:
    room = state.room
    if room.blocked_by:
        return f"Bills first: {room.blocked_by}. Saving starts again once that's covered."
    if room.later_per_week and room.later_from and room.tight_until:
        why = f" ({because})" if because else ""
        return (f"Money is tight until {_day(room.tight_until)}{why}, so nothing is set aside this week. "
                f"Saving starts again {_day(room.later_from)}.")
    return "No spare money after bills and your budgets this week. Lowering a budget makes room."


def protect_bills_first(session: Session, user: User, day: date) -> None:
    """If bills used money that was saved for dreams, take it from the least important dream first."""
    rows = saving_dreams(session, user.id)
    over = round(sum(d.saved_amount for d in rows) - max(0.0, user.current_money), 2)
    if over <= 0:
        return
    taken: list[tuple[Dream, float]] = []
    for d in reversed(rows):
        if over <= 0:
            break
        take = round(min(d.saved_amount, over), 2)
        if take <= 0:
            continue
        d.saved_amount = round(d.saved_amount - take, 2)
        if d.status == "reached":
            d.status = "active"
        over = round(over - take, 2)
        taken.append((d, take))
        session.add(d)
    session.commit()
    total = sum(t for _, t in taken)
    log_action(session, user_id=user.id, kind="dream", on_date=day, title="Bills came first",
               message=f"Your bills needed {_money(total)} that was saved for dreams, so it came from "
                       + ", ".join(f"{d.name} (-{_money(t)})" for d, t in taken)
                       + ". Kharcha keeps saving from what's spare.",
               details={"taken": {d.name: t for d, t in taken}})


def celebrate(session: Session, user: User, day: date, d: Dream, before_percent: float,
              per_week: float, ready_on: date | None) -> None:
    """A message when a dream crosses 25%, 50%, 75%, or is fully saved."""
    after = _percent(d)
    if d.saved_amount >= d.target_amount:
        d.status = "reached"
        session.add(d)
        session.commit()
        facts = {"dream": d.name, "target": d.target_amount, "saved": d.saved_amount}
        msg, by_ai = write_nudge("dream_reached", facts)
        log_action(session, user_id=user.id, kind="dream", on_date=day, title=f"{d.emoji} {d.name} is fully saved!",
                   message=msg, dedupe_key=f"dream:{d.id}:100", details={**facts, "written_by_ai": by_ai})
        return
    crossed = [m for m in MILESTONES if before_percent < m <= after]
    if not crossed:
        return
    facts = {"dream": d.name, "percent": after, "saved": d.saved_amount, "target": d.target_amount,
             "per_week": per_week, "ready_on": _day(ready_on), "target_date": _day(d.target_date)}
    msg, by_ai = write_nudge("dream_milestone", facts)
    log_action(session, user_id=user.id, kind="dream", on_date=day, title=f"{d.emoji} {d.name}: {crossed[-1]}% saved",
               message=msg, dedupe_key=f"dream:{d.id}:{crossed[-1]}", details={**facts, "written_by_ai": by_ai})


def weekly_set_aside(session: Session, user: User, day: date) -> None:
    """Every Monday: add each dream's weekly amount to its savings (once per Monday)."""
    if day.weekday() != SAVE_WEEKDAY:
        return
    key = f"dreams:{day.isoformat()}"
    if already_logged(session, user.id, key):
        return
    snap = build_snapshot(session, user, day)
    state = snap.dreams
    waiting = [d for d in state.rows if d.status == "active" and d.saved_amount < d.target_amount]
    if not waiting:
        return

    added: list[tuple[Dream, float, float]] = []
    for d in waiting:
        plan = state.plans.get(d.id)
        if not plan or plan.per_week <= 0 or d.last_saved_on == day:
            continue
        amount = round(min(plan.per_week, d.target_amount - d.saved_amount), 2)
        before = _percent(d)
        d.saved_amount = round(d.saved_amount + amount, 2)
        d.last_saved_on = day
        session.add(d)
        added.append((d, amount, before))
    session.commit()

    if not added:
        log_action(session, user_id=user.id, kind="dream", on_date=day, title="Dreams on hold this week",
                   message=on_hold_reason(state, tight_because(snap.items, state.room.tight_until)),
                   dedupe_key=key, reason=state.room.blocked_by)
        return
    total = sum(a for _, a, _ in added)
    log_action(session, user_id=user.id, kind="dream", on_date=day, title=f"Set aside {_money(total)} for your dreams",
               message=" · ".join(f"{d.emoji} {d.name} +{_money(a)}" for d, a, _ in added)
                       + ". The money stays in your account; safe-to-spend leaves it out.",
               dedupe_key=key, details={d.name: a for d, a, _ in added})
    for d, _, before in added:
        plan = state.plans[d.id]
        celebrate(session, user, day, d, before, plan.per_week, plan.ready_on)


def run_dreams(session: Session, user: User, day: date) -> None:
    session.refresh(user)
    protect_bills_first(session, user, day)
    weekly_set_aside(session, user, day)
