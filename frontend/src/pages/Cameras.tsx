import { useEffect, useMemo, useState } from "react";
import {
  API_URL,
  type CameraDetail,
  type CameraEndpointInfo,
  type CameraProbeResult,
  type CameraSummary,
  createCamera,
  deleteCamera,
  getAdminCamera,
  getCameras,
  probeCameraDiscovery,
  refreshOnvifCamera,
  scanCameraDiscovery,
  updateCamera,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

type EditableEndpoint = {
  endpoint_kind: "onvif" | "rtsp" | "http";
  endpoint_url: string;
  username: string;
  password_secret: string;
  has_password?: boolean;
  is_primary: boolean;
};

type DetailForm = {
  name: string;
  location: string;
  ip_address: string;
  stream_url: string;
  detection_enabled: boolean;
  recording_mode: "continuous" | "event";
  tracking_enabled: boolean;
  tracking_mode: "off" | "auto" | "patrol";
  tracking_target_person_id: string;
  connection_kind: "manual" | "onvif" | "rtsp" | "http";
  supports_ptz: boolean;
  onvif_profile_token: string;
  endpoints: EditableEndpoint[];
};

type ManualCreateForm = {
  name: string;
  location: string;
  ip_address: string;
  stream_url: string;
  username: string;
  password: string;
  detection_enabled: boolean;
  recording_mode: "continuous" | "event";
};

const EMPTY_MANUAL_FORM: ManualCreateForm = {
  name: "",
  location: "",
  ip_address: "",
  stream_url: "",
  username: "",
  password: "",
  detection_enabled: true,
  recording_mode: "continuous",
};

function toEditableEndpoints(endpoints: CameraEndpointInfo[]): EditableEndpoint[] {
  return endpoints.map((endpoint) => ({
    endpoint_kind: endpoint.endpoint_kind,
    endpoint_url: endpoint.endpoint_url,
    username: endpoint.username || "",
    password_secret: "",
    has_password: endpoint.has_password,
    is_primary: Boolean(endpoint.is_primary),
  }));
}

function toDetailForm(detail: CameraDetail): DetailForm {
  return {
    name: detail.name,
    location: detail.location || "",
    ip_address: detail.ip_address || "",
    stream_url: detail.stream_url || "",
    detection_enabled: detail.detection_enabled,
    recording_mode: (detail.recording_mode as "continuous" | "event") || "continuous",
    tracking_enabled: Boolean(detail.tracking_enabled),
    tracking_mode: (detail.tracking_mode as "off" | "auto" | "patrol") || "off",
    tracking_target_person_id: detail.tracking_target_person_id ? String(detail.tracking_target_person_id) : "",
    connection_kind: (detail.connection_kind as "manual" | "onvif" | "rtsp" | "http") || "manual",
    supports_ptz: Boolean(detail.supports_ptz),
    onvif_profile_token: detail.onvif_profile_token || "",
    endpoints: toEditableEndpoints(detail.endpoints || []),
  };
}

function buildManualEndpoints(form: ManualCreateForm): EditableEndpoint[] {
  const url = form.stream_url.trim();
  if (!url) return [];
  const endpoint_kind = url.toLowerCase().startsWith("rtsp://") ? "rtsp" : "http";
  return [
    {
      endpoint_kind,
      endpoint_url: url,
      username: form.username.trim(),
      password_secret: form.password,
      is_primary: true,
    },
  ];
}

const CamerasPage: React.FC = () => {
  const { token } = useAuth();
  const [cameras, setCameras] = useState<CameraSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<CameraDetail | null>(null);
  const [detailForm, setDetailForm] = useState<DetailForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualCreate, setManualCreate] = useState<ManualCreateForm>(EMPTY_MANUAL_FORM);
  const [discoveryBusy, setDiscoveryBusy] = useState(false);
  const [scanResults, setScanResults] = useState<any[]>([]);
  const [probeForm, setProbeForm] = useState({
    host: "",
    username: "",
    password: "",
    port: "",
    use_https: false,
    timeout: 5,
    location: "",
    name: "",
  });
  const [probeResult, setProbeResult] = useState<CameraProbeResult | null>(null);
  const [newRoiName, setNewRoiName] = useState("");

  const grouped = useMemo(() => {
    const map: Record<string, CameraSummary[]> = {};
    for (const camera of cameras) {
      const key = camera.location?.trim() || "Без локации";
      if (!map[key]) map[key] = [];
      map[key].push(camera);
    }
    for (const items of Object.values(map)) items.sort((a, b) => a.name.localeCompare(b.name));
    return map;
  }, [cameras]);

  const loadList = async (preserveSelection = true) => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const items = await getCameras(token);
      setCameras(items);
      if (!preserveSelection || selectedId === null || !items.some((camera) => camera.camera_id === selectedId)) {
        setSelectedId(items[0]?.camera_id ?? null);
      }
    } catch (event: any) {
      setError(event?.message || "Не удалось загрузить камеры.");
    } finally {
      setLoading(false);
    }
  };

  const loadDetail = async (cameraId: number | null) => {
    if (!token || cameraId === null) {
      setSelected(null);
      setDetailForm(null);
      return;
    }
    setDetailLoading(true);
    try {
      const detail = await getAdminCamera(token, cameraId);
      setSelected(detail);
      setDetailForm(toDetailForm(detail));
    } catch (event: any) {
      setError(event?.message || "Не удалось загрузить параметры камеры.");
      setSelected(null);
      setDetailForm(null);
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    loadList(false);
  }, [token]);

  useEffect(() => {
    loadDetail(selectedId);
  }, [selectedId, token]);

  const saveSelected = async () => {
    if (!token || !selectedId || !detailForm) return;
    setBusy(true);
    try {
      await updateCamera(token, selectedId, {
        name: detailForm.name,
        location: detailForm.location || undefined,
        ip_address: detailForm.ip_address || undefined,
        stream_url: detailForm.stream_url || undefined,
        detection_enabled: detailForm.detection_enabled,
        recording_mode: detailForm.recording_mode,
        tracking_enabled: detailForm.tracking_enabled,
        tracking_mode: detailForm.tracking_mode,
        tracking_target_person_id: detailForm.tracking_target_person_id ? Number(detailForm.tracking_target_person_id) : null,
        connection_kind: detailForm.connection_kind,
        supports_ptz: detailForm.supports_ptz,
        onvif_profile_token: detailForm.onvif_profile_token || null,
        endpoints: detailForm.endpoints
          .filter((endpoint) => endpoint.endpoint_url.trim())
          .map((endpoint) => ({
            endpoint_kind: endpoint.endpoint_kind,
            endpoint_url: endpoint.endpoint_url.trim(),
            username: endpoint.username.trim() || undefined,
            password_secret: endpoint.password_secret ? endpoint.password_secret : undefined,
            is_primary: endpoint.is_primary,
          })),
      });
      await loadList();
      await loadDetail(selectedId);
    } catch (event: any) {
      alert(event?.message || "Не удалось сохранить камеру.");
    } finally {
      setBusy(false);
    }
  };

  const removeSelected = async () => {
    if (!token || !selected) return;
    if (!window.confirm(`Удалить камеру «${selected.name}»?`)) return;
    setBusy(true);
    try {
      await deleteCamera(token, selected.camera_id);
      setSelectedId(null);
      await loadList(false);
    } catch (event: any) {
      alert(event?.message || "Не удалось удалить камеру.");
    } finally {
      setBusy(false);
    }
  };

  const scanNetwork = async () => {
    if (!token) return;
    setDiscoveryBusy(true);
    try {
      const items = await scanCameraDiscovery(token, { timeout: 4 });
      setScanResults(items);
    } catch (event: any) {
      alert(event?.message || "Не удалось выполнить ONVIF discovery.");
    } finally {
      setDiscoveryBusy(false);
    }
  };

  const runProbe = async () => {
    if (!token || !probeForm.host.trim()) return;
    setDiscoveryBusy(true);
    try {
      const result = await probeCameraDiscovery(token, {
        host: probeForm.host.trim(),
        username: probeForm.username.trim() || undefined,
        password: probeForm.password || undefined,
        port: probeForm.port ? Number(probeForm.port) : undefined,
        use_https: probeForm.use_https,
        timeout: probeForm.timeout,
      });
      setProbeResult(result);
      if (!probeForm.name.trim() && result.name) {
        setProbeForm((prev) => ({ ...prev, name: result.name || prev.name }));
      }
    } catch (event: any) {
      alert(event?.message || "Не удалось определить параметры камеры.");
    } finally {
      setDiscoveryBusy(false);
    }
  };

  const createFromProbe = async () => {
    if (!token || !probeResult) return;
    setBusy(true);
    try {
      await createCamera(token, {
        name: probeForm.name.trim() || probeResult.name || probeForm.host.trim(),
        location: probeForm.location.trim() || undefined,
        ip_address: probeResult.ip_address || probeForm.host.trim(),
        stream_url: probeResult.endpoints.find((endpoint) => endpoint.endpoint_kind === "rtsp")?.endpoint_url || undefined,
        detection_enabled: true,
        recording_mode: "continuous",
        connection_kind: probeResult.connection_kind,
        supports_ptz: probeResult.supports_ptz,
        onvif_profile_token: probeResult.onvif_profile_token || undefined,
        device_metadata: probeResult.device_metadata || undefined,
        endpoints: probeResult.endpoints.map((endpoint) => ({
          endpoint_kind: endpoint.endpoint_kind,
          endpoint_url: endpoint.endpoint_url,
          username: probeForm.username.trim() || undefined,
          password_secret: probeForm.password || undefined,
          is_primary: Boolean(endpoint.is_primary),
        })),
      });
      setProbeResult(null);
      setProbeForm({ host: "", username: "", password: "", port: "", use_https: false, timeout: 5, location: "", name: "" });
      await loadList(false);
    } catch (event: any) {
      alert(event?.message || "Не удалось создать камеру из автоопределения.");
    } finally {
      setBusy(false);
    }
  };

  const createManualCamera = async () => {
    if (!token || !manualCreate.name.trim()) return;
    setBusy(true);
    try {
      const endpoints = buildManualEndpoints(manualCreate);
      await createCamera(token, {
        name: manualCreate.name.trim(),
        location: manualCreate.location.trim() || undefined,
        ip_address: manualCreate.ip_address.trim() || undefined,
        stream_url: manualCreate.stream_url.trim() || undefined,
        detection_enabled: manualCreate.detection_enabled,
        recording_mode: manualCreate.recording_mode,
        connection_kind: endpoints[0]?.endpoint_kind || "manual",
        endpoints: endpoints.map((endpoint) => ({
          endpoint_kind: endpoint.endpoint_kind,
          endpoint_url: endpoint.endpoint_url,
          username: endpoint.username || undefined,
          password_secret: endpoint.password_secret || undefined,
          is_primary: endpoint.is_primary,
        })),
      });
      setManualCreate(EMPTY_MANUAL_FORM);
      await loadList(false);
    } catch (event: any) {
      alert(event?.message || "Не удалось добавить камеру вручную.");
    } finally {
      setBusy(false);
    }
  };

  const updateEndpoint = (index: number, patch: Partial<EditableEndpoint>) => {
    setDetailForm((prev) => {
      if (!prev) return prev;
      const endpoints = prev.endpoints.slice();
      endpoints[index] = { ...endpoints[index], ...patch };
      return { ...prev, endpoints };
    });
  };

  const addEndpoint = (endpoint_kind: EditableEndpoint["endpoint_kind"]) => {
    setDetailForm((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        endpoints: prev.endpoints.concat({ endpoint_kind, endpoint_url: "", username: "", password_secret: "", is_primary: prev.endpoints.length === 0 }),
      };
    });
  };

  const removeEndpoint = (index: number) => {
    setDetailForm((prev) => (prev ? { ...prev, endpoints: prev.endpoints.filter((_, i) => i !== index) } : prev));
  };

  const syncOnvif = async () => {
    if (!token || !selectedId) return;
    setBusy(true);
    try {
      const detail = await refreshOnvifCamera(token, selectedId);
      setSelected(detail);
      setDetailForm(toDetailForm(detail));
      await loadList();
    } catch (event: any) {
      alert(event?.message || "Не удалось синхронизировать ONVIF-камеру.");
    } finally {
      setBusy(false);
    }
  };

  const addRoi = async () => {
    if (!token || !selectedId || !newRoiName.trim()) return;
    setBusy(true);
    try {
      const response = await fetch(`${API_URL}/admin/cameras/${selectedId}/roi-zones`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ name: newRoiName.trim(), zone_type: "include" }),
      });
      if (!response.ok) throw new Error(await response.text());
      setNewRoiName("");
      await loadDetail(selectedId);
    } catch (event: any) {
      alert(event?.message || "Не удалось создать ROI-зону.");
    } finally {
      setBusy(false);
    }
  };

  const deleteRoi = async (zoneId: number) => {
    if (!token || !selectedId) return;
    setBusy(true);
    try {
      const response = await fetch(`${API_URL}/admin/cameras/${selectedId}/roi-zones/${zoneId}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error(await response.text());
      await loadDetail(selectedId);
    } catch (event: any) {
      alert(event?.message || "Не удалось удалить ROI-зону.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Administration</div>
          <h2 className="title">Камеры</h2>
          <div className="page-hero__lead">Автодетект ONVIF, хранение endpoints с учётными данными и подготовка камер для управления в полноэкранном Live.</div>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={() => loadList()} disabled={loading || busy}>Обновить список</button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Всего камер</div>
          <div className="summary-card__value">{cameras.length}</div>
          <div className="summary-card__hint">Активные камеры, доступные через backend.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">ONVIF-камер</div>
          <div className="summary-card__value">{cameras.filter((camera) => camera.onvif_enabled).length}</div>
          <div className="summary-card__hint">Для них доступны discovery, синхронизация и полноэкранное управление в Live.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Локаций</div>
          <div className="summary-card__value">{Object.keys(grouped).length}</div>
          <div className="summary-card__hint">Группировка по местам установки камер.</div>
        </div>
      </section>

      {error && <div className="danger">{error}</div>}

      <section className="admin-two-column">
        <div className="stack-grid">
          <div className="panel-card stack">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Автодетект ONVIF</h3>
                <div className="panel-card__lead">Сначала можно найти устройства в сети, потом проверить конкретный хост с логином и паролем.</div>
              </div>
              <button className="btn secondary" onClick={scanNetwork} disabled={discoveryBusy}>{discoveryBusy ? "Поиск..." : "Поиск в сети"}</button>
            </div>

            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
              <label className="field"><span className="label">Host / IP</span><input className="input" value={probeForm.host} onChange={(event) => setProbeForm((prev) => ({ ...prev, host: event.target.value }))} /></label>
              <label className="field"><span className="label">Порт</span><input className="input" value={probeForm.port} onChange={(event) => setProbeForm((prev) => ({ ...prev, port: event.target.value }))} placeholder="80 или 2020" /></label>
              <label className="field"><span className="label">Логин</span><input className="input" value={probeForm.username} onChange={(event) => setProbeForm((prev) => ({ ...prev, username: event.target.value }))} /></label>
              <label className="field"><span className="label">Пароль</span><input className="input" type="password" value={probeForm.password} onChange={(event) => setProbeForm((prev) => ({ ...prev, password: event.target.value }))} /></label>
              <label className="field"><span className="label">Название камеры</span><input className="input" value={probeForm.name} onChange={(event) => setProbeForm((prev) => ({ ...prev, name: event.target.value }))} placeholder="подставится после probe" /></label>
              <label className="field"><span className="label">Локация</span><input className="input" value={probeForm.location} onChange={(event) => setProbeForm((prev) => ({ ...prev, location: event.target.value }))} /></label>
            </div>

            <label className="field" style={{ maxWidth: 240 }}>
              <span className="label">Протокол ONVIF</span>
              <select className="input" value={probeForm.use_https ? "https" : "http"} onChange={(event) => setProbeForm((prev) => ({ ...prev, use_https: event.target.value === "https" }))}>
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
              </select>
            </label>

            <div className="page-actions"><button className="btn" onClick={runProbe} disabled={discoveryBusy || !probeForm.host.trim()}>{discoveryBusy ? "Проверка..." : "Определить камеру"}</button></div>

            {scanResults.length > 0 && (
              <div className="list-shell">
                {scanResults.map((device, index) => (
                  <button key={`${device.host || index}-${device.port || index}`} type="button" className="list-item" onClick={() => setProbeForm((prev) => ({ ...prev, host: device.host || prev.host, port: device.port ? String(device.port) : prev.port, use_https: Boolean(device.use_https), name: device.name || prev.name }))}>
                    <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                      <div className="list-item__title">{device.name || device.host || `Устройство ${index + 1}`}</div>
                      <span className="pill">{device.use_https ? "HTTPS" : "HTTP"}</span>
                    </div>
                    <div className="list-item__meta">{device.host || "хост не указан"}:{device.port || "?"}</div>
                  </button>
                ))}
              </div>
            )}

            {probeResult && (
              <div className="stack" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div className="panel-card__title">{probeResult.name || probeForm.host}</div>
                    <div className="panel-card__lead">Протоколы: {probeResult.protocols.join(", ") || "не определены"}</div>
                  </div>
                  <button className="btn" onClick={createFromProbe} disabled={busy}>Создать камеру</button>
                </div>
                {probeResult.warnings.length > 0 && <div className="warning">{probeResult.warnings.join(" ")}</div>}
                <div className="list-shell">
                  {probeResult.endpoints.map((endpoint, index) => (
                    <div key={`${endpoint.endpoint_kind}-${index}`} className="list-item" style={{ cursor: "default" }}>
                      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                        <div className="list-item__title">{endpoint.endpoint_kind.toUpperCase()}</div>
                        {endpoint.is_primary && <span className="pill">primary</span>}
                      </div>
                      <div className="list-item__meta">{endpoint.endpoint_url}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="panel-card stack">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Ручное добавление</h3>
                <div className="panel-card__lead">Для RTSP/HTTP-камер без ONVIF. Логин и пароль будут сохранены в endpoint.</div>
              </div>
            </div>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))" }}>
              <label className="field"><span className="label">Название</span><input className="input" value={manualCreate.name} onChange={(event) => setManualCreate((prev) => ({ ...prev, name: event.target.value }))} /></label>
              <label className="field"><span className="label">Локация</span><input className="input" value={manualCreate.location} onChange={(event) => setManualCreate((prev) => ({ ...prev, location: event.target.value }))} /></label>
              <label className="field"><span className="label">IP</span><input className="input" value={manualCreate.ip_address} onChange={(event) => setManualCreate((prev) => ({ ...prev, ip_address: event.target.value }))} /></label>
              <label className="field"><span className="label">Stream URL</span><input className="input" value={manualCreate.stream_url} onChange={(event) => setManualCreate((prev) => ({ ...prev, stream_url: event.target.value }))} placeholder="rtsp://... или http://..." /></label>
              <label className="field"><span className="label">Логин потока</span><input className="input" value={manualCreate.username} onChange={(event) => setManualCreate((prev) => ({ ...prev, username: event.target.value }))} /></label>
              <label className="field"><span className="label">Пароль потока</span><input className="input" type="password" value={manualCreate.password} onChange={(event) => setManualCreate((prev) => ({ ...prev, password: event.target.value }))} /></label>
            </div>
            <div className="page-actions"><button className="btn" onClick={createManualCamera} disabled={busy || !manualCreate.name.trim()}>Добавить вручную</button></div>
          </div>

          <div className="panel-card">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Список камер</h3>
                <div className="panel-card__lead">ONVIF-функции активируются только у камер с ONVIF endpoint.</div>
              </div>
            </div>
            {loading ? (
              <div className="muted">Загрузка...</div>
            ) : (
              Object.keys(grouped).sort().map((location) => (
                <div key={location} className="stack" style={{ marginBottom: 14 }}>
                  <div className="label" style={{ fontWeight: 700 }}>{location}</div>
                  <div className="list-shell">
                    {grouped[location].map((camera) => (
                      <button key={camera.camera_id} type="button" className={`list-item${camera.camera_id === selectedId ? " active" : ""}`} onClick={() => setSelectedId(camera.camera_id)}>
                        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                          <div className="list-item__title">{camera.name}</div>
                          <span className="pill">{camera.onvif_enabled ? "ONVIF" : camera.connection_kind.toUpperCase()}</span>
                        </div>
                        <div className="list-item__meta">{camera.ip_address || "IP не указана"} · {camera.detection_enabled ? "детекция включена" : "детекция выключена"}</div>
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
                <h3 className="panel-card__title">Карточка камеры</h3>
                <div className="panel-card__lead">Общие параметры, endpoints и учётные данные подключения.</div>
              </div>
              {selected && (
                <div className="page-actions">
                  <button className="btn secondary" onClick={saveSelected} disabled={busy || !detailForm}>Сохранить</button>
                  <button className="btn secondary" onClick={removeSelected} disabled={busy}>Удалить</button>
                </div>
              )}
            </div>

            {detailLoading ? (
              <div className="muted">Загрузка параметров камеры...</div>
            ) : !detailForm || !selected ? (
              <div className="muted">Выберите камеру слева.</div>
            ) : (
              <>
                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))" }}>
                  <label className="field"><span className="label">Название</span><input className="input" value={detailForm.name} onChange={(event) => setDetailForm((prev) => (prev ? { ...prev, name: event.target.value } : prev))} /></label>
                  <label className="field"><span className="label">Локация</span><input className="input" value={detailForm.location} onChange={(event) => setDetailForm((prev) => (prev ? { ...prev, location: event.target.value } : prev))} /></label>
                  <label className="field"><span className="label">IP</span><input className="input" value={detailForm.ip_address} onChange={(event) => setDetailForm((prev) => (prev ? { ...prev, ip_address: event.target.value } : prev))} /></label>
                  <label className="field"><span className="label">Основной stream URL</span><input className="input" value={detailForm.stream_url} onChange={(event) => setDetailForm((prev) => (prev ? { ...prev, stream_url: event.target.value } : prev))} /></label>
                  <label className="field"><span className="label">Детекция</span><select className="input" value={detailForm.detection_enabled ? "on" : "off"} onChange={(event) => setDetailForm((prev) => (prev ? { ...prev, detection_enabled: event.target.value === "on" } : prev))}><option value="on">Включена</option><option value="off">Выключена</option></select></label>
                  <label className="field"><span className="label">Запись</span><select className="input" value={detailForm.recording_mode} onChange={(event) => setDetailForm((prev) => (prev ? { ...prev, recording_mode: event.target.value as "continuous" | "event" } : prev))}><option value="continuous">Постоянная</option><option value="event">Событийная</option></select></label>
                </div>

                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
                  <label className="field"><span className="label">Tracking</span><select className="input" value={detailForm.tracking_enabled ? "on" : "off"} onChange={(event) => setDetailForm((prev) => (prev ? { ...prev, tracking_enabled: event.target.value === "on" } : prev))}><option value="off">Выключен</option><option value="on">Включён</option></select></label>
                  <label className="field"><span className="label">Режим tracking</span><select className="input" value={detailForm.tracking_mode} onChange={(event) => setDetailForm((prev) => (prev ? { ...prev, tracking_mode: event.target.value as "off" | "auto" | "patrol" } : prev))}><option value="off">Выключен</option><option value="auto">Auto</option><option value="patrol">Patrol</option></select></label>
                  <label className="field"><span className="label">person_id цели</span><input className="input" value={detailForm.tracking_target_person_id} onChange={(event) => setDetailForm((prev) => (prev ? { ...prev, tracking_target_person_id: event.target.value } : prev))} /></label>
                </div>

                <div className="panel-card__header" style={{ paddingTop: 8 }}>
                  <div>
                    <h3 className="panel-card__title">Endpoints</h3>
                    <div className="panel-card__lead">Пароль можно оставить пустым — backend сохранит уже записанный секрет для того же endpoint.</div>
                  </div>
                  <div className="page-actions">
                    <button className="btn secondary" onClick={() => addEndpoint("onvif")}>+ ONVIF</button>
                    <button className="btn secondary" onClick={() => addEndpoint("rtsp")}>+ RTSP</button>
                    <button className="btn secondary" onClick={() => addEndpoint("http")}>+ HTTP</button>
                  </div>
                </div>
                <div className="stack">
                  {detailForm.endpoints.length === 0 ? (
                    <div className="muted">Endpoints ещё не настроены.</div>
                  ) : detailForm.endpoints.map((endpoint, index) => (
                    <div key={`${endpoint.endpoint_kind}-${index}`} className="list-item" style={{ cursor: "default" }}>
                      <div className="grid" style={{ gridTemplateColumns: "140px 1fr 180px 180px auto", alignItems: "end" }}>
                        <label className="field"><span className="label">Тип</span><select className="input" value={endpoint.endpoint_kind} onChange={(event) => updateEndpoint(index, { endpoint_kind: event.target.value as EditableEndpoint["endpoint_kind"] })}><option value="onvif">ONVIF</option><option value="rtsp">RTSP</option><option value="http">HTTP</option></select></label>
                        <label className="field"><span className="label">URL</span><input className="input" value={endpoint.endpoint_url} onChange={(event) => updateEndpoint(index, { endpoint_url: event.target.value })} /></label>
                        <label className="field"><span className="label">Логин</span><input className="input" value={endpoint.username} onChange={(event) => updateEndpoint(index, { username: event.target.value })} /></label>
                        <label className="field"><span className="label">Пароль {endpoint.has_password ? "(хранится)" : ""}</span><input className="input" type="password" value={endpoint.password_secret} onChange={(event) => updateEndpoint(index, { password_secret: event.target.value })} placeholder={endpoint.has_password ? "оставьте пустым, чтобы не менять" : ""} /></label>
                        <div className="page-actions">
                          <label className="field" style={{ minWidth: 110 }}><span className="label">Primary</span><select className="input" value={endpoint.is_primary ? "yes" : "no"} onChange={(event) => updateEndpoint(index, { is_primary: event.target.value === "yes" })}><option value="yes">Да</option><option value="no">Нет</option></select></label>
                          <button className="btn secondary" onClick={() => removeEndpoint(index)}>Удалить</button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {selected && detailForm && selected.onvif_enabled && (
            <div className="panel-card stack">
              <div className="panel-card__header">
                <div>
                  <h3 className="panel-card__title">Сведения ONVIF</h3>
                  <div className="panel-card__lead">Здесь остаются только данные подключения. Само управление доступно в полноэкранном режиме на вкладке Live.</div>
                </div>
                <div className="page-actions">
                  <button className="btn secondary" onClick={syncOnvif} disabled={busy}>Синхронизировать</button>
                </div>
              </div>

              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
                <div className="summary-card">
                  <div className="summary-card__label">Подключение</div>
                  <div className="summary-card__value">{selected.connection_kind.toUpperCase()}</div>
                  <div className="summary-card__hint">Основной тип подключения камеры.</div>
                </div>
                <div className="summary-card">
                  <div className="summary-card__label">PTZ</div>
                  <div className="summary-card__value">{selected.supports_ptz ? "Да" : "Нет"}</div>
                  <div className="summary-card__hint">Кнопки управления появятся только в fullscreen Live и только по доступным возможностям камеры.</div>
                </div>
                <div className="summary-card">
                  <div className="summary-card__label">Пресеты</div>
                  <div className="summary-card__value">{selected.presets?.length ?? 0}</div>
                  <div className="summary-card__hint">Точки патруля настраиваются из полноэкранного просмотра.</div>
                </div>
              </div>

              {selected.device_metadata && (
                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))" }}>
                  <div className="field"><span className="label">Производитель</span><div className="input">{String(selected.device_metadata.manufacturer || "—")}</div></div>
                  <div className="field"><span className="label">Модель</span><div className="input">{String(selected.device_metadata.model || "—")}</div></div>
                  <div className="field"><span className="label">Серийный номер</span><div className="input">{String(selected.device_metadata.serial_number || "—")}</div></div>
                  <div className="field"><span className="label">Firmware</span><div className="input">{String(selected.device_metadata.firmware_version || "—")}</div></div>
                </div>
              )}
            </div>
          )}

          {selected && (
            <div className="panel-card stack">
              <div className="panel-card__header">
                <div>
                  <h3 className="panel-card__title">ROI-зоны</h3>
                  <div className="panel-card__lead">Локальные зоны анализа для Processor. Точки патруля ONVIF вынесены во вкладку Live.</div>
                </div>
              </div>

              <div className="page-actions" style={{ marginTop: 12 }}>
                <input className="input" style={{ flex: 1, minWidth: 220 }} value={newRoiName} onChange={(event) => setNewRoiName(event.target.value)} placeholder="Название ROI-зоны" />
                <button className="btn" onClick={addRoi} disabled={busy || !newRoiName.trim()}>Добавить ROI</button>
              </div>
              <div className="list-shell">
                {(selected.roi_zones || []).length === 0 ? (
                  <div className="muted">ROI-зон пока нет.</div>
                ) : (
                  selected.roi_zones.map((zone) => (
                    <div key={zone.roi_zone_id} className="list-item" style={{ cursor: "default" }}>
                      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                        <div className="list-item__title">{zone.name}</div>
                        <button className="btn secondary" onClick={() => deleteRoi(zone.roi_zone_id)}>Удалить</button>
                      </div>
                      <div className="list-item__meta">Тип: {zone.zone_type}</div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default CamerasPage;
