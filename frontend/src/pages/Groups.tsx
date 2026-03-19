import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createGroup, listGroups } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Group = { group_id: number; name: string; description?: string; membership_role?: string };

const GroupsPage: React.FC = () => {
  const { token } = useAuth();
  const nav = useNavigate();
  const [groups, setGroups] = useState<Group[]>([]);
  const [createForm, setCreateForm] = useState({ name: "", description: "" });
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!token) return;
    setError(null);
    try {
      const res = await listGroups(token);
      setGroups(res);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить группы");
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const submitCreate = async () => {
    if (!token) return;
    try {
      await createGroup(token, createForm.name, createForm.description || undefined);
      setCreateForm({ name: "", description: "" });
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка создания");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div>
        <h2 className="title">Группы</h2>
        <div className="muted">Создайте группу или перейдите в редактирование.</div>
      </div>
      {error && <div className="danger">{error}</div>}
      <div className="grid">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Создать группу</h3>
          <div className="stack">
            <label className="field">
              <span className="label">Название</span>
              <input
                className="input"
                value={createForm.name}
                onChange={(e) => setCreateForm((p) => ({ ...p, name: e.target.value }))}
                placeholder="Офис 1 этаж"
              />
            </label>
            <label className="field">
              <span className="label">Описание</span>
              <input
                className="input"
                value={createForm.description}
                onChange={(e) => setCreateForm((p) => ({ ...p, description: e.target.value }))}
                placeholder="Произвольный текст"
              />
            </label>
            <button className="btn" onClick={submitCreate} disabled={!createForm.name}>
              Создать
            </button>
          </div>
        </div>

        <div className="card">
          <h3 style={{ marginTop: 0 }}>Мои группы</h3>
          <div className="grid">
            {groups.map((g) => (
              <div key={g.group_id} className="card">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <h4 style={{ margin: 0 }}>{g.name}</h4>
                  <span className="pill">#{g.group_id}</span>
                </div>
                <div className="muted">{g.description || "Нет описания"}</div>
                <div className="muted" style={{ marginTop: 4 }}>
                  Ваша роль: {g.membership_role || "—"}
                </div>
                <button className="btn secondary" onClick={() => nav(`/groups/${g.group_id}`)}>
                  Редактировать
                </button>
              </div>
            ))}
            {groups.length === 0 && <div className="muted">Групп пока нет.</div>}
          </div>
        </div>
      </div>
    </div>
  );
};

export default GroupsPage;
