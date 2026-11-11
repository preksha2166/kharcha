import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api";
import { Button, Card, CardTitle, Empty } from "../components/ui";
import { inCurrency, monthYear, money } from "../format";
import { useApp } from "../state";

type Analysis = {
  study_months_total: number;
  study_months_left: number;
  interest_accrued_so_far: number;
  interest_by_repayment_start: number;
  paid_during_study: number;
  balance_at_repayment_start: number;
  monthly_payment: number;
  total_interest: number;
  total_paid: number;
  balance_points: { month: string; balance: number }[];
};

type LoanResp = {
  lender: string;
  currency: string;
  principal: number;
  annual_rate: number;
  repayment_start: string;
  disbursed_date: string;
  term_months: number;
  interest_type: string;
  analysis: Analysis;
} | null;

type Scenario = { baseline: Analysis; scenario: Analysis; savings: number; monthly_payment_drop: number; currency: string; fx_inr_per_usd: number };

export default function Loan() {
  const { data } = useApp();
  const [loan, setLoan] = useState<LoanResp | undefined>(undefined);
  const [pay, setPay] = useState(0);
  const [sc, setSc] = useState<Scenario | null>(null);

  useEffect(() => {
    api.get<LoanResp>("/loan").then(setLoan).catch(() => setLoan(null));
  }, [data?.today]);

  useEffect(() => {
    if (!loan) return;
    const t = setTimeout(() => {
      api.post<Scenario>("/loan/scenario", { monthly_payment: pay }).then(setSc).catch(() => setSc(null));
    }, 200);
    return () => clearTimeout(t);
  }, [loan, pay]);

  const monthlyInterest = loan ? (loan.principal * loan.annual_rate) / 100 / 12 : 0;
  const fx = data?.mode.fx_inr_per_usd ?? 88;

  const chart = useMemo(() => {
    if (!sc) return [];
    const map = new Map<string, { month: string; baseline?: number; scenario?: number }>();
    for (const p of sc.baseline.balance_points) map.set(p.month, { month: p.month, baseline: p.balance });
    for (const p of sc.scenario.balance_points) map.set(p.month, { ...(map.get(p.month) ?? { month: p.month }), scenario: p.balance });
    return [...map.values()].sort((a, b) => a.month.localeCompare(b.month));
  }, [sc]);

  if (loan === undefined) return <p className="text-sm text-muted">Loading…</p>;
  if (loan === null)
    return (
      <Empty>
        No loan yet. <Link className="font-semibold text-brand" to="/upload">Upload your loan letter</Link> and Kharcha will explain it.
      </Empty>
    );

  const a = loan.analysis;
  const cur = (n: number) => inCurrency(n, loan.currency);
  const usd = (n: number) => (loan.currency === "INR" ? money(n / fx) : money(n));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Your education loan</h1>
        <p className="text-sm text-muted">{loan.lender} · {loan.annual_rate}% {loan.interest_type} interest during studies · {loan.term_months / 12} years to repay</p>
      </div>

      <Card>
        <CardTitle>In plain words</CardTitle>
        <ul className="space-y-2 text-sm leading-relaxed">
          <li>You borrowed <strong>{cur(loan.principal)}</strong>. While you study, interest keeps adding up: about <strong>{cur(monthlyInterest)}</strong> every month.</li>
          <li>So far that's <strong>{cur(a.interest_accrued_so_far)}</strong>. By {monthYear(loan.repayment_start)} it will be <strong>{cur(a.interest_by_repayment_start)}</strong> if you pay nothing now.</li>
          <li>That interest gets added to the loan, so you'll repay <strong>{cur(a.monthly_payment)}/month</strong> (≈ {usd(a.monthly_payment)}) for {loan.term_months} months.</li>
        </ul>
      </Card>

      <Card>
        <CardTitle>What if I pay a little now?</CardTitle>
        <label className="text-sm font-medium" htmlFor="pay">Pay each month while studying: <span className="tabular text-brand">{cur(pay)}</span> <span className="text-muted">(≈ {usd(pay)})</span></label>
        <input
          id="pay"
          type="range"
          min={0}
          max={Math.ceil((monthlyInterest * 1.2) / 1000) * 1000}
          step={1000}
          value={pay}
          onChange={(e) => setPay(Number(e.target.value))}
          className="mt-2 w-full accent-[#312e81]"
        />
        <div className="mt-1 flex gap-2">
          {[0, 5000, 10000, Math.round(monthlyInterest / 1000) * 1000].map((v) => (
            <Button key={v} size="sm" tone="ghost" onClick={() => setPay(v)}>{v === 0 ? "Nothing" : cur(v)}</Button>
          ))}
        </div>
        {sc && (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl bg-emerald-50 p-4">
              <p className="text-xs text-emerald-800">You save in total</p>
              <p className="text-2xl font-bold tabular text-emerald-800">{cur(sc.savings)}</p>
              <p className="text-xs text-emerald-800">≈ {usd(sc.savings)}</p>
            </div>
            <div className="rounded-xl bg-stone-50 p-4">
              <p className="text-xs text-muted">Monthly payment after studies</p>
              <p className="text-2xl font-bold tabular">{cur(sc.scenario.monthly_payment)}</p>
              <p className="text-xs text-muted">{sc.monthly_payment_drop > 0 ? `${cur(sc.monthly_payment_drop)} less per month` : "no change"}</p>
            </div>
            <div className="rounded-xl bg-stone-50 p-4">
              <p className="text-xs text-muted">Total you'll pay</p>
              <p className="text-2xl font-bold tabular">{cur(sc.scenario.total_paid)}</p>
              <p className="text-xs text-muted">over {sc.scenario.study_months_left} study months + {loan.term_months} months</p>
            </div>
          </div>
        )}
        <div className="mt-5 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chart} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
              <CartesianGrid stroke="#eee8de" vertical={false} />
              <XAxis dataKey="month" tickFormatter={(m: string) => monthYear(m)} tick={{ fontSize: 11, fill: "#5f5b78" }} minTickGap={40} tickLine={false} axisLine={false} />
              <YAxis tickFormatter={(v: number) => (loan.currency === "INR" ? `₹${(v / 100000).toFixed(0)}L` : money(v))} tick={{ fontSize: 11, fill: "#5f5b78" }} width={56} tickLine={false} axisLine={false} />
              <Tooltip formatter={(v, n) => [cur(Number(v)), n === "baseline" ? "Pay nothing now" : "With your plan"]} labelFormatter={(m) => monthYear(String(m))} contentStyle={{ borderRadius: 12, fontSize: 12 }} />
              <Legend formatter={(v) => (v === "baseline" ? "Pay nothing now" : "With your plan")} />
              <Line type="monotone" dataKey="baseline" stroke="#a8a29e" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="scenario" stroke="#312e81" strokeWidth={2.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-muted">
          Estimates only, not financial advice. Converted at a fixed demo rate of ₹{fx}/$. Check your lender's exact terms before deciding.
        </p>
      </Card>
    </div>
  );
}
