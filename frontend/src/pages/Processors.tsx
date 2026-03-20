import { useCallback, useEffect, useMemo, useState } from "react";
import {
  assignCamerasToProcessor,
  deleteProcessor,
  generateProcessorCode,
  getCameras,
  listProcessors,
  type ProcessorOut,
  type SystemMetrics,
  unassignCameraFromProcessor,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Camera = {
  camera_id: number;
  name: string;
  location?: string;
};

function MetricBar({
  value,
  max,
  label,
  unit,
  color,
}: {
  value: number;
  max: number;
  label: string;
  unit?: string;
  color?: string;
}) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div style={{ flex: 1, minWidth: 110 }}>
      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700 }}>
        {value.toFixed(1)}
        {unit && <span style={{ fontSize: 11, fontWeight: 400 }}> {unit}</span>}
      </div>
      <div style={{ background: "var(--surface-muted)", borderRadius: 999, height: 7, marginTop: 6, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color || "var(--accent)", borderRadius: 999 }} />
      </div>
    </div>
  );
}

function MetricsPanel({ metrics }: { metrics: SystemMetrics }) {
  const uptimeStr = metrics.uptime_seconds
    ? `${Math.floor(metrics.uptime_seconds / 3600)}ч ${Math.floor((metrics.uptime_seconds % 3600) / 60)}м`
    : "—";

  return (
    <div className="summary-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", marginTop: 14 }}>
      <div className="summary-card" style={{ padding: 14 }}>
        <MetricBar
          value={metrics.cpu_percent ?? 0}
          max={100}
          label="CPU"
          unit="%"
          color={(metrics.cpu_percent ?? 0) > 80 ? "#ff6b6b" : (metrics.cpu_percent ?? 0) > 50 ? "#fbbf24" : "#22c55e"}
        />
      </div>
      <div className="summary-card" style={{ padding: 14 }}>
        <MetricBar
          value={metrics.ram_used_gb ?? 0}
          max={metrics.ram_total_gb ?? 1}
          label="RAM"
          unit={`/ ${(metrics.ram_total_gb ?? 0).toFixed(1)} GB`}
          color={(metrics.ram_percent ?? 0) > 80 ? "#ff6b6b" : "#22c55e"}
        />
      </div>
      {metrics.gpu_name && (
        <div className="summary-card" style={{ padding: 14 }}>
          <MetricBar
            value={metrics.gpu_util_percent ?? 0}
            max={100}
            label={metrics.gpu_name.substring(0, 18)}
            unit="%"
            color={(metrics.gpu_util_percent ?? 0) > 80 ? "#ff6b6b" : "#22c55e"}
          />
        </div>
      )}
      <div className="summary-card" style={{ padding: 14 }}>
        <div className="summary-card__label">Сеть</div>
        <div className="summary-card__hint" style={{ marginTop: 8 }}>
          <span style={{ color: "#22c55e" }}>↑{(metrics.net_sent_mbps ?? 0).toFixed(1)}</span>{" "}
          <span style={{ color: "#38bdf8" }}>↓{(metrics.net_recv_mbps ?? 0).toFixed(1)}</span> Мбит/с
        </div>
      </div>
      <div className="summary-card" style={{ padding: 14 }}>
        <div className="summary-card__label">GPU Temp</div>
        <div className="summary-card__value" style={{ fontSize: 22, marginTop: 8 }}>
          {metrics.gpu_temp_c != null ? `${metrics.gpu_temp_c}°C` : "—"}
        </div>
      </div>
      <div className="summary-card" style={{ padding: 14 }}>
        <div className="summary-card__label">Камер / аптайм</div>
        <div className="summary-card__hint" style={{ marginTop: 8 }}>
          {metrics.active_cameras ?? 0} камер · {uptimeStr}
        </div>
      </div>
    </div>
  );
}

function timeSince(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return `${seconds}с назад`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}м назад`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}ч назад`;
  return `${Math.floor(seconds / 86400)}д назад`;
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
    setError(null);
    try {
      const [processorItems, cameraItems] = await Promise.all([listProcessors(token), getCameras(token)]);
      setProcessors(processorItems);
      setCameras(cameraItems);
    } catch (event: any) {
      setError(event?.message || "Не удалось загрузить данные");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  const handleDelete = async (id: number) => {
    if (!token || !window.confirm("Удалить процессор?")) return;
    try {
      await deleteProcessor(token, id);
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка удаления");
    }
  };

  const handleGenerateCode = async () => {
    if (!token) return;
    setCodeLoading(true);
    try {
      setConnCode(await generateProcessorCode(token));
    } catch (event: any) {
      alert(event?.message || "Ошибка генерации кода");
    } finally {
      setCodeLoading(false);
    }
  };

  const handleAssignCamera = async (processorId: number, cameraId: number) => {
    if (!token) return;
    try {
      await assignCamerasToProcessor(token, processorId, [cameraId]);
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка назначения");
    }
  };

  const handleUnassign = async (processorId: number, cameraId: number) => {
    if (!token) return;
    try {
      await unassignCameraFromProcessor(token, processorId, cameraId);
      await load();
    } catch (event: any) {
      alert(event?.message || "Ошибка");
    }
  };

  const statusColor = (status: string, heartbeat?: string | null) => {
    if (status === "online" && heartbeat) {
      const ago = (Date.now() - new Date(heartbeat).getTime()) / 1000;
      if (ago > 90) return "#fbbf24";
    }
    if (status === "online") return "#22c55e";
    if (status === "offline") return "#f87171";
    return "var(--muted)";
  };

  const selectedProcessor = processors.find((processor) => processor.processor_id === selectedProc);
  const assignedCamIds = selectedProcessor?.assigned_cameras?.map((camera) => camera.camera_id) ?? [];
  const availableCameras = cameras.filter((camera) => !assignedCamIds.includes(camera.camera_id));

  const stats = useMemo(
    () => ({
      total: processors.length,
      online: processors.filter((processor) => processor.status === "online").length,
      cameras: processors.reduce((sum, processor) => sum + processor.camera_count, 0),
    }),
    [processors]
  );

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Processing</div>
          <h2 className="title">Процессоры</h2>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
          <button className="btn" onClick={handleGenerateCode} disabled={codeLoading}>
            {codeLoading ? "..." : "+ Код подключения"}
          </button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Всего процессоров</div>
          <div className="summary-card__value">{stats.total}</div>
          <div className="summary-card__hint">Все зарегистрированные узлы обработки video pipeline.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Онлайн</div>
          <div className="summary-card__value">{stats.online}</div>
          <div className="summary-card__hint">Живые узлы с heartbeat в пределах допустимого окна.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Назначено камер</div>
          <div className="summary-card__value">{stats.cameras}</div>
          <div className="summary-card__hint">Суммарное число камер, уже распределённых по процессорам.</div>
        </div>
      </section>

      {connCode && (
        <section className="panel-card" style={{ borderColor: "rgba(94, 240, 255, 0.32)" }}>
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Код подключения</h3>
              <div className="panel-card__lead">Действует 24 часа. Введите его в CCTV Processor на ПК, который нужно привязать.</div>
            </div>
            <span className="pill">до {new Date(connCode.expires_at).toLocaleString()}</span>
          </div>
          <div style={{ fontSize: 34, fontWeight: 800, letterSpacing: 6, fontFamily: "monospace", marginBottom: 12 }}>
            {connCode.code}
          </div>
          <div className="page-actions">
            <button className="btn secondary" onClick={() => navigator.clipboard.writeText(connCode.code)}>
              Копировать
            </button>
            <button className="btn secondary" onClick={() => setConnCode(null)}>
              Скрыть
            </button>
          </div>
        </section>
      )}

      {error && <div className="danger">{error}</div>}

      {loading && processors.length === 0 ? (
        <div className="panel-card">Загрузка...</div>
      ) : processors.length === 0 ? (
        <div className="panel-card">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Процессоров пока нет</h3>
              <div className="panel-card__lead">
                Сгенерируйте код подключения и введите его в установленный CCTV Processor, чтобы добавить первый узел.
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="list-shell">
          {processors.map((processor) => {
            const isSelected = selectedProc === processor.processor_id;
            const isOnline =
              processor.status === "online" &&
              processor.last_heartbeat &&
              (Date.now() - new Date(processor.last_heartbeat).getTime()) / 1000 < 90;

            return (
              <section key={processor.processor_id} className="panel-card">
                <div className="panel-card__header">
                  <div className="stack" style={{ gap: 8 }}>
                    <div className="row" style={{ gap: 10, alignItems: "center" }}>
                      <span
                        style={{
                          width: 10,
                          height: 10,
                          borderRadius: "50%",
                          background: statusColor(processor.status, processor.last_heartbeat),
                          display: "inline-block",
                          boxShadow: isOnline ? "0 0 8px #22c55e" : undefined,
                        }}
                      />
                      <h3 className="panel-card__title" style={{ margin: 0 }}>
                        {processor.name}
                      </h3>
                      <span className="pill" style={{ color: statusColor(processor.status, processor.last_heartbeat) }}>
                        {isOnline ? "online" : processor.status}
                      </span>
                      {processor.version && <span className="muted">v{processor.version}</span>}
                    </div>
                    <div className="chip-row">
                      {processor.ip_address && <span className="pill">IP: {processor.ip_address}</span>}
                      {processor.os_info && <span className="pill">{processor.os_info}</span>}
                      {processor.capabilities && (processor.capabilities as any).platform_version && (
                        <span className="pill">Build: {(processor.capabilities as any).platform_version}</span>
                      )}
                      {processor.capabilities && (processor.capabilities as any).gpu && (
                        <span className="pill">GPU: {(processor.capabilities as any).gpu}</span>
                      )}
                      {processor.capabilities && (processor.capabilities as any).inference_device && (
                        <span className="pill">Inference: {(processor.capabilities as any).inference_device}</span>
                      )}
                    </div>
                  </div>

                  <div className="page-actions">
                    {processor.last_heartbeat && <span className="muted">{timeSince(processor.last_heartbeat)}</span>}
                    <button className="btn secondary" onClick={() => setSelectedProc(isSelected ? null : processor.processor_id)}>
                      {isSelected ? "Скрыть назначения" : "Назначения"}
                    </button>
                    <button className="btn secondary" onClick={() => handleDelete(processor.processor_id)}>
                      Удалить
                    </button>
                  </div>
                </div>

                {processor.metrics && <MetricsPanel metrics={processor.metrics} />}

                {processor.assigned_cameras && processor.assigned_cameras.length > 0 && (
                  <div className="panel-card" style={{ marginTop: 14, padding: 16 }}>
                    <div className="panel-card__header" style={{ marginBottom: 10 }}>
                      <div>
                        <h3 className="panel-card__title">Назначенные камеры</h3>
                        <div className="panel-card__lead">Текущий состав обработчика и быстрое снятие назначения.</div>
                      </div>
                    </div>
                    <div className="chip-row">
                      {processor.assigned_cameras.map((camera) => (
                        <span key={camera.camera_id} className="pill" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                          {camera.name}
                          <button
                            style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0 }}
                            onClick={() => handleUnassign(processor.processor_id, camera.camera_id)}
                            type="button"
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {isSelected && (
                  <div className="panel-card" style={{ marginTop: 14, padding: 16 }}>
                    <div className="panel-card__header" style={{ marginBottom: 10 }}>
                      <div>
                        <h3 className="panel-card__title">Свободные камеры</h3>
                        <div className="panel-card__lead">Выберите камеры, которые ещё не назначены на текущий Processor.</div>
                      </div>
                    </div>
                    {availableCameras.length > 0 ? (
                      <div className="chip-row">
                        {availableCameras.map((camera) => (
                          <button
                            key={camera.camera_id}
                            className="btn secondary"
                            onClick={() => handleAssignCamera(processor.processor_id, camera.camera_id)}
                          >
                            + {camera.name}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="muted">Все камеры уже назначены.</div>
                    )}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default ProcessorsPage;
