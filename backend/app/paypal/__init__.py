"""PayPal sandbox integration: OAuth, Vault (save PayPal), Orders (charge), Payouts (pay landlord), Webhooks.

When PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are empty the module runs in MOCK mode:
it returns fake ids instantly so the rest of the app can be built and tested. Every mock
result carries "mock": True and the UI shows a MOCK badge.
"""
