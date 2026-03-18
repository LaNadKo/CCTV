import { useEffect, useState } from "react";
import {
  listProcessors,
  deleteProcessor,
  assignCamerasToProcessor,
  unassignCameraFromProcessor,
  getCameras,
  type ProcessorOut,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Camera = {
  camera_id: number;
  name: string;
  location?: string;
};

const ProcessorsPage: React.FC = () => {
  const { token } = useAuth();
  const [processors, setProcessors] = useState<ProcessorOut[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedProc, setSelectedProc] = useState<number | null>(null);

  const load = async () => {
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
  };

  useEffect(() => {
    load();
  }, [token]);

  const handleDelete = async (id: number) => {
    if (!token || !confirm("Удалить процессор?")) return;
    try {
      await deleteProcessor(token, id);
      await load();
    } catch (e: any) {
      alert(e?.message || "Ошибка удаления");
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

  const statusColor = (s: string) => {
    if (s === "online") return "#65ffa0";
    if (s === "offline") return "#ff6b6b";
    return "var(--muted)";
  };

  const selectedProcessor = processors.find((p) => p.processor_id === selectedProc);
  const assignedCamIds = selectedProcessor?.assigned_cameras?.map((ac) => ac.camera_id) ?? [];
  const availableCameras = cameras.filter((c) => !assignedCamIds.includes(c.camera_id));

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h2 className="title">Процессоры</h2>
          <div className="muted">Внешние сервисы обработки видео. Регистрируются через API-ключ.</div>
        </div>
        <button className="btn secondary" onClick={load}>
          Обновить
        </button>
      </div>

      {error && <div className="danger">{error}</div>}

      {loading ? (
        <div className="muted">Загрузка...</div>
      ) : processors.length === 0 ? (
        <div className="card">
          <div className="muted">
            Нет зарегистрированных процессоров. Создайте API-ключ со скоупом{" "}
            <code>processor:register</code> и запустите processor-сервис.
          </div>
        </div>
      ) : (
        <div className="grid">
          {processors.map((p) => (
            <div
              key={p.processor_id}
              className="card"
              style={{
                border: selectedProc === p.processor_id ? "1px solid var(--accent)" : undefined,
                cursor: "pointer",
              }}
              onClick={() => setSelectedProc(p.processor_id)}
            >
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ fontWeight: 600 }}>{p.name}</div>
                <span className="pill" style={{ color: statusColor(p.status) }}>
                  {p.status}
                </span>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                Камер: {p.camera_count}
                {p.capabilities && (p.capabilities as any).max_workers && (
                  <> | Max workers: {(p.capabilities as any).max_workers}</>
                )}
              </div>
              {p.assigned_cameras && p.assigned_cameras.length > 0 && (
                <div className="stack" style={{ marginTop: 6, gap: 2 }}>
                  {p.assigned_cameras.map((ac) => (
                    <div key={ac.camera_id} className="row" style={{ justifyContent: "space-between", fontSize: 12 }}>
                      <span>{ac.name} (#{ac.camera_id})</span>
                      <button
                        className="btn secondary"
                        style={{ fontSize: 10, padding: "1px 5px" }}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleUnassign(p.processor_id, ac.camera_id);
                        }}
                      >
                        x
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {p.last_heartbeat && (
                <div className="muted" style={{ fontSize: 12 }}>
                  Heartbeat: {new Date(p.last_heartbeat).toLocaleString()}
                </div>
              )}
              <div className="row" style={{ marginTop: 8, gap: 6 }}>
                <button
                  className="btn secondary"
                  style={{ fontSize: 12, padding: "4px 10px" }}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(p.processor_id);
                  }}
                >
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedProc !== null && selectedProcessor && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>
            Назначение камер — {selectedProcessor.name}
          </h3>

          {selectedProcessor.assigned_cameras && selectedProcessor.assigned_cameras.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div className="label" style={{ marginBottom: 4 }}>Назначенные камеры:</div>
              <div className="stack" style={{ gap: 4 }}>
                {selectedProcessor.assigned_cameras.map((ac) => (
                  <div key={ac.camera_id} className="row" style={{ gap: 8, alignItems: "center" }}>
                    <span>{ac.name} (#{ac.camera_id})</span>
                    <button
                      className="btn secondary"
                      style={{ fontSize: 11, padding: "2px 8px" }}
                      onClick={() => handleUnassign(selectedProc, ac.camera_id)}
                    >
                      Убрать
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {availableCameras.length > 0 ? (
            <div>
              <div className="label" style={{ marginBottom: 4 }}>Доступные камеры (нажмите для назначения):</div>
              <div className="stack" style={{ gap: 4 }}>
                {availableCameras.map((c) => (
                  <button
                    key={c.camera_id}
                    className="hour-card"
                    onClick={() => handleAssignCamera(selectedProc, c.camera_id)}
                    style={{ textAlign: "left" }}
                  >
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <span>{c.name} (#{c.camera_id})</span>
                      <span className="pill">+ Назначить</span>
                    </div>
                    {c.location && <div className="muted" style={{ fontSize: 11 }}>{c.location}</div>}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="muted">Все камеры уже назначены этому процессору.</div>
          )}
        </div>
      )}
    </div>
  );
};

export default ProcessorsPage;
