// Typed helpers for the FastAPI backend (see backend/app/api.py).

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const TOKEN_KEY = "kharcha_token";

/** The login token from "Log in with PayPal" (none = demo student, in demo mode). */
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: the login only lasts this page */
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  const token = getToken();
  if (token) (init.headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(`${BASE}/api${path}`, init);
  if (res.status === 401) {
    setToken(null);
    window.dispatchEvent(new Event("kharcha:logged-out"));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, msg);
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(p: string) => call<T>("GET", p),
  post: <T>(p: string, b?: unknown) => call<T>("POST", p, b ?? {}),
  patch: <T>(p: string, b: unknown) => call<T>("PATCH", p, b),
  put: <T>(p: string, b: unknown) => call<T>("PUT", p, b),
  del: <T>(p: string) => call<T>("DELETE", p),
  upload: <T>(p: string, form: FormData) => call<T>("POST", p, form),
};

// ---------- types ----------

export type Mode = {
  paypal: "mock" | "sandbox";
  ai: "on" | "off";
  demo: boolean;
  demo_offset_days: number;
  fx_inr_per_usd: number;
  paypal_fee_percent: number;
  paypal_fee_fixed: number;
};

export type UserView = {
  id: number;
  name: string;
  email: string | null;
  is_demo: boolean;
  logged_in_with_paypal: boolean;
  safety_cushion: number;
  balance_checked_on: string | null;
  notify_email: boolean;
  current_money: number;
  transfer_days_from_home: number;
  loan_set_aside_monthly: number;
  paypal_connected: boolean;
  paypal_payer_email: string | null;
  paypal_connected_mock: boolean;
};

export type Autopay = {
  id: number;
  max_amount: number;
  payee_paypal_email: string;
  earliest_days_before_due: number;
  latest_days_after_due: number;
  valid_until: string;
  paused: boolean;
} | null;

export type BillStatus = "ready" | "waiting_for_money" | "short" | "late" | "paid";

export type BillView = {
  id: number;
  name: string;
  category: string;
  payee_name: string;
  payee_paypal_email: string;
  amount: number;
  currency: string;
  recurrence: "monthly" | "once";
  due_day: number | null;
  due_date: string | null;
  grace_days: number;
  late_fee: number;
  pay_mode: "remind" | "paypal";
  paypal_fee: number;
  pay_today: boolean;
  period: string | null;
  due: string | null;
  days_to_due: number | null;
  pay_on: string | null;
  status: BillStatus;
  reason: string;
  last_free_day: string | null;
  shortfall: number;
  transfer_by: string | null;
  autopay: Autopay;
  pending_payment_id: number | null;
};

export type AlertView = {
  bill_id: number;
  name: string;
  due: string;
  period: string;
  status: "short" | "late";
  shortfall: number;
  transfer_by: string | null;
  reason: string;
  knock_on: boolean;
};

export type BudgetView = {
  category: string;
  weekly_limit: number;
  spent: number;
  left: number;
  percent: number;
  status: "ok" | "close" | "over";
};

export type LoanCard = {
  id: number;
  lender: string;
  currency: string;
  principal: number;
  annual_rate: number;
  repayment_start: string;
  study_months_left: number;
  interest_accrued_so_far: number;
  monthly_payment: number;
  monthly_payment_usd: number;
};

export type GuardCheck = { rule: string; ok: boolean; detail: string };

export type ActionView = {
  id: number;
  at: string;
  on_date: string | null;
  kind: "nudge" | "proposal" | "payment" | "block" | "approval" | "income" | "chat" | "info" | "dream";
  title: string;
  message: string;
  allowed: boolean | null;
  reason: string | null;
  bill_id: number | null;
  payment_id: number | null;
  details: (Record<string, unknown> & { checks?: GuardCheck[]; written_by_ai?: boolean }) | null;
};

export type Dashboard = {
  today: string;
  mode: Mode;
  user: UserView;
  safe_to_spend: {
    per_day: number;
    horizon_days: number;
    tightest_day: string;
    money_now: number;
    income_in_horizon: number;
    bills_in_horizon: number;
    loan_set_aside_in_horizon: number;
    dreams_saved: number;
    dreams_in_horizon: number;
    dreams_per_week: number;
    cushion: number;
    shortfall: number;
    first_short_day: string | null;
    planned_daily_spend: number;
  };
  bills: BillView[];
  alerts: AlertView[];
  approvals: BillView[];
  pay_yourself: BillView[];
  setup: { money: boolean; income: boolean; bills: boolean; paypal: boolean; done: boolean };
  balance_check_due: boolean;
  budgets: BudgetView[];
  loan: LoanCard | null;
  dreams: DreamsView;
  forecast: { day: string; closing: number; income: number; bills: number }[];
  recent_activity: ActionView[];
};

export type PaymentView = {
  id: number;
  bill_id: number;
  period: string;
  amount: number;
  status: string;
  trigger: string;
  paypal_order_id: string | null;
  paypal_capture_id: string | null;
  payout_batch_id: string | null;
  payout_status: string | null;
  mock: boolean;
  failure_reason: string | null;
  paid_on: string | null;
};

export type TransactionView = {
  id: number;
  date: string;
  merchant: string;
  category: string;
  amount: number;
  source: string;
  is_need: boolean | null;
  counted_in_balance: boolean;
};

export type IncomeView = {
  id: number;
  label: string;
  amount: number;
  recurrence: "once" | "monthly" | "biweekly";
  arrives_on: string;
  last_received: string | null;
};

export type AlertsView = {
  push_public_key: string;
  push_devices: number;
  email: string | null;
  notify_email: boolean;
  email_ready: boolean;
};

export type DreamPlanStatus =
  | "reached"
  | "on_track"
  | "behind"
  | "saving"
  | "starts_later"
  | "waiting_for_bills"
  | "no_room"
  | "paused"
  | "proposed"
  | "bought";

export type DreamView = {
  id: number;
  name: string;
  emoji: string;
  target_amount: number;
  saved_amount: number;
  target_date: string | null;
  priority: number;
  status: "proposed" | "active" | "paused" | "reached" | "bought";
  left: number;
  percent: number;
  per_week: number;
  later_per_week: number | null;
  starts_on: string | null;
  needed_per_week: number | null;
  ready_on: string | null;
  plan_status: DreamPlanStatus;
  reason: string;
  bought_on: string | null;
  bought_price: number | null;
};

export type MakeRoom = {
  category: string;
  from: number;
  to: number;
  gain_per_week: number;
  room_after: number;
  dream: string;
  ready_before: string | null;
  ready_after: string | null;
  status_after: DreamPlanStatus;
};

export type DreamsView = {
  room: {
    per_week: number;
    blocked_by: string | null;
    later_per_week: number | null;
    later_from: string | null;
    tight_until: string | null;
    tight_because: string | null;
  };
  weekly_surplus: number;
  monthly_surplus: number;
  saved_total: number;
  per_week: number;
  next_save_day: string;
  dreams: DreamView[];
  bought: DreamView[];
  make_room: MakeRoom[];
};
