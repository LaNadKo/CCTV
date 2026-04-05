import { useEffect, useMemo, useState } from "react";
import { adminCreateUser, adminDeleteUser, adminListUsers, adminSetUserRole, type UserOut } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const ROLES: Record<number, string> = { 1: "?????????????", 2: "????????", 3: "???????????" };

function formatFullName(user: Pick<UserOut, "last_name" | "first_name" | "middle_name">): string {
  return [user.last_name, user.first_name, user.middle_name].filter(Boolean).join(" ") || "?? ?????????";
}

const UsersPage: React.FC = () => {
  const { token, user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({
    login: "",
    password: "",
    role_id: 3,
    last_name: "",
    first_name: "",
    middle_name: "",
  });

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setUsers(await adminListUsers(token));
    } catch (event: any) {
      setError(event?.message || "?????? ???????? ?????????????");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [token]);

  const handleCreate = async () => {
    if (!token || !form.login.trim() || !form.password) return;
    try {
      await adminCreateUser(token, {
        login: form.login.trim(),
        password: form.password,
        role_id: form.role_id,
        last_name: form.last_name.trim() || undefined,
        first_name: form.first_name.trim() || undefined,
        middle_name: form.middle_name.trim() || undefined,
      });
      setForm({
        login: "",
        password: "",
        role_id: 3,
        last_name: "",
        first_name: "",
        middle_name: "",
      });
      await load();
    } catch (event: any) {
      alert(event?.message || "?????? ???????? ????????????");
    }
  };

  const handleDelete = async (userId: number) => {
    if (!token || !window.confirm("??????? ?????????????")) return;
    try {
      await adminDeleteUser(token, userId);
      await load();
    } catch (event: any) {
      alert(event?.message || "?????? ????????");
    }
  };

  const handleRoleChange = async (userId: number, newRoleId: number) => {
    if (!token) return;
    try {
      await adminSetUserRole(token, userId, newRoleId);
      await load();
    } catch (event: any) {
      alert(event?.message || "?????? ????? ????");
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
          <h2 className="title">????????????</h2>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={() => void load()}>
            ????????
          </button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">????? ?????????????</div>
          <div className="summary-card__value">{users.length}</div>
          <div className="summary-card__hint">????????? ??????? ?????? backend.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">??????????????</div>
          <div className="summary-card__value">{stats.admins}</div>
          <div className="summary-card__hint">?????? ?????? ? ???????????? ? ????????????.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">????????? / ???????????</div>
          <div className="summary-card__value">{stats.operators + stats.viewers}</div>
          <div className="summary-card__hint">??????? ??????? ?????? ??? ???????????? ????????????.</div>
        </div>
      </section>

      {error && <div className="danger">{error}</div>}

      <section className="admin-two-column">
        <div className="panel-card stack">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">????? ????????????</h3>
              <div className="panel-card__lead">???????? ??????? ?????? ? ??????????? ???????? ???.</div>
            </div>
          </div>

          <label className="field">
            <span className="label">???????</span>
            <input className="input" value={form.last_name} onChange={(event) => setForm((prev) => ({ ...prev, last_name: event.target.value }))} />
          </label>
          <label className="field">
            <span className="label">???</span>
            <input className="input" value={form.first_name} onChange={(event) => setForm((prev) => ({ ...prev, first_name: event.target.value }))} />
          </label>
          <label className="field">
            <span className="label">????????</span>
            <input className="input" value={form.middle_name} onChange={(event) => setForm((prev) => ({ ...prev, middle_name: event.target.value }))} />
          </label>
          <label className="field">
            <span className="label">?????</span>
            <input className="input" value={form.login} onChange={(event) => setForm((prev) => ({ ...prev, login: event.target.value }))} />
          </label>
          <label className="field">
            <span className="label">??????</span>
            <input className="input" type="password" value={form.password} onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))} />
          </label>
          <label className="field">
            <span className="label">????</span>
            <select className="input" value={form.role_id} onChange={(event) => setForm((prev) => ({ ...prev, role_id: Number(event.target.value) }))}>
              <option value={1}>?????????????</option>
              <option value={2}>????????</option>
              <option value={3}>???????????</option>
            </select>
          </label>
          <button className="btn" onClick={handleCreate} disabled={!form.login.trim() || !form.password}>
            ??????? ????????????
          </button>
        </div>

        <div className="panel-card">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">??????? ??????? ??????</h3>
              <div className="panel-card__lead">???, ???? ? ?????? ????? ?????? ?? ???? ????????????? ???????.</div>
            </div>
            <span className="pill">{users.length}</span>
          </div>

          {loading ? (
            <div className="muted">????????...</div>
          ) : users.length === 0 ? (
            <div className="muted">????????????? ???? ???.</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="soft-table">
                <thead>
                  <tr>
                    <th>???</th>
                    <th>?????</th>
                    <th>????</th>
                    <th>??????</th>
                    <th style={{ textAlign: "right" }}>????????</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.user_id}>
                      <td>
                        <div style={{ fontWeight: 700 }}>{formatFullName(user)}</div>
                        {user.user_id === currentUser?.user_id && <div className="muted">??????? ???????</div>}
                      </td>
                      <td>{user.login}</td>
                      <td>
                        {user.user_id === currentUser?.user_id ? (
                          <span className="pill">{ROLES[user.role_id] || `???? ${user.role_id}`}</span>
                        ) : (
                          <select
                            className="input"
                            value={user.role_id}
                            onChange={(event) => void handleRoleChange(user.user_id, Number(event.target.value))}
                          >
                            <option value={1}>?????????????</option>
                            <option value={2}>????????</option>
                            <option value={3}>???????????</option>
                          </select>
                        )}
                      </td>
                      <td>
                        {user.must_change_password ? (
                          <span className="pill" style={{ color: "#f87171" }}>
                            ??????? ????? ??????
                          </span>
                        ) : (
                          <span className="pill" style={{ color: "#22c55e" }}>
                            ???????
                          </span>
                        )}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {user.user_id !== currentUser?.user_id && (
                          <button className="btn secondary" onClick={() => void handleDelete(user.user_id)}>
                            ???????
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
