"""Low-level PayPal REST client with access-token caching."""

import logging
import threading
import time
import uuid
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("kharcha.paypal")


class PayPalError(Exception):
    def __init__(self, status: int, message: str, debug_id: str | None = None, details: Any = None):
        super().__init__(f"PayPal {status}: {message}" + (f" (debug_id {debug_id})" if debug_id else ""))
        self.status = status
        self.message = message
        self.debug_id = debug_id
        self.details = details


def is_mock() -> bool:
    return settings.paypal_mode == "mock"


def mock_id(prefix: str) -> str:
    return f"MOCK-{prefix}-{uuid.uuid4().hex[:10].upper()}"


class _TokenCache:
    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires_at - 60:
                return self._token
            resp = httpx.post(
                f"{settings.paypal_base_url}/v1/oauth2/token",
                auth=(settings.paypal_client_id, settings.paypal_client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
                timeout=30,
            )
            if resp.status_code != 200:
                raise PayPalError(resp.status_code, f"Could not get access token: {resp.text[:300]}")
            body = resp.json()
            self._token = body["access_token"]
            self._expires_at = time.time() + int(body.get("expires_in", 3000))
            return self._token


_tokens = _TokenCache()


def request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    request_id: str | None = None,
    extra_headers: dict | None = None,
) -> dict:
    """Call the PayPal API and return the JSON body. Raises PayPalError on failure."""
    headers = {
        "Authorization": f"Bearer {_tokens.get()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if request_id:
        # Same id = same result: protects against double charges on retries.
        headers["PayPal-Request-Id"] = request_id
    if extra_headers:
        headers.update(extra_headers)

    url = f"{settings.paypal_base_url}{path}"
    resp = httpx.request(method, url, json=json, headers=headers, timeout=45)
    log.info("PayPal %s %s -> %s", method, path, resp.status_code)
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except ValueError:
            body = {"message": resp.text[:300]}
        raise PayPalError(
            resp.status_code,
            body.get("message") or body.get("error_description") or body.get("name") or "Request failed",
            debug_id=body.get("debug_id"),
            details=body.get("details"),
        )
    if not resp.content:
        return {}
    return resp.json()


def link(body: dict, rel: str) -> str | None:
    for item in body.get("links", []) or []:
        if item.get("rel") == rel:
            return item.get("href")
    return None
