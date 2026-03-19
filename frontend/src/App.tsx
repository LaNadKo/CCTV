import { useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { usePWA } from "./hooks/usePWA";
import ApiKeysPage from "./pages/ApiKeys";
import CamerasPage from "./pages/Cameras";
import GroupsPage from "./pages/Groups";
import LivePage from "./pages/Live";
import LoginPage from "./pages/Login";
import PersonsPage from "./pages/Persons";
import ProcessorsPage from "./pages/Processors";
import RecordingsPage from "./pages/Recordings";
import ReportsPage from "./pages/Reports";
import ReviewsPage from "./pages/Reviews";
import SettingsPage from "./pages/Settings";
import UsersPage from "./pages/Users";
import { loadUiSettings } from "./lib/uiSettings";
import "./app.css";

function RequireAuth() {
  const { token, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="shell">Загрузка...</div>;
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />;
  return <Outlet />;
}

function RequireRole({ allow }: { allow: number[] }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="shell">Загрузка...</div>;
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
        <span>Установить CCTV Console как приложение?</span>
        <button className="btn" style={{ padding: "6px 14px", fontSize: 13 }} onClick={install}>
          Установить
        </button>
        <button className="btn secondary" style={{ padding: "6px 10px", fontSize: 13 }} onClick={() => setDismissed(true)}>
          Позже
        </button>
      </div>
    );
  }

  if (isIOS) {
    return (
      <div className="install-banner">
        <span>Нажмите кнопку поделиться и выберите «На экран Домой», чтобы установить приложение.</span>
        <button className="btn secondary" style={{ padding: "6px 10px", fontSize: 13 }} onClick={() => setDismissed(true)}>
          OK
        </button>
      </div>
    );
  }

  return null;
}

function Layout() {
  const location = useLocation();
  const { user, logout } = useAuth();
  const isAdmin = user?.role_id === 1;
  const isUser = user?.role_id === 1 || user?.role_id === 2;
  const [menuOpen, setMenuOpen] = useState(false);
  const [uiSettings] = useState(() => loadUiSettings());

  const allTabs = useMemo(
    () => [
      { to: "/live", label: "Live", show: true },
      { to: "/reviews", label: "Ревью", show: isUser },
      { to: "/reports", label: "Отчёты", show: isUser },
      { to: "/persons", label: "Персоны", show: isAdmin },
      { to: "/recordings", label: "Записи", show: true },
      { to: "/groups", label: "Группы", show: true },
      { to: "/cameras", label: "Камеры", show: isAdmin },
      { to: "/processors", label: "Процессоры", show: isAdmin },
      { to: "/users", label: "Пользователи", show: isAdmin },
      { to: "/apikeys", label: "API-ключи", show: isAdmin },
      { to: "/settings", label: "Настройки", show: true },
    ],
    [isAdmin, isUser]
  );

  const primaryTabs = useMemo(
    () => allTabs.filter((tab) => tab.show && uiSettings.primaryNav.includes(tab.to)),
    [allTabs, uiSettings.primaryNav]
  );

  const secondaryTabs = useMemo(
    () => allTabs.filter((tab) => tab.show && !primaryTabs.some((primary) => primary.to === tab.to)),
    [allTabs, primaryTabs]
  );

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  const menuActive = secondaryTabs.some((tab) => location.pathname.startsWith(tab.to));

  return (
    <div className="shell">
      <InstallBanner />
      <nav className="nav">
        <div className="brand">CCTV Console</div>

        <div className="nav-center">
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
          <div className="user-chip">
            <div className="user-name">{user.login}</div>
            <span className="pill" style={{ fontSize: 11, color: isAdmin ? "#fbbf24" : "#60a5fa" }}>
              {isAdmin ? "Админ" : user.role_id === 2 ? "Пользователь" : "Наблюдатель"}
            </span>
            <button className="btn secondary" onClick={logout}>
              Выйти
            </button>
          </div>
        )}
      </nav>
      <Outlet />
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/live" replace />} />
            <Route path="/live" element={<LivePage />} />
            <Route path="/recordings" element={<RecordingsPage />} />
            <Route path="/groups" element={<GroupsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
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
        <Route path="*" element={<Navigate to="/live" replace />} />
      </Routes>
    </AuthProvider>
  );
}

export default App;
