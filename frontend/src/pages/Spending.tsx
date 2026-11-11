import { AllCommunityModule, ModuleRegistry, themeQuartz, type CellValueChangedEvent, type ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, type TransactionView } from "../api";
import { Bar, Button, Card, CardTitle } from "../components/ui";
import { money, shortDay } from "../format";
import { useApp } from "../state";

ModuleRegistry.registerModules([AllCommunityModule]);

const CATEGORIES = ["Groceries", "Transport", "Eating out", "Fun", "Shopping", "Health", "Bills", "Other"];

const theme = themeQuartz.withParams({
  fontFamily: "Inter, system-ui, sans-serif",
  headerBackgroundColor: "#faf7f2",
  accentColor: "#312e81",
  borderColor: "#e7e2d9",
  rowHoverColor: "#f5f3ff",
  fontSize: 13,
});

const input = "mt-1 block w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-brand";

export default function Spending() {
  const { data, toast, refresh, run } = useApp();
  const [rows, setRows] = useState<TransactionView[]>([]);

  const load = useCallback(() => api.get<TransactionView[]>("/transactions?days=60").then(setRows), []);
  useEffect(() => {
    void load();
  }, [load, data?.today]);

  const cols = useMemo<ColDef<TransactionView>[]>(
    () => [
      { field: "date", headerName: "Date", width: 110, sort: "desc", valueFormatter: (p) => shortDay(p.value) },
      { field: "merchant", headerName: "Merchant", flex: 1, minWidth: 170 },
      {
        field: "category",
        headerName: "Category",
        width: 150,
        editable: true,
        cellEditor: "agSelectCellEditor",
        cellEditorParams: { values: CATEGORIES },
      },
      {
        field: "is_need",
        headerName: "Need?",
        width: 100,
        editable: true,
        cellDataType: "boolean",
        headerTooltip: "You decide what counts as a need. Kharcha's coach uses your choices.",
      },
      {
        field: "amount",
        headerName: "Amount",
        width: 110,
        type: "rightAligned",
        valueFormatter: (p) => money(p.value, true),
        cellClass: "tabular",
      },
      { field: "source", headerName: "Source", width: 100 },
      {
        headerName: "",
        width: 90,
        sortable: false,
        cellRenderer: (p: { data?: TransactionView }) =>
          p.data && (p.data.source === "manual" || p.data.source === "csv") ? (
            <button
              className="text-xs font-semibold text-red-700 hover:underline"
              onClick={() => {
                const id = p.data!.id;
                void run(() => api.del(`/transactions/${id}`), "Deleted.").then(load);
              }}
            >
              Delete
            </button>
          ) : null,
      },
    ],
    [load, run],
  );

  const onChange = useCallback(
    async (e: CellValueChangedEvent<TransactionView>) => {
      if (!e.data) return;
      try {
        await api.patch(`/transactions/${e.data.id}`, { category: e.data.category, is_need: e.data.is_need });
        await refresh();
      } catch (err) {
        toast(err instanceof Error ? err.message : String(err), "error");
        void load();
      }
    },
    [load, refresh, toast],
  );

  const last30 = rows.filter((r) => data && new Date(r.date) >= new Date(new Date(data.today).getTime() - 29 * 864e5));
  const needs = last30.filter((r) => r.is_need === true).reduce((s, r) => s + r.amount, 0);
  const wants = last30.filter((r) => r.is_need === false).reduce((s, r) => s + r.amount, 0);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Spending</h1>
        <p className="text-sm text-muted">Click a category or the Need? box to change it. Your choices teach the coach.</p>
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        <AddSpending onAdded={load} />
        <ImportCsv onImported={load} />
      </div>
      <div className="grid gap-5 md:grid-cols-3">
        <Card className="md:col-span-2">
          <CardTitle right={<EditBudgetsButton />}>This week vs. budget</CardTitle>
          <ul className="grid gap-4 sm:grid-cols-2">
            {data?.budgets.map((b) => (
              <li key={b.category}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="font-medium">{b.category}</span>
                  <span className="tabular text-muted">{money(b.left, true)} left</span>
                </div>
                <Bar percent={b.percent} status={b.status} />
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardTitle>Last 30 days</CardTitle>
          <p className="text-sm text-muted">Needs</p>
          <p className="text-2xl font-bold tabular">{money(needs, true)}</p>
          <p className="mt-2 text-sm text-muted">Wants</p>
          <p className="text-2xl font-bold tabular text-marigold">{money(wants, true)}</p>
        </Card>
      </div>
      <Card className="p-0">
        <div style={{ height: 520 }}>
          <AgGridReact<TransactionView>
            theme={theme}
            rowData={rows}
            columnDefs={cols}
            getRowId={(p) => String(p.data.id)}
            onCellValueChanged={onChange}
            singleClickEdit
            stopEditingWhenCellsLoseFocus
            animateRows
          />
        </div>
      </Card>
    </div>
  );
}

function AddSpending({ onAdded }: { onAdded: () => void }) {
  const { data, run } = useApp();
  const [merchant, setMerchant] = useState("");
  const [amount, setAmount] = useState("");
  const [on, setOn] = useState(data?.today ?? "");
  const ok = merchant.trim() && Number(amount) > 0;
  return (
    <Card>
      <CardTitle>Add spending</CardTitle>
      <form
        className="grid grid-cols-2 gap-3 sm:grid-cols-4"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!ok) return;
          const done = await run(
            () => api.post("/transactions", { merchant: merchant.trim(), amount: Number(amount), spent_on: on || null }),
            `Added. It came out of your money, so every plan stays right.`,
          );
          if (done) {
            setMerchant("");
            setAmount("");
            onAdded();
          }
        }}
      >
        <label className="col-span-2 text-xs font-medium text-muted">
          Where
          <input className={input} value={merchant} onChange={(e) => setMerchant(e.target.value)} placeholder="Green Grocer" maxLength={120} />
        </label>
        <label className="text-xs font-medium text-muted">
          Amount ($)
          <input className={input} value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="12.50" />
        </label>
        <label className="text-xs font-medium text-muted">
          Date
          <input type="date" className={input} value={on || data?.today || ""} max={data?.today} onChange={(e) => setOn(e.target.value)} />
        </label>
        <div className="col-span-2 sm:col-span-4">
          <Button size="sm" type="submit" disabled={!ok}>Add</Button>
        </div>
      </form>
    </Card>
  );
}

function ImportCsv({ onImported }: { onImported: () => void }) {
  const { toast, refresh } = useApp();
  const [busy, setBusy] = useState(false);
  async function onFile(file: File) {
    setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.upload<{ added: number; duplicates: number; skipped_income: number; money_change: number }>("/transactions/import", fd);
      toast(
        `Imported ${r.added} purchase${r.added === 1 ? "" : "s"}` +
          (r.duplicates ? `, skipped ${r.duplicates} already here` : "") +
          (r.money_change < 0 ? `. Your money went down by ${money(-r.money_change, true)}.` : "."),
      );
      await refresh();
      onImported();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <CardTitle>Import from your bank</CardTitle>
      <p className="text-sm text-muted">
        Most banks let you download your transactions as a CSV file for free. Kharcha adds the spending, skips money coming in, and never
        imports the same purchase twice. Only spending after your last balance check lowers your money.
      </p>
      <label className="mt-3 inline-flex">
        <span className={`inline-flex cursor-pointer items-center rounded-xl border border-line bg-white px-3 py-1.5 text-xs font-semibold hover:bg-stone-50 ${busy ? "opacity-50" : ""}`}>
          {busy ? "Importing…" : "Choose a CSV file"}
        </span>
        <input type="file" accept=".csv,text/csv" className="hidden" disabled={busy} onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
      </label>
    </Card>
  );
}

function EditBudgetsButton() {
  const { data, run } = useApp();
  const [open, setOpen] = useState(false);
  const [limits, setLimits] = useState<Record<string, string>>({});
  if (!data) return null;
  if (!open) {
    return (
      <button
        className="text-sm font-semibold text-brand"
        onClick={() => {
          setLimits(Object.fromEntries(data.budgets.map((b) => [b.category, String(b.weekly_limit)])));
          setOpen(true);
        }}
      >
        Edit budgets
      </button>
    );
  }
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-ink/30 p-4" onClick={() => setOpen(false)}>
      <div className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <p className="font-semibold">Weekly budgets</p>
        <p className="text-xs text-muted">Lower budgets leave more room for bills and dreams.</p>
        <div className="mt-3 space-y-2">
          {Object.entries(limits).map(([cat, v]) => (
            <label key={cat} className="flex items-center justify-between gap-3 text-sm">
              <span>{cat}</span>
              <span className="flex items-center gap-1">
                $<input className="w-20 rounded-lg border border-line px-2 py-1 tabular" value={v} inputMode="decimal"
                        onChange={(e) => setLimits({ ...limits, [cat]: e.target.value })} />
              </span>
            </label>
          ))}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" tone="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button
            size="sm"
            onClick={async () => {
              const body = Object.entries(limits).map(([category, v]) => ({ category, weekly_limit: Math.max(0, Number(v) || 0) }));
              if (await run(() => api.put("/budgets", body), "Budgets saved.")) setOpen(false);
            }}
          >
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}
