"""Dreams: saving for things the student wants (a flight home, a laptop) without risking a bill.

Money goes in this order: bills first, dreams second, fun third.

- Room for dreams this week: the most Kharcha can set aside every Monday while every bill in the
  forecast is still covered AND the student keeps their weekly budgets. If a bill is short, it's $0.
- Room later: money is often tight only until a big bill (like a term fee) is paid. After that
  tight stretch, the room is the student's normal weekly surplus (income minus bills, budgets and
  loan set-aside), so ready dates aren't stuck at today's worst week.
- Most important dream first. A dream with a date takes what it needs to be ready by that date.
  A dream without a date takes half of what's left, so some spare money stays as a cushion.
- Kharcha sets money aside every Monday. Nothing actually moves: the money stays in the account,
  marked as saved, and safe-to-spend leaves it out.

Pure functions only, so the rules are easy to test.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

SAVE_WEEKDAY = 0  # Monday
UNDATED_SHARE = 0.5
MAX_WEEKS = 260  # look up to 5 years ahead for ready dates


@dataclass(frozen=True)
class DreamSpec:
    id: int
    name: str
    target: float
    saved: float
    target_date: date | None
    priority: int  # 1 = most important
    paused: bool = False


@dataclass(frozen=True)
class Room:
    per_week: float  # whole dollars Kharcha can set aside this Monday
    blocked_by: str | None = None  # why it's $0 because of bills, if it is
    later_per_week: float | None = None  # room after the tight stretch (None: same as now)
    later_from: date | None = None  # first Monday the later room applies
    tight_until: date | None = None  # last day of the stretch that limits this week's room


@dataclass(frozen=True)
class DreamPlan:
    id: int
    left: float
    percent: float
    per_week: float  # what Kharcha sets aside this Monday
    later_per_week: float | None  # what it gets each week after the tight stretch
    needed_per_week: float | None  # what it takes to be ready by the date (dated dreams only)
    starts_on: date | None  # first Monday that gets money
    ready_on: date | None  # when it's fully saved; None if not within 5 years
    status: str  # reached | on_track | behind | saving | starts_later | waiting_for_bills | no_room | paused
    reason: str


def _money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


def _day(d: date, today: date) -> str:
    """'Sat, May 15', or 'May 15, 2028' when it's far away."""
    fmt = "%b %d, %Y" if (d - today).days > 300 else "%a, %b %d"
    return d.strftime(fmt).replace(" 0", " ")


def next_save_day(today: date) -> date:
    """Today if it's a Monday, otherwise the coming Monday."""
    return today + timedelta(days=(SAVE_WEEKDAY - today.weekday()) % 7)


def save_days_until(today: date, last: date) -> int:
    """How many Mondays from today through `last` (both included)."""
    first = next_save_day(today)
    return 0 if last < first else (last - first).days // 7 + 1


def room_per_week(
    *,
    today: date,
    closings: list[float],
    saved_total: float,
    reserve_per_day: float = 0.0,
    short_bill: str | None = None,
    weekly_surplus: float | None = None,
) -> Room:
    """closings[i]: forecast money at the end of day i (expected income, planned bill payments and
    weekly budgets included). reserve_per_day: other money kept aside (loan). weekly_surplus: the
    student's normal spare money per week, used after the tight stretch (None: keep this week's room)."""
    if short_bill:
        return Room(0.0, short_bill)
    later = None if weekly_surplus is None else float(max(0, math.floor(weekly_surplus)))

    # Real risk: the cash itself dips below what's saved for dreams (the loan reserve is only a
    # reservation, so it lowers the room below but doesn't put dream savings at risk).
    if saved_total > 0:
        for i, c in enumerate(closings):
            if c < saved_total:
                need = math.ceil(min(saved_total, saved_total - c))
                return Room(0.0, f"your bills and budgets may need {_money(need)} of your dream savings by "
                                 f"{_day(today + timedelta(days=i), today)}")

    frees = [c - saved_total - reserve_per_day * (i + 1) for i, c in enumerate(closings)]
    negative = [i for i, f in enumerate(frees) if f < 0]
    if negative:
        last = negative[-1]
        if later is None or last == len(frees) - 1:
            return Room(0.0)  # no spare money, and no end to the tight stretch in sight
        tight = today + timedelta(days=last)
        return Room(0.0, None, later, next_save_day(tight + timedelta(days=1)), tight)

    best: float | None = None
    best_day = today
    mondays = 0
    for i, free in enumerate(frees):
        d = today + timedelta(days=i)
        if d.weekday() == SAVE_WEEKDAY:
            mondays += 1
        if mondays and (best is None or free / mondays < best):
            best, best_day = free / mondays, d
    now = float(max(0, math.floor(best or 0)))
    if later is None:
        return Room(now)
    return Room(now, None, later, next_save_day(best_day + timedelta(days=1)), best_day)


def needed_per_week(today: date, left: float, target_date: date) -> float:
    weeks = save_days_until(today, target_date)
    return float(math.ceil(left)) if weeks == 0 else float(math.ceil(left / weeks))


def _room_on(room: Room, monday: date) -> float:
    if room.later_per_week is not None and room.later_from is not None and monday >= room.later_from:
        return room.later_per_week
    return room.per_week


def plan_dreams(dreams: list[DreamSpec], room: Room, today: date) -> list[DreamPlan]:
    """One plan per dream, in priority order. Simulates the Mondays ahead to find ready dates."""
    first = next_save_day(today)
    order = sorted(dreams, key=lambda x: (x.priority, x.id))
    left = {d.id: round(max(0.0, d.target - d.saved), 2) for d in order}
    saving = [d for d in order if not d.paused and left[d.id] > 0]
    this_week: dict[int, float] = {}
    later_amount: dict[int, float] = {}
    starts: dict[int, date] = {}
    ready: dict[int, date] = {}

    if not room.blocked_by and (room.per_week > 0 or (room.later_per_week or 0) > 0):
        for k in range(MAX_WEEKS):
            monday = first + timedelta(weeks=k)
            remaining = _room_on(room, monday)
            for d in saving:
                if d.id in ready:
                    continue
                lft = left[d.id]
                if d.target_date:
                    give = min(needed_per_week(monday, lft, d.target_date), remaining)
                else:
                    give = min(float(math.ceil(lft)), float(math.floor(remaining * UNDATED_SHARE)))
                give = min(float(math.floor(give)), lft) if give >= 1 else 0.0
                remaining -= give
                if k == 0:
                    this_week[d.id] = give
                if room.later_from and monday == next_save_day(max(room.later_from, first)) and d.id not in later_amount:
                    later_amount[d.id] = give
                if give > 0:
                    starts.setdefault(d.id, monday)
                    left[d.id] = round(lft - give, 2)
                    if left[d.id] <= 0:
                        ready[d.id] = monday
            if all(d.id in ready for d in saving):
                break

    plans: list[DreamPlan] = []
    for d in order:
        lft = round(max(0.0, d.target - d.saved), 2)
        percent = round(min(100.0, 100 * d.saved / d.target), 1) if d.target > 0 else 100.0
        need = needed_per_week(today, lft, d.target_date) if (d.target_date and lft > 0) else None
        now = this_week.get(d.id, 0.0)
        later = later_amount.get(d.id) if room.later_from else None
        start, done = starts.get(d.id), ready.get(d.id)
        # Why it starts later: the tight stretch, or more important dreams going first.
        tight_end = max(first, room.later_from) if room.later_from else first
        why_later = "once money is less tight" if (start and start <= tight_end) else "after your more important dreams"

        if lft <= 0:
            status, reason = "reached", "Fully saved. Enjoy it!"
        elif d.paused:
            status, reason = "paused", "Paused by you. Kharcha won't set money aside for it until you resume."
        elif room.blocked_by:
            status, reason = "waiting_for_bills", f"Bills first: {room.blocked_by}. Saving starts once that's covered."
        elif d.target_date and done and done <= d.target_date:
            status = "on_track"
            reason = f"Ready about {_day(done, today)}, in time for {_day(d.target_date, today)}."
            if now == 0 and start:
                reason += f" Saving starts {_day(start, today)}, {why_later}."
        elif d.target_date:
            status = "behind"
            if done:
                reason = (f"Needs {_money(need)} a week to be ready by {_day(d.target_date, today)}. At the pace Kharcha can "
                          f"manage, it's ready about {_day(done, today)}. Move the date or lower a budget.")
            else:
                reason = (f"Needs {_money(need)} a week to be ready by {_day(d.target_date, today)}, but there isn't enough "
                          "spare money for it yet. Lower a budget or move the date.")
        elif done and now > 0:
            status, reason = "saving", f"Ready about {_day(done, today)}."
        elif done:
            status, reason = "starts_later", f"Saving starts {_day(start, today)}, {why_later}. Ready about {_day(done, today)}."
        elif room.per_week == 0 and not room.later_per_week:
            status, reason = "no_room", "No spare money after bills and your budgets right now. Lowering a budget makes room."
        else:
            status, reason = "no_room", "Your more important dreams use all the spare money for now."
        plans.append(DreamPlan(d.id, lft, percent, now, later, need, start, done, status, reason))
    return plans
