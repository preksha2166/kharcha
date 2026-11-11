"""PayPal webhooks: verify the signature with PayPal, then update our payment records."""

import json
import logging

from sqlmodel import Session, select

from app.config import settings
from app.models import AgentAction, Payment
from app.paypal.client import is_mock, request

log = logging.getLogger("kharcha.webhooks")

# Header names PayPal sends (case-insensitive in Starlette).
_HEADERS = {
    "auth_algo": "paypal-auth-algo",
    "cert_url": "paypal-cert-url",
    "transmission_id": "paypal-transmission-id",
    "transmission_sig": "paypal-transmission-sig",
    "transmission_time": "paypal-transmission-time",
}


def verify(headers: dict, event: dict) -> bool:
    if is_mock():
        return True
    if not settings.paypal_webhook_id:
        log.warning("PAYPAL_WEBHOOK_ID is not set; rejecting webhook")
        return False
    body = {key: headers.get(h, "") for key, h in _HEADERS.items()}
    body["webhook_id"] = settings.paypal_webhook_id
    body["webhook_event"] = event
    resp = request("POST", "/v1/notifications/verify-webhook-signature", json=body)
    return resp.get("verification_status") == "SUCCESS"


def handle_event(session: Session, event: dict) -> str:
    """Match the event to a Payment by order / capture / payout id and update it."""
    kind = event.get("event_type", "")
    res = event.get("resource") or {}
    payment: Payment | None = None

    if kind.startswith("PAYMENT.CAPTURE."):
        capture_id = res.get("id")
        order_id = ((res.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
        if capture_id:
            payment = session.exec(select(Payment).where(Payment.paypal_capture_id == capture_id)).first()
        if payment is None and order_id:
            payment = session.exec(select(Payment).where(Payment.paypal_order_id == order_id)).first()
        if payment and kind == "PAYMENT.CAPTURE.DENIED":
            payment.status = "failed"
            payment.failure_reason = "PayPal denied the charge."
    elif kind.startswith("PAYMENT.PAYOUTS-ITEM.") or kind.startswith("PAYMENT.PAYOUTSBATCH."):
        batch_id = res.get("payout_batch_id") or (res.get("batch_header") or {}).get("payout_batch_id")
        if batch_id:
            payment = session.exec(select(Payment).where(Payment.payout_batch_id == batch_id)).first()
        if payment:
            payment.payout_status = res.get("transaction_status") or (res.get("batch_header") or {}).get("batch_status") or kind
            if kind.endswith((".FAILED", ".RETURNED", ".BLOCKED", ".DENIED")):
                payment.failure_reason = f"Payout to the payee had a problem: {kind}"

    if payment is None:
        log.info("Webhook %s matched no payment", kind)
        return "ignored"

    session.add(payment)
    session.add(AgentAction(
        user_id=payment.user_id,
        kind="info",
        title=f"PayPal confirmed: {kind}",
        message="PayPal sent a webhook about this payment.",
        bill_id=payment.bill_id,
        payment_id=payment.id,
        details_json=json.dumps({"event_type": kind, "event_id": event.get("id")}),
    ))
    session.commit()
    return "updated"
