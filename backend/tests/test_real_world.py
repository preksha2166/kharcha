"""The free real-world fixes: login, catch-up, wake-up URL, balance check-in, spending import,
safety cushion, remind-me mode, one-tap PayPal straight to the payee, alerts, and the DB upgrade step."""

from dataclasses import replace
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

import app.api as api_module
from app import clock
from app.config import settings
from app.db import add_missing_columns, engine
from app.finance.csv_import import parse_bank_csv
from app.guard.mandates import check_payment
from app.main import app
from app.models import AgentAction, Bill, IncomeEvent, PushSubscription, User
from app.seed.demo_data import get_demo_user
from app.services import notify
from app.services.daily import catch_up


def reset(client):
    client.post("/api/demo/reset")
    return date.fromisoformat(client.get("/api/dashboard").json()["today"])


def login(client) -> dict:
    url = client.post("/api/auth/paypal/start", json={"state": "s" * 32}).json()["url"]
    assert "code=MOCK-LOGIN" in url and "state=" + "s" * 32 in url
    return client.post("/api/auth/paypal/finish", json={"code": "MOCK-LOGIN"}).json()


# ---------- login ----------

def test_log_in_with_paypal_gives_each_student_their_own_data(monkeypatch):
    with TestClient(app) as client:
        reset(client)
        first = login(client)
        assert first["new_user"] is True and first["token"]
        auth = {"Authorization": f"Bearer {first['token']}"}
        mine = client.get("/api/dashboard", headers=auth).json()
        assert mine["user"]["name"] == "Student" and mine["user"]["is_demo"] is False
        assert mine["bills"] == [] and len(mine["budgets"]) == 4  # starter budgets, no demo data
        assert mine["setup"] == {"money": False, "income": False, "bills": False, "paypal": False, "done": False}
        assert client.get("/api/me", headers=auth).json()["logged_in"] is True

        # Same PayPal account again: same Kharcha account.
        again = login(client)
        assert again["new_user"] is False and again["user"]["id"] == first["user"]["id"]

        # The demo student is untouched.
        assert client.get("/api/dashboard").json()["user"]["is_demo"] is True

        client.post("/api/auth/logout", headers=auth)
        assert client.get("/api/dashboard", headers=auth).status_code == 401
        assert client.get("/api/dashboard", headers={"Authorization": "Bearer nope"}).status_code == 401

        # Outside demo mode, nobody gets in without logging in.
        monkeypatch.setattr(api_module, "settings", replace(settings, demo_mode=False))
        assert client.get("/api/dashboard").status_code == 401
        assert client.post("/api/demo/advance-days", json={"days": 1}).status_code == 401


def test_new_student_setup_steps():
    with TestClient(app) as client:
        reset(client)
        auth = {"Authorization": f"Bearer {login(client)['token']}"}
        today = date.fromisoformat(client.get("/api/dashboard", headers=auth).json()["today"])
        client.post("/api/user/balance", json={"current_money": 900}, headers=auth)
        client.post("/api/incomes", json={"label": "Money from home", "amount": 800, "recurrence": "monthly",
                                         "arrives_on": (today + timedelta(days=5)).isoformat()}, headers=auth)
        client.post("/api/bills", json={"name": "Rent", "payee_name": "Landlord", "payee_paypal_email": "", "amount": 700,
                                        "recurrence": "monthly", "due_day": 1}, headers=auth)
        dash = client.get("/api/dashboard", headers=auth).json()
        assert dash["setup"]["done"] is True
        assert dash["bills"][0]["pay_mode"] == "remind"  # new bills default to the free mode
        incomes = client.get("/api/incomes", headers=auth).json()
        assert incomes[0]["recurrence"] == "monthly"
        assert client.delete(f"/api/incomes/{incomes[0]['id']}", headers=auth).json()["ok"]


# ---------- reliability ----------

def test_catch_up_counts_money_that_arrived_while_the_server_slept():
    with TestClient(app) as client:
        reset(client)
    with Session(engine) as s:
        user = get_demo_user(s)
        today = clock.today(s)
        s.add(IncomeEvent(user_id=user.id, label="Late pay", amount=123.0, start_date=today - timedelta(days=2), recurrence="once"))
        user.last_check_on = today - timedelta(days=3)
        s.add(user)
        s.commit()
        before = user.current_money
        assert catch_up(s, user, today) == 3
        s.refresh(user)
        assert user.current_money == before + 123
        assert user.last_check_on == today
        got = s.exec(select(AgentAction).where(AgentAction.title == "Late pay: +$123")).first()
        assert got.on_date == today - timedelta(days=2)


def test_wake_up_url_needs_the_secret(monkeypatch):
    with TestClient(app) as client:
        reset(client)
        assert client.get("/api/cron/daily-check").status_code == 403  # no CRON_SECRET set
        monkeypatch.setattr(api_module, "settings", replace(settings, cron_secret="s3cret"))
        assert client.get("/api/cron/daily-check?key=wrong").status_code == 403
        r = client.post("/api/cron/daily-check", headers={"X-Cron-Secret": "s3cret"}).json()
        assert r["ok"] and r["users"] >= 1


def test_database_upgrade_adds_new_columns_with_defaults():
    with TestClient(app) as client:
        reset(client)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE bill DROP COLUMN pay_mode"))
    assert "bill.pay_mode" in add_missing_columns()
    with Session(engine) as s:
        assert {b.pay_mode for b in s.exec(select(Bill)).all()} == {"paypal"}


# ---------- the money number ----------

def test_balance_check_in_and_spending_lower_your_money():
    with TestClient(app) as client:
        today = reset(client)
        dash = client.get("/api/dashboard").json()
        assert dash["balance_check_due"] is False
        money = dash["user"]["current_money"]

        r = client.post("/api/transactions", json={"merchant": "Green Grocer", "amount": 20}).json()
        assert r["current_money"] == money - 20 and r["transaction"]["counted_in_balance"]
        old = client.post("/api/transactions", json={"merchant": "Old cafe", "amount": 5,
                                                     "spent_on": (today - timedelta(days=3)).isoformat()}).json()
        assert old["current_money"] == money - 20  # before the last balance check: already in the balance
        assert client.delete(f"/api/transactions/{r['transaction']['id']}").json()["current_money"] == money

        client.post("/api/user/balance", json={"current_money": 1000})
        assert client.get("/api/dashboard").json()["user"]["current_money"] == 1000
        client.post("/api/demo/advance-days", json={"days": 7})
        assert client.get("/api/dashboard").json()["balance_check_due"] is True


def test_bank_csv_import_skips_income_and_duplicates():
    csv_text = ("Date,Description,Amount\n"
                "{d1},QuickBite Delivery,-18.40\n"
                "{d1},PAYROLL CAMPUS JOB,560.00\n"
                "{d2},Green Grocer,\"-1,021.30\"\n"
                "not a date,???,-3\n")
    with TestClient(app) as client:
        today = reset(client)
        body = csv_text.format(d1=today.isoformat(), d2=(today - timedelta(days=10)).strftime("%m/%d/%Y"))
        money = client.get("/api/dashboard").json()["user"]["current_money"]
        r = client.post("/api/transactions/import", files={"file": ("bank.csv", body, "text/csv")}).json()
        assert r["added"] == 2 and r["skipped_income"] == 1 and r["skipped_unreadable"] == 1
        # The balance was checked today, so a bank file's rows from today and earlier are already in it.
        assert r["money_change"] == 0 and r["current_money"] == money
        again = client.post("/api/transactions/import", files={"file": ("bank.csv", body, "text/csv")}).json()
        assert again["added"] == 0 and again["duplicates"] == 2
        client.post("/api/demo/advance-days", json={"days": 1})
        newer = f"Date,Description,Amount\n{(today + timedelta(days=1)).isoformat()},Corner Cafe,-6.25\n"
        r = client.post("/api/transactions/import", files={"file": ("b.csv", newer, "text/csv")}).json()
        assert r["added"] == 1 and r["money_change"] == -6.25


def test_csv_parser_understands_debit_credit_columns():
    data = b"Posted Date;Payee;Debit;Credit\n2026-11-01;Bookstore;34.00;\n2026-11-02;Mom;;800.00\n2026-11-03;Bus;(2.75);\n"
    rows = parse_bank_csv(data)
    assert [(r.merchant, r.amount) for r in rows.rows] == [("Bookstore", 34.0), ("Bus", 2.75)]
    assert rows.skipped_income == 1


def test_safety_cushion_blocks_payments_that_would_eat_it():
    ok = check_payment(bill_payee_email="l@x.com", amount=1000, pay_date=date(2026, 12, 1), due_date=date(2026, 12, 1),
                       mandate=None, already_paid=False, has_saved_paypal=True, money_available=1100, cushion=50,
                       user_approved=False)
    tight = check_payment(bill_payee_email="l@x.com", amount=1080, pay_date=date(2026, 12, 1), due_date=date(2026, 12, 1),
                          mandate=None, already_paid=False, has_saved_paypal=True, money_available=1100, cushion=50,
                          user_approved=False)
    no_od = next(c for c in ok.checks if c.rule == "no_overdraft")
    assert no_od.ok and "cushion stays" in no_od.detail
    tight_od = next(c for c in tight.checks if c.rule == "no_overdraft")
    assert not tight_od.ok and "safety cushion" in tight_od.detail


# ---------- remind me, and paying straight to the payee ----------

def _remind_bill(client, today, amount=40.0):
    return client.post("/api/bills", json={
        "name": "Gym", "payee_name": "City Gym", "payee_paypal_email": "gym@example.com", "amount": amount,
        "recurrence": "once", "due_date": (today + timedelta(days=2)).isoformat(),
    }).json()


def test_remind_me_bill_reminds_on_the_best_day_and_i_paid_it():
    with TestClient(app) as client:
        today = reset(client)
        bill = _remind_bill(client, today)
        assert bill["pay_mode"] == "remind" and bill["paypal_fee"] == round(40 * 0.0349 + 0.49, 2)
        out = client.post("/api/demo/advance-days", json={"days": 2}).json()
        assert any(a["title"] == "Pay Gym today: $40" for a in out["new_activity"])
        dash = client.get("/api/dashboard").json()
        assert [b["name"] for b in dash["pay_yourself"]] == ["Gym"]
        assert not any(p["bill_id"] == bill["id"] for p in client.get("/api/payments").json())  # Kharcha didn't pay

        money = dash["user"]["current_money"]
        r = client.post(f"/api/bills/{bill['id']}/paid", json={}).json()
        assert r["current_money"] == money - 40 and r["payment"]["trigger"] == "self"
        dash = client.get("/api/dashboard").json()
        assert dash["pay_yourself"] == []
        assert next(b for b in dash["bills"] if b["id"] == bill["id"])["status"] == "paid"


def test_pay_with_paypal_goes_straight_to_the_payee():
    with TestClient(app) as client:
        today = reset(client)
        bill = _remind_bill(client, today, amount=25.0)
        co = client.post(f"/api/bills/{bill['id']}/checkout").json()
        assert co["mock"] and f"token={co['order_id']}" in co["approve_url"]
        money = client.get("/api/dashboard").json()["user"]["current_money"]
        r = client.post("/api/payments/checkout/capture", json={"order_id": co["order_id"]}).json()
        assert r["payment"]["status"] == "completed" and r["current_money"] == money - 25
        # Capturing twice is harmless.
        assert client.post("/api/payments/checkout/capture", json={"order_id": co["order_id"]}).json()["payment"]["status"] == "completed"
        assert any("straight to City Gym" in a["title"] for a in client.get("/api/activity").json())

        # Cancelling on PayPal leaves the bill unpaid.
        bill2 = client.post("/api/bills", json={"name": "Club", "payee_name": "Club", "payee_paypal_email": "c@example.com",
                                                "amount": 10, "recurrence": "once",
                                                "due_date": (today + timedelta(days=3)).isoformat()}).json()
        co2 = client.post(f"/api/bills/{bill2['id']}/checkout").json()
        client.post("/api/payments/checkout/cancel", json={"order_id": co2["order_id"]})
        assert next(b for b in client.get("/api/bills").json() if b["id"] == bill2["id"])["status"] != "paid"


# ---------- alerts ----------

def test_alerts_go_to_saved_devices(monkeypatch):
    sent = []
    monkeypatch.setattr(notify._pool, "submit", lambda fn, *args: sent.append(args))
    with TestClient(app) as client:
        reset(client)
        assert client.post("/api/alerts/test").status_code == 400  # nothing turned on yet
        sub = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "BKey", "auth": "auth"}}
        a = client.post("/api/alerts/push", json=sub).json()
        assert a["push_devices"] == 1 and len(a["push_public_key"]) == 87
        assert client.post("/api/alerts/test").json() == {"push": 1, "email": False}
        targets, _key, payload, email_to = sent[-1]
        assert targets[0]["endpoint"] == sub["endpoint"] and payload["title"] == "Kharcha alerts are on" and email_to is None

        # Important Activity entries become alerts; quiet ones don't.
        n = len(sent)
        with Session(engine) as s:
            user = get_demo_user(s)
            from app.services.activity import log_action
            log_action(s, user_id=user.id, kind="info", title="Just info")
            log_action(s, user_id=user.id, kind="block", title="Payment blocked")
        assert len(sent) == n + 1 and sent[-1][2]["title"] == "Payment blocked"

        # A phone that unsubscribed (410) is forgotten.
        def fake_push(target, key, payload):
            raise notify._Gone()

        monkeypatch.setattr(notify, "_push", fake_push)
        notify._deliver(targets, "key", payload, None)
        with Session(engine) as s:
            assert s.exec(select(PushSubscription)).all() == []


def test_email_alerts_when_turned_on(monkeypatch):
    sent = []
    monkeypatch.setattr(notify._pool, "submit", lambda fn, *args: sent.append(args))
    monkeypatch.setattr(notify, "settings", replace(settings, smtp_host="smtp.example.com", smtp_from="kharcha@example.com"))
    with TestClient(app) as client:
        reset(client)
        client.patch("/api/user", json={"email": "riya@example.com", "notify_email": True})
        with Session(engine) as s:
            user = s.get(User, get_demo_user(s).id)
            assert notify.send(s, user, title="Hi", body="Test") == {"push": 0, "email": True}
        assert sent[-1][3] == "riya@example.com"
