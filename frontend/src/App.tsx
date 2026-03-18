import { useState } from "react";
import { Navigate, Outlet, Route, Routes, useLocation, NavLink } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { usePWA } from "./hooks/usePWA";
import LoginPage from "./pages/Login";
import CamerasPage from "./pages/Cameras";
import ReviewsPage from "./pages/Reviews";
import LivePage from "./pages/Live";
import ProcessorsPage from "./pages/Processors";
import GroupsPage from "./pages/Groups";
import ApiKeysPage from "./pages/ApiKeys";
import RecordingsPage from "./pages/Recordings";
import PersonsPage from "./pages/Persons";
import ReportsPage from "./pages/Reports";
import UsersPage from "./pages/Users";
import "./app.css";

function RequireAuth() {
  const { token, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="shell">Загрузка...</div>;
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />;
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
        <button
          className="btn secondary"
          style={{ padding: "6px 10px", fontSize: 13 }}
          onClick={() => setDismissed(true)}
        >
          Позже
        </button>
      </div>
    );
  }

  if (isIOS) {
    return (
      <div className="install-banner">
        <span>
          Нажмите{" "}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ verticalAlign: "middle" }}>
            <path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8M16 6l-4-4-4 4M12 2v13" />
          </svg>{" "}
          → «На экран Домой» для установки
        </span>
        <button
          className="btn secondary"
          style={{ padding: "6px 10px", fontSize: 13 }}
          onClick={() => setDismissed(true)}
        >
          OK
        </button>
      </div>
    );
  }

  return null;
}

function Layout() {
  const { user, logout } = useAuth();
  const isAdmin = user?.role_id === 1;
  const isUser = user?.role_id === 1 || user?.role_id === 2;
  const [menuOpen, setMenuOpen] = useState(false);

  const allTabs = [
    { to: "/live", label: "Live", show: true },
    { to: "/recordings", label: "Записи", show: true },
    { to: "/reviews", label: "Ревью", show: isUser },
    { to: "/cameras", label: "Камеры", show: isAdmin },
    { to: "/groups", label: "Группы", show: true },
    { to: "/persons", label: "Персоны", show: isAdmin },
    { to: "/reports", label: "Отчёты", show: isUser },
    { to: "/processors", label: "Процессоры", show: isAdmin },
    { to: "/users", label: "Пользователи", show: isAdmin },
    { to: "/apikeys", label: "API-ключи", show: isAdmin },
  ];

  const tabs = allTabs.filter((t) => t.show);

  return (
    <div className="shell">
      <InstallBanner />
      <nav className="nav">
        <div className="brand">CCTV Console</div>

        <button className="hamburger" onClick={() => setMenuOpen(!menuOpen)} aria-label="Меню">
          <span className={menuOpen ? "ham-line open" : "ham-line"} />
          <span className={menuOpen ? "ham-line open" : "ham-line"} />
          <span className={menuOpen ? "ham-line open" : "ham-line"} />
        </button>

        <div className={`tabs ${menuOpen ? "tabs-open" : ""}`}>
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) => (isActive ? "tab active" : "tab")}
              onClick={() => setMenuOpen(false)}
            >
              {t.label}
            </NavLink>
          ))}
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
            <Route path="/reviews" element={<ReviewsPage />} />
            <Route path="/recordings" element={<RecordingsPage />} />
            <Route path="/cameras" element={<CamerasPage />} />
            <Route path="/groups" element={<GroupsPage />} />
            <Route path="/persons" element={<PersonsPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/processors" element={<ProcessorsPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/apikeys" element={<ApiKeysPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/live" replace />} />
      </Routes>
    </AuthProvider>
  );
}

export default App;
