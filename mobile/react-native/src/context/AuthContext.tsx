import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { getToken, setToken as saveToken, clearToken, getUser, setUser as saveUser, clearUser } from "../lib/storage";
import { meApi, initApiUrl } from "../lib/api";

type User = { user_id: number; login: string; role_id: number; face_login_enabled: boolean; must_change_password: boolean };

type AuthCtx = {
  token: string | null;
  user: User | null;
  ready: boolean;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const Ctx = createContext<AuthCtx>({
  token: null,
  user: null,
  ready: false,
  login: async () => {},
  logout: async () => {},
  refreshUser: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      await initApiUrl();
      const t = await getToken();
      if (t) {
        try {
          const u = await meApi(t);
          setToken(t);
          setUser(u);
        } catch {
          await clearToken();
          await clearUser();
        }
      }
      setReady(true);
    })();
  }, []);

  const login = useCallback(async (t: string) => {
    const u = await meApi(t);
    await saveToken(t);
    await saveUser(u);
    setToken(t);
    setUser(u);
  }, []);

  const logout = useCallback(async () => {
    await clearToken();
    await clearUser();
    setToken(null);
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    if (!token) return;
    const u = await meApi(token);
    await saveUser(u);
    setUser(u);
  }, [token]);

  return <Ctx.Provider value={{ token, user, ready, login, logout, refreshUser }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  return useContext(Ctx);
}
