import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  getHome,
  updateHome,
  createRoom,
  deleteRoom,
  addCameraToRoom,
  removeCameraFromRoom,
  createHomeInvite,
  updateHomeMemberRole,
  removeHomeMember,
  transferHomeOwnership,
  getHomeActivity,
  getCameras,
  type HomeDetailOut,
  type InviteOut,
  type ActivityOut,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Camera = { camera_id: number; name: string };

const HomeDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();
  const navigate = useNavigate();
  const homeId = Number(id);

  const [home, setHome] = useState<HomeDetailOut | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activities, setActivities] = useState<ActivityOut[]>([]);
  const [invite, setInvite] = useState<InviteOut | null>(null);

  // forms
  const [newRoomName, setNewRoomName] = useState("");
  const [addCamRoom, setAddCamRoom] = useState<{ roomId: number; camId: string } | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [showEdit, setShowEdit] = useState(false);

  const load = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [h, c, a] = await Promise.all([
        getHome(token, homeId),
        getCameras(token),
        getHomeActivity(token, homeId, 20),
      ]);
      setHome(h);
      setCameras(c);
      setActivities(a);
      setEditName(h.name);
      setEditDesc(h.description || "");
    } catch (e: any) {
      setError(e?.message || "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token, homeId]);

  const isOwner = home?.my_role === "owner";
  const isAdmin = isOwner || home?.my_role === "admin";

  const handleUpdate = async () => {
    if (!token) return;
    try {
      await updateHome(token, homeId, { name: editName, description: editDesc });
      setShowEdit(false);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleCreateRoom = async () => {
    if (!token || !newRoomName.trim()) return;
    try {
      await createRoom(token, homeId, newRoomName.trim());
      setNewRoomName("");
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleDeleteRoom = async (roomId: number) => {
    if (!token || !confirm("Удалить комнату?")) return;
    try {
      await deleteRoom(token, homeId, roomId);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleAddCamera = async (roomId: number) => {
    if (!token || !addCamRoom) return;
    const camId = parseInt(addCamRoom.camId, 10);
    if (isNaN(camId)) return;
    try {
      await addCameraToRoom(token, homeId, roomId, camId);
      setAddCamRoom(null);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleRemoveCamera = async (roomId: number, camId: number) => {
    if (!token) return;
    try {
      await removeCameraFromRoom(token, homeId, roomId, camId);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleInvite = async () => {
    if (!token) return;
    try {
      const inv = await createHomeInvite(token, homeId, "member", 72);
      setInvite(inv);
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleRoleChange = async (userId: number, role: string) => {
    if (!token) return;
    try {
      await updateHomeMemberRole(token, homeId, userId, role);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleRemoveMember = async (userId: number) => {
    if (!token || !confirm("Удалить участника?")) return;
    try {
      await removeHomeMember(token, homeId, userId);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleTransfer = async (userId: number) => {
    if (!token || !confirm("Передать владение этому участнику?")) return;
    try {
      await transferHomeOwnership(token, homeId, userId);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  if (loading) return <div className="stack" style={{ marginTop: 18 }}><div className="muted">Загрузка...</div></div>;
  if (error) return <div className="stack" style={{ marginTop: 18 }}><div className="danger">{error}</div></div>;
  if (!home) return null;

  const roleBadgeColor: Record<string, string> = {
    owner: "#fbbf24",
    admin: "#60a5fa",
    member: "#a78bfa",
    guest: "var(--muted)",
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <button className="btn secondary" style={{ fontSize: 12, padding: "4px 10px", marginBottom: 8 }} onClick={() => navigate("/homes")}>
            ← Назад
          </button>
          <h2 className="title">{home.name}</h2>
          {home.description && <div className="muted">{home.description}</div>}
        </div>
        <div className="row" style={{ gap: 6 }}>
          {isAdmin && (
            <button className="btn secondary" onClick={() => setShowEdit(!showEdit)}>
              Редактировать
            </button>
          )}
          {isAdmin && (
            <button className="btn" onClick={handleInvite}>
              Пригласить
            </button>
          )}
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
        </div>
      </div>

      {showEdit && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Редактирование дома</h3>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <label className="field">
              <span className="label">Название</span>
              <input className="input" value={editName} onChange={(e) => setEditName(e.target.value)} />
            </label>
            <label className="field">
              <span className="label">Описание</span>
              <input className="input" value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
            </label>
          </div>
          <button className="btn" style={{ marginTop: 10 }} onClick={handleUpdate}>
            Сохранить
          </button>
        </div>
      )}

      {invite && (
        <div className="card" style={{ background: "rgba(255,255,255,0.04)" }}>
          <div className="label">Код приглашения (действует 72 часа)</div>
          <div style={{ fontWeight: 600, fontSize: 18, wordBreak: "break-all" }}>{invite.invite_code}</div>
        </div>
      )}

      {/* Rooms */}
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Комнаты ({home.rooms.length})</h3>
        </div>

        {isAdmin && (
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <input
              className="input"
              style={{ flex: 1 }}
              value={newRoomName}
              onChange={(e) => setNewRoomName(e.target.value)}
              placeholder="Название комнаты"
            />
            <button className="btn" onClick={handleCreateRoom} disabled={!newRoomName.trim()}>
              Добавить
            </button>
          </div>
        )}

        <div className="stack" style={{ marginTop: 12 }}>
          {home.rooms.length === 0 && <div className="muted">Нет комнат.</div>}
          {home.rooms.map((room) => (
            <div key={room.room_id} className="card" style={{ background: "rgba(255,255,255,0.02)" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ fontWeight: 600 }}>{room.name}</div>
                <div className="row" style={{ gap: 6 }}>
                  {isAdmin && (
                    <button
                      className="btn secondary"
                      style={{ fontSize: 12, padding: "3px 8px" }}
                      onClick={() =>
                        setAddCamRoom(addCamRoom?.roomId === room.room_id ? null : { roomId: room.room_id, camId: "" })
                      }
                    >
                      + Камера
                    </button>
                  )}
                  {isAdmin && (
                    <button
                      className="btn secondary"
                      style={{ fontSize: 12, padding: "3px 8px" }}
                      onClick={() => handleDeleteRoom(room.room_id)}
                    >
                      Удалить
                    </button>
                  )}
                </div>
              </div>
              {room.cameras && room.cameras.length > 0 && (
                <div className="stack" style={{ marginTop: 8, gap: 4 }}>
                  {room.cameras.map((rc) => (
                    <div key={rc.camera_id} className="row" style={{ justifyContent: "space-between", padding: "4px 8px", background: "rgba(255,255,255,0.03)", borderRadius: 4 }}>
                      <span style={{ fontSize: 13 }}>{rc.camera_name} (#{rc.camera_id})</span>
                      {isAdmin && (
                        <button
                          className="btn secondary"
                          style={{ fontSize: 11, padding: "2px 6px" }}
                          onClick={() => handleRemoveCamera(room.room_id, rc.camera_id)}
                        >
                          Убрать
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {addCamRoom?.roomId === room.room_id && (
                <div className="row" style={{ gap: 8, marginTop: 8 }}>
                  <select
                    className="input"
                    style={{ flex: 1 }}
                    value={addCamRoom.camId}
                    onChange={(e) => setAddCamRoom({ ...addCamRoom, camId: e.target.value })}
                  >
                    <option value="">Выберите камеру</option>
                    {cameras.map((c) => (
                      <option key={c.camera_id} value={c.camera_id}>
                        {c.name} (#{c.camera_id})
                      </option>
                    ))}
                  </select>
                  <button className="btn" style={{ fontSize: 12, padding: "6px 12px" }} onClick={() => handleAddCamera(room.room_id)}>
                    Добавить
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Members */}
      <div className="card">
        <h3 style={{ margin: 0 }}>Участники ({home.members.length})</h3>
        <div className="stack" style={{ marginTop: 10 }}>
          {home.members.map((m) => (
            <div key={m.user_id} className="row" style={{ justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
              <div className="row" style={{ gap: 8 }}>
                <div>{m.login}</div>
                <span className="pill" style={{ color: roleBadgeColor[m.role] || "var(--muted)" }}>
                  {m.role}
                </span>
              </div>
              {isOwner && m.role !== "owner" && (
                <div className="row" style={{ gap: 4 }}>
                  <select
                    className="input"
                    style={{ fontSize: 12, padding: "3px 6px" }}
                    value={m.role}
                    onChange={(e) => handleRoleChange(m.user_id, e.target.value)}
                  >
                    <option value="admin">admin</option>
                    <option value="member">member</option>
                    <option value="guest">guest</option>
                  </select>
                  <button
                    className="btn secondary"
                    style={{ fontSize: 11, padding: "3px 6px" }}
                    onClick={() => handleTransfer(m.user_id)}
                  >
                    Передать
                  </button>
                  <button
                    className="btn secondary"
                    style={{ fontSize: 11, padding: "3px 6px" }}
                    onClick={() => handleRemoveMember(m.user_id)}
                  >
                    Убрать
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Activity */}
      <div className="card">
        <h3 style={{ margin: 0 }}>Журнал активности</h3>
        <div className="stack" style={{ marginTop: 10 }}>
          {activities.length === 0 && <div className="muted">Нет записей.</div>}
          {activities.map((a) => (
            <div key={a.activity_id} className="row" style={{ gap: 8, fontSize: 13 }}>
              <span className="muted" style={{ minWidth: 140 }}>
                {new Date(a.created_at).toLocaleString()}
              </span>
              <span>{a.user_login || "система"}</span>
              <span className="muted">{a.action}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default HomeDetailPage;
