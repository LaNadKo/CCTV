import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getGroup, inviteToGroup, transferOwner } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const GroupDetail: React.FC = () => {
  const { token } = useAuth();
  const { id } = useParams();
  const nav = useNavigate();
  const groupId = Number(id);
  const [group, setGroup] = useState<{ group_id: number; name: string; description?: string; membership_role?: string } | null>(null);
  const [inviteLogin, setInviteLogin] = useState("");
  const [invitePassword, setInvitePassword] = useState("");
  const [transferLogin, setTransferLogin] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!token || !groupId) return;
    try {
      const g = await getGroup(token, groupId);
      setGroup({ group_id: g.group_id, name: g.name, description: g.description, membership_role: g.membership_role });
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить группу");
    }
  };

  useEffect(() => {
    load();
  }, [token, groupId]);

  const doInvite = async () => {
    if (!token || !groupId) return;
    try {
      await inviteToGroup(token, groupId, inviteLogin, invitePassword || undefined);
      alert("Приглашение отправлено / пользователь добавлен");
      setInviteLogin("");
      setInvitePassword("");
    } catch (e: any) {
      alert(e?.message || "Ошибка приглашения");
    }
  };

  const doTransfer = async () => {
    if (!token || !groupId) return;
    try {
      await transferOwner(token, groupId, transferLogin);
      alert("Владелец обновлен");
      setTransferLogin("");
    } catch (e: any) {
      alert(e?.message || "Ошибка передачи");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <button className="btn secondary" onClick={() => nav(-1)}>
        ← Назад
      </button>
      <h2 className="title">Группа #{groupId}</h2>
      {error && <div className="danger">{error}</div>}
      {group && (
        <div className="card">
          <h3 style={{ margin: 0 }}>{group.name}</h3>
          <div className="muted">{group.description || "Нет описания"}</div>
          <div className="muted" style={{ marginTop: 4 }}>
            Ваша роль: {group.membership_role || "—"}
          </div>
        </div>
      )}

      <div className="grid">
        {(group?.membership_role === "owner" || group?.membership_role === "admin") && (
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Пригласить участника (по логину)</h3>
            <div className="stack">
              <label className="field">
                <span className="label">Логин</span>
                <input className="input" value={inviteLogin} onChange={(e) => setInviteLogin(e.target.value)} />
              </label>
              <label className="field">
                <span className="label">Пароль (если создаём нового)</span>
                <input
                  className="input"
                  value={invitePassword}
                  onChange={(e) => setInvitePassword(e.target.value)}
                />
              </label>
              <button className="btn" onClick={doInvite} disabled={!inviteLogin}>
                Пригласить / создать
              </button>
            </div>
          </div>
        )}

        {group?.membership_role === "owner" && (
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Передача владения (по логину)</h3>
            <div className="stack">
              <label className="field">
                <span className="label">Логин нового владельца</span>
                <input
                  className="input"
                  value={transferLogin}
                  onChange={(e) => setTransferLogin(e.target.value)}
                  placeholder="user@example"
                />
              </label>
              <button className="btn secondary" onClick={doTransfer} disabled={!transferLogin}>
                Передать
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default GroupDetail;
