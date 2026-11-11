"""PayPal Orders v2.

- charge_saved_paypal: full autopay. Charges the student's saved PayPal (vault_id) with no popup.
  PayPal ties a saved PayPal to the business that saved it, so this money goes to Kharcha's account and
  Payouts sends it on to the landlord. Real use needs PayPal partner approval (see README).
- create_checkout / capture_checkout: one-tap payment the student approves on PayPal, paid straight to
  the landlord or college. Kharcha never holds the money.
"""

from app.paypal.client import PayPalError, is_mock, link, mock_id, request


def _amount(value: float, currency: str) -> dict:
    return {"currency_code": currency, "value": f"{value:.2f}"}


def charge_saved_paypal(
    *,
    vault_id: str,
    amount: float,
    currency: str,
    description: str,
    reference_id: str,
    request_id: str,
) -> dict:
    if is_mock():
        return {
            "order_id": mock_id("ORDER"),
            "status": "COMPLETED",
            "capture_id": mock_id("CAPTURE"),
            "capture_status": "COMPLETED",
            "mock": True,
        }

    body = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": reference_id[:256],
                "description": description[:127],
                "amount": _amount(amount, currency),
            }
        ],
        "payment_source": {"paypal": {"vault_id": vault_id}},
    }
    order = request("POST", "/v2/checkout/orders", json=body, request_id=request_id)

    # With a vault_id PayPal usually completes the order right away. If not, capture it.
    if order.get("status") != "COMPLETED" and order.get("status") in {"APPROVED", "CREATED"}:
        order = request(
            "POST",
            f"/v2/checkout/orders/{order['id']}/capture",
            json={},
            request_id=f"{request_id}-capture",
        )

    capture = {}
    for unit in order.get("purchase_units", []) or []:
        captures = ((unit.get("payments") or {}).get("captures")) or []
        if captures:
            capture = captures[0]
            break
    return {
        "order_id": order.get("id"),
        "status": order.get("status"),
        "capture_id": capture.get("id"),
        "capture_status": capture.get("status"),
        "mock": False,
    }


def create_checkout(
    *,
    amount: float,
    currency: str,
    payee_email: str,
    description: str,
    reference_id: str,
    return_url: str,
    cancel_url: str,
    request_id: str,
) -> dict:
    """A one-time PayPal payment the student approves on PayPal, paid straight to the payee.
    Kharcha never holds the money: PayPal moves it from the student to the landlord or college."""
    if is_mock():
        order_id = mock_id("ORDER")
        sep = "&" if "?" in return_url else "?"
        return {"order_id": order_id, "approve_url": f"{return_url}{sep}token={order_id}", "mock": True}

    body = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": reference_id[:256],
                "description": description[:127],
                "amount": _amount(amount, currency),
                "payee": {"email_address": payee_email},
            }
        ],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "brand_name": "Kharcha",
                    "user_action": "PAY_NOW",
                    "shipping_preference": "NO_SHIPPING",
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                }
            }
        },
    }
    order = request("POST", "/v2/checkout/orders", json=body, request_id=request_id)
    approve = link(order, "payer-action") or link(order, "approve")
    if not approve:
        raise PayPalError(502, "PayPal didn't send a link to approve the payment.")
    return {"order_id": order["id"], "approve_url": approve, "mock": False}


def capture_checkout(order_id: str, request_id: str) -> dict:
    """After the student approves on PayPal, take the payment (money goes to the payee)."""
    if is_mock() or order_id.startswith("MOCK-"):
        return {"status": "COMPLETED", "capture_id": mock_id("CAPTURE"), "mock": True}
    order = request("POST", f"/v2/checkout/orders/{order_id}/capture", json={}, request_id=request_id)
    capture = {}
    for unit in order.get("purchase_units", []) or []:
        captures = ((unit.get("payments") or {}).get("captures")) or []
        if captures:
            capture = captures[0]
            break
    return {"status": order.get("status"), "capture_id": capture.get("id"), "mock": False}
