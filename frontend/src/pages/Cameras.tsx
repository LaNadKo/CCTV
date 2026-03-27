import { useEffect, useMemo, useState } from "react";
import { API_URL, createCamera, deleteCamera, getCameras, updateCamera } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Camera = {
  camera_id: number;
  name: string;
  location?: string;
  permission: string;
  ip_address?: string;
  stream_url?: string;
  detection_enabled: boolean;
  recording_mode: string;
  tracking_enabled?: boolean;
  tracking_mode?: string;
  tracking_target_person_id?: number | null;
  group_id?: number | null;
};

type Preset = {
  camera_preset_id: number;
  camera_id: number;
  name: string;
  preset_token?: string;
  order_index: number;
  dwell_seconds: number;
};

type RoiZone = {
  roi_zone_id: number;
  camera_id: number;
  name: string;
  zone_type: string;
  polygon_points?: string;
};

async function fetchPresets(token: string, cameraId: number): Promise<Preset[]> {
  const response = await fetch(`${API_URL}/admin/cameras/${cameraId}/presets`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) return [];
  return response.json();
}

async function fetchRoiZones(token: string, cameraId: number): Promise<RoiZone[]> {
  const response = await fetch(`${API_URL}/admin/cameras/${cameraId}/roi-zones`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) return [];
  return response.json();
}

const CamerasPage: React.FC = () => {
  const { token } = useAuth();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [roiZones, setRoiZones] = useState<RoiZone[]>([]);
  const [newPresetName, setNewPresetName] = useState("");
  const [newRoiName, setNewRoiName] = useState("");
  const [createForm, setCreateForm] = useState({
    name: "",
    location: "",
    ip_address: "",
    stream_url: "",
    status_id: "",
    detection_enabled: true,
    recording_mode: "continuous",
  });

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const response = await getCameras(token);
      setCameras(response);
      if (response.length && selectedId === null) {
        setSelectedId(response[0].camera_id);
      }
    } catch (event: any) {
      setError(event?.message || "Не удалось загрузить камеры.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  useEffect(() => {
    if (!token || selectedId === null) return;
    fetchPresets(token, selectedId).then(setPresets);
    fetchRoiZones(token, selectedId).then(setRoiZones);
  }, [token, selectedId]);

  const addPreset = async () => {
    if (!token || !selectedId || !newPresetName.trim()) return;
    await fetch(`${API_URL}/admin/cameras/${selectedId}/presets`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ name: newPresetName.trim() }),
    });
    setNewPresetName("");
    setPresets(await fetchPresets(token, selectedId));
  };

  const deletePreset = async (id: number) => {
    if (!token || !selectedId) return;
    await fetch(`${API_URL}/admin/cameras/${selectedId}/presets/${id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    setPresets(await fetchPresets(token, selectedId));
  };

  const addRoi = async () => {
    if (!token || !selectedId || !newRoiName.trim()) return;
    await fetch(`${API_URL}/admin/cameras/${selectedId}/roi-zones`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ name: newRoiName.trim(), zone_type: "include" }),
    });
    setNewRoiName("");
    setRoiZones(await fetchRoiZones(token, selectedId));
  };

  const deleteRoi = async (id: number) => {
    if (!token || !selectedId) return;
    await fetch(`${API_URL}/admin/cameras/${selectedId}/roi-zones/${id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    setRoiZones(await fetchRoiZones(token, selectedId));
  };

  const grouped = useMemo(() => {
    const map: Record<string, Camera[]> = {};
    cameras.forEach((camera) => {
      const key = camera.location?.trim() || "Без локации";
      if (!map[key]) map[key] = [];
      map[key].push(camera);
    });
    Object.values(map).forEach((items) => items.sort((left, right) => left.name.localeCompare(right.name)));
    return map;
  }, [cameras]);

  const selected = cameras.find((camera) => camera.camera_id === selectedId) || null;

  const submitCreate = async () => {
    if (!token) return;
    try {
      await createCamera(token, {
        name: createForm.name,
        location: createForm.location || undefined,
        ip_address: createForm.ip_address || undefined,
        stream_url: createForm.stream_url || undefined,
        status_id: createForm.status_id ? Number(createForm.status_id) : undefined,
        detection_enabled: createForm.detection_enabled,
        recording_mode: createForm.recording_mode as "continuous" | "event",
      });
      setCreateForm({
        name: "",
        location: "",
        ip_address: "",
        stream_url: "",
        status_id: "",
        detection_enabled: true,
        recording_mode: "continuous",
      });
      await load();
    } catch (event: any) {
      alert(event?.message || "Не удалось создать камеру.");
    }
  };

  const updateSelected = async (patch: Partial<Camera>) => {
    if (!token || !selected) return;
    try {
      await updateCamera(token, selected.camera_id, {
        name: patch.name,
        location: patch.location,
        ip_address: patch.ip_address,
        stream_url: patch.stream_url,
        detection_enabled: patch.detection_enabled,
        recording_mode: patch.recording_mode as "continuous" | "event" | undefined,
      });
      await load();
    } catch (event: any) {
      alert(event?.message || "Не удалось обновить камеру");
    }
  };

  const removeSelected = async () => {
    if (!token || !selected) return;
    if (!window.confirm(`Удалить камеру "${selected.name}"?`)) return;
    try {
      await deleteCamera(token, selected.camera_id);
      setSelectedId(null);
      await load();
    } catch (event: any) {
      alert(event?.message || "Не удалось удалить камеру");
    }
  };

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Administration</div>
          <h2 className="title">Камеры</h2>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Всего камер</div>
          <div className="summary-card__value">{cameras.length}</div>
          <div className="summary-card__hint">Все активные камеры backend без удалённых сущностей.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Локаций</div>
          <div className="summary-card__value">{Object.keys(grouped).length}</div>
          <div className="summary-card__hint">Группировка списка по реальным местам установки камер.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Выбрана</div>
          <div className="summary-card__value">{selected ? selected.name : "—"}</div>
          <div className="summary-card__hint">Карточка справа меняется без переключения на отдельные страницы.</div>
        </div>
      </section>

      {error && <div className="danger">{error}</div>}

      <section className="admin-two-column">
        <div className="stack-grid">
          <div className="panel-card stack">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Добавить камеру</h3>
                <div className="panel-card__lead">Минимальный набор для новой камеры и базовых режимов записи/детекции.</div>
              </div>
            </div>

            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))" }}>
              <label className="field">
                <span className="label">Название</span>
                <input className="input" value={createForm.name} onChange={(event) => setCreateForm((prev) => ({ ...prev, name: event.target.value }))} />
              </label>
              <label className="field">
                <span className="label">Локация</span>
                <input className="input" value={createForm.location} onChange={(event) => setCreateForm((prev) => ({ ...prev, location: event.target.value }))} />
              </label>
              <label className="field">
                <span className="label">IP</span>
                <input className="input" value={createForm.ip_address} onChange={(event) => setCreateForm((prev) => ({ ...prev, ip_address: event.target.value }))} />
              </label>
              <label className="field">
                <span className="label">Stream URL</span>
                <input className="input" value={createForm.stream_url} onChange={(event) => setCreateForm((prev) => ({ ...prev, stream_url: event.target.value }))} />
              </label>
              <label className="field">
                <span className="label">Детекция</span>
                <select
                  className="input"
                  value={createForm.detection_enabled ? "on" : "off"}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, detection_enabled: event.target.value === "on" }))}
                >
                  <option value="on">Включена</option>
                  <option value="off">Выключена</option>
                </select>
              </label>
              <label className="field">
                <span className="label">Запись</span>
                <select
                  className="input"
                  value={createForm.recording_mode}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, recording_mode: event.target.value }))}
                >
                  <option value="continuous">Постоянная</option>
                  <option value="event">Событийная</option>
                </select>
              </label>
            </div>

            <button className="btn" onClick={submitCreate} disabled={!createForm.name}>
              Создать
            </button>
          </div>

          <div className="panel-card">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Список камер</h3>
                <div className="panel-card__lead">Камеры сгруппированы по локациям и быстро открываются для редактирования.</div>
              </div>
            </div>

            {loading ? (
              <div className="muted">Загрузка...</div>
            ) : (
              Object.keys(grouped)
                .sort()
                .map((location) => (
                  <div key={location} className="stack" style={{ marginBottom: 14 }}>
                    <div className="label" style={{ fontWeight: 700 }}>
                      {location}
                    </div>
                    <div className="list-shell">
                      {grouped[location].map((camera) => (
                        <button
                          key={camera.camera_id}
                          className={`list-item${camera.camera_id === selectedId ? " active" : ""}`}
                          onClick={() => setSelectedId(camera.camera_id)}
                          type="button"
                        >
                          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                            <div className="list-item__title">{camera.name}</div>
                            <span className="pill">{camera.recording_mode === "continuous" ? "24/7" : "event"}</span>
                          </div>
                          <div className="list-item__meta">
                            {camera.ip_address || "IP не указан"} · {camera.detection_enabled ? "детекция включена" : "детекция выключена"}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                ))
            )}
          </div>
        </div>

        <div className="stack-grid">
          <div className="panel-card stack">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Параметры камеры</h3>
                <div className="panel-card__lead">
                  {selected ? "Все базовые настройки собраны в одном месте." : "Выберите камеру слева, чтобы открыть её карточку."}
                </div>
              </div>
              {selected && (
                <button className="btn secondary" onClick={removeSelected}>
                  Удалить камеру
                </button>
              )}
            </div>

            {selected ? (
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))" }}>
                <label className="field">
                  <span className="label">Название</span>
                  <input className="input" value={selected.name} onChange={(event) => updateSelected({ name: event.target.value })} />
                </label>
                <label className="field">
                  <span className="label">Локация</span>
                  <input className="input" value={selected.location || ""} onChange={(event) => updateSelected({ location: event.target.value })} />
                </label>
                <label className="field">
                  <span className="label">IP</span>
                  <input className="input" value={selected.ip_address || ""} onChange={(event) => updateSelected({ ip_address: event.target.value })} />
                </label>
                <label className="field">
                  <span className="label">Stream URL</span>
                  <input className="input" value={selected.stream_url || ""} onChange={(event) => updateSelected({ stream_url: event.target.value })} />
                </label>
                <label className="field">
                  <span className="label">Детекция</span>
                  <select
                    className="input"
                    value={selected.detection_enabled ? "on" : "off"}
                    onChange={(event) => updateSelected({ detection_enabled: event.target.value === "on" })}
                  >
                    <option value="on">Включена</option>
                    <option value="off">Выключена</option>
                  </select>
                </label>
                <label className="field">
                  <span className="label">Запись</span>
                  <select
                    className="input"
                    value={selected.recording_mode}
                    onChange={(event) => updateSelected({ recording_mode: event.target.value as "continuous" | "event" })}
                  >
                    <option value="continuous">Постоянная</option>
                    <option value="event">Событийная</option>
                  </select>
                </label>
              </div>
            ) : (
              <div className="muted">Камера пока не выбрана.</div>
            )}
          </div>

          {selected && (
            <div className="panel-card stack">
              <div className="panel-card__header">
                <div>
                  <h3 className="panel-card__title">ONVIF трекинг</h3>
                  <div className="panel-card__lead">Подготовка параметров трекинга и режима ведения цели.</div>
                </div>
              </div>
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
                <label className="field">
                  <span className="label">Трекинг</span>
                  <select
                    className="input"
                    value={selected.tracking_enabled ? "on" : "off"}
                    onChange={(event) => updateSelected({ tracking_enabled: event.target.value === "on" } as any)}
                  >
                    <option value="off">Выключен</option>
                    <option value="on">Включён</option>
                  </select>
                </label>
                <label className="field">
                  <span className="label">Режим</span>
                  <select
                    className="input"
                    value={selected.tracking_mode || "off"}
                    onChange={(event) => updateSelected({ tracking_mode: event.target.value } as any)}
                  >
                    <option value="off">Выключен</option>
                    <option value="auto">Авто</option>
                    <option value="patrol">Патруль</option>
                  </select>
                </label>
                <label className="field">
                  <span className="label">Цель (person_id)</span>
                  <input
                    className="input"
                    type="number"
                    value={selected.tracking_target_person_id ?? ""}
                    onChange={(event) =>
                      updateSelected({ tracking_target_person_id: event.target.value ? Number(event.target.value) : null } as any)
                    }
                    placeholder="любой"
                  />
                </label>
              </div>
            </div>
          )}

          {selected && (
            <div className="panel-card stack">
              <div className="panel-card__header">
                <div>
                  <h3 className="panel-card__title">PTZ пресеты</h3>
                  <div className="panel-card__lead">Быстрое управление точками обзора для ONVIF/PTZ-камер.</div>
                </div>
              </div>
              <div className="page-actions">
                <input
                  className="input"
                  style={{ flex: 1, minWidth: 220 }}
                  value={newPresetName}
                  onChange={(event) => setNewPresetName(event.target.value)}
                  placeholder="Название пресета"
                />
                <button className="btn" onClick={addPreset} disabled={!newPresetName.trim()}>
                  Добавить
                </button>
              </div>
              {presets.length === 0 ? (
                <div className="muted">Пресетов пока нет.</div>
              ) : (
                <div className="list-shell">
                  {presets.map((preset) => (
                    <div key={preset.camera_preset_id} className="list-item" style={{ cursor: "default" }}>
                      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                        <div className="list-item__title">{preset.name}</div>
                        <button className="btn secondary" onClick={() => deletePreset(preset.camera_preset_id)}>
                          Удалить
                        </button>
                      </div>
                      <div className="list-item__meta">dwell: {preset.dwell_seconds}с</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {selected && (
            <div className="panel-card stack">
              <div className="panel-card__header">
                <div>
                  <h3 className="panel-card__title">ROI зоны</h3>
                  <div className="panel-card__lead">Области интереса для включения и исключения зон анализа.</div>
                </div>
              </div>
              <div className="page-actions">
                <input
                  className="input"
                  style={{ flex: 1, minWidth: 220 }}
                  value={newRoiName}
                  onChange={(event) => setNewRoiName(event.target.value)}
                  placeholder="Название зоны"
                />
                <button className="btn" onClick={addRoi} disabled={!newRoiName.trim()}>
                  Добавить
                </button>
              </div>
              {roiZones.length === 0 ? (
                <div className="muted">Зон пока нет.</div>
              ) : (
                <div className="list-shell">
                  {roiZones.map((zone) => (
                    <div key={zone.roi_zone_id} className="list-item" style={{ cursor: "default" }}>
                      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                        <div className="list-item__title">{zone.name}</div>
                        <button className="btn secondary" onClick={() => deleteRoi(zone.roi_zone_id)}>
                          Удалить
                        </button>
                      </div>
                      <div className="list-item__meta">Тип зоны: {zone.zone_type}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default CamerasPage;
