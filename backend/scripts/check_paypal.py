"""Checks your PayPal sandbox setup without moving any money.

Run from the backend folder:
    .venv\\Scripts\\python scripts\\check_paypal.py      (Windows)
    .venv/bin/python scripts/check_paypal.py           (macOS/Linux)

It never prints your secret.
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.paypal import vault  # noqa: E402
from app.paypal.client import PayPalError  # noqa: E402

problems = 0


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def fix(msg: str) -> None:
    global problems
    problems += 1
    print(f"  [FIX]  {msg}")


def info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def main() -> int:
    print("\nKharcha: PayPal sandbox check\n")

    if settings.paypal_mode == "mock":
        fix("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are empty in backend/.env, so the app runs in MOCK mode.")
        return 1
    if "sandbox" not in settings.paypal_base_url:
        fix(f"PAYPAL_BASE_URL is {settings.paypal_base_url}. For the hackathon use https://api-m.sandbox.paypal.com")

    # 1. Can we log in with the Client ID + Secret?
    resp = httpx.post(
        f"{settings.paypal_base_url}/v1/oauth2/token",
        auth=(settings.paypal_client_id, settings.paypal_client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code != 200:
        fix(f"PayPal rejected the Client ID / Secret (HTTP {resp.status_code}). Copy both again from "
            "Apps & Credentials > Sandbox, with no spaces or quotes.")
        return 1
    body = resp.json()
    ok("Client ID and Secret work (got an access token).")
    scope = body.get("scope", "")

    # 2. Are the features Kharcha needs switched on for this app? (hints from the token's scopes)
    # Vault v3 has its own scope. The old v1 card-vault scope (".../v1/vault/credit-card") doesn't count.
    if "/services/vault/payment-tokens" in scope:
        ok("Vault v3 (save PayPal for later) looks enabled.")
    else:
        fix("Vault v3 isn't enabled for this app. In the app's settings, under Features, tick 'Accept payments', "
            "open Advanced options and tick 'Vault' (may be called 'Save payment methods'), then Save. "
            "If the option is missing, make a US sandbox business account and a new app under it.")
    if "payouts" in scope:
        ok("Payouts looks enabled.")
    else:
        fix("Payouts doesn't look enabled. In the app's settings, tick 'Payouts', then Save.")

    # 3. Real test: create a setup token (no money moves; it expires by itself in 3 days).
    try:
        st = vault.create_setup_token(
            return_url=f"{settings.frontend_url}/paypal/return",
            cancel_url=f"{settings.frontend_url}/paypal/cancel",
            request_id=f"kharcha-check-{uuid.uuid4().hex[:10]}",
        )
        if st.get("approve_url"):
            ok("Created a Vault setup token. 'Connect PayPal' should open the PayPal sandbox login.")
        else:
            fix("Setup token was created but PayPal sent no approve link. Check the Vault setting.")
    except PayPalError as exc:
        fix(f"Creating a Vault setup token failed: {exc}")
        if exc.details:
            for d in exc.details:
                info(f"PayPal says: {d.get('issue')}: {d.get('description')}")

    # 4. Who receives the money in the demo?
    for name, email in (("DEMO_LANDLORD_EMAIL", settings.demo_landlord_email),
                        ("DEMO_COLLEGE_EMAIL", settings.demo_college_email)):
        if email.endswith("@example.com"):
            fix(f"{name} isn't set. Use a sandbox Personal account email (like sb-xxxx@personal.example.com) "
                "so payouts actually arrive.")
        else:
            ok(f"{name} is set.")

    # 5. AI
    if settings.ai_enabled:
        ok(f"GEMINI_API_KEY is set (model {settings.ai_model}).")
    else:
        info("GEMINI_API_KEY is empty, so AI is off (template messages, no document reading or chat).")

    print()
    if problems:
        print(f"{problems} thing(s) to fix. Change backend/.env or the app settings, then run this again.\n")
        return 1
    print("All good. Restart the backend, click 'Reset demo', then 'Connect PayPal'.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
