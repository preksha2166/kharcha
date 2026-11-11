"""Short, friendly messages. The numbers come from finance/; Gemini only writes the words."""

import json
import logging

from google.genai import types

from app.ai.client import (AIFailed, AIRefused, AIUnavailable, check_refusal, enabled, first_text, generate,
                           thinking)

log = logging.getLogger("kharcha.ai")

SYSTEM = """You write one short money nudge for an international student on a tight budget.
- 1 or 2 sentences, at most 45 words.
- Use ONLY the numbers and dates in the facts. Never invent or recalculate numbers.
- Money is already written like "$1,200". Copy amounts exactly as written.
- Be warm, specific and practical. Say what to do next. Never shame or lecture.
- Plain text, no Markdown (no ** or # symbols). At most one emoji.
- Dream nudges are about something the student is saving for (like a flight home). Celebrate the progress warmly.
- This is general guidance, not financial advice."""


def _money(x) -> str:
    try:
        return f"${float(x):,.2f}".replace(".00", "")
    except (TypeError, ValueError):
        return str(x)


# Fact keys that hold dollar amounts.
MONEY_KEYS = {"amount", "late_fee", "shortfall", "spent", "limit", "safe_to_spend_per_day", "saved", "target", "per_week"}


def facts_for_ai(facts: dict) -> dict:
    """Money as "$1,200" and percents as "85%", so Gemini copies them instead of writing "1200.0"."""
    out = {}
    for key, value in facts.items():
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if is_number and key in MONEY_KEYS:
            out[key] = _money(value)
        elif is_number and key == "percent":
            out[key] = f"{value:.0f}%"
        else:
            out[key] = value
    return out


def template(kind: str, f: dict) -> str:
    if kind == "due_soon":
        head = f"{f['bill']} ({_money(f['amount'])}) is due {f['due']}."
        remind = f.get("pay_mode") == "remind"
        if f["status"] == "ready":
            return head + (f" You have enough. I'll remind you to pay it on {f['pay_on']}." if remind
                           else " You have enough, so autopay will pay it on time.")
        if f["status"] == "waiting_for_money":
            who = "pay it" if remind else "I'll pay"
            return head + (f" Your money from home lands by {f['pay_on']}, so {who} then, "
                           f"still before the late fee starts after {f['last_free_day']}.")
        if f["status"] == "short":
            return head + f" You're about {_money(f['shortfall'])} short. Start a transfer from home by {f['transfer_by']} to avoid the {_money(f['late_fee'])} late fee."
        return head + f" It's past the grace period, so a {_money(f['late_fee'])} late fee may apply. Let's pay it as soon as you can."
    if kind == "budget":
        return (
            f"You've used {f['percent']:.0f}% of this week's {f['category']} budget "
            f"({_money(f['spent'])} of {_money(f['limit'])}). Holding off for a few days keeps your bills safe."
        )
    if kind == "income":
        return f"{f['label']} arrived: +{_money(f['amount'])}."
    if kind == "dream_milestone":
        ready = f" At {_money(f['per_week'])} a week it's ready about {f['ready_on']}." if f.get("ready_on") else ""
        return f"{f['dream']}: {f['percent']:.0f}% saved ({_money(f['saved'])} of {_money(f['target'])}).{ready}"
    if kind == "dream_reached":
        return (f"You did it! {f['dream']} is fully saved ({_money(f['target'])}). "
                "When you buy it, tap 'I bought it' on the Dreams page.")
    return f.get("message", "")


def write_nudge(kind: str, facts: dict) -> tuple[str, bool]:
    """Returns (message, written_by_ai). Falls back to a template if AI is off or fails."""
    if not enabled():
        return template(kind, facts), False
    try:
        response = generate(
            contents=f"Nudge type: {kind}\nFacts (JSON):\n{json.dumps(facts_for_ai(facts), default=str, sort_keys=True)}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                max_output_tokens=2000,
                thinking_config=thinking("low"),
            ),
        )
        check_refusal(response)
        text = first_text(response)
        return (text or template(kind, facts)), bool(text)
    except (AIUnavailable, AIRefused, AIFailed) as exc:
        log.warning("Nudge fallback: %s", exc)
    except Exception as exc:  # network or API errors must never break the daily check
        log.warning("Nudge fallback after API error: %s", exc)
    return template(kind, facts), False
