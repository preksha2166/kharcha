import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { Card } from "../components/ui";
import { useApp } from "../state";

/** PayPal sends the student here after approving (or cancelling) a "Pay with PayPal" payment. */
export default function PayPalPaid() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh, toast } = useApp();
  const [msg, setMsg] = useState("Finishing your payment…");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const orderId = params.get("token");
    if (!orderId) {
      setMsg("PayPal didn't send the payment back. Check Activity, then try again.");
      return;
    }
    if (params.get("cancelled")) {
      api.post("/payments/checkout/cancel", { order_id: orderId }).finally(async () => {
        await refresh();
        toast("Payment cancelled. Nothing was paid.", "warn");
        navigate("/", { replace: true });
      });
      return;
    }
    api
      .post("/payments/checkout/capture", { order_id: orderId })
      .then(async () => {
        await refresh();
        toast("Paid. PayPal sent it straight to them.");
        navigate("/", { replace: true });
      })
      .catch((e: unknown) => setMsg(`The payment didn't go through: ${e instanceof Error ? e.message : String(e)}`));
  }, [navigate, params, refresh, toast]);

  return (
    <Card className="mx-auto mt-10 max-w-md text-center">
      <p className="text-sm text-muted">{msg}</p>
    </Card>
  );
}
