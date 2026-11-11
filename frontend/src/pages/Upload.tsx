import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { Badge, Button, Card, CardTitle } from "../components/ui";
import { useApp } from "../state";

type BillFacts = {
  payee_name: string | null;
  payee_email: string | null;
  amount: number | null;
  currency: string | null;
  recurrence: "monthly" | "once" | "unknown";
  due_day_of_month: number | null;
  due_date: string | null;
  grace_days: number | null;
  late_fee: number | null;
  late_fee_rule: string | null;
};

type LoanFacts = {
  lender: string | null;
  principal: number | null;
  currency: string | null;
  annual_interest_rate_percent: number | null;
  interest_type: "simple" | "compound" | "unknown";
  disbursed_on: string | null;
  repayment_starts_on: string | null;
  term_months: number | null;
};

type Extraction = {
  document_type: "lease" | "fee_notice" | "loan_letter" | "other";
  summary: string;
  bill: BillFacts | null;
  loan: LoanFacts | null;
  evidence: { field: string; page: number | null; quote: string }[];
  warnings: string[];
  confidence: "high" | "medium" | "low";
};

type UploadResp = { id: number; filename: string; mock: boolean; extraction: Extraction };

const v = (x: unknown) => (x === null || x === undefined ? "" : String(x));

export default function Upload() {
  const { run, data } = useApp();
  const [tab, setTab] = useState<"upload" | "manual">("upload");
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<UploadResp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});

  async function onFile(file: File) {
    setBusy(true);
    setErr(null);
    setRes(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.upload<UploadResp>("/documents", fd);
      setRes(r);
      const b = r.extraction.bill;
      const l = r.extraction.loan;
      setForm({
        name: r.extraction.document_type === "fee_notice" ? "College fee" : "Rent",
        payee_name: v(b?.payee_name),
        payee_paypal_email: v(b?.payee_email),
        amount: v(b?.amount),
        recurrence: b?.recurrence === "once" ? "once" : "monthly",
        due_day: v(b?.due_day_of_month),
        due_date: v(b?.due_date),
        grace_days: v(b?.grace_days ?? 0),
        late_fee: v(b?.late_fee ?? 0),
        autopay: b?.amount ? String(Math.ceil(b.amount * 1.05)) : "",
        pay_mode: "remind",
        lender: v(l?.lender),
        principal: v(l?.principal),
        currency: v(l?.currency ?? "INR"),
        annual_rate: v(l?.annual_interest_rate_percent),
        interest_type: l?.interest_type === "compound" ? "compound" : "simple",
        disbursed_date: v(l?.disbursed_on),
        repayment_start: v(l?.repayment_starts_on),
        term_months: v(l?.term_months),
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  async function confirm() {
    if (!res) return;
    const isLoan = res.extraction.document_type === "loan_letter";
    const body = isLoan
      ? {
          loan: {
            lender: form.lender, principal: Number(form.principal), currency: form.currency || "INR",
            annual_rate: Number(form.annual_rate), interest_type: form.interest_type,
            disbursed_date: form.disbursed_date, repayment_start: form.repayment_start, term_months: Number(form.term_months),
          },
        }
      : {
          bill: {
            bill: {
              name: form.name, category: res.extraction.document_type === "fee_notice" ? "tuition" : "rent",
              payee_name: form.payee_name, payee_paypal_email: form.payee_paypal_email, amount: Number(form.amount),
              recurrence: form.recurrence, due_day: form.recurrence === "monthly" ? Number(form.due_day) : null,
              due_date: form.recurrence === "once" ? form.due_date : null,
              grace_days: Number(form.grace_days || 0), late_fee: Number(form.late_fee || 0),
              pay_mode: form.pay_mode || "remind",
            },
            autopay_max_amount: form.pay_mode === "paypal" && form.autopay ? Number(form.autopay) : null,
          },
        };
    const ok = await run(() => api.post(`/documents/${res.id}/confirm`, body), isLoan ? "Loan saved." : "Bill saved.");
    if (ok) navigate(isLoan ? "/loan" : "/bills");
  }

  const x = res?.extraction;
  const quote = (field: string) => x?.evidence.find((e) => e.field.toLowerCase().includes(field));

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Add a bill</h1>
        <p className="text-sm text-muted">Upload a lease, a college fee notice or a loan letter and the AI reads it, or type the bill in yourself. You check every field before anything is saved.</p>
      </div>

      <div className="flex gap-1 rounded-xl bg-stone-100 p-1 text-sm">
        {([["upload", "Upload a document"], ["manual", "Type it yourself"]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
                  className={`flex-1 rounded-lg px-3 py-1.5 font-semibold ${tab === k ? "bg-white text-ink shadow-sm" : "text-muted hover:text-ink"}`}>
            {label}
          </button>
        ))}
      </div>

      {tab === "manual" ? <ManualBill /> : (
      <>
      {data?.mode.ai === "on" && (
        <Card className="border-amber-200 bg-amber-50 text-sm text-amber-900">
          <strong>Privacy:</strong> this demo reads documents with Gemini's free tier, where Google may use what you upload to improve
          its products. Use sample documents, not your real lease, or type the bill in yourself. Kharcha never stores the file itself,
          only the numbers you confirm.
        </Card>
      )}

      <Card>
        <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-line p-10 text-center hover:border-brand">
          <span className="text-sm font-semibold">{busy ? "Reading your document…" : "Choose a file"}</span>
          <span className="text-xs text-muted">PDF, PNG, JPG or TXT, up to 20 MB</span>
          <input type="file" className="hidden" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt" disabled={busy}
                 onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
        </label>
        {err && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{err}</p>}
      </Card>

      {res && x && (
        <Card>
          <CardTitle right={<div className="flex gap-1">{res.mock && <Badge tone="warn">Mock</Badge>}<Badge tone={x.confidence === "high" ? "ok" : "warn"}>{x.confidence} confidence</Badge></div>}>
            What the AI found in {res.filename}
          </CardTitle>
          <p className="text-sm">{x.summary}</p>
          {x.warnings.length > 0 && (
            <ul className="mt-3 space-y-1 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
              {x.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
            </ul>
          )}

          {x.document_type === "loan_letter" ? (
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <Field label="Lender" ev={quote("lender")}><input className={inp} value={form.lender} onChange={set("lender")} /></Field>
              <Field label="Amount borrowed" ev={quote("principal")}><input className={inp} value={form.principal} onChange={set("principal")} inputMode="decimal" /></Field>
              <Field label="Currency"><input className={inp} value={form.currency} onChange={set("currency")} /></Field>
              <Field label="Interest rate (%)" ev={quote("rate")}><input className={inp} value={form.annual_rate} onChange={set("annual_rate")} inputMode="decimal" /></Field>
              <Field label="Interest during studies">
                <select className={inp} value={form.interest_type} onChange={set("interest_type")}><option value="simple">Simple</option><option value="compound">Compound</option></select>
              </Field>
              <Field label="Loan paid out on" ev={quote("disburs")}><input type="date" className={inp} value={form.disbursed_date} onChange={set("disbursed_date")} /></Field>
              <Field label="Repayment starts" ev={quote("repayment")}><input type="date" className={inp} value={form.repayment_start} onChange={set("repayment_start")} /></Field>
              <Field label="Repayment months" ev={quote("term")}><input className={inp} value={form.term_months} onChange={set("term_months")} inputMode="numeric" /></Field>
            </div>
          ) : (
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <Field label="Name in Kharcha"><input className={inp} value={form.name} onChange={set("name")} /></Field>
              <Field label="Pay to" ev={quote("payee")}><input className={inp} value={form.payee_name} onChange={set("payee_name")} /></Field>
              <Field label="Payee's PayPal email (you must check this)" ev={quote("email")}>
                <input className={inp} value={form.payee_paypal_email} onChange={set("payee_paypal_email")} placeholder="landlord@example.com" />
              </Field>
              <Field label="Amount ($)" ev={quote("amount")}><input className={inp} value={form.amount} onChange={set("amount")} inputMode="decimal" /></Field>
              <Field label="Repeats">
                <select className={inp} value={form.recurrence} onChange={set("recurrence")}><option value="monthly">Every month</option><option value="once">One time</option></select>
              </Field>
              {form.recurrence === "monthly" ? (
                <Field label="Due day of month" ev={quote("due")}><input className={inp} value={form.due_day} onChange={set("due_day")} inputMode="numeric" /></Field>
              ) : (
                <Field label="Due date" ev={quote("due")}><input type="date" className={inp} value={form.due_date} onChange={set("due_date")} /></Field>
              )}
              <Field label="Grace days (no late fee)" ev={quote("grace")}><input className={inp} value={form.grace_days} onChange={set("grace_days")} inputMode="numeric" /></Field>
              <Field label="Late fee ($)" ev={quote("late")}><input className={inp} value={form.late_fee} onChange={set("late_fee")} inputMode="decimal" /></Field>
              <Field label="How to pay it">
                <select className={inp} value={form.pay_mode} onChange={set("pay_mode")}>
                  <option value="remind">Remind me on the best day (free)</option>
                  <option value="paypal">Full autopay with my saved PayPal</option>
                </select>
              </Field>
              {form.pay_mode === "paypal" && (
                <Field label="Autopay limit ($), leave empty to always ask">
                  <input className={inp} value={form.autopay} onChange={set("autopay")} inputMode="decimal" />
                </Field>
              )}
            </div>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <Button tone="ghost" onClick={() => setRes(null)}>Discard</Button>
            <Button onClick={confirm}>Looks right, save it</Button>
          </div>
        </Card>
      )}
      </>
      )}
    </div>
  );
}

function ManualBill() {
  const { run } = useApp();
  const navigate = useNavigate();
  const [f, setF] = useState<Record<string, string>>({
    name: "", payee_name: "", payee_paypal_email: "", amount: "", recurrence: "monthly", due_day: "1", due_date: "",
    grace_days: "0", late_fee: "0", pay_mode: "remind", autopay: "",
  });
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const ready = f.name.trim() && f.payee_name.trim() && Number(f.amount) > 0 && (f.recurrence === "monthly" ? Number(f.due_day) > 0 : f.due_date);

  async function save() {
    const ok = await run(async () => {
      const bill = await api.post<{ id: number }>("/bills", {
        name: f.name.trim(), category: "other", payee_name: f.payee_name.trim(), payee_paypal_email: f.payee_paypal_email.trim(),
        amount: Number(f.amount), recurrence: f.recurrence, due_day: f.recurrence === "monthly" ? Number(f.due_day) : null,
        due_date: f.recurrence === "once" ? f.due_date : null, grace_days: Number(f.grace_days || 0), late_fee: Number(f.late_fee || 0),
        pay_mode: f.pay_mode,
      });
      if (f.pay_mode === "paypal" && Number(f.autopay) > 0) {
        await api.post(`/bills/${bill.id}/mandate`, { max_amount: Number(f.autopay) });
      }
    }, `${f.name.trim()} saved.`);
    if (ok) navigate("/bills");
  }

  return (
    <Card>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name in Kharcha"><input className={inp} value={f.name} onChange={set("name")} placeholder="Rent" /></Field>
        <Field label="Pay to"><input className={inp} value={f.payee_name} onChange={set("payee_name")} placeholder="Maple Apartments" /></Field>
        <Field label="Their PayPal email (optional, for 'Pay with PayPal')">
          <input className={inp} value={f.payee_paypal_email} onChange={set("payee_paypal_email")} placeholder="landlord@example.com" />
        </Field>
        <Field label="Amount ($)"><input className={inp} value={f.amount} onChange={set("amount")} inputMode="decimal" placeholder="1200" /></Field>
        <Field label="Repeats">
          <select className={inp} value={f.recurrence} onChange={set("recurrence")}><option value="monthly">Every month</option><option value="once">One time</option></select>
        </Field>
        {f.recurrence === "monthly" ? (
          <Field label="Due day of month"><input className={inp} value={f.due_day} onChange={set("due_day")} inputMode="numeric" /></Field>
        ) : (
          <Field label="Due date"><input type="date" className={inp} value={f.due_date} onChange={set("due_date")} /></Field>
        )}
        <Field label="Grace days (no late fee)"><input className={inp} value={f.grace_days} onChange={set("grace_days")} inputMode="numeric" /></Field>
        <Field label="Late fee ($)"><input className={inp} value={f.late_fee} onChange={set("late_fee")} inputMode="decimal" /></Field>
        <Field label="How to pay it">
          <select className={inp} value={f.pay_mode} onChange={set("pay_mode")}>
            <option value="remind">Remind me on the best day (free)</option>
            <option value="paypal">Full autopay with my saved PayPal</option>
          </select>
        </Field>
        {f.pay_mode === "paypal" && (
          <Field label="Autopay limit ($), leave empty to always ask">
            <input className={inp} value={f.autopay} onChange={set("autopay")} inputMode="decimal" />
          </Field>
        )}
      </div>
      <div className="mt-5 flex justify-end">
        <Button onClick={save} disabled={!ready}>Save bill</Button>
      </div>
    </Card>
  );
}

const inp = "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none focus:border-brand";

function Field({ label, ev, children }: { label: string; ev?: { page: number | null; quote: string }; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-muted">{label}</span>
      {children}
      {ev && <span className="mt-1 block text-xs italic text-muted">"{ev.quote}"{ev.page ? `, page ${ev.page}` : ""}</span>}
    </label>
  );
}
