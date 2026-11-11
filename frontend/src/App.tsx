import { useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";

import { api, setToken } from "./api";
import { Badge, Button } from "./components/ui";
import { day } from "./format";
import Activity from "./pages/Activity";
import Ask from "./pages/Ask";
import AuthReturn from "./pages/AuthReturn";
import Bills from "./pages/Bills";
import DashboardPage from "./pages/Dashboard";
import Dreams from "./pages/Dreams";
import Loan from "./pages/Loan";
import Login from "./pages/Login";
import PayPalPaid from "./pages/PayPalPaid";
import PayPalReturn from "./pages/PayPalReturn";
import Settings from "./pages/Settings";
import Spending from "./pages/Spending";
import Upload from "./pages/Upload";
import { useApp } from "./state";

const NAV = [
  { to: "/", label: "Home" },
  { to: "/bills", label: "Bills" },
  { to: "/spending", label: "Spending" },
  { to: "/dreams", label: "Dreams" },
  { to: "/loan", label: "Loan" },
  { to: "/ask", label: "Ask Kharcha" },
  { to: "/activity", label: "Activity" },
  { to: "/upload", label: "Add bill" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  const { data, error, waking, toasts, needLogin, loggedIn } = useApp();
  const location = useLocation();
  const onAuthPage = location.pathname.startsWith("/auth/");

  return (
    <div className="min-h-screen pb-28">
      <header className="sticky top-0 z-20 border-b border-line bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand text-sm font-extrabold text-marigold">K</span>
            <span className="text-lg font-extrabold tracking-tight">Kharcha</span>
          </NavLink>
          <nav className="order-3 -mx-1 flex w-full gap-1 overflow-x-auto md:order-none md:w-auto">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium ${isActive ? "bg-brand text-white" : "text-muted hover:bg-white hover:text-ink"}`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            {data && (
              <>
                <Badge tone={data.mode.paypal === "mock" ? "warn" : "ok"}>PayPal {data.mode.paypal}</Badge>
                <Badge tone={data.mode.ai === "on" ? "ok" : "warn"}>AI {data.mode.ai}</Badge>
                {loggedIn ? (
                  <Link to="/settings" className="ml-1 rounded-lg px-2 py-1 text-sm font-semibold hover:bg-white">{data.user.name}</Link>
                ) : (
                  <Link to="/login" className="ml-1 rounded-lg bg-marigold px-2.5 py-1 text-xs font-semibold text-ink hover:bg-amber-400">Log in</Link>
                )}
              </>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        {waking && !error && (
          <div role="status" className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            Waking up the server… Kharcha runs on free hosting, which sleeps when nobody is using it. This can take up to a minute.
          </div>
        )}
        {error && (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            Can't reach the backend: {error}.
            {["localhost", "127.0.0.1"].includes(window.location.hostname) ? " Is it running on port 8000?" : " Please try again in a minute."}
          </div>
        )}
        {needLogin && !onAuthPage ? (
          <Login />
        ) : (
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/bills" element={<Bills />} />
          <Route path="/spending" element={<Spending />} />
          <Route path="/dreams" element={<Dreams />} />
          <Route path="/loan" element={<Loan />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/paypal/return" element={<PayPalReturn />} />
          <Route path="/paypal/cancel" element={<PayPalReturn cancelled />} />
          <Route path="/paypal/paid" element={<PayPalPaid />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/login" element={<Login />} />
          <Route path="/auth/paypal/return" element={<AuthReturn />} />
        </Routes>
        )}
      </main>

      {data?.mode.demo && <DemoBar />}

      <div className="fixed right-4 top-16 z-40 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`rounded-xl border px-4 py-3 text-sm shadow-lg ${
              t.tone === "error" ? "border-red-200 bg-red-50 text-red-800" : t.tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-emerald-200 bg-white text-ink"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}

function DemoBar() {
  const { data, run, toast } = useApp();
  const [busy, setBusy] = useState(false);
  if (!data) return null;

  async function advance(days: number) {
    setBusy(true);
    await run(async () => {
      const res = await api.post<{ today: string; new_activity: { title: string; kind: string }[] }>("/demo/advance-days", { days });
      const important = res.new_activity.filter((a) => ["payment", "block", "approval", "income", "nudge", "dream"].includes(a.kind));
      toast(important.length ? important.map((a) => a.title).join(" · ") : `Now ${day(res.today)}. Nothing new happened.`, important.some((a) => a.kind === "block") ? "warn" : "ok");
    });
    setBusy(false);
  }

  return (
    <div className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-ink text-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-marigold">Demo clock</span>
        <span className="text-sm">
          Today is <strong>{day(data.today)}</strong>
          {data.mode.demo_offset_days > 0 && <span className="text-white/60"> (+{data.mode.demo_offset_days} days)</span>}
        </span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" tone="warm" disabled={busy} onClick={() => advance(1)}>+1 day</Button>
          <Button size="sm" tone="warm" disabled={busy} onClick={() => advance(7)}>+7 days</Button>
          <Button
            size="sm"
            tone="ghost"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await api.post("/demo/reset");
                setToken(null); // the reset removes every account, including a logged-in one
              }, "Demo reset to day 0.")
            }
          >
            Reset demo
          </Button>
        </div>
      </div>
    </div>
  );
}
