import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { createMediaToken, me, type CurrentUser } from "../lib/api";

type AuthContextValue = {
  user: CurrentUser | null;
  token: string | null;
  mediaToken: string | null;
  login: (token: string, user: CurrentUser, mediaToken?: string | null) => void;
  logout: () => void;
  loading: boolean;
  refreshUser: () => Promise<CurrentUser | null>;
  refreshMediaToken: () => Promise<string | null>;
  replaceUser: (user: CurrentUser | null) => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);
const STORAGE_KEY = "cctv_token";
const MEDIA_STORAGE_KEY = "cctv_media_token";

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(STORAGE_KEY));
  const [mediaToken, setMediaToken] = useState<string | null>(() => localStorage.getItem(MEDIA_STORAGE_KEY));
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState<boolean>(!!token);

  const refreshMediaToken = async (): Promise<string | null> => {
    if (!token) {
      setMediaToken(null);
      localStorage.removeItem(MEDIA_STORAGE_KEY);
      return null;
    }
    const data = await createMediaToken(token);
    localStorage.setItem(MEDIA_STORAGE_KEY, data.media_access_token);
    setMediaToken(data.media_access_token);
    return data.media_access_token;
  };

  const refreshUser = async (): Promise<CurrentUser | null> => {
    if (!token) {
      setUser(null);
      setLoading(false);
      return null;
    }

    try {
      const data = await me(token);
      setUser(data);
      await refreshMediaToken();
      return data;
    } catch (error) {
      console.error("Failed to fetch profile", error);
      setToken(null);
      setMediaToken(null);
      setUser(null);
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(MEDIA_STORAGE_KEY);
      return null;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token) {
      setLoading(false);
      setUser(null);
      setMediaToken(null);
      localStorage.removeItem(MEDIA_STORAGE_KEY);
      return;
    }

    setLoading(true);
    void refreshUser();
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const id = window.setInterval(() => {
      void refreshMediaToken().catch((error) => console.error("Failed to refresh media token", error));
    }, 10 * 60 * 1000);
    return () => window.clearInterval(id);
  }, [token]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      mediaToken,
      loading,
      login: (t, u, mt) => {
        localStorage.setItem(STORAGE_KEY, t);
        setToken(t);
        if (mt) {
          localStorage.setItem(MEDIA_STORAGE_KEY, mt);
          setMediaToken(mt);
        } else {
          localStorage.removeItem(MEDIA_STORAGE_KEY);
          setMediaToken(null);
        }
        setUser(u);
      },
      logout: () => {
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(MEDIA_STORAGE_KEY);
        setToken(null);
        setMediaToken(null);
        setUser(null);
      },
      refreshUser,
      refreshMediaToken,
      replaceUser: setUser,
    }),
    [user, token, mediaToken, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
};
