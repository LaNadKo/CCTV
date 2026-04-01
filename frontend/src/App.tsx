import { useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { usePWA } from "./hooks/usePWA";
import ApiKeysPage from "./pages/ApiKeys";
import CamerasPage from "./pages/Cameras";
import GroupsPage from "./pages/Groups";
import HelpPage from "./pages/Help";
import LivePage from "./pages/Live";
import LoginPage from "./pages/Login";
import PersonsPage from "./pages/Persons";
import ProcessorsPage from "./pages/Processors";
import RecordingsPage from "./pages/Recordings";
import ReportsPage from "./pages/Reports";
import ReviewsPage from "./pages/Reviews";
import SettingsPage from "./pages/Settings";
import UsersPage from "./pages/Users";
import { UI_SETTINGS_EVENT, loadUiSettings, type ThemeMode, type UiSettings } from "./lib/uiSettings";
import "./app.css";

const LAST_ROUTE_KEY = "cctv_last_route";

function normalizeStoredRoute(value: string | null | undefined, fallback = "/live"): string {
  if (!value || typeof value !== "string") return fallback;
  if (!value.startsWith("/") || value === "/login") return fallback;
  return value;
}

function resolveStartRoute(uiSettings: UiSettings): string {
  if (typeof window === "undefined") {
    return uiSettings.primaryNav[0] || "/live";
  }
  return normalizeStoredRoute(localStorage.getItem(LAST_ROUTE_KEY), uiSettings.primaryNav[0] || "/live");
}

function resolveThemeMode(mode: ThemeMode): "dark" | "light" {
  if (mode === "dark" || mode === "light") {
    return mode;
  }
  if (typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: light)").matches) {
    return "light";
  }
  return "dark";
}

function applyAccentPalette(settings: UiSettings): void {
  document.documentElement.style.setProperty("--accent", settings.primaryAccent);
  document.documentElement.style.setProperty("--accent-2", settings.secondaryAccent);
}

function ThemeSync({ settings }: { settings: UiSettings }) {
  useEffect(() => {
    const applyTheme = () => {
      const resolved = resolveThemeMode(settings.themeMode);
      document.documentElement.dataset.theme = resolved;
      document.documentElement.style.colorScheme = resolved;
      applyAccentPalette(settings);
    };

    applyTheme();

    if (settings.themeMode !== "system") {
      return;
    }

    const media = window.matchMedia("(prefers-color-scheme: light)");
    const handleChange = () => applyTheme();
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, [settings.primaryAccent, settings.secondaryAccent, settings.themeMode]);

  return null;
}

function RequireAuth() {
  const { token, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div className="shell">Загрузка...</div>;
  }

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <Outlet />;
}

function RequireRole({ allow }: { allow: number[] }) {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="shell">Загрузка...</div>;
  }

  if (!user || !allow.includes(user.role_id)) {
    return <Navigate to="/live" replace />;
  }

  return <Outlet />;
}

function InstallBanner() {
  const { canInstall, isIOS, install } = usePWA();
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  if (canInstall) {
    return (
      <div className="install-banner">
        <span>Установить CCTV Console как отдельное приложение?</span>
        <button className="btn" onClick={install}>
          Установить
        </button>
        <button className="btn secondary" onClick={() => setDismissed(true)}>
          Позже
        </button>
      </div>
    );
  }

  if (isIOS) {
    return (
      <div className="install-banner">
        <span>Откройте меню «Поделиться» и выберите «На экран Домой», чтобы установить приложение.</span>
        <button className="btn secondary" onClick={() => setDismissed(true)}>
          Понятно
        </button>
      </div>
    );
  }

  return null;
}

function Layout({ uiSettings }: { uiSettings: UiSettings }) {
  const location = useLocation();
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  const isAdmin = user?.role_id === 1;
  const isUser = user?.role_id === 1 || user?.role_id === 2;

  const allTabs = useMemo(
    () => [
      { to: "/live", label: "Live", show: true },
      { to: "/recordings", label: "Записи", show: true },
      { to: "/reviews", label: "Ревью", show: isUser },
      { to: "/reports", label: "Отчёты", show: isUser },
      { to: "/persons", label: "Персоны", show: isAdmin },
      { to: "/groups", label: "Группы", show: true },
      { to: "/cameras", label: "Камеры", show: isAdmin },
      { to: "/processors", label: "Процессоры", show: isAdmin },
      { to: "/users", label: "Пользователи", show: isAdmin },
      { to: "/apikeys", label: "API-ключи", show: isAdmin },
      { to: "/settings", label: "Настройки", show: true },
      { to: "/help", label: "Справка", show: true },
    ],
    [isAdmin, isUser]
  );

  const primaryTabs = useMemo(
    () => {
      const visibleTabs = allTabs.filter((tab) => tab.show);
      return uiSettings.primaryNav
        .map((route) => visibleTabs.find((tab) => tab.to === route))
        .filter((tab): tab is (typeof visibleTabs)[number] => Boolean(tab));
    },
    [allTabs, uiSettings.primaryNav]
  );

  const secondaryTabs = useMemo(
    () => allTabs.filter((tab) => tab.show && !primaryTabs.some((primary) => primary.to === tab.to)),
    [allTabs, primaryTabs]
  );

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const route = `${location.pathname}${location.search}${location.hash}`;
    localStorage.setItem(LAST_ROUTE_KEY, route);
  }, [location.hash, location.pathname, location.search]);

  const menuActive = secondaryTabs.some((tab) => location.pathname.startsWith(tab.to));
  const roleLabel = isAdmin ? "Администратор" : user?.role_id === 2 ? "Оператор" : "Наблюдатель";
  const roleClass = isAdmin ? "role-admin" : user?.role_id === 2 ? "role-user" : "role-viewer";
  const userDisplayName = [user?.last_name, user?.first_name, user?.middle_name].filter(Boolean).join(" ") || user?.login || "";

  return (
    <div className="shell app-shell">
      <InstallBanner />

      <header className="app-header">
        <div className="app-header__brand">
          <div className="brand-mark">CCTV</div>
          <div className="stack" style={{ gap: 2 }}>
            <div className="brand-title">Console</div>
            <div className="brand-subtitle">Единый клиент для backend и Processor</div>
          </div>
        </div>

        <div className="app-header__nav">
          <div className="tabs primary-tabs">
            {primaryTabs.map((tab) => (
              <NavLink key={tab.to} to={tab.to} className={({ isActive }) => (isActive ? "tab active" : "tab")}>
                {tab.label}
              </NavLink>
            ))}
          </div>

          <div className="menu-wrap">
            <button
              className={menuActive || menuOpen ? "tab menu-trigger active" : "tab menu-trigger"}
              onClick={() => setMenuOpen((prev) => !prev)}
              type="button"
            >
              Меню
            </button>
            {menuOpen && (
              <div className="menu-dropdown">
                {secondaryTabs.map((tab) => (
                  <NavLink key={tab.to} to={tab.to} className={({ isActive }) => (isActive ? "menu-link active" : "menu-link")}>
                    {tab.label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
        </div>

        {user && (
          <div className="user-panel">
            <div className="user-panel__meta">
              <div className="user-panel__name">{userDisplayName}</div>
              <span className={`role-badge ${roleClass}`}>{roleLabel}</span>
            </div>
            <button className="btn secondary" onClick={logout}>
              Выйти
            </button>
          </div>
        )}
      </header>

      <main className="page-slot">
        <Outlet />
      </main>
    </div>
  );
}

function AppRoutes({ uiSettings }: { uiSettings: UiSettings }) {
  const startRoute = resolveStartRoute(uiSettings);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout uiSettings={uiSettings} />}>
          <Route index element={<Navigate to={startRoute} replace />} />
          <Route path="/live" element={<LivePage />} />
          <Route path="/recordings" element={<RecordingsPage />} />
          <Route path="/groups" element={<GroupsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route element={<RequireRole allow={[1, 2]} />}>
            <Route path="/reviews" element={<ReviewsPage />} />
            <Route path="/reports" element={<ReportsPage />} />
          </Route>
          <Route element={<RequireRole allow={[1]} />}>
            <Route path="/persons" element={<PersonsPage />} />
            <Route path="/cameras" element={<CamerasPage />} />
            <Route path="/processors" element={<ProcessorsPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/apikeys" element={<ApiKeysPage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to={startRoute} replace />} />
    </Routes>
  );
}

function App() {
  const [uiSettings, setUiSettings] = useState<UiSettings>(() => loadUiSettings());

  useEffect(() => {
    const refreshSettings = () => setUiSettings(loadUiSettings());
    window.addEventListener(UI_SETTINGS_EVENT, refreshSettings as EventListener);
    window.addEventListener("storage", refreshSettings);
    return () => {
      window.removeEventListener(UI_SETTINGS_EVENT, refreshSettings as EventListener);
      window.removeEventListener("storage", refreshSettings);
    };
  }, []);

  return (
    <AuthProvider>
      <ThemeSync settings={uiSettings} />
      <AppRoutes uiSettings={uiSettings} />
    </AuthProvider>
  );
}

export default App;
