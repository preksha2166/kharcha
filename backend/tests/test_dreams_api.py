"""Dreams through the real API (mock PayPal, AI off): bills first, weekly set-aside, buy, reorder."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import clock
from app.ai import agent
from app.db import engine
from app.main import app
from app.models import User


def dreams(client):
    return client.get("/api/dreams").json()


def by_name(view, name):
    return next(d for d in view["dreams"] if d["name"] == name)


def activity_titles(client):
    return [a["title"] for a in client.get("/api/activity").json()]


def test_bills_first_then_dreams_get_the_spare_money():
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        today = date.fromisoformat(client.get("/api/dashboard").json()["today"])
        flight_by = (today + timedelta(days=200)).isoformat()
        client.post("/api/dreams", json={"name": "Flight home", "target_amount": 1200, "target_date": flight_by, "emoji": "✈️"})
        view = client.post("/api/dreams", json={"name": "Laptop", "target_amount": 1000}).json()

        # The spring fee is short, so dreams wait: bills first.
        assert "Spring term fee" in view["room"]["blocked_by"]
        assert {d["plan_status"] for d in view["dreams"]} == {"waiting_for_bills"}
        assert view["weekly_surplus"] > 0  # normal months do have spare money

        # The student asks family for the shortfall (one tap on the alert) -> dreams can plan again.
        alert = client.get("/api/dashboard").json()["alerts"][0]
        client.post("/api/incomes", json={"amount": 1800, "arrives_on": alert["transfer_by"]})
        dash = client.get("/api/dashboard").json()
        assert dash["alerts"] == []
        view = dash["dreams"]
        assert view["room"]["blocked_by"] is None
        flight = by_name(view, "Flight home")
        assert flight["ready_on"] is not None and flight["plan_status"] in {"on_track", "behind"}
        assert by_name(view, "Laptop")["priority"] == 2

        # Next Monday Kharcha sets money aside (or explains why not), once.
        days = (7 - today.weekday()) % 7 or 7
        out = client.post("/api/demo/advance-days", json={"days": days}).json()
        dream_acts = [a for a in out["new_activity"] if a["kind"] == "dream"]
        assert len(dream_acts) == 1
        assert dream_acts[0]["title"].startswith(("Set aside", "Dreams on hold"))
        client.post("/api/demo/run-check")
        assert len([a for a in client.get("/api/activity").json() if a["kind"] == "dream"
                    and a["title"].startswith(("Set aside", "Dreams on hold"))]) == 1


def test_saved_money_is_not_spendable_and_bills_come_first():
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        before = client.get("/api/dashboard").json()["safe_to_spend"]
        r = client.post("/api/dreams", json={"name": "Car", "target_amount": 5000, "saved_amount": 2000})
        assert r.status_code == 400  # can't mark more as saved than you have
        client.post("/api/dreams", json={"name": "Concert trip", "target_amount": 300, "saved_amount": 200})
        after = client.get("/api/dashboard").json()["safe_to_spend"]
        assert after["dreams_saved"] == 200
        assert after["per_day"] < before["per_day"]

        # Money drops below what's saved (say a bill took it): the dream gives way, bills first.
        client.patch("/api/user", json={"current_money": 50})
        client.post("/api/demo/run-check")
        assert dreams(client)["saved_total"] == 50
        assert "Bills came first" in activity_titles(client)


def test_reorder_pause_buy_and_remove():
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        client.post("/api/dreams", json={"name": "Flight home", "target_amount": 1200})
        view = client.post("/api/dreams", json={"name": "Headphones", "target_amount": 100, "saved_amount": 100}).json()
        phones = by_name(view, "Headphones")
        assert phones["status"] == "reached" and phones["plan_status"] == "reached"

        view = client.post(f"/api/dreams/{phones['id']}/move", json={"direction": "up"}).json()
        assert [d["name"] for d in view["dreams"]] == ["Headphones", "Flight home"]

        flight = by_name(view, "Flight home")
        view = client.patch(f"/api/dreams/{flight['id']}", json={"paused": True}).json()
        assert by_name(view, "Flight home")["plan_status"] == "paused"
        view = client.patch(f"/api/dreams/{flight['id']}", json={"paused": False, "target_date": None}).json()
        assert by_name(view, "Flight home")["status"] == "active"

        money = client.get("/api/dashboard").json()["user"]["current_money"]
        view = client.post(f"/api/dreams/{phones['id']}/bought", json={"price": 95}).json()
        assert [d["name"] for d in view["dreams"]] == ["Flight home"]
        assert view["bought"][0]["name"] == "Headphones" and view["bought"][0]["bought_price"] == 95
        assert client.get("/api/dashboard").json()["user"]["current_money"] == money - 95
        assert any(t.startswith("Dream come true") for t in activity_titles(client))

        view = client.request("DELETE", f"/api/dreams/{flight['id']}").json()
        assert view["dreams"] == []


def test_ask_kharcha_suggests_a_dream_the_student_saves_with_a_tap():
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        with Session(engine) as session:
            user = session.get(User, 1)
            today = clock.today(session)
            out = agent._run_tool(session, user, today, "propose_dream", {
                "name": "Flight home", "target_amount": 1200, "target_date": (today + timedelta(days=190)).isoformat(),
                "emoji": "✈️", "already_saved": 0})
            assert out["created_suggestion"] and out["needs_student_tap"]
            assert out["plan"]["status"] == "waiting_for_bills"  # the spring fee is short
            bad = agent._run_tool(session, user, today, "propose_dream", {
                "name": "Old", "target_amount": 10, "target_date": "2000-01-01", "emoji": "", "already_saved": 0})
            assert "error" in bad
        # A suggestion isn't a dream until the student taps Save.
        assert dreams(client)["dreams"] == []
        view = client.post(f"/api/dreams/{out['dream_id']}/confirm").json()
        assert [(d["name"], d["priority"]) for d in view["dreams"]] == [("Flight home", 1)]
        assert client.post(f"/api/dreams/{out['dream_id']}/confirm").status_code == 400
