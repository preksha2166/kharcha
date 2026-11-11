import { useState } from "react";

import { api, type BillView } from "../api";
import { money } from "../format";
import { useApp } from "../state";
import { Button } from "./ui";

/** The two free ways to pay a "remind me" bill: a one-tap PayPal payment straight to the payee, or "I paid it". */
export default function PayButtons({ bill }: { bill: BillView }) {
  const { run, toast } = useApp();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function payWithPayPal() {
    setBusy(true);
    try {
      const r = await api.post<{ approve_url: string }>(`/bills/${bill.id}/checkout`);
      window.location.href = r.approve_url;
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
      setBusy(false);
    }
  }

  if (confirming) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm">Paid {money(bill.amount)} to {bill.payee_name}?</span>
        <Button size="sm" onClick={() => run(() => api.post(`/bills/${bill.id}/paid`, {}), `Marked ${bill.name} as paid.`)}>Yes, I paid it</Button>
        <Button size="sm" tone="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {bill.payee_paypal_email && (
        <Button size="sm" tone="warm" disabled={busy} onClick={payWithPayPal} title="You approve it on PayPal; the money goes straight to them">
          {busy ? "Opening PayPal…" : "Pay with PayPal"}
        </Button>
      )}
      <Button size="sm" tone="ghost" onClick={() => setConfirming(true)}>I paid it</Button>
    </div>
  );
}
