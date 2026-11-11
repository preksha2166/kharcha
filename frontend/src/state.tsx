import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, ApiError, getToken, setToken, type Dashboard } from "./api";

type Toast = { id: number; text: string; tone: "ok" | "warn" | "error" };

type Ctx = {
  data: Dashboard | null;
  error: string | null;
  /** True while the server is slow to answer or unreachable (a free host waking up); we keep retrying. */
  waking: boolean;
  /** True when the server wants a login (demo mode is off and nobody is logged in). */
  needLogin: boolean;
  loggedIn: boolean;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  /** Run an action, show a toast, then refresh the dashboard. */
  run: (fn: () => Promise<unknown>, okText?: string) => Promise<boolean>;
  toast: (text: string, tone?: Toast["tone"]) => void;
  toasts: Toast[];
};

const AppCtx = createContext<Ctx | null>(null);

// Free hosting (Render) puts the API to sleep when nobody uses it; waking up takes up to about a minute.
// Meanwhile requests hang, fail to connect, or get a 502/503/504, so keep retrying for a while.
const SLOW_MS = 4000;
const RETRY_MS = 5000;
const MAX_RETRIES = 24; // about 2 minutes

function isWakingUp(e: unknown): boolean {
  return !(e instanceof ApiError) || [502, 503, 504].includes(e.status);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function AppProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [needLogin, setNeedLogin] = useState(false);
  const [loggedIn, setLoggedIn] = useState(() => Boolean(getToken()));

  const toast = useCallback((text: string, tone: Toast["tone"] = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5200);
  }, []);

  const refresh = useCallback(async () => {
    for (let attempt = 0; ; attempt++) {
      const slow = setTimeout(() => setWaking(true), SLOW_MS);
      try {
        setData(await api.get<Dashboard>("/dashboard"));
        setError(null);
        setWaking(false);
        setNeedLogin(false);
        setLoggedIn(Boolean(getToken()));
        return;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          setData(null);
          setNeedLogin(true);
          setLoggedIn(false);
          setError(null);
          setWaking(false);
          return;
        }
        if (isWakingUp(e) && attempt < MAX_RETRIES) {
          setWaking(true);
          await sleep(RETRY_MS);
          continue;
        }
        setWaking(false);
        setError(e instanceof Error ? e.message : String(e));
        return;
      } finally {
        clearTimeout(slow);
      }
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* already logged out */
    }
    setToken(null);
    setLoggedIn(false);
    setData(null);
    await refresh();
  }, [refresh]);

  const run = useCallback(
    async (fn: () => Promise<unknown>, okText?: string) => {
      try {
        await fn();
        if (okText) toast(okText);
        await refresh();
        return true;
      } catch (e) {
        toast(e instanceof Error ? e.message : String(e), "error");
        await refresh();
        return false;
      }
    },
    [refresh, toast],
  );

  useEffect(() => {
    void refresh();
    const onLoggedOut = () => {
      setLoggedIn(false);
      void refresh();
    };
    window.addEventListener("kharcha:logged-out", onLoggedOut);
    return () => window.removeEventListener("kharcha:logged-out", onLoggedOut);
  }, [refresh]);

  return (
    <AppCtx.Provider value={{ data, error, waking, needLogin, loggedIn, logout, refresh, run, toast, toasts }}>{children}</AppCtx.Provider>
  );
}

export function useApp(): Ctx {
  const ctx = useContext(AppCtx);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
