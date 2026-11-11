import { useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError, type DreamView } from "../api";
import { Badge, Button, Card } from "../components/ui";
import { dayOrYear, money } from "../format";
import { useApp } from "../state";
import { DreamPill } from "./Dreams";

type Msg = { role: "user" | "assistant"; content: string; tools?: string[]; approvals?: number[]; dreams?: DreamView[] };

const SUGGESTIONS = [
  "I want to fly home in May. A round trip is about $1,200.",
  "Can I afford a $60 concert ticket this week?",
  "Why aren't you paying my rent on the due date?",
  "How much do I save if I pay ₹10,000 a month on my loan now?",
  "Please pay my phone bill early.",
];

export default function Ask() {
  const { data, refresh } = useApp();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function send(q: string) {
    if (!q.trim() || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: q.trim() }];
    setMsgs(next);
    setText("");
    setBusy(true);
    setErr(null);
    try {
      const res = await api.post<{
        reply: string;
        tools_used: string[];
        approval_payment_ids: number[];
        dream_proposals: DreamView[];
      }>("/chat", {
        messages: next.map(({ role, content }) => ({ role, content })),
      });
      setMsgs([
        ...next,
        { role: "assistant", content: res.reply, tools: res.tools_used, approvals: res.approval_payment_ids, dreams: res.dream_proposals },
      ]);
      if (res.approval_payment_ids.length) await refresh();
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 503 ? "AI is off. Add GEMINI_API_KEY to backend/.env and restart the backend." : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Ask Kharcha</h1>
        <p className="text-sm text-muted">It reads your real numbers with tools. It can suggest a dream or ask you to approve a payment, but it can never move money on its own.</p>
      </div>
      {data?.mode.ai === "off" && (
        <Card className="border-amber-200 bg-amber-50 text-sm">AI is off in this environment. Add an API key to turn on the assistant.</Card>
      )}
      <Card className="min-h-[320px]">
        {msgs.length === 0 ? (
          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)} className="rounded-full border border-line bg-paper px-3 py-1.5 text-sm hover:border-brand hover:text-brand">
                {s}
              </button>
            ))}
          </div>
        ) : (
          <ul className="space-y-4">
            {msgs.map((m, i) => (
              <li key={i} className={m.role === "user" ? "flex justify-end" : ""}>
                <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${m.role === "user" ? "bg-brand text-white" : "bg-stone-50"}`}>
                  <p className="whitespace-pre-wrap">{m.content}</p>
                  {m.tools && m.tools.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {[...new Set(m.tools)].map((t) => <Badge key={t}>checked {t.replace(/_/g, " ")}</Badge>)}
                    </div>
                  )}
                  {m.dreams && m.dreams.length > 0 && (
                    <div className="mt-3 space-y-2">
                      {m.dreams.map((d) => <DreamProposal key={d.id} dream={d} today={data?.today ?? ""} />)}
                    </div>
                  )}
                  {m.approvals && m.approvals.length > 0 && (
                    <p className="mt-2 text-xs font-semibold text-amber-800">
                      Approval request created. <Link to="/" className="underline">Review it on Home</Link>.
                    </p>
                  )}
                </div>
              </li>
            ))}
            {busy && <li className="text-sm text-muted">Kharcha is checking your numbers…</li>}
          </ul>
        )}
        {err && <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{err}</p>}
      </Card>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send(text);
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask about your bills, budget, loan or dreams…"
          className="flex-1 rounded-xl border border-line bg-white px-4 py-2.5 text-sm outline-none focus:border-brand"
          maxLength={1000}
        />
        <Button type="submit" disabled={busy || !text.trim()}>Send</Button>
      </form>
    </div>
  );
}

/** A dream Kharcha suggested. It's only a suggestion until the student taps Save. */
function DreamProposal({ dream: d, today }: { dream: DreamView; today: string }) {
  const { run } = useApp();
  const [state, setState] = useState<"open" | "saved" | "dismissed">("open");
  return (
    <div className="rounded-xl border border-line bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">
          {d.emoji} {d.name} · {money(d.target_amount)}
          {d.target_date ? ` by ${dayOrYear(d.target_date, today)}` : ""}
        </p>
        <DreamPill status={d.plan_status} />
      </div>
      <p className="mt-1 text-xs text-muted">{d.reason}</p>
      {state === "open" ? (
        <div className="mt-2 flex gap-2">
          <Button
            size="sm"
            onClick={async () => {
              if (await run(() => api.post(`/dreams/${d.id}/confirm`), `Saved your dream: ${d.name}.`)) setState("saved");
            }}
          >
            Save dream
          </Button>
          <Button
            size="sm"
            tone="ghost"
            onClick={async () => {
              if (await run(() => api.del(`/dreams/${d.id}`))) setState("dismissed");
            }}
          >
            No thanks
          </Button>
        </div>
      ) : (
        <p className="mt-2 text-xs font-semibold text-brand">
          {state === "saved" ? (
            <>
              Saved. <Link to="/dreams" className="underline">See it on Dreams</Link>.
            </>
          ) : (
            "Not saved."
          )}
        </p>
      )}
    </div>
  );
}
