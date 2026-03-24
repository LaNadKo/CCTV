import { useEffect, useState } from "react";
import {
  adminListUsers,
  adminCreateUser,
  adminDeleteUser,
  adminSetUserRole,
  type UserOut,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

const ROLES: Record<number, string> = { 1: "Админ", 2: "Пользователь", 3: "Наблюдатель" };

const UsersPage: React.FC = () => {
  const { token, user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [roleId, setRoleId] = useState(3);

  const load = async () => {
    if (!token) return;
    setLoading(true);
    try {
      setUsers(await adminListUsers(token));
    } catch (e: any) {
      setError(e?.message || "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [token]);

  const handleCreate = async () => {
    if (!token || !login.trim() || !password) return;
    try {
      await adminCreateUser(token, login.trim(), password, roleId);
      setLogin("");
      setPassword("");
      setRoleId(3);
      setShowCreate(false);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleDelete = async (userId: number) => {
    if (!token || !confirm("Удалить пользователя?")) return;
    try {
      await adminDeleteUser(token, userId);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleRoleChange = async (userId: number, newRoleId: number) => {
    if (!token) return;
    try {
      await adminSetUserRole(token, userId, newRoleId);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h2 className="title">Пользователи</h2>
          <div className="muted">Управление пользователями системы.</div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn secondary" onClick={load}>Обновить</button>
          <button className="btn" onClick={() => setShowCreate(!showCreate)}>Создать</button>
        </div>
      </div>

      {error && <div className="danger">{error}</div>}

      {showCreate && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Новый пользователь</h3>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
            <label className="field">
              <span className="label">Логин</span>
              <input className="input" value={login} onChange={(e) => setLogin(e.target.value)} />
            </label>
            <label className="field">
              <span className="label">Пароль</span>
              <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            <label className="field">
              <span className="label">Роль</span>
              <select className="input" value={roleId} onChange={(e) => setRoleId(Number(e.target.value))}>
                <option value={1}>Админ</option>
                <option value={2}>Пользователь</option>
                <option value={3}>Наблюдатель</option>
              </select>
            </label>
          </div>
          <button className="btn" style={{ marginTop: 10 }} onClick={handleCreate} disabled={!login.trim() || !password}>
            Создать
          </button>
        </div>
      )}

      {loading ? (
        <div className="muted">Загрузка...</div>
      ) : (
        <div className="card">
          <div className="stack" style={{ gap: 0 }}>
            {users.map((u) => (
              <div key={u.user_id} className="row" style={{ justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                <div className="row" style={{ gap: 12 }}>
                  <span style={{ fontWeight: 600, minWidth: 120 }}>{u.login}</span>
                  <span className="pill" style={{ color: u.role_id === 1 ? "#fbbf24" : u.role_id === 2 ? "#60a5fa" : "var(--muted)" }}>
                    {ROLES[u.role_id] || `Роль ${u.role_id}`}
                  </span>
                  {u.must_change_password && <span className="pill" style={{ color: "#f87171" }}>Смена пароля</span>}
                </div>
                {u.user_id !== currentUser?.user_id && (
                  <div className="row" style={{ gap: 6 }}>
                    <select
                      className="input"
                      style={{ fontSize: 12, padding: "3px 6px" }}
                      value={u.role_id}
                      onChange={(e) => handleRoleChange(u.user_id, Number(e.target.value))}
                    >
                      <option value={1}>Админ</option>
                      <option value={2}>Пользователь</option>
                      <option value={3}>Наблюдатель</option>
                    </select>
                    <button
                      className="btn secondary"
                      style={{ fontSize: 11, padding: "3px 8px" }}
                      onClick={() => handleDelete(u.user_id)}
                    >
                      Удалить
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default UsersPage;
