import { useState } from "react";

import { api } from "../api";
import { useApp } from "../state";
import { Button } from "./ui";

/** Starts PayPal's "save PayPal for later" (Vault) flow. PayPal redirects back to /paypal/return. */
export default function ConnectPayPal({ size = "md" }: { size?: "sm" | "md" }) {
  const { toast } = useApp();
  const [busy, setBusy] = useState(false);

  async function connect() {
    setBusy(true);
    try {
      const st = await api.post<{ id: string; approve_url: string; mock: boolean }>("/paypal/setup-token", {
        return_path: "/paypal/return",
        cancel_path: "/paypal/cancel",
      });
      try {
        sessionStorage.setItem("kharcha_setup_token", st.id);
      } catch {
        /* storage blocked: the return URL also carries the token id */
      }
      window.location.href = st.approve_url;
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
      setBusy(false);
    }
  }

  return (
    <Button tone="warm" size={size} disabled={busy} onClick={connect}>
      {busy ? "Opening PayPal…" : "Connect PayPal"}
    </Button>
  );
}
