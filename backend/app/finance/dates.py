"""Small date helpers for monthly bills and income."""

import calendar
from collections.abc import Iterator
from datetime import date, timedelta


def add_months(d: date, months: int, day: int | None = None) -> date:
    """Move d by N months. Keeps `day` (or d.day), clamped to the month's length."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    wanted = day if day is not None else d.day
    return date(year, month, min(wanted, calendar.monthrange(year, month)[1]))


def monthly_due_date(year: int, month: int, due_day: int) -> date:
    return date(year, month, min(due_day, calendar.monthrange(year, month)[1]))


def period_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_between(start: date, end: date) -> int:
    """Whole months from start to end (0 if end <= start)."""
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def daterange(start: date, end_inclusive: date) -> Iterator[date]:
    d = start
    while d <= end_inclusive:
        yield d
        d += timedelta(days=1)


def week_start(d: date) -> date:
    """Monday of d's week."""
    return d - timedelta(days=d.weekday())
