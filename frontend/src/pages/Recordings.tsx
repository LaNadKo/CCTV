import { useEffect, useMemo, useState } from "react";
import { API_URL, getCameras, getTimeline, listRecordings, recordingSnapshotUrl } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type DbRec = {
  recording_file_id: number;
  camera_id: number;
  video_stream_id: number;
  file_kind: string;
  file_path: string;
  started_at: string;
  ended_at?: string;
  duration_seconds?: number;
  file_size_bytes?: number;
  checksum?: string;
};

type TimelineEvent = {
  event_id: number;
  camera_id: number;
  event_ts: string;
  person_id?: number | null;
  event_type: string;
};

const HOURS = Array.from({ length: 24 }, (_, index) => index);

const formatDuration = (value?: number) => {
  if (!value) return "0 с";
  if (value < 60) return `${Math.round(value)} с`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes} мин ${seconds.toString().padStart(2, "0")} с`;
};

const formatBytes = (value?: number) => {
  if (!value) return "-";
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} КБ`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} МБ`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} ГБ`;
};

const RecordingsPage: React.FC = () => {
  const { token } = useAuth();
  const [records, setRecords] = useState<DbRec[]>([]);
  const [cameras, setCameras] = useState<{ camera_id: number; name: string; location?: string }[]>([]);
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [selectedHour, setSelectedHour] = useState<number | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [videoOpenMap, setVideoOpenMap] = useState<Record<number, boolean>>({});
  const [snapshotMissingMap, setSnapshotMissingMap] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const cams = await getCameras(token);
      const mapped = cams.map((camera) => ({
        camera_id: camera.camera_id,
        name: camera.name,
        location: camera.location,
      }));
      setCameras(mapped);
      const activeCameraId = cameraId ?? mapped[0]?.camera_id ?? null;
      if (activeCameraId !== null) {
        setCameraId(activeCameraId);
      }

      const dayFrom = `${selectedDate}T00:00:00`;
      const dayTo = `${selectedDate}T23:59:59`;
      const [recordingItems, timelineItems] = await Promise.all([
        listRecordings(token, activeCameraId ?? undefined, dayFrom, dayTo),
        getTimeline(token, activeCameraId ?? undefined, dayFrom, dayTo),
      ]);

      const sorted = [...recordingItems].sort(
        (left, right) => new Date(left.started_at).getTime() - new Date(right.started_at).getTime()
      );

      setRecords(sorted);
      setTimeline(timelineItems);

      if (selectedHour === null && sorted.length > 0) {
        setSelectedHour(new Date(sorted[0].started_at).getHours());
      } else if (selectedHour !== null && !sorted.some((record) => new Date(record.started_at).getHours() === selectedHour)) {
        setSelectedHour(sorted.length ? new Date(sorted[0].started_at).getHours() : null);
      }
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить записи.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token, cameraId, selectedDate]);

  const activeCamera = useMemo(
    () => cameras.find((camera) => camera.camera_id === cameraId) || null,
    [cameraId, cameras]
  );

  const byHour = useMemo(() => {
    const map: Record<number, DbRec[]> = {};
    for (const hour of HOURS) map[hour] = [];
    for (const record of records) {
      const hour = new Date(record.started_at).getHours();
      map[hour].push(record);
    }
    return map;
  }, [records]);

  const selectedHourRecords = useMemo(() => {
    if (selectedHour === null) return records;
    return byHour[selectedHour] || [];
  }, [byHour, selectedHour, records]);

  const timelineMarks = useMemo(() => {
    return timeline.map((event) => {
      const dt = new Date(event.event_ts);
      const seconds = dt.getHours() * 3600 + dt.getMinutes() * 60 + dt.getSeconds();
      const color =
        event.event_type === "face_recognized"
          ? "#22c55e"
          : event.event_type === "face_unknown"
            ? "#f97316"
            : "#38bdf8";
      return { left: (seconds / 86400) * 100, color };
    });
  }, [timeline]);

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="title">Записи</h2>
          <div className="muted">Клипы хранятся на Processor и подтягиваются по выбранной дате через backend-прокси.</div>
        </div>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <select
            className="input"
            value={cameraId ?? ""}
            onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : null)}
            style={{ minWidth: 220 }}
          >
            {cameras.map((camera) => (
              <option key={camera.camera_id} value={camera.camera_id}>
                {camera.name} (#{camera.camera_id})
              </option>
            ))}
          </select>
          <input type="date" className="input" value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)} />
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
        </div>
      </div>

      {error && <div className="danger">{error}</div>}
      {loading && <div className="card">Загрузка...</div>}

      {!loading && (
        <>
          <div className="card stack">
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <div className="stack" style={{ gap: 4 }}>
                <h3 style={{ margin: 0 }}>Таймлайн</h3>
                <div className="muted">Зелёный — подтверждённое лицо, оранжевый — неизвестное лицо.</div>
              </div>
              <span className="pill">{timeline.length} событий</span>
            </div>
            <div className="timeline-bar" style={{ height: 22 }}>
              {timelineMarks.map((mark, index) => (
                <div
                  key={`${mark.left}-${index}`}
                  className="timeline-mark"
                  style={{ left: `${mark.left}%`, background: mark.color, height: 18, top: 2 }}
                />
              ))}
            </div>
          </div>

          <div className="card stack">
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <div className="stack" style={{ gap: 4 }}>
                <h3 style={{ margin: 0 }}>Вся лента</h3>
                <div className="muted">{activeCamera?.name || "Камера не выбрана"} · {activeCamera?.location || "Локация не указана"}</div>
              </div>
              <span className="pill">{records.length} клипов</span>
            </div>

            <div className="recording-hours-grid">
              {HOURS.map((hour) => {
                const items = byHour[hour] || [];
                const active = selectedHour === hour;
                return (
                  <button
                    key={hour}
                    className={`hour-card${active ? " active" : ""}`}
                    onClick={() => setSelectedHour(hour)}
                  >
                    <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                      <div style={{ fontWeight: 700 }}>{String(hour).padStart(2, "0")}:00</div>
                      <span className="pill" style={{ color: items.length ? "#22c55e" : "var(--muted)" }}>
                        {items.length ? `${items.length} шт` : "нет"}
                      </span>
                    </div>
                    <div className="muted" style={{ marginTop: 8 }}>
                      {items.length ? "Открыть" : "Клипов нет"}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="card stack">
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>
                {selectedHour !== null ? `Клипы за ${String(selectedHour).padStart(2, "0")}:00` : "Клипы"}
              </h3>
              {selectedHour !== null && <button className="btn secondary" onClick={() => setSelectedHour(null)}>Показать все</button>}
            </div>

            {selectedHourRecords.length === 0 ? (
              <div className="muted">Клипов за выбранный час нет.</div>
            ) : (
              <div className="recordings-clips-grid">
                {selectedHourRecords.map((record) => {
                  const startedAt = new Date(record.started_at);
                  const fileUrl = `${API_URL}/recordings/file/${record.recording_file_id}?token=${encodeURIComponent(token || "")}`;
                  const snapshotUrl = recordingSnapshotUrl(
                    record.recording_file_id,
                    token || "",
                    record.duration_seconds ? Math.max(Math.floor(record.duration_seconds / 2), 1) : undefined
                  );
                  const snapshotMissing = snapshotMissingMap[record.recording_file_id];

                  return (
                    <div key={record.recording_file_id} className="record-card stack" style={{ gap: 10 }}>
                      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                        <div className="stack" style={{ gap: 2 }}>
                          <div style={{ fontWeight: 700 }}>{startedAt.toLocaleTimeString()}</div>
                          <div className="muted">
                            {formatDuration(record.duration_seconds)} · {formatBytes(record.file_size_bytes)}
                          </div>
                        </div>
                        <span className="pill">#{record.recording_file_id}</span>
                      </div>

                      {!videoOpenMap[record.recording_file_id] ? (
                        snapshotMissing ? (
                          <div className="recordings-thumb recordings-thumb-empty">Превью недоступно</div>
                        ) : (
                          <img
                            src={snapshotUrl}
                            alt={`record-${record.recording_file_id}`}
                            loading="lazy"
                            className="recordings-thumb"
                            onError={() =>
                              setSnapshotMissingMap((prev) => ({
                                ...prev,
                                [record.recording_file_id]: true,
                              }))
                            }
                          />
                        )
                      ) : (
                        <video
                          className="recordings-thumb"
                          src={fileUrl}
                          controls
                          preload="metadata"
                          playsInline
                        />
                      )}

                      <div className="row" style={{ justifyContent: "space-between" }}>
                        {!videoOpenMap[record.recording_file_id] ? (
                          <button
                            className="btn secondary"
                            onClick={() =>
                              setVideoOpenMap((prev) => ({
                                ...prev,
                                [record.recording_file_id]: true,
                              }))
                            }
                          >
                            Открыть
                          </button>
                        ) : (
                          <a className="btn secondary" href={fileUrl} target="_blank" rel="noreferrer">
                            Оригинальный файл
                          </a>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default RecordingsPage;
