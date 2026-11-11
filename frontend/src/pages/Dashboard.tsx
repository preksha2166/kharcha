import { useState } from "react";
import { Link } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api, type BillView, type Dashboard } from "../api";
import ConnectPayPal from "../components/ConnectPayPal";
import PayButtons from "../components/PayButtons";
import PlanTransfer from "../components/PlanTransfer";
import { Bar, Button, Card, CardTitle, Empty, StatusPill } from "../components/ui";
import { day, inr, money, relDays, shortDay } from "../format";
import { useApp } from "../state";
import { ActionRow } from "./Activity";
import { DreamBar, dreamPace } from "./Dreams";

export default function DashboardPage() {
  const { data } = useApp();
  if (!data) return <p className="text-sm text-muted">Loading…</p>;

  const open = data.bills.filter((b) => b.status !== "paid").slice(0, 4);

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div className="space-y-5 lg:col-span-2">
        <SafeToSpend data={data} />
        {!data.user.is_demo && !data.setup.done && <GettingStarted data={data} />}
        {data.balance_check_due && data.user.balance_checked_on && <BalanceCheck data={data} />}
        <PayToday data={data} />
        {!data.user.paypal_connected && data.setup.done && (
          <Card className="flex flex-wrap items-center justify-between gap-3 border-marigold/40 bg-marigold-soft">
            <div>
              <p className="font-semibold">Connect PayPal (optional)</p>
              <p className="text-sm text-muted">Only if you want full autopay. "Remind me" bills work without it.</p>
            </div>
            <ConnectPayPal />
          </Card>
        )}
        <Approvals data={data} />
        <Alerts data={data} />
        <Card>
          <CardTitle right={<Link to="/bills" className="text-sm font-semibold text-brand">All bills →</Link>}>Coming up</CardTitle>
          {open.length === 0 ? <Empty>No bills due. Nice.</Empty> : (
            <ul className="divide-y divide-line">
              {open.map((b) => <BillRow key={`${b.id}-${b.period}`} bill={b} />)}
            </ul>
          )}
        </Card>
        <Forecast data={data} />
      </div>

      <div className="space-y-5">
        <Card>
          <CardTitle right={<Link to="/spending" className="text-sm font-semibold text-brand">Details →</Link>}>This week's budget</CardTitle>
          <ul className="space-y-3">
            {data.budgets.map((b) => (
              <li key={b.category}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="font-medium">{b.category}</span>
                  <span className="tabular text-muted">{money(b.spent, true)} / {money(b.weekly_limit)}</span>
                </div>
                <Bar percent={b.percent} status={b.status} />
              </li>
            ))}
          </ul>
        </Card>
        <DreamsCard data={data} />
        {data.loan && (
          <Card>
            <CardTitle right={<Link to="/loan" className="text-sm font-semibold text-brand">Plan →</Link>}>Education loan</CardTitle>
            <p className="text-sm text-muted">{data.loan.lender}</p>
            <p className="mt-2 text-2xl font-bold tabular">{inr(data.loan.monthly_payment)}<span className="text-sm font-medium text-muted"> /month</span></p>
            <p className="text-sm text-muted">
              after studies (≈ {money(data.loan.monthly_payment_usd)} at the demo rate), starting {shortDay(data.loan.repayment_start)}.
            </p>
            <p className="mt-3 rounded-lg bg-marigold-soft px-3 py-2 text-sm">
              Interest so far: <strong className="tabular">{inr(data.loan.interest_accrued_so_far)}</strong>. {data.loan.study_months_left} study months left to chip away at it.
            </p>
          </Card>
        )}
        <Card>
          <CardTitle right={<Link to="/activity" className="text-sm font-semibold text-brand">All →</Link>}>What Kharcha did</CardTitle>
          {data.recent_activity.length === 0 ? <Empty>Nothing yet.</Empty> : (
            <ul className="space-y-3">
              {data.recent_activity.slice(0, 5).map((a) => <ActionRow key={a.id} action={a} compact />)}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

const field = "w-28 rounded-lg border border-line bg-white px-2 py-1.5 text-sm tabular text-ink";

function GettingStarted({ data }: { data: Dashboard }) {
  const { run } = useApp();
  const [money_, setMoney] = useState("");
  const s = data.setup;
  const Step = ({ done, n, title, children }: { done: boolean; n: number; title: string; children: React.ReactNode }) => (
    <li className="flex gap-3">
      <span className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold ${done ? "bg-emerald-500 text-white" : "bg-brand-soft text-brand"}`}>
        {done ? "✓" : n}
      </span>
      <div className="min-w-0 flex-1">
        <p className={`font-semibold ${done ? "text-muted line-through" : ""}`}>{title}</p>
        {!done && <div className="mt-1 text-sm text-muted">{children}</div>}
      </div>
    </li>
  );
  return (
    <Card className="border-brand/30">
      <CardTitle>Getting started</CardTitle>
      <ul className="space-y-4">
        <Step done={s.money} n={1} title="How much money do you have now?">
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (money_.trim() !== "") void run(() => api.post("/user/balance", { current_money: Number(money_) }), "Saved.");
            }}
          >
            <span>$</span>
            <input className={field} value={money_} onChange={(e) => setMoney(e.target.value)} inputMode="decimal" placeholder="1100" />
            <Button size="sm" type="submit">Save</Button>
            <span className="text-xs">Check your bank app. Kharcha can't read it.</span>
          </form>
        </Step>
        <Step done={s.income} n={2} title="What money do you get?">
          Money from home, a campus job paycheck… <Link to="/settings" className="font-semibold text-brand underline">Add it in Settings</Link>.
        </Step>
        <Step done={s.bills} n={3} title="What bills do you pay?">
          Rent, phone, college fees. <Link to="/upload" className="font-semibold text-brand underline">Upload the lease or type it in</Link>.
        </Step>
        <Step done={s.paypal} n={4} title="Connect PayPal (optional)">
          Only for full autopay. You can always pay yourself and tap "I paid it".
        </Step>
      </ul>
    </Card>
  );
}

function BalanceCheck({ data }: { data: Dashboard }) {
  const { run } = useApp();
  const [fixing, setFixing] = useState(false);
  const [value, setValue] = useState(String(data.user.current_money));
  return (
    <Card className="border-brand/30 bg-brand-soft">
      <p className="font-semibold">Quick check: is your money still about {money(data.user.current_money)}?</p>
      <p className="text-sm text-muted">
        Last checked {day(data.user.balance_checked_on)}. Every plan uses this number, so a quick look at your bank app keeps them right.
      </p>
      {fixing ? (
        <form
          className="mt-3 flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => api.post("/user/balance", { current_money: Number(value) }), "Balance updated.");
          }}
        >
          <span className="text-sm">It's $</span>
          <input className={field} value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal" autoFocus />
          <Button size="sm" type="submit">Save</Button>
          <Button size="sm" tone="ghost" type="button" onClick={() => setFixing(false)}>Cancel</Button>
        </form>
      ) : (
        <div className="mt-3 flex gap-2">
          <Button size="sm" onClick={() => run(() => api.post("/user/balance", { current_money: data.user.current_money }), "Thanks, all set.")}>
            Yes, that's right
          </Button>
          <Button size="sm" tone="ghost" onClick={() => setFixing(true)}>No, fix it</Button>
        </div>
      )}
    </Card>
  );
}

function PayToday({ data }: { data: Dashboard }) {
  if (data.pay_yourself.length === 0) return null;
  return (
    <Card className="border-marigold/50 bg-marigold-soft">
      <CardTitle>Pay today</CardTitle>
      <ul className="space-y-4">
        {data.pay_yourself.map((b) => (
          <li key={`${b.id}-${b.period}`} className="space-y-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-semibold">{b.name} to {b.payee_name}</p>
              <p className="text-lg font-bold tabular">{money(b.amount)}</p>
            </div>
            <p className="text-sm text-muted">
              {b.status === "short" || b.status === "late" ? b.reason : `Today is the best day. No late fee until ${day(b.last_free_day)}.`}
            </p>
            <PayButtons bill={b} />
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">"Pay with PayPal" sends it straight to them after you approve it on PayPal. Kharcha never holds your money.</p>
    </Card>
  );
}

function DreamsCard({ data }: { data: Dashboard }) {
  const v = data.dreams;
  return (
    <Card>
      <CardTitle right={<Link to="/dreams" className="text-sm font-semibold text-brand">All →</Link>}>Dreams</CardTitle>
      {v.dreams.length === 0 ? (
        <p className="text-sm text-muted">
          Saving for a flight home or a new laptop? <Link to="/dreams" className="font-semibold text-brand">Add a dream</Link> and
          Kharcha sets money aside every Monday, after bills.
        </p>
      ) : (
        <ul className="space-y-3">
          {v.dreams.slice(0, 3).map((d) => (
            <li key={d.id}>
              <div className="mb-1 flex justify-between gap-2 text-sm">
                <span className="truncate font-medium">{d.emoji} {d.name}</span>
                <span className="tabular text-muted">{money(d.saved_amount)} / {money(d.target_amount)}</span>
              </div>
              <DreamBar dream={d} />
              <p className="mt-1 text-xs text-muted">{dreamPace(d, data.today)}</p>
            </li>
          ))}
        </ul>
      )}
      {v.room.blocked_by && v.dreams.length > 0 && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">On hold: bills come first. {v.room.blocked_by}.</p>
      )}
    </Card>
  );
}

function SafeToSpend({ data }: { data: Dashboard }) {
  const s = data.safe_to_spend;
  const short = s.shortfall > 0;
  return (
    <Card className="overflow-hidden bg-brand p-0 text-white">
      <div className="p-6">
        <p className="text-sm font-medium text-white/70">Hi {data.user.name}. Safe to spend today</p>
        <p className="mt-1 text-5xl font-extrabold tracking-tight tabular">
          {money(s.per_day, true)}
          <span className="ml-2 text-lg font-semibold text-white/60">per day</span>
        </p>
        <p className="mt-2 max-w-xl text-sm text-white/80">
          {short
            ? `Even spending $0, you'd be ${money(s.shortfall)} short by ${day(s.first_short_day)}. See the alert below.`
            : `Spend up to this each day and every bill in the next ${s.horizon_days} days is still covered. Your budgets plan ${money(s.planned_daily_spend, true)}/day.`}
          {!short && (s.dreams_saved > 0 || s.dreams_per_week > 0) && " Money for your dreams is already left out."}
          {!short && s.cushion > 0 && ` Your ${money(s.cushion)} safety cushion stays untouched.`}
        </p>
      </div>
      <dl className={`grid grid-cols-2 gap-px bg-white/10 text-sm ${s.dreams_saved > 0 || s.dreams_in_horizon > 0 ? "sm:grid-cols-5" : "sm:grid-cols-4"}`}>
        {[
          ["Money now", money(s.money_now)],
          ["Coming in (30d)", `+${money(s.income_in_horizon)}`],
          ["Bills (30d)", `−${money(s.bills_in_horizon)}`],
          ["Loan set-aside", `−${money(s.loan_set_aside_in_horizon)}`],
          ...(s.dreams_saved > 0 || s.dreams_in_horizon > 0
            ? [["For dreams", `−${money(Math.round(s.dreams_saved + s.dreams_in_horizon))}`]]
            : []),
        ].map(([k, v]) => (
          <div key={k} className="bg-brand px-6 py-3">
            <dt className="text-xs text-white/60">{k}</dt>
            <dd className="font-semibold tabular">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function Approvals({ data }: { data: Dashboard }) {
  const { run } = useApp();
  if (data.approvals.length === 0) return null;
  return (
    <Card className="border-amber-300 bg-amber-50">
      <CardTitle>Needs your OK</CardTitle>
      <ul className="space-y-4">
        {data.approvals.map((b) => (
          <li key={b.pending_payment_id} className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="font-semibold">{b.name}: {money(b.amount)} to {b.payee_name}</p>
              <p className="text-sm text-amber-900">The guard stopped this payment. Tap approve if it's right.</p>
            </div>
            <div className="flex gap-2">
              <Button tone="ghost" size="sm" onClick={() => run(() => api.post(`/payments/${b.pending_payment_id}/decline`), "Declined.")}>Decline</Button>
              <Button size="sm" onClick={() => run(() => api.post(`/payments/${b.pending_payment_id}/approve`), `Paid ${b.name}.`)}>Approve & pay</Button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Alerts({ data }: { data: Dashboard }) {
  const main = data.alerts.filter((a) => !a.knock_on);
  const knock = data.alerts.filter((a) => a.knock_on);
  if (main.length === 0) return null;
  return (
    <Card className="border-amber-200">
      <CardTitle>Heads-up</CardTitle>
      <ul className="space-y-3">
        {main.map((a) => (
          <li key={`${a.bill_id}-${a.period}`} className="rounded-xl bg-amber-50 p-4">
            <p className="font-semibold">
              {a.name} on {day(a.due)}: {a.status === "late" ? "late" : `about ${money(Math.ceil(a.shortfall))} short`}
            </p>
            <p className="mt-1 text-sm text-amber-900">{a.reason}</p>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <PlanTransfer shortfall={Math.max(...data.alerts.map((a) => a.shortfall))} transferBy={main[0].transfer_by} />
        <span className="text-xs text-muted">Tell Kharcha once family says yes, and it plans with that money.</span>
      </div>
      {knock.length > 0 && (
        <p className="mt-3 text-xs text-muted">
          If this isn't fixed, {knock.length} later bill{knock.length > 1 ? "s" : ""} ({knock.map((k) => k.name).join(", ")}) would also be short.
        </p>
      )}
    </Card>
  );
}

export function BillRow({ bill }: { bill: BillView }) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="font-semibold">{bill.name}</p>
          <StatusPill status={bill.status} />
        </div>
        <p className="text-sm text-muted">
          {bill.payee_name} · due {day(bill.due)} ({relDays(bill.days_to_due)})
          {bill.pay_mode === "remind"
            ? " · remind me"
            : bill.autopay && !bill.autopay.paused
              ? ` · autopay ≤ ${money(bill.autopay.max_amount)}`
              : " · asks you first"}
        </p>
        {bill.status === "waiting_for_money" && (
          <p className="mt-1 text-sm text-brand">
            {bill.pay_mode === "remind" ? "Best day to pay" : "Will pay"} {day(bill.pay_on)}, still before the late fee starts after {day(bill.last_free_day)}.
          </p>
        )}
      </div>
      <p className="text-lg font-bold tabular">{money(bill.amount)}</p>
    </li>
  );
}

function Forecast({ data }: { data: Dashboard }) {
  const points = data.forecast.map((p) => ({ ...p, label: shortDay(p.day) }));
  const min = Math.min(0, ...points.map((p) => p.closing));
  return (
    <Card>
      <CardTitle>Your money, next 60 days</CardTitle>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
            <defs>
              <linearGradient id="bal" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#312e81" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#312e81" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#eee8de" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#5f5b78" }} interval={9} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 11, fill: "#5f5b78" }} tickFormatter={(v: number) => money(v)} width={64} domain={[min, "auto"]} tickLine={false} axisLine={false} />
            <Tooltip
              formatter={(v) => [money(Number(v), true), "Balance"]}
              labelFormatter={(l) => String(l)}
              contentStyle={{ borderRadius: 12, border: "1px solid #e7e2d9", fontSize: 12 }}
            />
            <ReferenceLine y={0} stroke="#dc2626" strokeDasharray="4 4" />
            <Area type="monotone" dataKey="closing" stroke="#312e81" strokeWidth={2} fill="url(#bal)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-muted">Includes expected money from home and paychecks, planned bill payments, and your weekly budgets.</p>
    </Card>
  );
}
