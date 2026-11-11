"""Save the student's PayPal once (Vault v3, save without purchase), so autopay needs no popup later.

Flow: create setup token -> student approves on PayPal (approve link) -> create payment token.
Docs: https://developer.paypal.com/docs/checkout/save-payment-methods/purchase-later/payment-tokens-api/paypal/
Sandbox app settings: enable "Accept payments" and, under Advanced options, "Vault".
"""

from app.paypal.client import is_mock, link, mock_id, request


def create_setup_token(*, return_url: str, cancel_url: str, request_id: str) -> dict:
    if is_mock():
        token_id = mock_id("SETUP")
        # In mock mode the "approve" step just returns straight to our app.
        return {
            "id": token_id,
            "status": "PAYER_ACTION_REQUIRED",
            "approve_url": f"{return_url}{'&' if '?' in return_url else '?'}approval_token_id={token_id}&mock=1",
            "mock": True,
        }

    body = {
        "payment_source": {
            "paypal": {
                "description": "Kharcha autopay for rent and bills, only within limits you set",
                "permit_multiple_payment_tokens": False,
                "usage_pattern": "IMMEDIATE",
                "usage_type": "MERCHANT",
                "customer_type": "CONSUMER",
                "experience_context": {
                    "brand_name": "Kharcha",
                    "locale": "en-US",
                    # Rent isn't shipped. If sandbox rejects this value, try "GET_FROM_FILE".
                    "shipping_preference": "NO_SHIPPING",
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                },
            }
        }
    }
    resp = request("POST", "/v3/vault/setup-tokens", json=body, request_id=request_id)
    return {
        "id": resp["id"],
        "status": resp.get("status"),
        "approve_url": link(resp, "approve"),
        "mock": False,
    }


def create_payment_token(*, setup_token_id: str, request_id: str) -> dict:
    if is_mock():
        return {
            "id": mock_id("VAULT"),
            "customer_id": mock_id("CUSTOMER"),
            "payer_email": "student-mock@example.com",
            "mock": True,
        }

    body = {"payment_source": {"token": {"id": setup_token_id, "type": "SETUP_TOKEN"}}}
    resp = request("POST", "/v3/vault/payment-tokens", json=body, request_id=request_id)
    paypal = (resp.get("payment_source") or {}).get("paypal") or {}
    return {
        "id": resp["id"],
        "customer_id": (resp.get("customer") or {}).get("id"),
        "payer_email": paypal.get("email_address"),
        "mock": False,
    }
