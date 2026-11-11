import { useEffect, useState } from "react";

import { api, type ActionView } from "../api";
import { Badge, Card, CardTitle, Empty } from "../components/ui";
import { shortDay } from "../format";
import { useApp } from "../state";

const ICON: Record<ActionView["kind"], { icon: string; cls: string }> = {
  payment: { icon: "✓", cls: "bg-emerald-100 text-emerald-700" },
  block: { icon: "⛔", cls: "bg-red-100 text-red-700" },
  approval: { icon: "?", cls: "bg-amber-100 text-amber-800" },
  nudge: { icon: "💬", cls: "bg-brand-soft text-brand" },
  income: { icon: "+", cls: "bg-emerald-100 text-emerald-700" },
  chat: { icon: "✦", cls: "bg-brand-soft text-brand" },
  proposal: { icon: "→", cls: "bg-brand-soft text-brand" },
  info: { icon: "i", cls: "bg-stone-100 text-stone-600" },
  dream: { icon: "★", cls: "bg-marigold-soft text-amber-700" },
};

export function ActionRow({ action, compact = false }: { action: ActionView; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const i = ICON[action.kind] ?? ICON.info;
  const checks = action.details?.checks ?? [];
  return (
    <li className="flex gap-3">
      <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold ${i.cls}`}>{i.icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2">
          <p className="text-sm font-semibold">{action.title}</p>
          {action.details?.written_by_ai === true && <Badge tone="brand">AI</Badge>}
          {action.on_date && <span className="text-xs text-muted">{shortDay(action.on_date)}</span>}
        </div>
        {action.message && <p className={`text-sm text-muted ${compact ? "line-clamp-2" : ""}`}>{action.message}</p>}
        {!compact && checks.length > 0 && (
          <div className="mt-1">
            <button className="text-xs font-semibold text-brand" onClick={() => setOpen(!open)}>
              {open ? "Hide" : "Show"} guard checks
            </button>
            {open && (
              <ul className="mt-2 space-y-1 rounded-lg bg-stone-50 p-3 text-xs">
                {checks.map((c) => (
                  <li key={c.rule} className={c.ok ? "text-emerald-700" : "font-semibold text-red-700"}>
                    {c.ok ? "✓" : "✗"} {c.detail}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

export default function Activity() {
  const { data } = useApp();
  const [rows, setRows] = useState<ActionView[] | null>(null);

  useEffect(() => {
    api.get<ActionView[]>("/activity").then(setRows).catch(() => setRows([]));
  }, [data?.today, data?.recent_activity[0]?.id]);

  return (
    <Card>
      <CardTitle>Activity log</CardTitle>
      <p className="-mt-2 mb-4 text-sm text-muted">
        Every warning, payment and block, with the reason. The AI writes the words; plain code makes every money decision.
      </p>
      {!rows ? <p className="text-sm text-muted">Loading…</p> : rows.length === 0 ? <Empty>Nothing yet.</Empty> : (
        <ul className="space-y-4">{rows.map((a) => <ActionRow key={a.id} action={a} />)}</ul>
      )}
    </Card>
  );
}
