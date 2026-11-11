"""The whole demo story through the real API (mock PayPal, AI off)."""

from fastapi.testclient import TestClient

from app.main import app


def rent(dash):
    return next(b for b in dash["bills"] if b["name"] == "Rent")


def test_rent_story_smart_timing_then_guard_block_and_approval():
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        dash = client.get("/api/dashboard").json()
        assert dash["mode"]["paypal"] == "mock"
        r = rent(dash)
        assert r["days_to_due"] == 7
        # $1,100 now, rent $1,200, money from home arrives 2 days after the due date.
        assert r["status"] == "waiting_for_money"
        assert r["pay_on"] > r["due"]
        assert r["pay_on"] <= r["last_free_day"]
        assert dash["safe_to_spend"]["per_day"] > 0
        assert any(a["status"] == "short" and a["name"] == "Spring term fee" for a in dash["alerts"])
        # The 7-day heads-up was written on startup.
        assert any(a["kind"] == "nudge" and "Rent" in a["title"] for a in dash["recent_activity"])

        # Connect PayPal (mock vault).
        st = client.post("/api/paypal/setup-token", json={}).json()
        assert st["mock"] and "approval_token_id" in st["approve_url"]
        user = client.post("/api/paypal/payment-token", json={"setup_token_id": st["id"]}).json()
        assert user["paypal_connected"]

        # Due date: not enough money yet, so nothing is paid.
        client.post("/api/demo/advance-days", json={"days": 7})
        payments = client.get("/api/payments").json()
        assert not any(p["status"] == "completed" and p["amount"] == 1200 for p in payments)

        # Two days later the money arrives and rent is paid inside the grace period.
        out = client.post("/api/demo/advance-days", json={"days": 2}).json()
        kinds = [a["kind"] for a in out["new_activity"]]
        assert "income" in kinds and "payment" in kinds
        paid = [p for p in client.get("/api/payments").json() if p["amount"] == 1200 and p["status"] == "completed"]
        assert len(paid) == 1 and paid[0]["mock"]
        assert rent(client.get("/api/dashboard").json())["period"] != paid[0]["period"]

        # Landlord raises rent to $1,400 (above the $1,250 limit) -> guard blocks, asks for approval.
        client.patch(f"/api/bills/{r['id']}", json={"amount": 1400})
        client.patch("/api/user", json={"current_money": 3000})
        client.post("/api/demo/advance-days", json={"days": 30})
        pending = [p for p in client.get("/api/payments").json() if p["status"] == "needs_approval" and p["amount"] == 1400]
        assert len(pending) == 1
        acts = client.get("/api/activity").json()
        assert any(a["kind"] == "block" and "above your $1,250 limit" in (a["reason"] or "") for a in acts)

        # The student taps Approve -> paid.
        res = client.post(f"/api/payments/{pending[0]['id']}/approve").json()
        assert res["payment"]["status"] == "completed"
        assert res["guard"]["allowed"]


def test_agent_needs_api_key():
    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Can I afford a $60 ticket?"}]})
        assert resp.status_code == 503


def test_document_upload_mock_extraction_and_confirm():
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        up = client.post("/api/documents", files={"file": ("my-lease.txt", b"Rent is $1,200 due on the 1st.", "text/plain")})
        body = up.json()
        assert body["mock"] and body["extraction"]["document_type"] == "lease"
        bill = body["extraction"]["bill"]
        confirm = client.post(f"/api/documents/{body['id']}/confirm", json={
            "bill": {
                "bill": {"name": "New rent", "category": "rent", "payee_name": bill["payee_name"],
                         "payee_paypal_email": "landlord@example.com", "amount": bill["amount"],
                         "recurrence": "monthly", "due_day": bill["due_day_of_month"],
                         "grace_days": bill["grace_days"], "late_fee": bill["late_fee"]},
                "autopay_max_amount": 1250,
            }
        }).json()
        assert confirm["bill"]["name"] == "New rent"
        assert confirm["autopay"]["max_amount"] == 1250
