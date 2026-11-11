"""'Ask Kharcha': a Gemini agent with read-only money tools plus ONE action tool.

The action tool, propose_payment, can only create a request that the student approves
with a tap. The agent can't move money, change limits, or approve its own requests.
"""

import json
import logging
from datetime import date, timedelta

from google.genai import types
from sqlmodel import Session, select

from app import views
from app.ai.client import AIRefused, AIUnavailable, check_refusal, enabled, first_text, generate, thinking
from app.config import settings
from app.finance.dreams import plan_dreams, room_per_week
from app.finance.loan import compare
from app.finance.safe_to_spend import safe_to_spend
from app.guard.mandates import check_payment
from app.models import Bill, Dream, Loan, Payment, Transaction, User
from app.services.autopay import request_approval
from app.services.planner import (PAID_STATUSES, Snapshot, build_snapshot, dream_spec, dreams_state, mandate_spec,
                                  short_bill_text)
from app.views import iso, loan_spec, planned_view

log = logging.getLogger("kharcha.agent")

MAX_ROUNDS = 6


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TOOLS = [
    {
        "name": "get_overview",
        "description": "Current money, safe-to-spend per day, the next unpaid occurrence of every bill with its smart-timing plan, and this week's budgets. Call this first for most questions.",
        "input_schema": _schema({}, []),
    },
    {
        "name": "get_upcoming_bills",
        "description": "Unpaid bills due within the next N days (1-60), each with due date, planned pay date, status and shortfall.",
        "input_schema": _schema({"days": {"type": "integer", "description": "Days ahead, 1 to 60"}}, ["days"]),
    },
    {
        "name": "get_spending",
        "description": "Spending totals by category and top merchants for the last N days. Use category '' for all categories.",
        "input_schema": _schema(
            {"days": {"type": "integer"}, "category": {"type": "string", "description": "Category name or '' for all"}},
            ["days", "category"],
        ),
    },
    {
        "name": "check_affordability",
        "description": "Checks if spending a one-off amount today still keeps every bill in the next 30 days covered. Returns safe-to-spend before and after.",
        "input_schema": _schema(
            {"amount": {"type": "number"}, "what": {"type": "string", "description": "What the money is for"}},
            ["amount", "what"],
        ),
    },
    {
        "name": "loan_scenario",
        "description": "Compares the education loan's total cost if the student pays nothing during studies vs. a fixed monthly amount (in the loan's currency, usually INR) toward interest.",
        "input_schema": _schema({"monthly_payment": {"type": "number"}}, ["monthly_payment"]),
    },
    {
        "name": "get_dreams",
        "description": "The student's dreams (things they're saving for): saved so far, weekly amount Kharcha sets aside, ready date and status, plus this week's room for dreams. Bills come first, dreams second.",
        "input_schema": _schema({}, []),
    },
    {
        "name": "propose_dream",
        "description": "Suggest a new dream (something to save for, like a flight home or a laptop). This does NOT save it: it creates a suggestion the student saves with one tap, and returns Kharcha's plan for it (weekly amount, ready date, or why it must wait for bills). One call per dream.",
        "input_schema": _schema(
            {
                "name": {"type": "string", "description": "Short name, like 'Flight home' or 'New laptop'"},
                "target_amount": {"type": "number", "description": "Cost in USD"},
                "target_date": {"type": "string", "description": "Wanted-by date as YYYY-MM-DD, or '' if the student gave no date"},
                "emoji": {"type": "string", "description": "One fitting emoji"},
                "already_saved": {"type": "number", "description": "USD already saved for it, 0 if none"},
            },
            ["name", "target_amount", "target_date", "emoji", "already_saved"],
        ),
    },
    {
        "name": "propose_payment",
        "description": "Ask the student to approve paying a bill now (for example paying early). This does NOT pay. It runs the guard rules and creates an approval request the student must tap. Use only when the student asks to pay or clearly benefits.",
        "input_schema": _schema(
            {"bill_id": {"type": "integer"}, "reason": {"type": "string", "description": "One sentence shown to the student"}},
            ["bill_id", "reason"],
        ),
    },
]

# Gemini's form of the same tools. A tool with no inputs gets no schema at all.
GEMINI_TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name=t["name"],
        description=t["description"],
        parameters_json_schema=t["input_schema"] if t["input_schema"]["properties"] else None,
    )
    for t in TOOLS
])


def _system(today: date) -> str:
    return f"""You are Kharcha, a friendly money assistant for an international student in the US who lives on a loan and money from home.

Today is {today.isoformat()} (use this date, not your own sense of time).

Rules:
- Get numbers from the tools before answering any money question. Never invent or recalculate numbers yourself; quote what the tools return.
- You cannot move money. propose_payment only creates a request that the student approves in the app. Say that clearly when you use it.
- Keep answers short: under 90 words, plain language, concrete next step. Use $ amounts.
- Plain text only: no Markdown, no ** or # symbols, no bullet lists. The app shows your reply as plain text.
- When money is tight, be kind and practical, never judgmental.
- Dreams are things the student is saving for (a flight home, a laptop). Money goes bills first, dreams second, fun third. Every Monday Kharcha sets money aside from what's truly spare; the money stays in their account and safe-to-spend leaves it out.
- When the student says they want to buy or save for something, call propose_dream (one call per dream). It only creates a suggestion they save with one tap. If they gave no date, pass '' and don't ask for one; tell them the ready date the tool returns.
- If a dream must wait for bills, say so kindly and say what would unblock it (for example, asking family for the short bill's amount). If a dream is behind, offer one concrete fix: a later date or a lower budget.
- check_affordability shows whether spending would push a dream later; mention it when it does.
- needed_per_week is what a dream would need to make its date, not a promise. Only promise a weekly amount or ready date the tool returned as the plan (this_week, later_per_week, ready_on).
- This is general guidance, not financial advice. For loan decisions, suggest confirming with the lender."""


def _dreams_summary(snap: Snapshot) -> dict:
    state = snap.dreams
    return {
        "room_this_week": state.room.per_week,
        "room_later_per_week": state.room.later_per_week,
        "room_later_from": iso(state.room.later_from),
        "normal_spare_per_week": state.weekly_surplus,
        "on_hold_because": state.room.blocked_by,
        "saved_total": state.saved_total,
        "set_aside_per_week": state.per_week,
        "dreams": [
            {k: v for k, v in views.dream_view(d, state.plans.get(d.id)).items()
             if k in {"id", "name", "target_amount", "saved_amount", "target_date", "status", "percent", "per_week",
                      "later_per_week", "starts_on", "needed_per_week", "ready_on", "plan_status", "reason"}}
            for d in state.rows
        ],
    }


def _dream_impact(snap: Snapshot, amount: float) -> list[dict]:
    """Which dreams would be ready later if the student spent `amount` today."""
    state = snap.dreams
    if not state.rows:
        return []
    room = room_per_week(today=snap.today, closings=[p.closing - state.cushion - amount for p in snap.points],
                         saved_total=state.saved_total, reserve_per_day=snap.user.loan_set_aside_monthly / 30.0,
                         short_bill=short_bill_text(snap.items), weekly_surplus=state.weekly_surplus)
    after = {p.id: p for p in plan_dreams([dream_spec(d) for d in state.rows], room, snap.today)}
    out = []
    for d in state.rows:
        b, a = state.plans.get(d.id), after.get(d.id)
        if b and a and (b.ready_on != a.ready_on or b.status != a.status):
            out.append({"dream": d.name, "ready_before": iso(b.ready_on), "ready_after": iso(a.ready_on),
                        "status_after": a.status})
    return out


def _propose_dream(session: Session, user: User, today: date, snap: Snapshot, args: dict) -> dict:
    target = float(args.get("target_amount") or 0)
    if target <= 0:
        return {"error": "target_amount must be more than 0."}
    target_date = None
    raw = str(args.get("target_date") or "").strip()
    if raw:
        try:
            target_date = date.fromisoformat(raw)
        except ValueError:
            return {"error": "target_date must be YYYY-MM-DD, or '' for no date."}
        if target_date <= today:
            return {"error": f"target_date must be after today ({today.isoformat()})."}
    saved = min(max(0.0, float(args.get("already_saved") or 0)), target)
    free = max(0.0, user.current_money - snap.dreams.saved_total)
    if saved > free + 0.005:
        return {"error": f"Only ${free:,.0f} of the student's money isn't saved for other dreams yet."}
    d = Dream(user_id=user.id, name=str(args.get("name") or "My dream").strip()[:60],
              emoji=str(args.get("emoji") or "").strip()[:8] or "⭐", target_amount=round(target, 2),
              saved_amount=round(saved, 2), target_date=target_date, priority=10_000, status="proposed")
    session.add(d)
    session.commit()
    session.refresh(d)
    state = dreams_state(session, user, today, snap.points, snap.items, extra=d)
    plan = state.plans[d.id]
    return {
        "created_suggestion": True,
        "dream_id": d.id,
        "needs_student_tap": True,
        "plan": {"this_week": plan.per_week, "later_per_week": plan.later_per_week, "starts_on": iso(plan.starts_on),
                 "needed_per_week": plan.needed_per_week, "ready_on": iso(plan.ready_on), "status": plan.status,
                 "reason": plan.reason},
        "on_hold_because": state.room.blocked_by,
    }


def _run_tool(session: Session, user: User, today: date, name: str, args: dict) -> dict:
    snap = build_snapshot(session, user, today)

    if name == "get_overview":
        return {
            "money_now": user.current_money,
            "safe_to_spend_per_day": snap.safe.per_day,
            "shortfall_next_30_days": snap.safe.shortfall,
            "bills": [planned_view(i, today) for i in snap.current.values()],
            "planned_daily_spending_from_budgets": snap.daily_spend,
            "dreams": _dreams_summary(snap),
        }

    if name == "get_dreams":
        return {**_dreams_summary(snap), "make_room_by_lowering_a_budget": views.make_room(session, snap)}

    if name == "propose_dream":
        return _propose_dream(session, user, today, snap, args)

    if name == "get_upcoming_bills":
        days = max(1, min(60, int(args["days"])))
        end = today + timedelta(days=days)
        return {"bills": [planned_view(i, today) for i in snap.items if i.due <= end]}

    if name == "get_spending":
        days = max(1, min(90, int(args["days"])))
        cat = (args.get("category") or "").strip()
        start = today - timedelta(days=days - 1)
        txs = session.exec(select(Transaction).where(Transaction.user_id == user.id, Transaction.date >= start,
                                                     Transaction.date <= today)).all()
        if cat:
            txs = [t for t in txs if t.category.lower() == cat.lower()]
        by_cat: dict[str, float] = {}
        by_merchant: dict[str, float] = {}
        for t in txs:
            by_cat[t.category] = round(by_cat.get(t.category, 0) + t.amount, 2)
            by_merchant[t.merchant] = round(by_merchant.get(t.merchant, 0) + t.amount, 2)
        top = sorted(by_merchant.items(), key=lambda kv: -kv[1])[:5]
        return {"days": days, "total": round(sum(by_cat.values()), 2), "by_category": by_cat, "top_merchants": top}

    if name == "check_affordability":
        amount = float(args["amount"])
        base = dict(money_now=user.current_money - amount, today=today, incomes=snap.incomes, outflows=snap.outflows,
                    loan_set_aside_monthly=user.loan_set_aside_monthly, cushion=snap.dreams.cushion)
        after = safe_to_spend(**base, dreams_saved=snap.dreams.saved_total, dreams_per_week=snap.dreams.per_week)
        bills_only = safe_to_spend(**base)
        return {
            "what": args.get("what"),
            "amount": amount,
            "safe_per_day_before": snap.safe.per_day,
            "safe_per_day_after": after.per_day,
            "bills_still_covered": bills_only.shortfall == 0,
            "would_use_money_saved_for_dreams": bills_only.shortfall == 0 and after.shortfall > 0,
            "shortfall_after": bills_only.shortfall,
            "dreams_pushed_later": _dream_impact(snap, amount),
        }

    if name == "loan_scenario":
        loan = session.exec(select(Loan).where(Loan.user_id == user.id)).first()
        if not loan:
            return {"error": "No loan on file yet. Upload the loan letter first."}
        c = compare(loan_spec(loan), today, float(args["monthly_payment"]))
        return {
            "currency": loan.currency,
            "fx_inr_per_usd_demo_rate": settings.fx_inr_per_usd,
            "monthly_payment_during_study": float(args["monthly_payment"]),
            "study_months_left": c["scenario"].study_months_left,
            "baseline_total_paid": c["baseline"].total_paid,
            "scenario_total_paid": c["scenario"].total_paid,
            "savings": c["savings"],
            "baseline_monthly_payment_after_study": c["baseline"].monthly_payment,
            "scenario_monthly_payment_after_study": c["scenario"].monthly_payment,
        }

    if name == "propose_payment":
        bill = session.get(Bill, int(args["bill_id"]))
        if not bill or bill.user_id != user.id:
            return {"error": "No such bill."}
        item = snap.current.get(bill.id)
        if not item:
            return {"error": "Nothing is due for this bill right now."}
        already = any(p.status in PAID_STATUSES for p in session.exec(
            select(Payment).where(Payment.bill_id == bill.id, Payment.period == item.period)).all())
        decision = check_payment(
            bill_payee_email=bill.payee_paypal_email, amount=bill.amount, pay_date=today, due_date=item.due,
            mandate=mandate_spec(item.mandate), already_paid=already, has_saved_paypal=bool(user.paypal_vault_id),
            money_available=user.current_money, cushion=user.safety_cushion,
        )
        if decision.code in {"saved_paypal", "not_already_paid", "known_payee"}:
            return {"created_request": False, "guard": decision.as_dict()}
        payment = request_approval(session, user=user, bill=bill, period=item.period, due=item.due, today=today,
                                   trigger="agent", decision=decision, note=str(args.get("reason", ""))[:300])
        return {"created_request": True, "payment_id": payment.id, "needs_student_tap": True, "guard": decision.as_dict()}

    return {"error": f"Unknown tool {name}"}


def chat(session: Session, user: User, today: date, history: list[dict]) -> dict:
    """history: [{role: 'user'|'assistant', content: str}], last item is the new user message."""
    if not enabled():
        raise AIUnavailable("AI is not configured. Add GEMINI_API_KEY to backend/.env.")

    contents = _contents(history)
    used_tools: list[str] = []
    created: list[int] = []
    dream_ids: list[int] = []
    config = types.GenerateContentConfig(
        system_instruction=_system(today),
        tools=[GEMINI_TOOLS],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # our loop runs the tools
        max_output_tokens=8000,
        thinking_config=thinking("medium"),
    )

    def done(reply: str) -> dict:
        return {"reply": reply, "tools_used": used_tools, "approval_payment_ids": created, "dream_ids": dream_ids}

    for _ in range(MAX_ROUNDS):
        response = generate(contents=contents, config=config)
        try:
            check_refusal(response)
        except AIRefused:
            return done("Sorry, I can't help with that one. Try asking about your bills, budget or loan.")

        calls = response.function_calls or []
        if not calls:
            return done(first_text(response) or "Sorry, I couldn't answer that. Try asking another way.")

        # Send the model's turn back unchanged: Gemini 3 needs its thought signatures to continue.
        contents.append(response.candidates[0].content)
        parts = []
        for call in calls:
            used_tools.append(call.name)
            try:
                out = _run_tool(session, user, today, call.name, dict(call.args or {}))
                if out.get("payment_id"):
                    created.append(out["payment_id"])
                if out.get("dream_id"):
                    dream_ids.append(out["dream_id"])
                result = {"output": json.loads(json.dumps(out, default=str))}
            except Exception as exc:  # report tool errors to Gemini instead of crashing the chat
                log.exception("Tool %s failed", call.name)
                result = {"error": str(exc)}
            part = types.Part.from_function_response(name=call.name, response=result)
            part.function_response.id = call.id
            parts.append(part)
        contents.append(types.Content(role="user", parts=parts))

    return done("I looked at a lot of numbers but couldn't finish. Try a more specific question.")


def _contents(history: list[dict]) -> list[types.Content]:
    """Chat history in Gemini's format. Gemini calls the assistant 'model', and the chat must start
    with the user, so leading assistant messages are dropped and back-to-back ones are merged."""
    contents: list[types.Content] = []
    for m in history:
        if not m.get("content"):
            continue
        role = "model" if m["role"] == "assistant" else "user"
        if not contents and role == "model":
            continue
        part = types.Part.from_text(text=m["content"])
        if contents and contents[-1].role == role:
            contents[-1].parts.append(part)
        else:
            contents.append(types.Content(role=role, parts=[part]))
    return contents
