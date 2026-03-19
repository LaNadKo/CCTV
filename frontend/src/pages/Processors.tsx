import { useEffect, useState, useCallback } from "react";
import {
  listProcessors,
  deleteProcessor,
  assignCamerasToProcessor,
  unassignCameraFromProcessor,
  generateProcessorCode,
  getCameras,
  type ProcessorOut,
  type SystemMetrics,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Camera = {
  camera_id: number;
  name: string;
  location?: string;
};

function MetricBar({ value, max, label, unit, color }: { value: number; max: number; label: string; unit?: string; color?: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div style={{ flex: 1, minWidth: 100 }}>
      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700 }}>
        {value.toFixed(1)}{unit && <span style={{ fontSize: 11, fontWeight: 400 }}> {unit}</span>}
      </div>
      <div style={{ background: "var(--bg)", borderRadius: 4, height: 6, marginTop: 4, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color || "var(--accent)", borderRadius: 4, transition: "width 0.5s" }} />
      </div>
    </div>
  );
}

function MetricsPanel({ m }: { m: SystemMetrics }) {
  const uptimeStr = m.uptime_seconds
    ? `${Math.floor(m.uptime_seconds / 3600)}ч ${Math.floor((m.uptime_seconds % 3600) / 60)}м`
    : "—";
  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 10 }}>
      <MetricBar value={m.cpu_percent ?? 0} max={100} label="CPU" unit="%" color={
        (m.cpu_percent ?? 0) > 80 ? "#ff6b6b" : (m.cpu_percent ?? 0) > 50 ? "#ffc107" : "#65ffa0"
      } />
      <MetricBar value={m.ram_used_gb ?? 0} max={m.ram_total_gb ?? 1} label="RAM"
        unit={`/ ${(m.ram_total_gb ?? 0).toFixed(1)} GB`}
        color={(m.ram_percent ?? 0) > 80 ? "#ff6b6b" : "#65ffa0"} />
      {m.gpu_name && (
        <MetricBar value={m.gpu_util_percent ?? 0} max={100} label={m.gpu_name.substring(0, 18)} unit="%"
          color={(m.gpu_util_percent ?? 0) > 80 ? "#ff6b6b" : "#65ffa0"} />
      )}
      <div style={{ flex: 1, minWidth: 80 }}>
        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>Сеть</div>
        <div style={{ fontSize: 13 }}>
          <span style={{ color: "#65ffa0" }}>↑{(m.net_sent_mbps ?? 0).toFixed(1)}</span>{" "}
          <span style={{ color: "#6bc5ff" }}>↓{(m.net_recv_mbps ?? 0).toFixed(1)}</span>{" "}
          <span style={{ fontSize: 10, color: "var(--muted)" }}>Мбит/с</span>
        </div>
      </div>
      {m.gpu_temp_c != null && (
        <div style={{ flex: "0 0 auto", minWidth: 60 }}>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>GPU Temp</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: m.gpu_temp_c > 75 ? "#ff6b6b" : "#65ffa0" }}>
            {m.gpu_temp_c}°C
          </div>
        </div>
      )}
      <div style={{ flex: "0 0 auto", minWidth: 60 }}>
        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>Камеры</div>
        <div style={{ fontSize: 16, fontWeight: 700 }}>{m.active_cameras ?? 0}</div>
      </div>
      <div style={{ flex: "0 0 auto", minWidth: 60 }}>
        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>Аптайм</div>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{uptimeStr}</div>
      </div>
    </div>
  );
}

function timeSince(dateStr: string): string {
  const secs = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (secs < 60) return `${secs}с назад`;
  if (secs < 3600) return `${Math.floor(secs / 60)}м назад`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}ч назад`;
  return `${Math.floor(secs / 86400)}д назад`;
}

const ProcessorsPage: React.FC = () => {
  const { token } = useAuth();
  const [processors, setProcessors] = useState<ProcessorOut[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedProc, setSelectedProc] = useState<number | null>(null);
  const [connCode, setConnCode] = useState<{ code: string; expires_at: string } | null>(null);
  const [codeLoading, setCodeLoading] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [p, c] = await Promise.all([listProcessors(token), getCameras(token)]);
      setProcessors(p);
      setCameras(c);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 10s
  useEffect(() => {
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  const handleDelete = async (id: number) => {
    if (!token || !confirm("Удалить процессор?")) return;
    try {
      await deleteProcessor(token, id);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка удаления");
    }
  };

  const handleGenerateCode = async () => {
    if (!token) return;
    setCodeLoading(true);
    try {
      const data = await generateProcessorCode(token);
      setConnCode(data);
    } catch (e: any) {
      alert(e?.message || "Ошибка генерации кода");
    } finally {
      setCodeLoading(false);
    }
  };

  const handleAssignCamera = async (procId: number, camId: number) => {
    if (!token) return;
    try {
      await assignCamerasToProcessor(token, procId, [camId]);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка назначения");
    }
  };

  const handleUnassign = async (procId: number, camId: number) => {
    if (!token) return;
    try {
      await unassignCameraFromProcessor(token, procId, camId);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const statusColor = (s: string, hb?: string | null) => {
    if (s === "online" && hb) {
      const ago = (Date.now() - new Date(hb).getTime()) / 1000;
      if (ago > 90) return "#ffc107"; // stale
    }
    if (s === "online") return "#65ffa0";
    if (s === "offline") return "#ff6b6b";
    return "var(--muted)";
  };

  const selectedProcessor = processors.find((p) => p.processor_id === selectedProc);
  const assignedCamIds = selectedProcessor?.assigned_cameras?.map((ac) => ac.camera_id) ?? [];
  const availableCameras = cameras.filter((c) => !assignedCamIds.includes(c.camera_id));

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 10 }}>
        <div>
          <h2 className="title">Процессоры</h2>
          <div className="muted">Внешние сервисы обработки видео. Подключаются по коду.</div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn secondary" onClick={load}>Обновить</button>
          <button className="btn" onClick={handleGenerateCode} disabled={codeLoading}>
            {codeLoading ? "..." : "+ Код подключения"}
          </button>
        </div>
      </div>

      {/* Connection code banner */}
      {connCode && (
        <div className="card" style={{ border: "1px solid var(--accent)", background: "var(--card-active)" }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 4 }}>
                Код подключения (действует 24 часа)
              </div>
              <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: 4, fontFamily: "monospace" }}>
                {connCode.code}
              </div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
                Введите этот код в приложении процессора
              </div>
            </div>
            <div className="stack" style={{ gap: 4 }}>
              <button className="btn secondary" style={{ fontSize: 12 }} onClick={() => {
                navigator.clipboard.writeText(connCode.code);
              }}>
                Копировать
              </button>
              <button className="btn secondary" style={{ fontSize: 12 }} onClick={() => setConnCode(null)}>
                Скрыть
              </button>
            </div>
          </div>
        </div>
      )}

      {error && <div className="danger">{error}</div>}

      {loading && processors.length === 0 ? (
        <div className="muted">Загрузка...</div>
      ) : processors.length === 0 ? (
        <div className="card">
          <div className="muted" style={{ textAlign: "center", padding: 20 }}>
            <div style={{ fontSize: 40, marginBottom: 10 }}>🖥</div>
            Нет подключённых процессоров.<br />
            Нажмите <b>«+ Код подключения»</b>, чтобы сгенерировать код,<br />
            затем введите его в приложении CCTV Processor на ПК.
          </div>
        </div>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          {processors.map((p) => {
            const isSelected = selectedProc === p.processor_id;
            const isOnline = p.status === "online" && p.last_heartbeat &&
              (Date.now() - new Date(p.last_heartbeat).getTime()) / 1000 < 90;
            return (
              <div
                key={p.processor_id}
                className="card"
                style={{
                  border: isSelected ? "1px solid var(--accent)" : undefined,
                  cursor: "pointer",
                }}
                onClick={() => setSelectedProc(isSelected ? null : p.processor_id)}
              >
                {/* Header row */}
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                  <div className="row" style={{ gap: 10, alignItems: "center" }}>
                    <span style={{
                      width: 10, height: 10, borderRadius: "50%",
                      background: statusColor(p.status, p.last_heartbeat),
                      display: "inline-block",
                      boxShadow: isOnline ? "0 0 6px #65ffa0" : undefined,
                    }} />
                    <span style={{ fontWeight: 700, fontSize: 16 }}>{p.name}</span>
                    <span className="pill" style={{
                      color: statusColor(p.status, p.last_heartbeat),
                      fontSize: 11,
                    }}>
                      {isOnline ? "online" : p.status}
                    </span>
                    {p.version && <span style={{ fontSize: 11, color: "var(--muted)" }}>v{p.version}</span>}
                  </div>
                  <div className="row" style={{ gap: 6 }}>
                    {p.last_heartbeat && (
                      <span style={{ fontSize: 11, color: "var(--muted)" }}>
                        {timeSince(p.last_heartbeat)}
                      </span>
                    )}
                    <button
                      className="btn secondary"
                      style={{ fontSize: 11, padding: "3px 8px" }}
                      onClick={(e) => { e.stopPropagation(); handleDelete(p.processor_id); }}
                    >
                      Удалить
                    </button>
                  </div>
                </div>

                {/* Info row */}
                <div className="row" style={{ gap: 16, marginTop: 6, fontSize: 12, color: "var(--muted)", flexWrap: "wrap" }}>
                  {p.capabilities && (p.capabilities as any).hostname && <span>Host: {(p.capabilities as any).hostname}</span>}
                  {p.ip_address && <span>IP: {p.ip_address}</span>}
                  {p.os_info && <span>{p.os_info}</span>}
                  {p.capabilities && (p.capabilities as any).platform_version && <span>Build: {(p.capabilities as any).platform_version}</span>}
                  {p.capabilities && (p.capabilities as any).cpu_count && <span>CPU: {(p.capabilities as any).cpu_count} threads</span>}
                  <span>Камер: {p.camera_count}</span>
                  {p.capabilities && (p.capabilities as any).gpu && (
                    <span>GPU: {(p.capabilities as any).gpu}</span>
                  )}
                  {p.capabilities && (p.capabilities as any).inference_device && (
                    <span>Inference: {(p.capabilities as any).inference_device}</span>
                  )}
                  {p.capabilities && (p.capabilities as any).ram_gb && (
                    <span>RAM: {(p.capabilities as any).ram_gb} GB</span>
                  )}
                  {p.capabilities && (p.capabilities as any).python && (
                    <span>Python: {(p.capabilities as any).python}</span>
                  )}
                </div>

                {/* Metrics */}
                {p.metrics && <MetricsPanel m={p.metrics} />}

                {/* Assigned cameras */}
                {p.assigned_cameras && p.assigned_cameras.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>Назначенные камеры:</div>
                    <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                      {p.assigned_cameras.map((ac) => (
                        <span key={ac.camera_id} className="pill" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                          {ac.name}
                          <button
                            style={{ background: "none", border: "none", color: "var(--muted)", cursor: "pointer", padding: 0, fontSize: 12 }}
                            onClick={(e) => { e.stopPropagation(); handleUnassign(p.processor_id, ac.camera_id); }}
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Expand: camera assignment */}
                {isSelected && (
                  <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Назначить камеры</div>
                    {availableCameras.length > 0 ? (
                      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                        {availableCameras.map((c) => (
                          <button
                            key={c.camera_id}
                            className="btn secondary"
                            style={{ fontSize: 12, padding: "4px 10px" }}
                            onClick={(e) => { e.stopPropagation(); handleAssignCamera(p.processor_id, c.camera_id); }}
                          >
                            + {c.name}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="muted" style={{ fontSize: 12 }}>Все камеры назначены.</div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default ProcessorsPage;
