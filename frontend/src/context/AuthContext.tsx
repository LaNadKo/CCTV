import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { me, type CurrentUser } from "../lib/api";

type AuthContextValue = {
  user: CurrentUser | null;
  token: string | null;
  login: (token: string, user: CurrentUser) => void;
  logout: () => void;
  loading: boolean;
  refreshUser: () => Promise<CurrentUser | null>;
  replaceUser: (user: CurrentUser | null) => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);
const STORAGE_KEY = "cctv_token";

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(STORAGE_KEY));
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState<boolean>(!!token);

  const refreshUser = async (): Promise<CurrentUser | null> => {
    if (!token) {
      setUser(null);
      setLoading(false);
      return null;
    }

    try {
      const data = await me(token);
      setUser(data);
      return data;
    } catch (error) {
      console.error("Failed to fetch profile", error);
      setToken(null);
      setUser(null);
      localStorage.removeItem(STORAGE_KEY);
      return null;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token) {
      setLoading(false);
      setUser(null);
      return;
    }

    setLoading(true);
    void refreshUser();
  }, [token]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      loading,
      login: (t, u) => {
        localStorage.setItem(STORAGE_KEY, t);
        setToken(t);
        setUser(u);
      },
      logout: () => {
        localStorage.removeItem(STORAGE_KEY);
        setToken(null);
        setUser(null);
      },
      refreshUser,
      replaceUser: setUser,
    }),
    [user, token, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
};
