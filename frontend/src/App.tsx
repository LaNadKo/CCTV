import { useState } from "react";
import { Navigate, Outlet, Route, Routes, useLocation, NavLink } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { HomeProvider, useHome } from "./context/HomeContext";
import { usePWA } from "./hooks/usePWA";
import LoginPage from "./pages/Login";
import RegisterPage from "./pages/Register";
import CamerasPage from "./pages/Cameras";
import ReviewsPage from "./pages/Reviews";
import LivePage from "./pages/Live";
import ProcessorsPage from "./pages/Processors";
import HomesPage from "./pages/Homes";
import HomeDetailPage from "./pages/HomeDetail";
import ApiKeysPage from "./pages/ApiKeys";
import RecordingsPage from "./pages/Recordings";
import PersonsPage from "./pages/Persons";
import "./app.css";

function RequireAuth() {
  const { token, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="shell">Загрузка...</div>;
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />;
  return <Outlet />;
}

const ROLE_LEVEL: Record<string, number> = { guest: 0, member: 1, admin: 2, owner: 3 };

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
  const { homes, currentHome, currentRole, setCurrentHome } = useHome();
  const isSystemAdmin = user?.role_id === 1;
  const level = currentRole ? (ROLE_LEVEL[currentRole] ?? 0) : isSystemAdmin ? 3 : 0;
  const [menuOpen, setMenuOpen] = useState(false);

  const allTabs = [
    { to: "/live", label: "Live", minLevel: 0 },
    { to: "/recordings", label: "Записи", minLevel: 0 },
    { to: "/reviews", label: "Ревью", minLevel: 1 },
    { to: "/cameras", label: "Камеры", minLevel: 2 },
    { to: "/homes", label: "Дома", minLevel: 0 },
    { to: "/persons", label: "Персоны", minLevel: 2 },
    { to: "/processors", label: "Процессоры", minLevel: 2 },
    { to: "/apikeys", label: "API-ключи", minLevel: 2 },
  ];

  const tabs = allTabs.filter((t) => isSystemAdmin || level >= t.minLevel);

  return (
    <div className="shell">
      <InstallBanner />
      <nav className="nav">
        <div className="brand">CCTV Console</div>

        {/* Hamburger for mobile */}
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
            <select
              className="home-select"
              value={currentHome?.home_id ?? ""}
              onChange={(e) => {
                const id = e.target.value;
                if (!id) {
                  setCurrentHome(null);
                } else {
                  const h = homes.find((h) => h.home_id === Number(id));
                  if (h) setCurrentHome(h);
                }
              }}
            >
              <option value="">{isSystemAdmin ? "Все дома" : "Выберите дом"}</option>
              {homes.map((h) => (
                <option key={h.home_id} value={h.home_id}>
                  {h.name} ({h.my_role})
                </option>
              ))}
            </select>
            <div className="user-name">{user.login}</div>
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
      <HomeProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route index element={<Navigate to="/live" replace />} />
              <Route path="/live" element={<LivePage />} />
              <Route path="/reviews" element={<ReviewsPage />} />
              <Route path="/recordings" element={<RecordingsPage />} />
              <Route path="/cameras" element={<CamerasPage />} />
              <Route path="/homes" element={<HomesPage />} />
              <Route path="/homes/:id" element={<HomeDetailPage />} />
              <Route path="/persons" element={<PersonsPage />} />
              <Route path="/processors" element={<ProcessorsPage />} />
              <Route path="/apikeys" element={<ApiKeysPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/live" replace />} />
        </Routes>
      </HomeProvider>
    </AuthProvider>
  );
}

export default App;
