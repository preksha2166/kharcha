# Kharcha

**An AI that pays your rent, but only within limits you set.**

Kharcha is a money copilot for international students living on a loan and money from home. It reads your lease, fee notices and loan letter, warns you **7 days before** a bill with a plan, and pays through **PayPal** on the smartest day, never outside the limits you approved.

Built for the PayPal AI Hackathon 2026 by **Preksha Dewoolkar** and **Chirag Patankar**.

**Live demo:** https://kharcha-eka5.onrender.com (on a free server, so the first load can take up to a minute) · **Demo video:** https://youtu.be/27xjjOc04qQ

## What it does

| Feature | How |
|---|---|
| **Reads your documents** | Upload a lease, fee notice or loan letter. Gemini extracts the amount, due date, grace period and late fee, and quotes the page each value came from. You confirm every field before anything is saved. |
| **Smart timing** | Bank autopay pays on the due date even if your money from home lands two days later. Kharcha checks the forecast and, if the money arrives **inside the no-late-fee grace period**, waits and pays then: no overdraft, no fee. |
| **Remind me (free, the default)** | On the best day, Kharcha reminds you (in the app, on your phone, or by email). Pay your usual way and tap **I paid it**, or tap **Pay with PayPal**: you approve it on PayPal and the money goes **straight to the landlord or college**. Kharcha never holds your money. |
| **Full autopay with a leash** | You approve once: *"Pay Maple Apartments up to $1,250, from 3 days before the due date to the end of the grace period."* Kharcha charges your **saved PayPal** (Vault + Orders API) and pays the landlord (**Payouts API**). Anything outside the limit is **blocked** and waits for your one-tap approval. Each bill shows the PayPal fee first. |
| **Safe to spend today** | One number: how much you can spend per day and still cover every bill in the next 30 days. |
| **Budget coach** | Weekly limits per category. You decide what counts as a need; the coach nudges you when a category is close to its limit. |
| **Loan planner** | Your loan explained in plain words: interest during studies, monthly payment after, and how much you save by paying a little now. |
| **Dreams** | Tell Kharcha what you're saving for: a flight home, a laptop. **Bills first, dreams second, fun third.** Every Monday it sets aside only what's truly spare, shows when each dream will be ready, pauses dreams while a bill is short, and suggests one budget to lower to get there sooner. The money stays in your account; safe-to-spend just leaves it out. |
| **Ask Kharcha** | A Gemini agent with read-only money tools. It can *propose* a payment or *suggest* a dream, but only you can approve it. |
| **Activity log** | Every warning, payment and block, with the guard's checks. |
| **Your own account** | **Log in with PayPal**. Each student sees only their own data. In demo mode anyone can also try the demo student without logging in. |
| **Alerts outside the app** | Phone notifications (install Kharcha on your home screen) and email, for "due in 7 days", "pay today", payments and blocks. |
| **A balance you can trust** | A weekly one-tap check ("Is your money still about $1,150?"), spending you add or **import from your bank's CSV** lowers it, and a **safety cushion** Kharcha never plans to spend. |

### The design rule: AI suggests, code decides

- The AI never calls PayPal. Every payment goes through `backend/app/guard/`, plain Python rules with unit tests: payee matches, amount ≤ limit, inside the date window, not expired, not already paid, no overdraft.
- All money math (forecast, safe-to-spend, loan schedule, dream plans) is plain Python in `backend/app/finance/`. Gemini only explains the numbers.
- Uploaded documents are untrusted. Extraction results are suggestions that the student must confirm, and a changed payee is blocked by the guard.

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams and details.

## PayPal and AI tools used

**PayPal (sandbox REST APIs)**
- **Log in with PayPal** (`/connect` + `/v1/identity/oauth2/userinfo`): each student's own account.
- **Orders v2 one-tap payment** (`purchase_units[].payee`): the student approves on PayPal and the money goes straight to the landlord or college.
- **Vault v3** (`/v3/vault/setup-tokens`, `/v3/vault/payment-tokens`): save the student's PayPal once, without a purchase.
- **Orders v2** (`/v2/checkout/orders` with `payment_source.paypal.vault_id`): merchant-initiated charge with no popup, plus a `PayPal-Request-Id` so a payment can't be charged twice.
- **Payouts v1** (`/v1/payments/payouts`): pay the landlord or college.
- **Webhooks** (`/v1/notifications/verify-webhook-signature`): confirm captures and payouts.

**AI: Gemini API** (Google Gen AI Python SDK, model `gemini-3.6-flash`, free tier)
- Document reading: PDF/image input plus **structured output** (JSON schema from a Pydantic model) with page-level evidence.
- Nudges: short messages written from numbers our code computed.
- "Ask Kharcha" agent: function calling with JSON-schema tools. Its two action tools only create something the student taps: `propose_payment` (an approval request) and `propose_dream` (a "Save dream" card with Kharcha's plan).

**Other:** FastAPI, SQLite (SQLModel), React + Vite + Tailwind, **AG Grid** (spending table), Recharts.

## Run it locally

You need **Python 3.12+** and **Node 20.19+**.

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
uvicorn app.main:app --port 8000
```

With an empty `.env`, the app runs in **mock mode**: fake PayPal ids and template messages, clearly labeled "PayPal mock" and "AI off" in the header. Everything else works.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

### 3. Try the demo story

The demo student, Riya, has $1,100. Rent ($1,200) is due in 7 days, and $800 from home arrives 2 days after the due date.

1. **Home** shows *Safe to spend today*, the rent marked **Smart wait**, and a heads-up that the spring fee will be short.
2. Click **Connect PayPal** (in mock mode it returns immediately).
3. Click **+7 days** on the demo clock: it's the due date, and rent is *not* charged, because that would overdraw.
4. Click **+1 day** twice: money from home arrives, and rent is paid inside the grace period. Open **Activity** → *Show guard checks*.
5. On **Bills**, click the rent amount and change it to **$1,400** (the landlord raised it). Advance about 30 days: the guard **blocks** the payment because it's above the $1,250 limit, and **Home** asks for your OK.
6. **Dreams:** in **Ask Kharcha**, tap *"I want to fly home in May…"* and then **Save dream** (needs AI on; or add it on the **Dreams** page). It waits, because the spring fee is short and bills come first. Tap **I asked family for $…** on the alert: now the plan shows money is tight until the fee, then roughly $50 a week for dreams, the flight's ready date, and a **Make room** idea. Advance to a Monday to see money set aside.
7. Click **Reset demo** to start over.

## Running it for real

Everything below is free. The demo keeps working as before (`DEMO_MODE=true`).

1. **Log in with PayPal.** In your PayPal app (developer.paypal.com → Apps & Credentials → your app), under *Other features* tick **Log in with PayPal** → *Advanced Settings*: Return URL `http://localhost:5173/auth/paypal/return` (or your deployed frontend + `/auth/paypal/return`), choose **Email** and **Full name**, add any privacy-policy and user-agreement URL (for testing, `https://example.com`), and save. Then set `DEMO_MODE=false` so everyone must log in.
2. **Never miss a bill day on free hosting.** Free servers sleep. Set `CRON_SECRET` to a long random string, and at [cron-job.org](https://cron-job.org) (free) call `https://<your-api>/api/cron/daily-check?key=<CRON_SECRET>` every hour. When the server wakes up, Kharcha also **catches up on any missed days** (money that arrived, reminders, dream savings).
3. **Keep your data.** Free hosts wipe local files on restart, so use a free Postgres (for example [Neon](https://neon.tech), no card needed): set `DATABASE_URL` to the URL they give you. New columns are added automatically when you update Kharcha.
4. **Alerts.** Phone alerts work with no setup: open **Settings → Alerts → Turn on phone alerts** (on iPhone, first *Share → Add to Home Screen*). For email, fill in `SMTP_*` in `.env` with any SMTP account (a Gmail app password, or a free Brevo account).
5. **Privacy.** Kharcha never stores uploaded files, only the numbers you confirm. On Gemini's free tier Google may use what you send, so upload sample documents, or type bills in yourself (**Add bill → Type it yourself**).

**Still not free (a real launch needs these):** a bank connection (for example Plaid) to read balances automatically, the paid Gemini tier for private documents, and **PayPal partner approval** for full autopay. PayPal ties a saved PayPal to the business that saved it, so fully automatic payments go through Kharcha's account and Payouts. A real launch needs PayPal's partner (multiparty) setup so even autopay goes straight to the landlord. Until then, **Remind me + Pay with PayPal** is the real-world mode: free, and Kharcha never holds anyone's money.

## Use the real PayPal sandbox and Gemini

1. At [developer.paypal.com](https://developer.paypal.com), open **Apps & Credentials** → **Sandbox** → create an app. In the app settings, enable **Accept payments** and, under Advanced options, **Vault**. Make sure **Payouts** is enabled.
2. Under **Sandbox accounts**, use one **personal** account as the student (you'll log in with it when you click *Connect PayPal*), and one more personal account as the landlord/college.
3. Fill in `backend/.env`:
   ```
   PAYPAL_CLIENT_ID=...
   PAYPAL_CLIENT_SECRET=...
   DEMO_LANDLORD_EMAIL=<landlord sandbox email>
   DEMO_COLLEGE_EMAIL=<college sandbox email>
   GEMINI_API_KEY=...            # free key from aistudio.google.com
   ```
4. Restart the backend and click **Reset demo**.
5. **Webhooks** need a public URL. After deploying, add `https://<your-api>/api/webhooks/paypal` in the app's webhook settings and set `PAYPAL_WEBHOOK_ID`.

## Deploy to Render (free)

[`render.yaml`](render.yaml) sets up two free services: **kharcha-api** (the FastAPI backend, a web service) and **kharcha** (the React app, a static site).

1. Push this repo to GitHub.
2. At [render.com](https://render.com), sign up with GitHub, click **New → Blueprint** and pick the repo. Render lists both services and asks for the values marked `sync: false`:
   - `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `DEMO_LANDLORD_EMAIL`, `DEMO_COLLEGE_EMAIL`, `GEMINI_API_KEY`: the same values as in your `backend/.env`.
   - `FRONTEND_URL`: `https://kharcha.onrender.com`. `VITE_API_URL`: `https://kharcha-api.onrender.com`. No slash at the end. These are best guesses; step 3 checks them.
   - `DATABASE_URL`: leave it blank for SQLite, or paste a free [Neon](https://neon.tech) Postgres URL to keep data across restarts.
   - `PAYPAL_WEBHOOK_ID`: leave it blank for now (step 5).
3. When the first deploy finishes, check each service's URL at the top of its page. If a name was taken, Render adds a suffix (for example `kharcha-api-ab12.onrender.com`). In that case fix `FRONTEND_URL` on **kharcha-api** and `VITE_API_URL` on **kharcha** in each service's **Environment** tab, and save and redeploy. The static site has to be rebuilt, because `VITE_API_URL` is read at build time.
4. **Log in with PayPal:** in your PayPal app settings, add `<FRONTEND_URL>/auth/paypal/return` as a Return URL (see *Running it for real*, step 1).
5. **Webhooks:** in your PayPal app, add a webhook to `https://<kharcha-api URL>/api/webhooks/paypal` with the `PAYMENT.CAPTURE.*` and `PAYMENT.PAYOUTS-ITEM.*` events. Then copy its ID into `PAYPAL_WEBHOOK_ID` on **kharcha-api**.
6. **Wake-up timer:** Render made a random `CRON_SECRET` (in kharcha-api's **Environment** tab). Use it with [cron-job.org](https://cron-job.org) as described in *Running it for real*, step 2.

Things to know about the free tier:
- The API sleeps after about 15 minutes without visits and takes up to a minute to wake. Meanwhile the app shows *Waking up the server…* and keeps retrying. Open it a minute before you record or demo.
- Without `DATABASE_URL`, the SQLite database starts fresh on every restart. The demo student comes back each time, but logged-in students lose their data.
- If Render asks for a card when you create the Blueprint, create the two services by hand instead (**New → Web Service** and **New → Static Site**), with the same settings as in `render.yaml`.

## Tests

```bash
cd backend
python -m pytest -q
```

The tests cover smart timing, every guard rule, the loan, safe-to-spend and dreams math, payout status checks, login, catch-up, the wake-up URL, balance check-ins, bank CSV import, the safety cushion, remind-me bills, one-tap PayPal payments, alerts, the database upgrade step, and the full demo and dreams stories through the API (mock PayPal, AI off).

## Notes

- Sandbox only. No real money moves.
- In the sandbox, money flows student → Kharcha's business account → landlord. A real launch would pay the landlord directly with PayPal's multiparty tools, under the right licenses.
- PayPal doesn't let third-party apps read a personal account's balance, so the student enters their current money (the demo seeds it).
- All names in the demo (Maple Apartments, City Transit Card, Shiksha Bank, State University) are made up.
- Loan figures are estimates, not financial advice.

## License

[MIT](LICENSE)
