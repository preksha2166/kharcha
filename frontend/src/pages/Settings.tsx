import { useCallback, useEffect, useState } from "react";

import { api, type AlertsView, type IncomeView } from "../api";
import { Badge, Button, Card, CardTitle, Empty } from "../components/ui";
import { addDays, day, money } from "../format";
import { useApp } from "../state";
import { startPayPalLogin } from "./Login";

const input = "mt-1 block w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-brand";

export default function Settings() {
  const { data } = useApp();
  if (!data) return <p className="text-sm text-muted">Loading…</p>;
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Settings</h1>
          <p className="text-sm text-muted">Your numbers, the money you get, and how Kharcha reaches you.</p>
        </div>
        <MoneySettings />
        <Incomes />
      </div>
      <div className="space-y-5 lg:pt-14">
        <Alerts />
        <Account />
      </div>
    </div>
  );
}

function MoneySettings() {
  const { data, run } = useApp();
  const u = data!.user;
  const [cushion, setCushion] = useState(String(u.safety_cushion));
  const [days, setDays] = useState(String(u.transfer_days_from_home));
  const [loan, setLoan] = useState(String(u.loan_set_aside_monthly));
  return (
    <Card>
      <CardTitle>Your money</CardTitle>
      <form
        className="grid gap-3 sm:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          void run(
            () =>
              api.patch("/user", {
                safety_cushion: Number(cushion) || 0,
                transfer_days_from_home: Number(days) || 0,
                loan_set_aside_monthly: Number(loan) || 0,
              }),
            "Saved.",
          );
        }}
      >
        <label className="text-xs font-medium text-muted">
          Safety cushion ($)
          <input className={input} value={cushion} onChange={(e) => setCushion(e.target.value)} inputMode="decimal" />
        </label>
        <label className="text-xs font-medium text-muted">
          Days a transfer from home takes
          <input className={input} value={days} onChange={(e) => setDays(e.target.value)} inputMode="numeric" />
        </label>
        <label className="text-xs font-medium text-muted">
          Loan set-aside per month ($)
          <input className={input} value={loan} onChange={(e) => setLoan(e.target.value)} inputMode="decimal" />
        </label>
        <p className="text-xs text-muted sm:col-span-3">
          Kharcha never plans to leave less than your safety cushion, so a small mistake in your balance can't overdraw you.
          Your balance now: <strong className="text-ink">{money(u.current_money, true)}</strong>
          {u.balance_checked_on ? `, last checked ${day(u.balance_checked_on)}` : ", not checked yet"}. You can fix it on Home.
        </p>
        <div className="sm:col-span-3">
          <Button size="sm" type="submit">Save</Button>
        </div>
      </form>
    </Card>
  );
}

const EVERY: Record<IncomeView["recurrence"], string> = { once: "once", monthly: "every month", biweekly: "every 2 weeks" };

export function Incomes() {
  const { data, run } = useApp();
  const [rows, setRows] = useState<IncomeView[] | null>(null);
  const [label, setLabel] = useState("Money from home");
  const [amount, setAmount] = useState("");
  const [every, setEvery] = useState<IncomeView["recurrence"]>("monthly");
  const [next, setNext] = useState(data ? addDays(data.today, 7) : "");
  const load = useCallback(() => api.get<IncomeView[]>("/incomes").then(setRows).catch(() => setRows([])), []);
  useEffect(() => {
    void load();
  }, [load, data?.today, data?.user.id]);

  return (
    <Card>
      <CardTitle>Money you get</CardTitle>
      {rows === null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <Empty>Add the money you get, like money from home or a campus job paycheck.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2 first:pt-0">
              <div className="text-sm">
                <p className="font-semibold">{r.label}: {money(r.amount)}</p>
                <p className="text-muted">
                  {EVERY[r.recurrence]}, {r.recurrence === "once" ? "on" : "from"} {day(r.arrives_on)}
                  {r.last_received ? ` · last arrived ${day(r.last_received)}` : ""}
                </p>
              </div>
              <Button size="sm" tone="danger" onClick={() => run(() => api.del(`/incomes/${r.id}`), "Removed.").then(load)}>Remove</Button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="mt-4 grid gap-3 rounded-xl bg-stone-50 p-3 sm:grid-cols-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!(Number(amount) > 0) || !label.trim()) return;
          const ok = await run(
            () => api.post("/incomes", { label: label.trim(), amount: Number(amount), recurrence: every, arrives_on: next }),
            "Added. Kharcha now plans with it.",
          );
          if (ok) {
            setAmount("");
            void load();
          }
        }}
      >
        <label className="text-xs font-medium text-muted">
          What
          <input className={input} value={label} onChange={(e) => setLabel(e.target.value)} maxLength={60} />
        </label>
        <label className="text-xs font-medium text-muted">
          Amount ($)
          <input className={input} value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="800" />
        </label>
        <label className="text-xs font-medium text-muted">
          How often
          <select className={input} value={every} onChange={(e) => setEvery(e.target.value as IncomeView["recurrence"])}>
            <option value="monthly">Every month</option>
            <option value="biweekly">Every 2 weeks</option>
            <option value="once">Just once</option>
          </select>
        </label>
        <label className="text-xs font-medium text-muted">
          Next time it arrives
          <input type="date" className={input} value={next} min={data?.today} onChange={(e) => setNext(e.target.value)} />
        </label>
        <div className="sm:col-span-2">
          <Button size="sm" type="submit" disabled={!(Number(amount) > 0)}>Add money</Button>
        </div>
      </form>
    </Card>
  );
}

function urlB64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function Alerts() {
  const { data, run, toast } = useApp();
  const [a, setA] = useState<AlertsView | null>(null);
  const [email, setEmail] = useState(data?.user.email ?? "");
  const [busy, setBusy] = useState(false);
  const [thisDevice, setThisDevice] = useState<string | null>(null);

  const load = useCallback(() => api.get<AlertsView>("/alerts").then(setA).catch(() => setA(null)), []);
  useEffect(() => {
    void load();
    if (pushSupported()) {
      navigator.serviceWorker.getRegistration().then((reg) => reg?.pushManager.getSubscription()).then((sub) => setThisDevice(sub?.endpoint ?? null)).catch(() => {});
    }
  }, [load]);

  async function turnOn() {
    if (!a) return;
    setBusy(true);
    try {
      if (!pushSupported()) throw new Error("This browser can't show alerts. On iPhone, first tap Share → Add to Home Screen, then open Kharcha from there.");
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("Alerts are blocked for this site. Allow notifications in your browser settings, then try again.");
      const reg = await navigator.serviceWorker.register("/sw.js");
      await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToBytes(a.push_public_key) });
      const json = sub.toJSON();
      setA(await api.post<AlertsView>("/alerts/push", { endpoint: json.endpoint, keys: json.keys }));
      setThisDevice(sub.endpoint);
      toast("Phone alerts are on for this device.");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.getRegistration();
      const sub = await reg?.pushManager.getSubscription();
      if (sub) {
        setA(await api.post<AlertsView>("/alerts/push/remove", { endpoint: sub.endpoint }));
        await sub.unsubscribe();
      }
      setThisDevice(null);
      toast("Phone alerts are off for this device.");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardTitle right={a && a.push_devices > 0 ? <Badge tone="ok">{a.push_devices} device{a.push_devices > 1 ? "s" : ""}</Badge> : undefined}>Alerts</CardTitle>
      <p className="text-sm text-muted">
        Get "Rent is due in 7 days", "Pay today" and "Payment blocked" on your phone, even when Kharcha is closed. Free.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {thisDevice ? (
          <Button size="sm" tone="ghost" disabled={busy} onClick={turnOff}>Turn off on this device</Button>
        ) : (
          <Button size="sm" tone="warm" disabled={busy || !a} onClick={turnOn}>Turn on phone alerts</Button>
        )}
        <Button size="sm" tone="ghost" onClick={() => run(() => api.post("/alerts/test"), "Test alert sent.")}>Send a test</Button>
      </div>
      <p className="mt-2 text-xs text-muted">On iPhone: tap Share → Add to Home Screen, open Kharcha from there, then turn alerts on.</p>

      <div className="mt-5 border-t border-line pt-4">
        <label className="text-xs font-medium text-muted">
          Email
          <input className={input} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" type="email" />
        </label>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={Boolean(data?.user.notify_email)}
            disabled={!a?.email_ready}
            onChange={(e) => void run(() => api.patch("/user", { email, notify_email: e.target.checked }), e.target.checked ? "Email alerts on." : "Email alerts off.")}
          />
          Email me alerts too
        </label>
        {a && !a.email_ready && (
          <p className="mt-1 text-xs text-muted">Email needs an SMTP account in backend/.env (SMTP_HOST, SMTP_FROM…). See the README.</p>
        )}
        <Button size="sm" tone="ghost" className="mt-3" onClick={() => run(() => api.patch("/user", { email }), "Email saved.")}>Save email</Button>
      </div>
    </Card>
  );
}

function Account() {
  const { data, loggedIn, logout, toast } = useApp();
  const u = data!.user;
  return (
    <Card>
      <CardTitle>Account</CardTitle>
      {loggedIn ? (
        <>
          <p className="text-sm">
            Logged in as <strong>{u.name}</strong>
            {u.email ? ` (${u.email})` : ""} with PayPal.
          </p>
          <Button size="sm" tone="ghost" className="mt-3" onClick={() => void logout()}>Log out</Button>
        </>
      ) : (
        <>
          <p className="text-sm">
            You're using the <strong>demo student</strong>. Log in with PayPal to get your own private Kharcha.
          </p>
          <Button
            size="sm"
            tone="warm"
            className="mt-3"
            onClick={() => startPayPalLogin().catch((e: unknown) => toast(e instanceof Error ? e.message : String(e), "error"))}
          >
            Log in with PayPal
          </Button>
        </>
      )}
    </Card>
  );
}
