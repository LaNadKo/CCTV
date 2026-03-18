import { createContext, useContext, useEffect, useMemo, useState, useCallback } from "react";
import { listHomes, type HomeOut } from "../lib/api";
import { useAuth } from "./AuthContext";

type HomeContextValue = {
  homes: HomeOut[];
  currentHome: HomeOut | null;
  currentRole: string | null;
  setCurrentHome: (home: HomeOut | null) => void;
  refreshHomes: () => Promise<void>;
  loading: boolean;
};

const HomeContext = createContext<HomeContextValue | undefined>(undefined);

const STORAGE_KEY = "cctv_current_home";

export const HomeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { token } = useAuth();
  const [homes, setHomes] = useState<HomeOut[]>([]);
  const [currentHome, setCurrentHomeState] = useState<HomeOut | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshHomes = useCallback(async () => {
    if (!token) return;
    try {
      const data = await listHomes(token);
      setHomes(data);

      const savedId = localStorage.getItem(STORAGE_KEY);
      if (savedId) {
        const found = data.find((h) => h.home_id === Number(savedId));
        if (found) {
          setCurrentHomeState(found);
        } else {
          localStorage.removeItem(STORAGE_KEY);
          setCurrentHomeState(null);
        }
      }
    } catch (e) {
      console.error("Failed to load homes", e);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    refreshHomes();
  }, [refreshHomes]);

  const setCurrentHome = useCallback((home: HomeOut | null) => {
    setCurrentHomeState(home);
    if (home) {
      localStorage.setItem(STORAGE_KEY, String(home.home_id));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const currentRole = currentHome?.my_role ?? null;

  const value = useMemo<HomeContextValue>(
    () => ({ homes, currentHome, currentRole, setCurrentHome, refreshHomes, loading }),
    [homes, currentHome, currentRole, setCurrentHome, refreshHomes, loading],
  );

  return <HomeContext.Provider value={value}>{children}</HomeContext.Provider>;
};

export const useHome = (): HomeContextValue => {
  const ctx = useContext(HomeContext);
  if (!ctx) throw new Error("useHome must be used within HomeProvider");
  return ctx;
};
