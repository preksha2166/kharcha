import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, setToken, type UserView } from "../api";
import { Card } from "../components/ui";
import { useApp } from "../state";
import { takeLoginState } from "./Login";

/** PayPal sends the student here after "Log in with PayPal". */
export default function AuthReturn() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh, toast } = useApp();
  const [msg, setMsg] = useState("Logging you in…");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = params.get("code");
    const state = params.get("state");
    const expected = takeLoginState();
    if (params.get("error") || !code) {
      setMsg("You didn't finish logging in with PayPal.");
      return;
    }
    if (!state || !expected || state !== expected) {
      setMsg("This login link didn't come from this browser. Please try logging in again.");
      return;
    }
    api
      .post<{ token: string; new_user: boolean; user: UserView }>("/auth/paypal/finish", { code })
      .then(async (r) => {
        setToken(r.token);
        await refresh();
        toast(r.new_user ? `Welcome, ${r.user.name}! Let's set up your money.` : `Welcome back, ${r.user.name}.`);
        navigate("/", { replace: true });
      })
      .catch((e: unknown) => setMsg(e instanceof Error ? e.message : String(e)));
  }, [navigate, params, refresh, toast]);

  return (
    <Card className="mx-auto mt-10 max-w-md text-center">
      <p className="text-sm text-muted">{msg}</p>
      {msg !== "Logging you in…" && (
        <Link to="/login" className="mt-3 inline-block text-sm font-semibold text-brand underline">Back to login</Link>
      )}
    </Card>
  );
}
