import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { Button, Card } from "../components/ui";

const STATE_KEY = "kharcha_login_state";

function randomState(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Starts "Log in with PayPal". PayPal sends the student back to /auth/paypal/return. */
export async function startPayPalLogin() {
  const state = randomState();
  try {
    sessionStorage.setItem(STATE_KEY, state);
  } catch {
    /* without storage we can't check `state`, so the return page will ask to try again */
  }
  const { url } = await api.post<{ url: string }>("/auth/paypal/start", { state });
  window.location.href = url;
}

export function takeLoginState(): string | null {
  try {
    const s = sessionStorage.getItem(STATE_KEY);
    sessionStorage.removeItem(STATE_KEY);
    return s;
  } catch {
    return null;
  }
}

export default function Login() {
  const [cfg, setCfg] = useState<{ demo_mode: boolean; mock: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ demo_mode: boolean; mock: boolean }>("/auth/config").then(setCfg).catch(() => setCfg(null));
  }, []);

  async function login() {
    setBusy(true);
    setErr(null);
    try {
      await startPayPalLogin();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md pt-10">
      <Card className="text-center">
        <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-brand text-2xl font-extrabold text-marigold">K</span>
        <h1 className="mt-4 text-2xl font-extrabold tracking-tight">Welcome to Kharcha</h1>
        <p className="mt-2 text-sm text-muted">
          Your money copilot: bills on the smartest day, never past your limits, and money set aside for your dreams.
        </p>
        <Button tone="warm" className="mt-6 w-full" disabled={busy} onClick={login}>
          {busy ? "Opening PayPal…" : "Log in with PayPal"}
        </Button>
        {cfg?.mock && <p className="mt-2 text-xs text-muted">PayPal is in mock mode here, so this logs you in as a test student.</p>}
        {err && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{err}</p>}
        <p className="mt-4 text-xs text-muted">
          Kharcha only gets your name and email from PayPal. It never sees your PayPal password or balance.
        </p>
        {cfg?.demo_mode && (
          <p className="mt-4 text-sm">
            <Link to="/" className="font-semibold text-brand underline">Or try the demo student, no login</Link>
          </p>
        )}
      </Card>
    </div>
  );
}
