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

const formatDuration = (value?: number) => {
  if (!value) return "0 c";
  if (value < 60) return `${Math.round(value)} c`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes} мин ${seconds.toString().padStart(2, "0")} c`;
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
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [videoOpenMap, setVideoOpenMap] = useState<Record<number, boolean>>({});
  const [fallbackMap, setFallbackMap] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const cams = await getCameras(token);
      const mappedCameras = cams.map((camera) => ({
        camera_id: camera.camera_id,
        name: camera.name,
        location: camera.location,
      }));
      setCameras(mappedCameras);

      const activeCameraId = cameraId ?? mappedCameras[0]?.camera_id ?? null;
      if (activeCameraId !== null) {
        setCameraId(activeCameraId);
      }

      const dayFrom = `${selectedDate}T00:00:00`;
      const dayTo = `${selectedDate}T23:59:59`;

      const [recordingItems, timelineItems] = await Promise.all([
        listRecordings(token, activeCameraId ?? undefined, dayFrom, dayTo),
        getTimeline(token, activeCameraId ?? undefined, dayFrom, dayTo),
      ]);

      setRecords(
        [...recordingItems].sort(
          (left, right) => new Date(right.started_at).getTime() - new Date(left.started_at).getTime()
        )
      );
      setTimeline(timelineItems);
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

  const summary = useMemo(() => {
    const totalDuration = records.reduce((sum, record) => sum + (record.duration_seconds || 0), 0);
    const faceEvents = timeline.filter((event) => event.event_type.includes("face")).length;
    return {
      clipCount: records.length,
      totalDuration,
      faceEvents,
    };
  }, [records, timeline]);

  const timelineMarks = useMemo(() => {
    return timeline.map((event) => {
      const dt = new Date(event.event_ts);
      const seconds = dt.getHours() * 3600 + dt.getMinutes() * 60 + dt.getSeconds();
      const color = event.event_type === "face_recognized" ? "#22c55e" : event.event_type === "face_unknown" ? "#f97316" : "#3b82f6";
      return { left: (seconds / 86400) * 100, color };
    });
  }, [timeline]);

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="title">Записи</h2>
          <div className="muted">Клипы хранятся на Processor и подтягиваются за выбранную дату.</div>
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
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
            <div className="card stack" style={{ gap: 4 }}>
              <div className="muted">Камера</div>
              <div style={{ fontWeight: 700 }}>{activeCamera?.name || "Не выбрана"}</div>
              <div className="muted">{activeCamera?.location || "Локация не указана"}</div>
            </div>
            <div className="card stack" style={{ gap: 4 }}>
              <div className="muted">Клипов за день</div>
              <div style={{ fontWeight: 700, fontSize: 24 }}>{summary.clipCount}</div>
            </div>
            <div className="card stack" style={{ gap: 4 }}>
              <div className="muted">Суммарная длительность</div>
              <div style={{ fontWeight: 700, fontSize: 24 }}>{formatDuration(summary.totalDuration)}</div>
            </div>
            <div className="card stack" style={{ gap: 4 }}>
              <div className="muted">Событий на таймлайне</div>
              <div style={{ fontWeight: 700, fontSize: 24 }}>{summary.faceEvents}</div>
            </div>
          </div>

          <div className="card">
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <div className="stack" style={{ gap: 4 }}>
                <h3 style={{ margin: 0 }}>Таймлайн событий</h3>
                <div className="muted">Зелёный — распознано, оранжевый — неизвестное лицо.</div>
              </div>
              <span className="pill">{timeline.length} событий</span>
            </div>
            <div style={{ position: "relative", height: 28, marginTop: 12, background: "#0d1b2a", borderRadius: 8 }}>
              {timelineMarks.map((mark, index) => (
                <div
                  key={`${mark.left}-${index}`}
                  style={{
                    position: "absolute",
                    left: `${mark.left}%`,
                    top: 2,
                    width: 4,
                    height: 24,
                    background: mark.color,
                    borderRadius: 999,
                  }}
                />
              ))}
            </div>
          </div>

          {records.length === 0 ? (
            <div className="card">За выбранный день клипов пока нет.</div>
          ) : (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))" }}>
              {records.map((record) => {
                const startedAt = new Date(record.started_at);
                const endedAt = record.ended_at
                  ? new Date(record.ended_at)
                  : new Date(startedAt.getTime() + (record.duration_seconds || 0) * 1000);
                const eventsInside = timeline.filter((event) => {
                  const ts = new Date(event.event_ts).getTime();
                  return ts >= startedAt.getTime() && ts <= endedAt.getTime();
                });
                const fileUrl = `${API_URL}/recordings/file/${record.recording_file_id}?token=${encodeURIComponent(token || "")}`;
                const mjpegUrl = `${API_URL}/recordings/file/${record.recording_file_id}/mjpeg?token=${encodeURIComponent(token || "")}`;
                const snapshotUrl = recordingSnapshotUrl(
                  record.recording_file_id,
                  token || "",
                  record.duration_seconds ? Math.max(Math.floor(record.duration_seconds / 2), 1) : undefined
                );
                const fallback = fallbackMap[record.recording_file_id];
                return (
                  <div key={record.recording_file_id} className="card stack" style={{ gap: 10 }}>
                    <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                      <div className="stack" style={{ gap: 2 }}>
                        <h3 style={{ margin: 0 }}>{startedAt.toLocaleTimeString()}</h3>
                        <div className="muted">
                          {startedAt.toLocaleDateString()} · {formatDuration(record.duration_seconds)}
                        </div>
                      </div>
                      <span className="pill">{eventsInside.length} событий</span>
                    </div>

                    {!videoOpenMap[record.recording_file_id] ? (
                      <img
                        src={snapshotUrl}
                        alt={`clip-${record.recording_file_id}`}
                        loading="lazy"
                        style={{
                          width: "100%",
                          aspectRatio: "16 / 9",
                          objectFit: "cover",
                          borderRadius: 10,
                          background: "#0d1b2a",
                        }}
                      />
                    ) : fallback ? (
                      <img
                        src={mjpegUrl}
                        alt={`clip-mjpeg-${record.recording_file_id}`}
                        style={{
                          width: "100%",
                          aspectRatio: "16 / 9",
                          objectFit: "cover",
                          borderRadius: 10,
                          background: "#0d1b2a",
                        }}
                      />
                    ) : (
                      <video
                        controls
                        preload="none"
                        poster={snapshotUrl}
                        style={{
                          width: "100%",
                          aspectRatio: "16 / 9",
                          borderRadius: 10,
                          background: "#0d1b2a",
                        }}
                        onError={() =>
                          setFallbackMap((prev) => ({
                            ...prev,
                            [record.recording_file_id]: true,
                          }))
                        }
                      >
                        <source src={fileUrl} type="video/mp4" />
                      </video>
                    )}

                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <div className="muted">Размер: {formatBytes(record.file_size_bytes)}</div>
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
                          Открыть видео
                        </button>
                      ) : fallback ? (
                        <button
                          className="btn secondary"
                          onClick={() =>
                            setFallbackMap((prev) => ({
                              ...prev,
                              [record.recording_file_id]: false,
                            }))
                          }
                        >
                          Попробовать MP4
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default RecordingsPage;
