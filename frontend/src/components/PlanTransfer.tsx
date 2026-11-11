import { useState } from "react";

import { api } from "../api";
import { addDays, money } from "../format";
import { useApp } from "../state";
import { Button } from "./ui";

/** "I asked family for it": tells Kharcha about money on its way, so bills (and dreams) can plan with it. */
export default function PlanTransfer({ shortfall, transferBy }: { shortfall: number; transferBy: string | null }) {
  const { data, run } = useApp();
  const [open, setOpen] = useState(false);
  const suggested = Math.ceil(shortfall / 100) * 100;
  const [amount, setAmount] = useState(String(suggested));
  const days = data?.user.transfer_days_from_home ?? 4;
  const earliest = data ? addDays(data.today, 0) : "";
  const fallback = data ? addDays(data.today, days) : "";
  const arrival = transferBy ? addDays(transferBy, days) : fallback;
  const [arrives, setArrives] = useState(arrival < earliest ? fallback : arrival);

  if (!open) {
    return (
      <Button size="sm" tone="ghost" onClick={() => setOpen(true)}>
        I asked family for {money(suggested)}
      </Button>
    );
  }

  async function save() {
    const value = Number(amount);
    if (!(value > 0) || !arrives) return;
    const ok = await run(
      () => api.post("/incomes", { label: "Transfer from home", amount: value, arrives_on: arrives }),
      `Got it. Kharcha now plans with ${money(value)} arriving then.`,
    );
    if (ok) setOpen(false);
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded-xl bg-white p-3 ring-1 ring-amber-200"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <label className="text-xs font-medium text-muted">
        Amount ($)
        <input
          className="mt-1 block w-28 rounded-lg border border-line px-2 py-1.5 text-sm tabular text-ink"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          inputMode="decimal"
        />
      </label>
      <label className="text-xs font-medium text-muted">
        Arrives on
        <input
          type="date"
          className="mt-1 block rounded-lg border border-line px-2 py-1.5 text-sm text-ink"
          value={arrives}
          min={earliest}
          onChange={(e) => setArrives(e.target.value)}
        />
      </label>
      <Button size="sm" type="submit">Save</Button>
      <Button size="sm" tone="ghost" type="button" onClick={() => setOpen(false)}>Cancel</Button>
    </form>
  );
}
