"""Pay the landlord / college (Payouts v1). Sandbox: receivers should be sandbox account emails."""

from app.paypal.client import is_mock, mock_id, request


def send_payout(
    *,
    receiver_email: str,
    amount: float,
    currency: str,
    note: str,
    sender_batch_id: str,
) -> dict:
    if is_mock():
        return {"batch_id": mock_id("PAYOUT"), "batch_status": "SUCCESS", "mock": True}

    body = {
        "sender_batch_header": {
            # Unique per payout. PayPal rejects a repeated id, which stops double payouts.
            "sender_batch_id": sender_batch_id[:256],
            "email_subject": "You have a payment via Kharcha",
            "email_message": note[:1000],
        },
        "items": [
            {
                "recipient_type": "EMAIL",
                "receiver": receiver_email,
                "amount": {"value": f"{amount:.2f}", "currency": currency},
                "note": note[:4000],
                "sender_item_id": sender_batch_id[:63],
            }
        ],
    }
    resp = request("POST", "/v1/payments/payouts", json=body)
    header = resp.get("batch_header") or {}
    return {
        "batch_id": header.get("payout_batch_id"),
        "batch_status": header.get("batch_status"),
        "mock": False,
    }


def get_payout(batch_id: str) -> dict:
    if is_mock() or batch_id.startswith("MOCK-"):
        return {"batch_status": "SUCCESS", "item_status": "SUCCESS", "mock": True}
    resp = request("GET", f"/v1/payments/payouts/{batch_id}")
    items = resp.get("items") or []
    return {
        "batch_status": (resp.get("batch_header") or {}).get("batch_status"),
        "item_status": items[0].get("transaction_status") if items else None,
        "mock": False,
    }
