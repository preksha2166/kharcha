const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

export function money(n: number | null | undefined, cents = false): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (!cents && Math.abs(n - Math.round(n)) < 0.005) return usd0.format(n);
  return usd2.format(n);
}

export function inr(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return inr0.format(n);
}

export function inCurrency(n: number, currency: string): string {
  return currency === "INR" ? inr(n) : money(n);
}

function parse(iso: string): Date {
  return new Date(`${iso.slice(0, 10)}T00:00:00`);
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  return parse(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

export function shortDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  return parse(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function monthYear(iso: string): string {
  return parse(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

export function relDays(n: number | null | undefined): string {
  if (n === null || n === undefined) return "";
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n < 0 ? `${-n} days ago` : `in ${n} days`;
}

/** "Mon, Jun 21", or "Jun 21, 2027" when it isn't in the same year as `todayIso`. */
export function dayOrYear(iso: string | null | undefined, todayIso: string): string {
  if (!iso) return "—";
  if (iso.slice(0, 4) === todayIso.slice(0, 4)) return day(iso);
  return parse(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function addDays(iso: string, n: number): string {
  const d = parse(iso);
  d.setDate(d.getDate() + n);
  const pad = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
