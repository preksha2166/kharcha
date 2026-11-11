import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api, type Dashboard, type DreamPlanStatus, type DreamView, type MakeRoom } from "../api";
import PlanTransfer from "../components/PlanTransfer";
import { Button, Card, CardTitle, Empty } from "../components/ui";
import { day, dayOrYear, money, shortDay } from "../format";
import { useApp } from "../state";

const PILL: Record<DreamPlanStatus, { label: string; cls: string }> = {
  reached: { label: "Ready!", cls: "bg-emerald-100 text-emerald-800 ring-emerald-300" },
  on_track: { label: "On track", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  saving: { label: "Saving", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  behind: { label: "Behind", cls: "bg-amber-50 text-amber-800 ring-amber-200" },
  starts_later: { label: "Starts later", cls: "bg-brand-soft text-brand ring-indigo-200" },
  waiting_for_bills: { label: "Bills first", cls: "bg-amber-50 text-amber-800 ring-amber-200" },
  no_room: { label: "No room yet", cls: "bg-stone-100 text-stone-600 ring-stone-200" },
  paused: { label: "Paused", cls: "bg-stone-100 text-stone-600 ring-stone-200" },
  proposed: { label: "Suggested", cls: "bg-brand-soft text-brand ring-indigo-200" },
  bought: { label: "Bought", cls: "bg-stone-100 text-stone-600 ring-stone-200" },
};

export function DreamPill({ status }: { status: DreamPlanStatus }) {
  const p = PILL[status] ?? PILL.no_room;
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${p.cls}`}>{p.label}</span>;
}

export function DreamBar({ dream }: { dream: DreamView }) {
  const good = ["reached", "on_track", "saving"].includes(dream.plan_status);
  const warn = ["behind", "waiting_for_bills"].includes(dream.plan_status);
  const color = good ? "bg-emerald-500" : warn ? "bg-marigold" : "bg-brand";
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-stone-100">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, Math.max(2, dream.percent))}%` }} />
    </div>
  );
}

/** One short line: when it's ready and how fast it's growing. */
export function dreamPace(d: DreamView, today: string): string {
  if (d.plan_status === "reached") return "Fully saved";
  if (d.plan_status === "paused") return "Paused";
  if (d.plan_status === "waiting_for_bills") return "Waiting for bills to be covered";
  if (!d.ready_on) return "No room yet";
  const pace =
    d.per_week > 0
      ? `${money(d.per_week)} this week`
      : d.starts_on
        ? `starts ${shortDay(d.starts_on)}`
        : "";
  return `Ready about ${dayOrYear(d.ready_on, today)}${pace ? ` · ${pace}` : ""}`;
}

const EMOJI: [RegExp, string][] = [
  [/flight|fly|ticket|home|trip|travel|visit/i, "✈️"],
  [/mac|laptop|computer|ipad|tablet/i, "💻"],
  [/phone|iphone|pixel/i, "📱"],
  [/bike|cycle/i, "🚲"],
  [/car/i, "🚗"],
  [/camera/i, "📷"],
  [/gift|present|birthday/i, "🎁"],
  [/course|class|exam|book/i, "📚"],
  [/emergency|cushion|rainy/i, "🛟"],
];

function guessEmoji(name: string): string {
  return EMOJI.find(([re]) => re.test(name))?.[1] ?? "⭐";
}

export default function Dreams() {
  const { data } = useApp();
  if (!data) return <p className="text-sm text-muted">Loading…</p>;
  const v = data.dreams;

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div className="space-y-5 lg:col-span-2">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Dreams</h1>
          <p className="text-sm text-muted">
            Bills first, dreams second, fun third. Every Monday Kharcha sets money aside from what's truly spare. Nothing moves:
            the money stays in your account, and safe-to-spend leaves it out.
          </p>
        </div>
        <RoomCard data={data} />
        {v.dreams.length === 0 ? (
          <Empty>No dreams yet. Add one here, or tell Ask Kharcha: "I want to fly home in May, about $1,200."</Empty>
        ) : (
          <ul className="space-y-4">
            {v.dreams.map((d, i) => (
              <DreamCard key={d.id} dream={d} today={data.today} first={i === 0} last={i === v.dreams.length - 1} />
            ))}
          </ul>
        )}
        {v.make_room.length > 0 && <MakeRoomCard data={data} ideas={v.make_room} />}
        {v.bought.length > 0 && (
          <Card>
            <CardTitle>Dreams come true</CardTitle>
            <ul className="divide-y divide-line">
              {v.bought.map((d) => (
                <li key={d.id} className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
                  <span className="font-medium">{d.emoji} {d.name}</span>
                  <span className="text-sm text-muted">
                    {money(d.bought_price)} · {shortDay(d.bought_on)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
      <div className="space-y-5">
        <AddDream />
        <Card className="bg-brand-soft">
          <p className="text-sm font-semibold text-brand">Just say it</p>
          <p className="mt-1 text-sm text-muted">
            In <Link to="/ask" className="font-semibold text-brand underline">Ask Kharcha</Link>, type what you're saving for, like
            "a MacBook, about $1,000". Kharcha works out the weekly amount and the ready date, and you save it with one tap.
          </p>
        </Card>
      </div>
    </div>
  );
}

function RoomCard({ data }: { data: Dashboard }) {
  const v = data.dreams;
  const r = v.room;
  if (r.blocked_by) {
    const alerts = data.alerts;
    const worst = alerts.length ? Math.max(...alerts.map((a) => a.shortfall)) : 0;
    return (
      <Card className="border-amber-300 bg-amber-50">
        <p className="text-sm font-semibold text-amber-900">On hold: bills come first</p>
        <p className="mt-1 text-sm text-amber-900">
          {capital(r.blocked_by)}. Kharcha won't set money aside for dreams until that's covered, so a dream never makes a bill late.
        </p>
        {alerts.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <PlanTransfer shortfall={worst} transferBy={alerts[0].transfer_by} />
          </div>
        )}
        <Stats v={v} today={data.today} />
      </Card>
    );
  }
  const later = r.later_per_week !== null && r.later_from && r.later_per_week !== r.per_week;
  return (
    <Card className="overflow-hidden bg-brand p-0 text-white">
      <div className="p-6">
        <p className="text-sm font-medium text-white/70">Room for dreams this week</p>
        <p className="mt-1 text-4xl font-extrabold tracking-tight tabular">
          {money(r.per_week)}
          <span className="ml-2 text-base font-semibold text-white/60">this Monday</span>
        </p>
        <p className="mt-2 max-w-xl text-sm text-white/80">
          {later
            ? `Money is tight until ${day(r.tight_until)}${r.tight_because ? ` (${r.tight_because})` : ""}. From ${day(r.later_from)} there's about ${money(r.later_per_week)} a week for dreams.`
            : "That's what's left after every bill in the next 60 days and your weekly budgets."}{" "}
          {v.monthly_surplus > 0
            ? `In a normal month you have about ${money(Math.round(v.monthly_surplus))} spare.`
            : "Right now more goes out each month than comes in, so lowering a budget is the way to make room."}
        </p>
      </div>
      <Stats v={v} today={data.today} dark />
    </Card>
  );
}

function Stats({ v, today, dark = false }: { v: Dashboard["dreams"]; today: string; dark?: boolean }) {
  const items: [string, string][] = [
    ["Saved so far", money(v.saved_total)],
    ["Setting aside this Monday", money(v.per_week)],
    ["Next set-aside", dayOrYear(v.next_save_day, today)],
  ];
  return (
    <dl className={`grid grid-cols-3 gap-px text-sm ${dark ? "bg-white/10" : "mt-4 overflow-hidden rounded-xl bg-amber-200"}`}>
      {items.map(([k, val]) => (
        <div key={k} className={dark ? "bg-brand px-6 py-3" : "bg-amber-50 px-4 py-2"}>
          <dt className={`text-xs ${dark ? "text-white/60" : "text-amber-800"}`}>{k}</dt>
          <dd className="font-semibold tabular">{val}</dd>
        </div>
      ))}
    </dl>
  );
}

function DreamCard({ dream: d, today, first, last }: { dream: DreamView; today: string; first: boolean; last: boolean }) {
  const { run } = useApp();
  const [mode, setMode] = useState<"view" | "edit" | "bought" | "remove">("view");
  const paused = d.status === "paused";

  return (
    <li>
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-marigold-soft text-2xl">{d.emoji}</span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-lg font-bold">{d.name}</p>
                <DreamPill status={d.plan_status} />
              </div>
              <p className="text-sm text-muted">
                {d.target_date ? `Goal: ${dayOrYear(d.target_date, today)}` : "No date: whenever there's room"} · Priority #{d.priority}
              </p>
            </div>
          </div>
          <p className="text-right">
            <span className="text-xl font-bold tabular">{money(d.saved_amount)}</span>
            <span className="text-sm text-muted"> of {money(d.target_amount)}</span>
          </p>
        </div>

        <div className="mt-4">
          <DreamBar dream={d} />
          <div className="mt-2 flex flex-wrap justify-between gap-2 text-sm">
            <span className="font-medium">{dreamPace(d, today)}</span>
            <span className="text-muted tabular">{Math.round(d.percent)}%</span>
          </div>
          {d.later_per_week !== null && d.later_per_week > 0 && d.later_per_week !== d.per_week && (
            <p className="text-sm text-muted">Then about {money(d.later_per_week)} a week once money is less tight.</p>
          )}
          <p className="mt-2 text-sm text-muted">{d.reason}</p>
        </div>

        {mode === "view" && (
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" tone="ghost" disabled={first} onClick={() => run(() => api.post(`/dreams/${d.id}/move`, { direction: "up" }))} aria-label="More important">
              ↑ More important
            </Button>
            <Button size="sm" tone="ghost" disabled={last} onClick={() => run(() => api.post(`/dreams/${d.id}/move`, { direction: "down" }))} aria-label="Less important">
              ↓
            </Button>
            {d.status !== "reached" && (
              <Button size="sm" tone="ghost" onClick={() => run(() => api.patch(`/dreams/${d.id}`, { paused: !paused }), paused ? "Resumed." : "Paused.")}>
                {paused ? "Resume" : "Pause"}
              </Button>
            )}
            <Button size="sm" tone="ghost" onClick={() => setMode("edit")}>Edit</Button>
            <Button size="sm" tone={d.status === "reached" ? "warm" : "ghost"} onClick={() => setMode("bought")}>I bought it</Button>
            <Button size="sm" tone="danger" onClick={() => setMode("remove")}>Remove</Button>
          </div>
        )}
        {mode === "edit" && <EditDream dream={d} onDone={() => setMode("view")} />}
        {mode === "bought" && <BoughtForm dream={d} onDone={() => setMode("view")} />}
        {mode === "remove" && (
          <Confirm onCancel={() => setMode("view")}>
            <span className="text-sm">
              Remove {d.name}?{d.saved_amount > 0 ? ` The ${money(d.saved_amount)} saved goes back to your spending money.` : ""}
            </span>
            <Button size="sm" tone="danger" onClick={() => run(() => api.del(`/dreams/${d.id}`), `Removed ${d.name}.`)}>Remove</Button>
          </Confirm>
        )}
      </Card>
    </li>
  );
}

function Confirm({ children, onCancel }: { children: ReactNode; onCancel: () => void }) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl bg-stone-50 p-3">
      {children}
      <Button size="sm" tone="ghost" onClick={onCancel}>Cancel</Button>
    </div>
  );
}

const input = "mt-1 block w-full rounded-lg border border-line px-3 py-2 text-sm text-ink outline-none focus:border-brand";

function EditDream({ dream: d, onDone }: { dream: DreamView; onDone: () => void }) {
  const { run } = useApp();
  const [cost, setCost] = useState(String(d.target_amount));
  const [date, setDate] = useState(d.target_date ?? "");
  const [saved, setSaved] = useState(String(d.saved_amount));
  return (
    <form
      className="mt-4 grid gap-3 rounded-xl bg-stone-50 p-3 sm:grid-cols-4"
      onSubmit={async (e) => {
        e.preventDefault();
        const ok = await run(
          () => api.patch(`/dreams/${d.id}`, { target_amount: Number(cost), target_date: date || null, saved_amount: Number(saved) }),
          "Saved.",
        );
        if (ok) onDone();
      }}
    >
      <label className="text-xs font-medium text-muted">
        Cost ($)
        <input className={input} value={cost} onChange={(e) => setCost(e.target.value)} inputMode="decimal" />
      </label>
      <label className="text-xs font-medium text-muted">
        By when (optional)
        <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label className="text-xs font-medium text-muted">
        Saved so far ($)
        <input className={input} value={saved} onChange={(e) => setSaved(e.target.value)} inputMode="decimal" />
      </label>
      <div className="flex items-end gap-2">
        <Button size="sm" type="submit">Save</Button>
        <Button size="sm" tone="ghost" type="button" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

function BoughtForm({ dream: d, onDone }: { dream: DreamView; onDone: () => void }) {
  const { run } = useApp();
  const [price, setPrice] = useState(String(d.target_amount));
  return (
    <Confirm onCancel={onDone}>
      <label className="text-sm">
        It cost $
        <input className="ml-1 w-24 rounded-lg border border-line px-2 py-1 text-sm tabular" value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" />
      </label>
      <Button
        size="sm"
        tone="warm"
        onClick={async () => {
          if (await run(() => api.post(`/dreams/${d.id}/bought`, { price: Number(price) }), `Dream come true: ${d.name}! 🎉`)) onDone();
        }}
      >
        Mark as bought
      </Button>
    </Confirm>
  );
}

function AddDream() {
  const { run } = useApp();
  const [name, setName] = useState("");
  const [cost, setCost] = useState("");
  const [date, setDate] = useState("");
  const [saved, setSaved] = useState("");
  const ready = name.trim() && Number(cost) > 0;

  return (
    <Card>
      <CardTitle>Add a dream</CardTitle>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!ready) return;
          const ok = await run(
            () =>
              api.post("/dreams", {
                name: name.trim(),
                target_amount: Number(cost),
                target_date: date || null,
                saved_amount: Number(saved) || 0,
                emoji: guessEmoji(name),
              }),
            `Added ${name.trim()}.`,
          );
          if (ok) {
            setName("");
            setCost("");
            setDate("");
            setSaved("");
          }
        }}
      >
        <label className="block text-xs font-medium text-muted">
          What are you saving for?
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="Flight home" maxLength={60} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs font-medium text-muted">
            Cost ($)
            <input className={input} value={cost} onChange={(e) => setCost(e.target.value)} placeholder="1200" inputMode="decimal" />
          </label>
          <label className="text-xs font-medium text-muted">
            Saved already ($)
            <input className={input} value={saved} onChange={(e) => setSaved(e.target.value)} placeholder="0" inputMode="decimal" />
          </label>
        </div>
        <label className="block text-xs font-medium text-muted">
          By when? (optional)
          <input type="date" className={input} value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <p className="text-xs text-muted">No date? Kharcha saves whenever there's room and tells you when it'll be ready.</p>
        <Button type="submit" disabled={!ready} className="w-full">
          {name.trim() ? `${guessEmoji(name)} Add dream` : "Add dream"}
        </Button>
      </form>
    </Card>
  );
}

function MakeRoomCard({ data, ideas }: { data: Dashboard; ideas: MakeRoom[] }) {
  const { run } = useApp();
  return (
    <Card className="border-emerald-200">
      <CardTitle>Make room</CardTitle>
      <p className="-mt-2 mb-3 text-sm text-muted">Lower one budget and the difference goes to your dreams, every week.</p>
      <ul className="space-y-3">
        {ideas.map((m) => (
          <li key={m.category} className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-emerald-50 p-3">
            <div className="min-w-0 text-sm">
              <p className="font-semibold">
                {m.category}: {money(m.from)} → {money(m.to)} a week
              </p>
              <p className="text-emerald-900">
                +{money(m.gain_per_week)} a week for dreams. {m.dream} ready about {dayOrYear(m.ready_after, data.today)}
                {m.ready_before ? ` instead of ${dayOrYear(m.ready_before, data.today)}` : ""}.
              </p>
            </div>
            <Button
              size="sm"
              onClick={() =>
                run(
                  () =>
                    api.put(
                      "/budgets",
                      data.budgets.map((b) => ({ category: b.category, weekly_limit: b.category === m.category ? m.to : b.weekly_limit })),
                    ),
                  `${m.category} budget is now ${money(m.to)} a week.`,
                )
              }
            >
              Do it
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function capital(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
