import { useEffect, useMemo, useState } from "react";
import { createCamera, getCameras, updateCamera, API_URL } from "../lib/api";
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

async function fetchPresets(token: string, camId: number): Promise<Preset[]> {
  const res = await fetch(`${API_URL}/admin/cameras/${camId}/presets`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) return [];
  return res.json();
}

async function fetchRoiZones(token: string, camId: number): Promise<RoiZone[]> {
  const res = await fetch(`${API_URL}/admin/cameras/${camId}/roi-zones`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) return [];
  return res.json();
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
      const res = await getCameras(token);
      setCameras(res);
      if (res.length && selectedId === null) setSelectedId(res[0].camera_id);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить камеры.");
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
    cameras.forEach((c) => {
      const key = c.location?.trim() || "Без локации";
      if (!map[key]) map[key] = [];
      map[key].push(c);
    });
    Object.values(map).forEach((arr) => arr.sort((a, b) => a.name.localeCompare(b.name)));
    return map;
  }, [cameras]);

  const selected = cameras.find((c) => c.camera_id === selectedId) || null;

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
    } catch (e: any) {
      alert(e?.message || "Не удалось создать камеру.");
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
    } catch (e: any) {
      alert(e?.message || "Не удалось обновить камеру");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h2 className="title">Камеры</h2>
          <div className="muted">Настройка параметров камер.</div>
        </div>
        <button className="btn secondary" onClick={load}>
          Обновить
        </button>
      </div>
      {error && <div className="danger">{error}</div>}

      <div className="grid" style={{ gridTemplateColumns: "260px 1fr", gap: 16 }}>
        <div className="card" style={{ maxHeight: "70vh", overflowY: "auto" }}>
          <h3 style={{ marginTop: 0 }}>Дерево камер</h3>
          {loading ? (
            <div className="muted">Загрузка...</div>
          ) : (
            Object.keys(grouped)
              .sort()
              .map((loc) => (
                <div key={loc} className="stack" style={{ marginBottom: 10 }}>
                  <div className="label" style={{ fontWeight: 600 }}>{loc}</div>
                  {grouped[loc].map((c) => (
                    <div
                      key={c.camera_id}
                      className={"tree-item" + (c.camera_id === selectedId ? " active" : "")}
                      style={{ padding: "6px 8px", borderRadius: 6, cursor: "pointer", background: c.camera_id === selectedId ? "#1f2a3a" : "transparent" }}
                      onClick={() => setSelectedId(c.camera_id)}
                    >
                      {c.name}
                    </div>
                  ))}
                </div>
              ))
          )}
        </div>

        <div className="stack" style={{ gap: 12 }}>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Добавить камеру</h3>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 8 }}>
              <label className="field">
                <span className="label">Название</span>
                <input className="input" value={createForm.name} onChange={(e) => setCreateForm((p) => ({ ...p, name: e.target.value }))} />
              </label>
              <label className="field">
                <span className="label">Локация</span>
                <input className="input" value={createForm.location} onChange={(e) => setCreateForm((p) => ({ ...p, location: e.target.value }))} />
              </label>
              <label className="field">
                <span className="label">IP</span>
                <input className="input" value={createForm.ip_address} onChange={(e) => setCreateForm((p) => ({ ...p, ip_address: e.target.value }))} />
              </label>
              <label className="field">
                <span className="label">Stream URL</span>
                <input className="input" value={createForm.stream_url} onChange={(e) => setCreateForm((p) => ({ ...p, stream_url: e.target.value }))} />
              </label>
              <label className="field">
                <span className="label">Детекция</span>
                <select
                  className="input"
                  value={createForm.detection_enabled ? "on" : "off"}
                  onChange={(e) => setCreateForm((p) => ({ ...p, detection_enabled: e.target.value === "on" }))}
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
                  onChange={(e) => setCreateForm((p) => ({ ...p, recording_mode: e.target.value }))}
                >
                  <option value="continuous">Постоянная</option>
                  <option value="event">Событийная</option>
                </select>
              </label>
            </div>
            <button className="btn" style={{ marginTop: 10 }} onClick={submitCreate} disabled={!createForm.name}>
              Создать
            </button>
          </div>

          <div className="card">
            <h3 style={{ marginTop: 0 }}>Параметры камеры</h3>
            {selected ? (
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 8 }}>
                <label className="field">
                  <span className="label">Название</span>
                  <input className="input" value={selected.name} onChange={(e) => updateSelected({ name: e.target.value })} />
                </label>
                <label className="field">
                  <span className="label">Локация</span>
                  <input className="input" value={selected.location || ""} onChange={(e) => updateSelected({ location: e.target.value })} />
                </label>
                <label className="field">
                  <span className="label">IP</span>
                  <input className="input" value={selected.ip_address || ""} onChange={(e) => updateSelected({ ip_address: e.target.value })} />
                </label>
                <label className="field">
                  <span className="label">Stream URL</span>
                  <input className="input" value={selected.stream_url || ""} onChange={(e) => updateSelected({ stream_url: e.target.value })} />
                </label>
                <label className="field">
                  <span className="label">Детекция</span>
                  <select
                    className="input"
                    value={selected.detection_enabled ? "on" : "off"}
                    onChange={(e) => updateSelected({ detection_enabled: e.target.value === "on" })}
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
                    onChange={(e) => updateSelected({ recording_mode: e.target.value as "continuous" | "event" })}
                  >
                    <option value="continuous">Постоянная</option>
                    <option value="event">Событийная</option>
                  </select>
                </label>
              </div>
            ) : (
              <div className="muted">Выберите камеру слева.</div>
            )}
          </div>

          {selected && (
            <div className="card">
              <h3 style={{ marginTop: 0 }}>ONVIF Трекинг</h3>
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 8 }}>
                <label className="field">
                  <span className="label">Трекинг</span>
                  <select
                    className="input"
                    value={selected.tracking_enabled ? "on" : "off"}
                    onChange={(e) => updateSelected({ tracking_enabled: e.target.value === "on" } as any)}
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
                    onChange={(e) => updateSelected({ tracking_mode: e.target.value } as any)}
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
                    onChange={(e) =>
                      updateSelected({ tracking_target_person_id: e.target.value ? Number(e.target.value) : null } as any)
                    }
                    placeholder="любой"
                  />
                </label>
              </div>
            </div>
          )}

          {selected && (
            <div className="card">
              <h3 style={{ marginTop: 0 }}>Пресеты PTZ</h3>
              <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                <input
                  className="input"
                  style={{ flex: 1 }}
                  value={newPresetName}
                  onChange={(e) => setNewPresetName(e.target.value)}
                  placeholder="Название пресета"
                />
                <button className="btn" onClick={addPreset} disabled={!newPresetName.trim()}>
                  Добавить
                </button>
              </div>
              {presets.length === 0 ? (
                <div className="muted">Нет пресетов.</div>
              ) : (
                <div className="stack" style={{ gap: 4 }}>
                  {presets.map((p) => (
                    <div key={p.camera_preset_id} className="row" style={{ justifyContent: "space-between" }}>
                      <span>{p.name} (dwell: {p.dwell_seconds}с)</span>
                      <button className="btn secondary" style={{ fontSize: 11, padding: "3px 8px" }} onClick={() => deletePreset(p.camera_preset_id)}>
                        Удалить
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {selected && (
            <div className="card">
              <h3 style={{ marginTop: 0 }}>ROI Зоны</h3>
              <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                <input
                  className="input"
                  style={{ flex: 1 }}
                  value={newRoiName}
                  onChange={(e) => setNewRoiName(e.target.value)}
                  placeholder="Название зоны"
                />
                <button className="btn" onClick={addRoi} disabled={!newRoiName.trim()}>
                  Добавить
                </button>
              </div>
              {roiZones.length === 0 ? (
                <div className="muted">Нет зон.</div>
              ) : (
                <div className="stack" style={{ gap: 4 }}>
                  {roiZones.map((z) => (
                    <div key={z.roi_zone_id} className="row" style={{ justifyContent: "space-between" }}>
                      <span>
                        {z.name}{" "}
                        <span className="pill" style={{ fontSize: 11 }}>{z.zone_type}</span>
                      </span>
                      <button className="btn secondary" style={{ fontSize: 11, padding: "3px 8px" }} onClick={() => deleteRoi(z.roi_zone_id)}>
                        Удалить
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CamerasPage;
