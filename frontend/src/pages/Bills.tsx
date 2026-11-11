import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type BillView } from "../api";
import ConnectPayPal from "../components/ConnectPayPal";
import PayButtons from "../components/PayButtons";
import { Badge, Button, Card, Empty, StatusPill } from "../components/ui";
import { day, money, relDays } from "../format";
import { useApp } from "../state";

export default function Bills() {
  const { data, run } = useApp();
  if (!data) return <p className="text-sm text-muted">Loading…</p>;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Bills & autopay</h1>
          <p className="text-sm text-muted">Kharcha picks the best day to pay, but never goes past the limits you set here.</p>
        </div>
        <div className="flex items-center gap-2">
          {data.user.paypal_connected ? (
            <>
              <Badge tone="ok">PayPal connected{data.user.paypal_connected_mock ? " (mock)" : ""}</Badge>
              <Button tone="ghost" size="sm" onClick={() => run(() => api.post("/paypal/disconnect"), "PayPal disconnected.")}>Disconnect</Button>
            </>
          ) : (
            <ConnectPayPal size="sm" />
          )}
          <Link to="/upload"><Button size="sm">Add a bill</Button></Link>
        </div>
      </div>
      <Card className="bg-stone-50 text-sm text-muted">
        <strong className="text-ink">Two ways to pay.</strong> <strong className="text-ink">Remind me</strong> (free): Kharcha tells you the best day,
        and you pay from your bank or with one tap on PayPal, straight to them. <strong className="text-ink">Full autopay</strong>: Kharcha pays with
        your saved PayPal inside your limits. PayPal takes about {data.mode.paypal_fee_percent}% + {money(data.mode.paypal_fee_fixed, true)} from what the
        receiver gets, and for real use it needs PayPal partner approval, so it's a demo for now.
      </Card>
      {data.bills.length === 0 ? <Empty>No bills yet. Upload a lease or fee notice, or type one in.</Empty> : (
        <div className="grid gap-4 md:grid-cols-2">
          {data.bills.map((b) => <BillCard key={b.id} bill={b} />)}
        </div>
      )}
    </div>
  );
}

function BillCard({ bill }: { bill: BillView }) {
  const { run } = useApp();
  const [editingLimit, setEditingLimit] = useState(false);
  const [limit, setLimit] = useState(String(bill.autopay?.max_amount ?? Math.ceil(bill.amount * 1.05)));
  const [editingAmount, setEditingAmount] = useState(false);
  const [amount, setAmount] = useState(String(bill.amount));

  const saveLimit = () =>
    run(() => api.post(`/bills/${bill.id}/mandate`, { max_amount: Number(limit) }), `Autopay limit for ${bill.name} saved.`).then(() =>
      setEditingLimit(false),
    );
  const saveAmount = () =>
    run(() => api.patch(`/bills/${bill.id}`, { amount: Number(amount) }), `${bill.name} is now ${money(Number(amount))}.`).then(() =>
      setEditingAmount(false),
    );

  const ap = bill.autopay;
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-bold">{bill.name}</h3>
            <StatusPill status={bill.status} />
          </div>
          <p className="text-sm text-muted">{bill.payee_name} · {bill.recurrence === "monthly" ? "monthly" : "one-time"}</p>
        </div>
        <div className="text-right">
          {editingAmount ? (
            <div className="flex items-center gap-1">
              <input className="w-24 rounded-lg border border-line px-2 py-1 text-right text-sm tabular" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
              <Button size="sm" onClick={saveAmount}>Save</Button>
            </div>
          ) : (
            <button className="text-xl font-extrabold tabular hover:underline" title="Change amount (e.g. landlord raised rent)" onClick={() => setEditingAmount(true)}>
              {money(bill.amount)}
            </button>
          )}
        </div>
      </div>

      {bill.status !== "paid" && (
        <dl className="mt-4 grid grid-cols-3 gap-2 rounded-xl bg-stone-50 p-3 text-sm">
          <div><dt className="text-xs text-muted">Due</dt><dd className="font-semibold">{day(bill.due)}</dd><dd className="text-xs text-muted">{relDays(bill.days_to_due)}</dd></div>
          <div><dt className="text-xs text-muted">No late fee until</dt><dd className="font-semibold">{day(bill.last_free_day)}</dd><dd className="text-xs text-muted">{bill.late_fee ? `then ${money(bill.late_fee)} fee` : "no fee"}</dd></div>
          <div><dt className="text-xs text-muted">{bill.pay_mode === "remind" ? "Best day to pay" : "Kharcha pays"}</dt><dd className="font-semibold text-brand">{day(bill.pay_on)}</dd></div>
        </dl>
      )}
      <p className="mt-3 text-sm">{bill.reason}</p>

      <div className="mt-4 flex flex-wrap items-center gap-1 rounded-xl bg-stone-100 p-1 text-sm">
        {(["remind", "paypal"] as const).map((m) => (
          <button
            key={m}
            className={`flex-1 rounded-lg px-3 py-1.5 font-semibold ${bill.pay_mode === m ? "bg-white text-ink shadow-sm" : "text-muted hover:text-ink"}`}
            onClick={() =>
              bill.pay_mode !== m &&
              run(() => api.patch(`/bills/${bill.id}`, { pay_mode: m }), m === "remind" ? `${bill.name}: Kharcha will remind you.` : `${bill.name}: full autopay.`)
            }
          >
            {m === "remind" ? "Remind me (free)" : "Full autopay"}
          </button>
        ))}
      </div>

      {bill.pay_mode === "remind" ? (
        <div className="mt-4 border-t border-line pt-4">
          <p className="text-sm text-muted">
            On the best day Kharcha reminds you{bill.pay_today ? " (that's today)" : ""}. Pay {bill.payee_name} your usual way, or with one tap on PayPal straight to them.
          </p>
          {bill.status !== "paid" && bill.due && (
            <div className="mt-3">
              <PayButtons bill={bill} />
            </div>
          )}
        </div>
      ) : (
      <div className="mt-4 border-t border-line pt-4">
        <p className="mb-3 text-xs text-muted">
          PayPal fee on each payment: about {money(bill.paypal_fee, true)} (taken from what the receiver gets).
        </p>
        {editingLimit ? (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>Pay {bill.payee_name} automatically, up to</span>
            <input className="w-24 rounded-lg border border-line px-2 py-1 tabular" value={limit} onChange={(e) => setLimit(e.target.value)} inputMode="decimal" />
            <Button size="sm" onClick={saveLimit}>Save limit</Button>
            <Button size="sm" tone="ghost" onClick={() => setEditingLimit(false)}>Cancel</Button>
          </div>
        ) : ap ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm">
              <span className="font-semibold">{ap.paused ? "Autopay paused" : `Autopay up to ${money(ap.max_amount)}`}</span>
              <span className="text-muted"> · from {ap.earliest_days_before_due} days before to {ap.latest_days_after_due} days after the due date · until {day(ap.valid_until)}</span>
            </p>
            <div className="flex gap-2">
              <Button size="sm" tone="ghost" onClick={() => setEditingLimit(true)}>Change limit</Button>
              <Button size="sm" tone="ghost" onClick={() => run(() => api.patch(`/mandates/${ap.id}`, { paused: !ap.paused }), ap.paused ? "Autopay resumed." : "Autopay paused.")}>
                {ap.paused ? "Resume" : "Pause"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-muted">Autopay is off. Kharcha will ask you before paying.</p>
            <Button size="sm" tone="ghost" onClick={() => setEditingLimit(true)}>Turn on autopay</Button>
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {bill.pending_payment_id ? (
            <Button size="sm" onClick={() => run(() => api.post(`/payments/${bill.pending_payment_id}/approve`), `Paid ${bill.name}.`)}>
              Approve & pay {money(bill.amount)}
            </Button>
          ) : bill.status !== "paid" ? (
            <Button size="sm" tone="ghost" onClick={() => run(() => api.post(`/bills/${bill.id}/pay`), `Paid ${bill.name}.`)}>
              Pay now
            </Button>
          ) : null}
        </div>
      </div>
      )}
    </Card>
  );
}
