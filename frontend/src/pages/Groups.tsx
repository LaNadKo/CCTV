import { useEffect, useMemo, useState } from "react";
import {
  assignCameraToGroup,
  createGroup,
  deleteGroup,
  getCameras,
  getGroup,
  listGroups,
  unassignCameraFromGroup,
  updateGroup,
  type GroupDetail,
  type GroupOut,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Camera = { camera_id: number; name: string; location?: string; group_id?: number | null };

const GroupsPage: React.FC = () => {
  const { token, user } = useAuth();
  const isAdmin = user?.role_id === 1;
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
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
      const [groupItems, cameraItems] = await Promise.all([listGroups(token), getCameras(token)]);
      setGroups(groupItems);
      setAllCameras(cameraItems);
    } catch (event: any) {
      setError(event?.message || "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const openGroup = async (groupId: number) => {
    if (!token) return;
    try {
      const detail = await getGroup(token, groupId);
      setSelectedGroup(detail);
      setEditName(detail.name);
      setEditDesc(detail.description || "");
    } catch (event: any) {
      alert(event?.message || "Ошибка");
    }
  };

  const handleCreate = async () => {
    if (!token || !name.trim()) return;
    try {
      await createGroup(token, name.trim(), desc.trim() || undefined);
      setName("");
      setDesc("");
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка");
    }
  };

  const handleDelete = async (id: number) => {
    if (!token || !window.confirm("Удалить группу? Камеры останутся, но будут без группы.")) return;
    try {
      await deleteGroup(token, id);
      if (selectedGroup?.group_id === id) {
        setSelectedGroup(null);
        setEditName("");
        setEditDesc("");
      }
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка удаления");
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
    } catch (event: any) {
      alert(event?.message || "Ошибка");
    }
  };

  const handleAssignCamera = async () => {
    if (!token || !selectedGroup || !addCamId) return;
    try {
      await assignCameraToGroup(token, selectedGroup.group_id, Number(addCamId));
      setAddCamId("");
      await openGroup(selectedGroup.group_id);
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка");
    }
  };

  const handleUnassignCamera = async (cameraId: number) => {
    if (!token || !selectedGroup) return;
    try {
      await unassignCameraFromGroup(token, selectedGroup.group_id, cameraId);
      await openGroup(selectedGroup.group_id);
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка");
    }
  };

  const unassignedCameras = allCameras.filter(
    (camera) => !selectedGroup?.cameras.some((groupCamera) => groupCamera.camera_id === camera.camera_id)
  );

  const stats = useMemo(
    () => ({
      groups: groups.length,
      cameras: groups.reduce((sum, group) => sum + group.camera_count, 0),
      selected: selectedGroup?.cameras.length || 0,
    }),
    [groups, selectedGroup]
  );

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Structure</div>
          <h2 className="title">Группы</h2>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Всего групп</div>
          <div className="summary-card__value">{stats.groups}</div>
          <div className="summary-card__hint">Логические наборы камер для фильтрации live и отчётности.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Камер в группах</div>
          <div className="summary-card__value">{stats.cameras}</div>
          <div className="summary-card__hint">Суммарное количество назначений по всем текущим группам.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">В выбранной группе</div>
          <div className="summary-card__value">{stats.selected || "—"}</div>
          <div className="summary-card__hint">Для быстрого контроля состава группы без ручного просмотра списка.</div>
        </div>
      </section>

      {error && <div className="danger">{error}</div>}

      <section className="admin-two-column">
        <div className="stack-grid">
          {isAdmin && (
            <div className="panel-card stack">
              <div className="panel-card__header">
                <div>
                  <h3 className="panel-card__title">Создать группу</h3>
                  <div className="panel-card__lead">Минимальный набор: имя и при необходимости краткое описание.</div>
                </div>
              </div>
              <label className="field">
                <span className="label">Название</span>
                <input className="input" value={name} onChange={(event) => setName(event.target.value)} placeholder="Офис" />
              </label>
              <label className="field">
                <span className="label">Описание</span>
                <input className="input" value={desc} onChange={(event) => setDesc(event.target.value)} placeholder="Камеры офиса" />
              </label>
              <button className="btn" onClick={handleCreate} disabled={!name.trim()}>
                Создать
              </button>
            </div>
          )}

          <div className="panel-card">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Список групп</h3>
                <div className="panel-card__lead">Выберите группу, чтобы открыть её состав и редактирование.</div>
              </div>
              <span className="pill">{groups.length}</span>
            </div>

            {loading ? (
              <div className="muted">Загрузка...</div>
            ) : groups.length === 0 ? (
              <div className="muted">Групп пока нет.</div>
            ) : (
              <div className="list-shell">
                {groups.map((group) => (
                  <button
                    key={group.group_id}
                    className={`list-item${selectedGroup?.group_id === group.group_id ? " active" : ""}`}
                    onClick={() => openGroup(group.group_id)}
                    type="button"
                  >
                    <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                      <div className="list-item__title">{group.name}</div>
                      <span className="pill">{group.camera_count} камер</span>
                    </div>
                    <div className="list-item__meta">{group.description || "Описание не указано"}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="panel-card stack">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">{selectedGroup ? selectedGroup.name : "Карточка группы"}</h3>
              <div className="panel-card__lead">
                {selectedGroup
                  ? "Редактирование параметров группы и управление назначенными камерами."
                  : "Выберите группу слева, чтобы открыть её карточку."}
              </div>
            </div>
            {isAdmin && selectedGroup && (
              <button className="btn secondary" onClick={() => handleDelete(selectedGroup.group_id)}>
                Удалить
              </button>
            )}
          </div>

          {!selectedGroup ? (
            <div className="muted">Группа пока не выбрана.</div>
          ) : (
            <>
              {isAdmin ? (
                <>
                  <label className="field">
                    <span className="label">Название</span>
                    <input className="input" value={editName} onChange={(event) => setEditName(event.target.value)} />
                  </label>
                  <label className="field">
                    <span className="label">Описание</span>
                    <input className="input" value={editDesc} onChange={(event) => setEditDesc(event.target.value)} />
                  </label>
                  <div className="page-actions">
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
                </>
              ) : (
                <div className="muted">{selectedGroup.description || "Описание не указано"}</div>
              )}

              <div className="panel-card" style={{ padding: 16 }}>
                <div className="panel-card__header" style={{ marginBottom: 10 }}>
                  <div>
                    <h3 className="panel-card__title">Камеры в группе</h3>
                    <div className="panel-card__lead">Состав текущей группы с быстрым снятием назначения.</div>
                  </div>
                  <span className="pill">{selectedGroup.cameras.length}</span>
                </div>

                {selectedGroup.cameras.length === 0 ? (
                  <div className="muted">Камер в группе пока нет.</div>
                ) : (
                  <div className="list-shell">
                    {selectedGroup.cameras.map((camera) => (
                      <div key={camera.camera_id} className="list-item" style={{ cursor: "default" }}>
                        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                          <div className="list-item__title">{camera.name}</div>
                          {isAdmin && (
                            <button className="btn secondary" onClick={() => handleUnassignCamera(camera.camera_id)}>
                              Убрать
                            </button>
                          )}
                        </div>
                        <div className="list-item__meta">{camera.location || "Локация не указана"}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {isAdmin && unassignedCameras.length > 0 && (
                <div className="panel-card" style={{ padding: 16 }}>
                  <div className="panel-card__header" style={{ marginBottom: 10 }}>
                    <div>
                      <h3 className="panel-card__title">Добавить камеру</h3>
                      <div className="panel-card__lead">Свяжите свободную камеру с выбранной группой.</div>
                    </div>
                  </div>
                  <div className="page-actions" style={{ alignItems: "flex-end" }}>
                    <label className="field" style={{ flex: 1, minWidth: 220 }}>
                      <span className="label">Свободная камера</span>
                      <select className="input" value={addCamId} onChange={(event) => setAddCamId(event.target.value)}>
                        <option value="">Выберите камеру...</option>
                        {unassignedCameras.map((camera) => (
                          <option key={camera.camera_id} value={camera.camera_id}>
                            {camera.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button className="btn" onClick={handleAssignCamera} disabled={!addCamId}>
                      Добавить
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
};

export default GroupsPage;
