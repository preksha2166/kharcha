import type { ButtonHTMLAttributes, ReactNode } from "react";

import type { BillStatus } from "../api";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  // Only add the default background / padding when the caller didn't pass its own,
  // because two classes for the same CSS property don't reliably override each other.
  const bg = /(^|\s)bg-/.test(className) ? "" : "bg-white";
  const pad = /(^|\s)p-\d/.test(className) ? "" : "p-5";
  return <section className={`rounded-2xl border border-line shadow-[0_1px_0_rgba(19,18,43,0.04)] ${bg} ${pad} ${className}`}>{children}</section>;
}

export function CardTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">{children}</h2>
      {right}
    </div>
  );
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "primary" | "ghost" | "danger" | "warm"; size?: "sm" | "md" };

export function Button({ tone = "primary", size = "md", className = "", ...rest }: BtnProps) {
  const tones = {
    primary: "bg-brand text-white hover:bg-indigo-900",
    warm: "bg-marigold text-ink hover:bg-amber-400",
    ghost: "border border-line bg-white text-ink hover:bg-stone-50",
    danger: "border border-red-200 bg-white text-red-700 hover:bg-red-50",
  };
  const sizes = { sm: "px-3 py-1.5 text-xs", md: "px-4 py-2 text-sm" };
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-1.5 rounded-xl font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${tones[tone]} ${sizes[size]} ${className}`}
    />
  );
}

const STATUS: Record<BillStatus, { label: string; cls: string }> = {
  ready: { label: "On track", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  waiting_for_money: { label: "Smart wait", cls: "bg-brand-soft text-brand ring-indigo-200" },
  short: { label: "Short", cls: "bg-amber-50 text-amber-800 ring-amber-200" },
  late: { label: "Late", cls: "bg-red-50 text-red-700 ring-red-200" },
  paid: { label: "Paid", cls: "bg-stone-100 text-stone-600 ring-stone-200" },
};

export function StatusPill({ status }: { status: BillStatus }) {
  const s = STATUS[status];
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${s.cls}`}>{s.label}</span>;
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warn" | "ok" | "brand" }) {
  const tones = {
    neutral: "bg-stone-100 text-stone-700",
    warn: "bg-amber-100 text-amber-900",
    ok: "bg-emerald-100 text-emerald-800",
    brand: "bg-brand-soft text-brand",
  };
  return <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${tones[tone]}`}>{children}</span>;
}

export function Bar({ percent, status }: { percent: number; status: "ok" | "close" | "over" }) {
  const color = status === "over" ? "bg-red-500" : status === "close" ? "bg-marigold" : "bg-emerald-500";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-stone-100">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, Math.max(2, percent))}%` }} />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-muted">{children}</p>;
}
