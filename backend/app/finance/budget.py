"""Weekly budget status per category."""

from dataclasses import dataclass
from datetime import date, timedelta

from app.finance.dates import week_start


@dataclass(frozen=True)
class SpendItem:
    on: date
    category: str
    amount: float


@dataclass(frozen=True)
class BudgetStatus:
    category: str
    weekly_limit: float
    spent: float
    left: float
    percent: float
    status: str  # ok | close | over


def weekly_status(limits: dict[str, float], items: list[SpendItem], today: date) -> list[BudgetStatus]:
    start = week_start(today)
    end = start + timedelta(days=6)
    spent: dict[str, float] = {c: 0.0 for c in limits}
    for it in items:
        if start <= it.on <= end and it.category in spent:
            spent[it.category] += it.amount
    out = []
    for cat, limit in limits.items():
        s = round(spent[cat], 2)
        pct = round(100 * s / limit, 1) if limit > 0 else 0.0
        status = "over" if s > limit else ("close" if pct >= 80 else "ok")
        out.append(BudgetStatus(cat, limit, s, round(limit - s, 2), pct, status))
    return out


CATEGORY_RULES: list[tuple[str, str, bool]] = [
    # (keyword in merchant name, category, is it a need?)
    ("grocer", "Groceries", True),
    ("market", "Groceries", True),
    ("transit", "Transport", True),
    ("bus", "Transport", True),
    ("ride", "Transport", False),
    ("delivery", "Eating out", False),
    ("cafe", "Eating out", False),
    ("café", "Eating out", False),
    ("pizza", "Eating out", False),
    ("stream", "Fun", False),
    ("movie", "Fun", False),
    ("cinema", "Fun", False),
    ("book", "Shopping", True),
    ("pharmacy", "Health", True),
]


def rule_category(merchant: str) -> tuple[str, bool | None]:
    """Keyword rules. The AI handles anything these miss (see ai/categorize.py)."""
    m = merchant.lower()
    for keyword, category, need in CATEGORY_RULES:
        if keyword in m:
            return category, need
    return "Other", None
