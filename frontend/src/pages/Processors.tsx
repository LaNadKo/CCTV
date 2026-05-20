import { useCallback, useEffect, useMemo, useState } from "react";
import {
  assignCamerasToProcessor,
  cancelProcessorCommand,
  createProcessorCommand,
  deleteProcessor,
  generateProcessorCode,
  getCameras,
  listProcessorCommands,
  listProcessors,
  type ProcessorCommandOut,
  type ProcessorOut,
  type SystemMetrics,
  unassignCameraFromProcessor,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Camera = {
  camera_id: number;
  name: string;
  location?: string | null;
};

const COMMANDS = [
  {
    type: "reload_assignments",
    label: "Перезагрузить назначения",
    hint: "Processor сразу перечитает список камер и применит изменения без ожидания poll-интервала.",
  },
  {
    type: "restart_workers",
    label: "Перезапустить обработчики",
    hint: "Остановит и заново поднимет обработчики назначенных камер.",
  },
  {
    type: "refresh_gallery",
    label: "Обновить галерею лиц",
    hint: "Перечитает эмбеддинги персон и обновит их в активных обработчиках.",
  },
  {
    type: "stop_all_cameras",
    label: "Остановить камеры",
    hint: "Остановит все обработчики камер на выбранном Processor до следующего reload/restart.",
  },
  {
    type: "shutdown",
    label: "Перезапустить контейнер",
    hint: "Processor завершит процесс. В Docker он поднимется заново через restart policy.",
  },
] as const;

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
    <div style={{ flex: 1, minWidth: 118 }}>
      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 800, color: "var(--text-strong)" }}>
        {value.toFixed(1)}
        {unit && <span style={{ fontSize: 11, fontWeight: 500 }}> {unit}</span>}
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
    : "нет данных";

  return (
    <div className="summary-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", marginTop: 14 }}>
      <div className="summary-card" style={{ padding: 14 }}>
        <MetricBar
          value={metrics.cpu_percent ?? 0}
          max={100}
          label="CPU"
          unit="%"
          color={(metrics.cpu_percent ?? 0) > 80 ? "#ef4444" : (metrics.cpu_percent ?? 0) > 55 ? "#f59e0b" : "#22c55e"}
        />
      </div>
      <div className="summary-card" style={{ padding: 14 }}>
        <MetricBar
          value={metrics.ram_used_gb ?? 0}
          max={metrics.ram_total_gb ?? 1}
          label="RAM"
          unit={`/ ${(metrics.ram_total_gb ?? 0).toFixed(1)} GB`}
          color={(metrics.ram_percent ?? 0) > 80 ? "#ef4444" : "#22c55e"}
        />
      </div>
      <div className="summary-card" style={{ padding: 14 }}>
        <MetricBar
          value={metrics.gpu_util_percent ?? 0}
          max={100}
          label={metrics.gpu_name ? `GPU: ${metrics.gpu_name.substring(0, 18)}` : "GPU"}
          unit="%"
          color={(metrics.gpu_util_percent ?? 0) > 80 ? "#ef4444" : "#38bdf8"}
        />
      </div>
      <div className="summary-card" style={{ padding: 14 }}>
        <div className="summary-card__label">Сеть</div>
        <div className="summary-card__hint" style={{ marginTop: 8 }}>
          <span style={{ color: "#22c55e" }}>↑{(metrics.net_sent_mbps ?? 0).toFixed(1)}</span>{" "}
          <span style={{ color: "#38bdf8" }}>↓{(metrics.net_recv_mbps ?? 0).toFixed(1)}</span> Мбит/с
        </div>
      </div>
      <div className="summary-card" style={{ padding: 14 }}>
        <div className="summary-card__label">Камеры / аптайм</div>
        <div className="summary-card__hint" style={{ marginTop: 8 }}>
          {metrics.active_cameras ?? 0} камер · {uptimeStr}
        </div>
      </div>
    </div>
  );
}

function timeSince(dateStr?: string | null): string {
  if (!dateStr) return "нет heartbeat";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000));
  if (seconds < 60) return `${seconds}с назад`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}м назад`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}ч назад`;
  return `${Math.floor(seconds / 86400)}д назад`;
}

function isProcessorOnline(processor: ProcessorOut): boolean {
  if (processor.status !== "online" || !processor.last_heartbeat) return false;
  return (Date.now() - new Date(processor.last_heartbeat).getTime()) / 1000 < 90;
}

function statusColor(processor: ProcessorOut): string {
  if (isProcessorOnline(processor)) return "#22c55e";
  if (processor.status === "online") return "#f59e0b";
  if (processor.status === "offline") return "#ef4444";
  return "var(--muted)";
}

function commandLabel(type: string): string {
  return COMMANDS.find((command) => command.type === type)?.label || type;
}

function commandStatusLabel(status: string): string {
  if (status === "pending") return "в очереди";
  if (status === "running") return "выполняется";
  if (status === "succeeded") return "успешно";
  if (status === "failed") return "ошибка";
  if (status === "cancelled") return "отменено";
  return status;
}

function CommandHistory({
  commands,
  onCancel,
}: {
  commands: ProcessorCommandOut[];
  onCancel: (command: ProcessorCommandOut) => void;
}) {
  if (commands.length === 0) {
    return <div className="muted">Команд пока нет. Отправьте первую команду из панели управления.</div>;
  }

  return (
    <div className="list-shell" style={{ gap: 8 }}>
      {commands.map((command) => (
        <div key={command.command_id} className="list-item" style={{ cursor: "default" }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="list-item__title">#{command.command_id} · {commandLabel(command.command_type)}</div>
            <span className="pill">{commandStatusLabel(command.status)}</span>
          </div>
          <div className="list-item__meta">
            Создана: {new Date(command.created_at).toLocaleString()}
            {command.completed_at ? ` · Завершена: ${new Date(command.completed_at).toLocaleString()}` : ""}
          </div>
          {command.error_message && <div className="danger" style={{ marginTop: 8 }}>{command.error_message}</div>}
          {command.result && (
            <code style={{ marginTop: 8, display: "block", color: "var(--muted)", whiteSpace: "pre-wrap" }}>
              {typeof command.result === "string" ? command.result : JSON.stringify(command.result, null, 2)}
            </code>
          )}
          {(command.status === "pending" || command.status === "running") && (
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn secondary" onClick={() => onCancel(command)}>
                Отменить
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

const ProcessorsPage: React.FC = () => {
  const { token } = useAuth();
  const [processors, setProcessors] = useState<ProcessorOut[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [commands, setCommands] = useState<Record<number, ProcessorCommandOut[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedProc, setSelectedProc] = useState<number | null>(null);
  const [connCode, setConnCode] = useState<{ code: string; expires_at: string } | null>(null);
  const [codeLoading, setCodeLoading] = useState(false);
  const [commandLoading, setCommandLoading] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
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

  const loadCommands = useCallback(async (processorId: number) => {
    if (!token) return;
    const items = await listProcessorCommands(token, processorId);
    setCommands((prev) => ({ ...prev, [processorId]: items }));
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (selectedProc) {
      loadCommands(selectedProc).catch(() => undefined);
    }
  }, [loadCommands, selectedProc]);

  const handleDelete = async (id: number) => {
    if (!token || !window.confirm("Удалить Processor из backend? Назначения камер тоже будут удалены.")) return;
    try {
      await deleteProcessor(token, id);
      setSelectedProc(null);
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
      alert(event?.message || "Ошибка снятия назначения");
    }
  };

  const handleCommand = async (processorId: number, commandType: string) => {
    if (!token) return;
    const key = `${processorId}:${commandType}`;
    setCommandLoading(key);
    try {
      await createProcessorCommand(token, processorId, commandType);
      await Promise.all([load(), loadCommands(processorId)]);
    } catch (event: any) {
      alert(event?.message || "Не удалось отправить команду");
    } finally {
      setCommandLoading(null);
    }
  };

  const handleCancelCommand = async (command: ProcessorCommandOut) => {
    if (!token) return;
    try {
      await cancelProcessorCommand(token, command.processor_id, command.command_id);
      await Promise.all([load(), loadCommands(command.processor_id)]);
    } catch (event: any) {
      alert(event?.message || "Не удалось отменить команду");
    }
  };

  const selectedProcessor = processors.find((processor) => processor.processor_id === selectedProc);
  const assignedCamIds = selectedProcessor?.assigned_cameras?.map((camera) => camera.camera_id) ?? [];
  const availableCameras = cameras.filter((camera) => !assignedCamIds.includes(camera.camera_id));

  const stats = useMemo(
    () => ({
      total: processors.length,
      online: processors.filter(isProcessorOnline).length,
      stale: processors.filter((processor) => processor.status === "online" && !isProcessorOnline(processor)).length,
      cameras: processors.reduce((sum, processor) => sum + processor.camera_count, 0),
      pending: processors.reduce((sum, processor) => sum + (processor.pending_commands ?? 0), 0),
      running: processors.reduce((sum, processor) => sum + (processor.running_commands ?? 0), 0),
    }),
    [processors]
  );

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Processing Control Plane</div>
          <h2 className="title">Процессоры</h2>
          <div className="muted">Централизованное управление узлами обработки: статус, нагрузка, камеры и удалённые команды.</div>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
          <button className="btn" onClick={handleGenerateCode} disabled={codeLoading}>
            {codeLoading ? "Генерация..." : "+ Код подключения"}
          </button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Всего узлов</div>
          <div className="summary-card__value">{stats.total}</div>
          <div className="summary-card__hint">Все Processor, зарегистрированные в текущей чистой БД.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Онлайн</div>
          <div className="summary-card__value">{stats.online}/{stats.total}</div>
          <div className="summary-card__hint">{stats.stale > 0 ? `${stats.stale} узл. с просроченным heartbeat.` : "Heartbeat в норме."}</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Назначено камер</div>
          <div className="summary-card__value">{stats.cameras}</div>
          <div className="summary-card__hint">Камеры распределяются централизованно с этой страницы.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Очередь команд</div>
          <div className="summary-card__value">{stats.pending + stats.running}</div>
          <div className="summary-card__hint">{stats.pending} ожидает · {stats.running} выполняется</div>
        </div>
      </section>

      {connCode && (
        <section className="panel-card" style={{ borderColor: "rgba(94, 240, 255, 0.32)" }}>
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Код подключения Processor</h3>
              <div className="panel-card__lead">Действует 24 часа. Введите его в Processor на новом ПК или в Docker-переменную подключения.</div>
            </div>
            <span className="pill">до {new Date(connCode.expires_at).toLocaleString()}</span>
          </div>
          <div style={{ fontSize: 34, fontWeight: 900, letterSpacing: 6, fontFamily: "monospace", marginBottom: 12 }}>
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
              <h3 className="panel-card__title">Processor ещё не подключён</h3>
              <div className="panel-card__lead">
                Сгенерируйте код подключения или запустите встроенный Docker Processor с серверным API-ключом.
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="list-shell" style={{ gap: 16 }}>
          {processors.map((processor) => {
            const isSelected = selectedProc === processor.processor_id;
            const isOnline = isProcessorOnline(processor);
            const color = statusColor(processor);
            const caps = processor.capabilities || {};
            const processorCommands = commands[processor.processor_id] || [];

            return (
              <section key={processor.processor_id} className="panel-card">
                <div className="panel-card__header">
                  <div className="stack" style={{ gap: 8 }}>
                    <div className="row" style={{ gap: 10, alignItems: "center" }}>
                      <span
                        style={{
                          width: 11,
                          height: 11,
                          borderRadius: "50%",
                          background: color,
                          display: "inline-block",
                          boxShadow: isOnline ? "0 0 12px #22c55e" : undefined,
                        }}
                      />
                      <h3 className="panel-card__title" style={{ margin: 0 }}>
                        {processor.name}
                      </h3>
                      <span className="pill" style={{ color }}>
                        {isOnline ? "online" : processor.status}
                      </span>
                      {processor.version && <span className="muted">v{processor.version}</span>}
                    </div>
                    <div className="chip-row">
                      {processor.ip_address && <span className="pill">IP: {processor.ip_address}</span>}
                      {processor.os_info && <span className="pill">{processor.os_info}</span>}
                      {processor.node_uid && <span className="pill">Node: {processor.node_uid.slice(0, 10)}...</span>}
                      {typeof caps.gpu === "string" && <span className="pill">GPU: {caps.gpu}</span>}
                      {typeof caps.inference_device === "string" && <span className="pill">Inference: {caps.inference_device}</span>}
                      {typeof caps.platform_version === "string" && <span className="pill">Build: {caps.platform_version}</span>}
                    </div>
                  </div>

                  <div className="page-actions">
                    <span className="muted">{timeSince(processor.last_heartbeat)}</span>
                    <button className="btn secondary" onClick={() => {
                      setSelectedProc(isSelected ? null : processor.processor_id);
                      if (!isSelected) loadCommands(processor.processor_id).catch(() => undefined);
                    }}>
                      {isSelected ? "Свернуть" : "Управление"}
                    </button>
                    <button className="btn secondary" onClick={() => handleDelete(processor.processor_id)}>
                      Удалить
                    </button>
                  </div>
                </div>

                {processor.metrics && <MetricsPanel metrics={processor.metrics} />}

                <div className="summary-grid" style={{ marginTop: 14, gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                  <div className="summary-card" style={{ padding: 14 }}>
                    <div className="summary-card__label">Камеры</div>
                    <div className="summary-card__value" style={{ fontSize: 24 }}>{processor.camera_count}</div>
                  </div>
                  <div className="summary-card" style={{ padding: 14 }}>
                    <div className="summary-card__label">Команды</div>
                    <div className="summary-card__hint" style={{ marginTop: 8 }}>
                      {processor.pending_commands ?? 0} в очереди · {processor.running_commands ?? 0} выполняется
                    </div>
                  </div>
                  <div className="summary-card" style={{ padding: 14 }}>
                    <div className="summary-card__label">Последняя команда</div>
                    <div className="summary-card__hint" style={{ marginTop: 8 }}>
                      {processor.last_command ? `${commandLabel(processor.last_command.command_type)} · ${commandStatusLabel(processor.last_command.status)}` : "нет команд"}
                    </div>
                  </div>
                </div>

                {isSelected && (
                  <div className="grid" style={{ marginTop: 16, alignItems: "start" }}>
                    <section className="panel-card" style={{ padding: 16 }}>
                      <div className="panel-card__header">
                        <div>
                          <h3 className="panel-card__title">Удалённое управление</h3>
                          <div className="panel-card__lead">Команды ставятся в очередь backend и выполняются самим Processor при следующем poll.</div>
                        </div>
                      </div>
                      <div className="list-shell" style={{ gap: 10 }}>
                        {COMMANDS.map((command) => (
                          <button
                            key={command.type}
                            className="list-item"
                            type="button"
                            disabled={commandLoading === `${processor.processor_id}:${command.type}`}
                            onClick={() => handleCommand(processor.processor_id, command.type)}
                          >
                            <div className="list-item__title">{command.label}</div>
                            <div className="list-item__meta">{command.hint}</div>
                          </button>
                        ))}
                      </div>
                    </section>

                    <section className="panel-card" style={{ padding: 16 }}>
                      <div className="panel-card__header">
                        <div>
                          <h3 className="panel-card__title">Назначенные камеры</h3>
                          <div className="panel-card__lead">Processor применит изменения автоматически или по команде reload.</div>
                        </div>
                      </div>
                      {processor.assigned_cameras.length > 0 ? (
                        <div className="chip-row">
                          {processor.assigned_cameras.map((camera) => (
                            <span key={camera.camera_id} className="pill" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                              {camera.name}
                              <button
                                style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0 }}
                                onClick={() => handleUnassign(processor.processor_id, camera.camera_id)}
                                type="button"
                              >
                                x
                              </button>
                            </span>
                          ))}
                        </div>
                      ) : (
                        <div className="muted">Камеры не назначены.</div>
                      )}

                      <div style={{ height: 16 }} />
                      <h3 className="panel-card__title">Свободные камеры</h3>
                      <div style={{ height: 10 }} />
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
                        <div className="muted">Все камеры уже назначены на этот Processor.</div>
                      )}
                    </section>

                    <section className="panel-card" style={{ padding: 16 }}>
                      <div className="panel-card__header">
                        <div>
                          <h3 className="panel-card__title">История команд</h3>
                          <div className="panel-card__lead">Последние команды, их статусы и ответы Processor.</div>
                        </div>
                        <button className="btn secondary" onClick={() => loadCommands(processor.processor_id)}>
                          Обновить
                        </button>
                      </div>
                      <CommandHistory commands={processorCommands} onCancel={handleCancelCommand} />
                    </section>
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
