"""Payout status refresh (PayPal can't send webhooks to a laptop) and money formatting for Gemini."""

from datetime import date

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.ai.nudges import facts_for_ai
from app.db import engine
from app.main import app
from app.models import AgentAction, Bill, Payment, User
from app.paypal import payouts
from app.services.autopay import refresh_payouts

TODAY = date(2026, 11, 16)


def test_facts_for_ai_writes_money_like_people_do():
    out = facts_for_ai({"bill": "Phone plan", "amount": 25.0, "late_fee": 5.0, "shortfall": 1572.5,
                        "percent": 84.6, "days_to_due": 3, "autopay_on": True})
    assert out["amount"] == "$25"
    assert out["late_fee"] == "$5"
    assert out["shortfall"] == "$1,572.50"
    assert out["percent"] == "85%"
    assert out["days_to_due"] == 3 and out["autopay_on"] is True and out["bill"] == "Phone plan"


def _pending_payout(session: Session) -> Payment:
    user = session.exec(select(User)).first()
    bill = session.exec(select(Bill).where(Bill.name == "Rent")).first()
    p = Payment(user_id=user.id, bill_id=bill.id, period="2026-11", amount=1200.0, status="completed",
                trigger="autopay", payout_batch_id="BATCH-TEST", payout_status="PENDING")
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _payout_actions(session: Session, payment_id: int) -> list[AgentAction]:
    return session.exec(select(AgentAction).where(AgentAction.payment_id == payment_id)).all()


def test_payout_success_is_recorded_once(monkeypatch):
    with TestClient(app) as client:
        client.post("/api/demo/reset")
    statuses = iter(["PROCESSING", "SUCCESS", "SUCCESS"])
    monkeypatch.setattr(payouts, "get_payout", lambda _id: {"batch_status": "PROCESSING", "item_status": next(statuses)})
    with Session(engine) as session:
        p = _pending_payout(session)
        user = session.get(User, p.user_id)
        for _ in range(3):
            refresh_payouts(session, user, TODAY)
        session.refresh(p)
        assert p.payout_status == "SUCCESS"
        acts = _payout_actions(session, p.id)
        assert [a.title for a in acts] == ["Maple Apartments received $1,200"]
        assert acts[0].kind == "payment"


def test_failed_payout_warns_the_student(monkeypatch):
    with TestClient(app) as client:
        client.post("/api/demo/reset")
    monkeypatch.setattr(payouts, "get_payout", lambda _id: {"batch_status": "SUCCESS", "item_status": "RETURNED"})
    with Session(engine) as session:
        p = _pending_payout(session)
        refresh_payouts(session, session.get(User, p.user_id), TODAY)
        session.refresh(p)
        assert p.payout_status == "RETURNED"
        assert "couldn't deliver" in p.failure_reason
        acts = _payout_actions(session, p.id)
        assert len(acts) == 1 and acts[0].kind == "block" and acts[0].allowed is False


def test_paypal_error_never_breaks_the_daily_check(monkeypatch):
    with TestClient(app) as client:
        client.post("/api/demo/reset")

    def boom(_id):
        raise RuntimeError("network down")

    monkeypatch.setattr(payouts, "get_payout", boom)
    with Session(engine) as session:
        p = _pending_payout(session)
        refresh_payouts(session, session.get(User, p.user_id), TODAY)
        session.refresh(p)
        assert p.payout_status == "PENDING"
        assert _payout_actions(session, p.id) == []
