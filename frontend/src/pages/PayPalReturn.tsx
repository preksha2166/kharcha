import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { Card } from "../components/ui";
import { useApp } from "../state";

export default function PayPalReturn({ cancelled = false }: { cancelled?: boolean }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh, toast } = useApp();
  const [msg, setMsg] = useState(cancelled ? "You cancelled connecting PayPal." : "Saving your PayPal…");
  const started = useRef(false);

  useEffect(() => {
    if (cancelled || started.current) return;
    started.current = true;
    let stored: string | null = null;
    try {
      stored = sessionStorage.getItem("kharcha_setup_token");
    } catch {
      /* ignore */
    }
    const tokenId = params.get("approval_token_id") ?? stored;
    if (!tokenId) {
      setMsg("PayPal didn't send back a token. Please try connecting again.");
      return;
    }
    api
      .post("/paypal/payment-token", { setup_token_id: tokenId })
      .then(async () => {
        try {
          sessionStorage.removeItem("kharcha_setup_token");
        } catch {
          /* ignore */
        }
        await refresh();
        toast("PayPal connected. Autopay can now run inside your limits.");
        navigate("/bills", { replace: true });
      })
      .catch((e: unknown) => setMsg(`Couldn't save PayPal: ${e instanceof Error ? e.message : String(e)}`));
  }, [cancelled, navigate, params, refresh, toast]);

  return (
    <Card className="mx-auto max-w-md text-center">
      <p className="text-sm text-muted">{msg}</p>
    </Card>
  );
}
