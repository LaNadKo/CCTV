import { useEffect, useState } from "react";
import {
  listGroups,
  createGroup,
  deleteGroup,
  getGroup,
  updateGroup,
  getCameras,
  assignCameraToGroup,
  unassignCameraFromGroup,
  type GroupOut,
  type GroupDetail,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Camera = { camera_id: number; name: string; location?: string; group_id?: number | null };

const GroupsPage: React.FC = () => {
  const { token, user } = useAuth();
  const isAdmin = user?.role_id === 1;
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [selectedGroup, setSelectedGroup] = useState<GroupDetail | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [allCameras, setAllCameras] = useState<Camera[]>([]);
  const [addCamId, setAddCamId] = useState("");

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const [g, c] = await Promise.all([listGroups(token), getCameras(token)]);
      setGroups(g);
      setAllCameras(c);
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
      await createGroup(token, name.trim(), desc.trim() || undefined);
      setName("");
      setDesc("");
      setShowCreate(false);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleDelete = async (id: number) => {
    if (!token || !confirm("Удалить группу? Камеры останутся, но будут без группы.")) return;
    try {
      await deleteGroup(token, id);
      if (selectedGroup?.group_id === id) {
        setSelectedGroup(null);
        setEditName("");
        setEditDesc("");
      }
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка удаления");
    }
  };

  const openGroup = async (groupId: number) => {
    if (!token) return;
    try {
      const detail = await getGroup(token, groupId);
      setSelectedGroup(detail);
      setEditName(detail.name);
      setEditDesc(detail.description || "");
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleUpdate = async () => {
    if (!token || !selectedGroup || !editName.trim()) return;
    try {
      await updateGroup(token, selectedGroup.group_id, {
        name: editName.trim(),
        description: editDesc.trim() || undefined,
      });
      await openGroup(selectedGroup.group_id);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleAssignCamera = async () => {
    if (!token || !selectedGroup || !addCamId) return;
    try {
      await assignCameraToGroup(token, selectedGroup.group_id, Number(addCamId));
      setAddCamId("");
      await openGroup(selectedGroup.group_id);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleUnassignCamera = async (camId: number) => {
    if (!token || !selectedGroup) return;
    try {
      await unassignCameraFromGroup(token, selectedGroup.group_id, camId);
      await openGroup(selectedGroup.group_id);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const unassignedCameras = allCameras.filter(
    (camera) => !selectedGroup?.cameras.some((groupCamera) => groupCamera.camera_id === camera.camera_id)
  );

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h2 className="title">Группы</h2>
          <div className="muted">Логические группировки камер.</div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn secondary" onClick={load}>Обновить</button>
          {isAdmin && (
            <button className="btn" onClick={() => setShowCreate(!showCreate)}>Создать группу</button>
          )}
        </div>
      </div>

      {error && <div className="danger">{error}</div>}

      {showCreate && isAdmin && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Новая группа</h3>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <label className="field">
              <span className="label">Название</span>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Офис" />
            </label>
            <label className="field">
              <span className="label">Описание</span>
              <input className="input" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Камеры офиса" />
            </label>
          </div>
          <button className="btn" style={{ marginTop: 10 }} onClick={handleCreate} disabled={!name.trim()}>
            Создать
          </button>
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: selectedGroup ? "1fr 1fr" : "1fr", gap: 16 }}>
        <div className="stack">
          {loading ? (
            <div className="muted">Загрузка...</div>
          ) : groups.length === 0 ? (
            <div className="card"><div className="muted">Нет групп.</div></div>
          ) : (
            groups.map((group) => (
              <div
                key={group.group_id}
                className="card"
                style={{
                  cursor: "pointer",
                  border: selectedGroup?.group_id === group.group_id ? "1px solid #60a5fa" : undefined,
                }}
                onClick={() => openGroup(group.group_id)}
              >
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div style={{ fontWeight: 600 }}>{group.name}</div>
                  <span className="pill">{group.camera_count} камер</span>
                </div>
                {group.description && <div className="muted" style={{ marginTop: 4 }}>{group.description}</div>}
                {isAdmin && (
                  <button
                    className="btn secondary"
                    style={{ fontSize: 12, padding: "4px 10px", marginTop: 8 }}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleDelete(group.group_id);
                    }}
                  >
                    Удалить
                  </button>
                )}
              </div>
            ))
          )}
        </div>

        {selectedGroup && (
          <div className="card">
            {isAdmin ? (
              <div className="stack" style={{ gap: 8, marginBottom: 12 }}>
                <label className="field">
                  <span className="label">Название</span>
                  <input className="input" value={editName} onChange={(e) => setEditName(e.target.value)} />
                </label>
                <label className="field">
                  <span className="label">Описание</span>
                  <input className="input" value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
                </label>
                <div className="row" style={{ gap: 8 }}>
                  <button className="btn" onClick={handleUpdate} disabled={!editName.trim()}>
                    Сохранить
                  </button>
                  <button
                    className="btn secondary"
                    onClick={() => {
                      setEditName(selectedGroup.name);
                      setEditDesc(selectedGroup.description || "");
                    }}
                  >
                    Сбросить
                  </button>
                </div>
              </div>
            ) : (
              <>
                <h3 style={{ marginTop: 0 }}>{selectedGroup.name}</h3>
                {selectedGroup.description && <div className="muted" style={{ marginBottom: 12 }}>{selectedGroup.description}</div>}
              </>
            )}

            <div style={{ fontWeight: 600, marginBottom: 8 }}>Камеры ({selectedGroup.cameras.length})</div>
            {selectedGroup.cameras.length === 0 ? (
              <div className="muted">Нет камер в группе.</div>
            ) : (
              <div className="stack" style={{ gap: 4 }}>
                {selectedGroup.cameras.map((camera) => (
                  <div
                    key={camera.camera_id}
                    className="row"
                    style={{
                      justifyContent: "space-between",
                      padding: "4px 8px",
                      background: "rgba(255,255,255,0.03)",
                      borderRadius: 4,
                    }}
                  >
                    <span style={{ fontSize: 13 }}>
                      {camera.name} {camera.location ? `(${camera.location})` : ""}
                    </span>
                    {isAdmin && (
                      <button
                        className="btn secondary"
                        style={{ fontSize: 11, padding: "2px 6px" }}
                        onClick={() => handleUnassignCamera(camera.camera_id)}
                      >
                        Убрать
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {isAdmin && unassignedCameras.length > 0 && (
              <div className="row" style={{ gap: 8, marginTop: 12 }}>
                <select className="input" style={{ flex: 1 }} value={addCamId} onChange={(e) => setAddCamId(e.target.value)}>
                  <option value="">Добавить камеру...</option>
                  {unassignedCameras.map((camera) => (
                    <option key={camera.camera_id} value={camera.camera_id}>{camera.name}</option>
                  ))}
                </select>
                <button className="btn" style={{ fontSize: 12, padding: "6px 12px" }} onClick={handleAssignCamera} disabled={!addCamId}>
                  Добавить
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default GroupsPage;
