"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setToken, ROLE_RANK, type Role, type User } from "./api";

interface AuthCtx { user: User | null; loading: boolean; login: (email: string, password: string) => Promise<void>; logout: () => void; can: (min: Role) => boolean }
const Ctx = createContext<AuthCtx>({ user: null, loading: true, login: async () => {}, logout: () => {}, can: () => false });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!getToken()) { setLoading(false); return; }
    api<User>("/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setLoading(false));
  }, []);
  const login = useCallback(async (email: string, password: string) => {
    const r = await api<{ access_token: string; user: User }>("/auth/login", { json: { email, password } });
    setToken(r.access_token);
    setUser(r.user);
  }, []);
  const logout = useCallback(() => { setToken(null); setUser(null); window.location.href = "/login"; }, []);
  const can = useCallback((min: Role) => !!user && ROLE_RANK[user.role] >= ROLE_RANK[min], [user]);
  return <Ctx.Provider value={{ user, loading, login, logout, can }}>{children}</Ctx.Provider>;
}
export const useAuth = () => useContext(Ctx);

/** Tiny data hook: load on mount / when deps change, expose reload. */
export function useApi<T>(path: string | null, params?: Record<string, unknown>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const [tick, setTick] = useState(0);
  const key = JSON.stringify(params ?? {});
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    api<T>(path, { params })
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, key, tick, ...deps]);
  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}
