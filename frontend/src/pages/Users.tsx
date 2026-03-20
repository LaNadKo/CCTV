import { useEffect, useMemo, useState } from "react";
import { adminCreateUser, adminDeleteUser, adminListUsers, adminSetUserRole, type UserOut } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const ROLES: Record<number, string> = { 1: "Администратор", 2: "Оператор", 3: "Наблюдатель" };

const UsersPage: React.FC = () => {
  const { token, user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [roleId, setRoleId] = useState(3);

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setUsers(await adminListUsers(token));
    } catch (event: any) {
      setError(event?.message || "Ошибка загрузки пользователей");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const handleCreate = async () => {
    if (!token || !login.trim() || !password) return;
    try {
      await adminCreateUser(token, login.trim(), password, roleId);
      setLogin("");
      setPassword("");
      setRoleId(3);
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка создания пользователя");
    }
  };

  const handleDelete = async (userId: number) => {
    if (!token || !window.confirm("Удалить пользователя?")) return;
    try {
      await adminDeleteUser(token, userId);
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка удаления");
    }
  };

  const handleRoleChange = async (userId: number, newRoleId: number) => {
    if (!token) return;
    try {
      await adminSetUserRole(token, userId, newRoleId);
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка смены роли");
    }
  };

  const stats = useMemo(
    () => ({
      admins: users.filter((user) => user.role_id === 1).length,
      operators: users.filter((user) => user.role_id === 2).length,
      viewers: users.filter((user) => user.role_id === 3).length,
    }),
    [users]
  );

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Administration</div>
          <h2 className="title">Пользователи</h2>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Всего пользователей</div>
          <div className="summary-card__value">{users.length}</div>
          <div className="summary-card__hint">Активные системные учётные записи backend.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Администраторы</div>
          <div className="summary-card__value">{stats.admins}</div>
          <div className="summary-card__hint">Имеют доступ ко всем административным разделам.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Операторы / наблюдатели</div>
          <div className="summary-card__value">{stats.operators + stats.viewers}</div>
          <div className="summary-card__hint">Рабочие учётные записи для повседневного использования системы.</div>
        </div>
      </section>

      {error && <div className="danger">{error}</div>}

      <section className="admin-two-column">
        <div className="panel-card stack">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Новый пользователь</h3>
              <div className="panel-card__lead">Пользователь создаётся администратором и сразу получает нужную роль.</div>
            </div>
          </div>

          <label className="field">
            <span className="label">Логин</span>
            <input className="input" value={login} onChange={(event) => setLogin(event.target.value)} />
          </label>
          <label className="field">
            <span className="label">Пароль</span>
            <input className="input" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          <label className="field">
            <span className="label">Роль</span>
            <select className="input" value={roleId} onChange={(event) => setRoleId(Number(event.target.value))}>
              <option value={1}>Администратор</option>
              <option value={2}>Оператор</option>
              <option value={3}>Наблюдатель</option>
            </select>
          </label>
          <button className="btn" onClick={handleCreate} disabled={!login.trim() || !password}>
            Создать пользователя
          </button>
        </div>

        <div className="panel-card">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Текущие учётные записи</h3>
              <div className="panel-card__lead">Список ролей и служебных признаков по всем пользователям системы.</div>
            </div>
            <span className="pill">{users.length}</span>
          </div>

          {loading ? (
            <div className="muted">Загрузка...</div>
          ) : users.length === 0 ? (
            <div className="muted">Пользователей пока нет.</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="soft-table">
                <thead>
                  <tr>
                    <th>Логин</th>
                    <th>Роль</th>
                    <th>Статус</th>
                    <th style={{ textAlign: "right" }}>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.user_id}>
                      <td>
                        <div style={{ fontWeight: 700 }}>{user.login}</div>
                        {user.user_id === currentUser?.user_id && <div className="muted">Текущий аккаунт</div>}
                      </td>
                      <td>
                        {user.user_id === currentUser?.user_id ? (
                          <span className="pill">{ROLES[user.role_id] || `Роль ${user.role_id}`}</span>
                        ) : (
                          <select
                            className="input"
                            value={user.role_id}
                            onChange={(event) => handleRoleChange(user.user_id, Number(event.target.value))}
                          >
                            <option value={1}>Администратор</option>
                            <option value={2}>Оператор</option>
                            <option value={3}>Наблюдатель</option>
                          </select>
                        )}
                      </td>
                      <td>
                        {user.must_change_password ? (
                          <span className="pill" style={{ color: "#f87171" }}>
                            Требует смены пароля
                          </span>
                        ) : (
                          <span className="pill" style={{ color: "#22c55e" }}>
                            Активен
                          </span>
                        )}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {user.user_id !== currentUser?.user_id && (
                          <button className="btn secondary" onClick={() => handleDelete(user.user_id)}>
                            Удалить
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default UsersPage;
