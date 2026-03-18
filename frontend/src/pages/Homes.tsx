import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listHomes, createHome, joinHomeByCode, deleteHome, type HomeOut } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const HomesPage: React.FC = () => {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [homes, setHomes] = useState<HomeOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [joinCode, setJoinCode] = useState("");

  const load = async () => {
    if (!token) return;
    setLoading(true);
    try {
      setHomes(await listHomes(token));
    } catch (e: any) {
      setError(e?.message || "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const handleCreate = async () => {
    if (!token || !name.trim()) return;
    try {
      const h = await createHome(token, name.trim(), desc.trim() || undefined);
      setName("");
      setDesc("");
      setShowCreate(false);
      navigate(`/homes/${h.home_id}`);
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleJoin = async () => {
    if (!token || !joinCode.trim()) return;
    try {
      await joinHomeByCode(token, joinCode.trim());
      setJoinCode("");
      await load();
    } catch (e: any) {
      alert(e?.message || "Неверный код приглашения");
    }
  };

  const handleDelete = async (id: number) => {
    if (!token || !confirm("Удалить дом? Все комнаты и участники будут удалены.")) return;
    try {
      await deleteHome(token, id);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка удаления");
    }
  };

  const roleBadge = (role?: string | null) => {
    if (!role) return null;
    const colors: Record<string, string> = {
      owner: "#fbbf24",
      admin: "#60a5fa",
      member: "#a78bfa",
      guest: "var(--muted)",
    };
    return (
      <span className="pill" style={{ color: colors[role] || "var(--muted)" }}>
        {role}
      </span>
    );
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h2 className="title">Дома</h2>
          <div className="muted">Группировка камер по принципу Xiaomi Home: Дом → Комната → Камера.</div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
          <button className="btn" onClick={() => setShowCreate(!showCreate)}>
            Создать дом
          </button>
        </div>
      </div>

      {error && <div className="danger">{error}</div>}

      {showCreate && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Новый дом</h3>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <label className="field">
              <span className="label">Название</span>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Мой дом" />
            </label>
            <label className="field">
              <span className="label">Описание</span>
              <input className="input" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Основной объект" />
            </label>
          </div>
          <button className="btn" style={{ marginTop: 10 }} onClick={handleCreate} disabled={!name.trim()}>
            Создать
          </button>
        </div>
      )}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Присоединиться по коду</h3>
        <div className="row" style={{ gap: 8 }}>
          <input
            className="input"
            style={{ flex: 1 }}
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value)}
            placeholder="Код приглашения"
          />
          <button className="btn secondary" onClick={handleJoin} disabled={!joinCode.trim()}>
            Войти
          </button>
        </div>
      </div>

      {loading ? (
        <div className="muted">Загрузка...</div>
      ) : homes.length === 0 ? (
        <div className="card">
          <div className="muted">Нет домов. Создайте новый или присоединитесь по коду приглашения.</div>
        </div>
      ) : (
        <div className="grid">
          {homes.map((h) => (
            <div
              key={h.home_id}
              className="card"
              style={{ cursor: "pointer" }}
              onClick={() => navigate(`/homes/${h.home_id}`)}
            >
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ fontWeight: 600 }}>{h.name}</div>
                {roleBadge(h.my_role)}
              </div>
              {h.description && <div className="muted" style={{ marginTop: 4 }}>{h.description}</div>}
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                Комнат: {h.room_count} · Участников: {h.member_count}
              </div>
              {h.my_role === "owner" && (
                <button
                  className="btn secondary"
                  style={{ fontSize: 12, padding: "4px 10px", marginTop: 8 }}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(h.home_id);
                  }}
                >
                  Удалить
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default HomesPage;
