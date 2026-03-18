import { useEffect, useMemo, useRef, useState } from "react";
import { listRecordings, recordingSnapshotUrl, getTimeline, getCameras, API_URL } from "../lib/api";
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

const RecordingsPage: React.FC = () => {
  const { token } = useAuth();
  const [records, setRecords] = useState<DbRec[]>([]);
  const [cameras, setCameras] = useState<{ camera_id: number; name: string }[]>([]);
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(() => {
    const d = new Date();
    return d.toISOString().slice(0, 10);
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [fallbackMap, setFallbackMap] = useState<Record<number, boolean>>({});
  const allVideoRef = useRef<HTMLDivElement | null>(null);
  const [selectedHour, setSelectedHour] = useState<number | null>(null);

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const cams = await getCameras(token);
      setCameras(cams.map((c) => ({ camera_id: c.camera_id, name: c.name })));
      const cam = cameraId ?? cams[0]?.camera_id ?? null;
      if (cam !== null) setCameraId(cam);

      const recs = await listRecordings(token, cam ?? undefined);
      setRecords(recs);

      const dayFrom = selectedDate ? `${selectedDate}T00:00:00` : undefined;
      const dayTo = selectedDate ? `${selectedDate}T23:59:59` : undefined;
      const tl = await getTimeline(token, cam ?? undefined, dayFrom, dayTo);
      setTimeline(tl);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить записи.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, cameraId, selectedDate]);

  const recordsForDay = useMemo(() => {
    if (!selectedDate) return [];
    return records.filter((r) => r.started_at.slice(0, 10) === selectedDate);
  }, [records, selectedDate]);

  const eventsByDay = useMemo(() => {
    if (!selectedDate) return [];
    return timeline.filter((e) => e.event_ts.slice(0, 10) === selectedDate);
  }, [timeline, selectedDate]);

  const groupedByHour = useMemo(() => {
    const map: Record<number, DbRec[]> = {};
    recordsForDay.forEach((r) => {
      const h = new Date(r.started_at).getHours();
      if (!map[h]) map[h] = [];
      map[h].push(r);
    });
    Object.values(map).forEach((arr) => arr.sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime()));
    return map;
  }, [recordsForDay]);

  const timelineMarks = useMemo(() => {
    return eventsByDay.map((e) => {
      const d = new Date(e.event_ts);
      const sec = d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
      const type = e.event_type;
      const color = type === "face_recognized" ? "#22c55e" : type === "face_unknown" ? "#f97316" : "#3b82f6";
      return { left: (sec / 86400) * 100, color };
    });
  }, [eventsByDay]);

  const scrollToAllVideo = () => {
    allVideoRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="title">Записи</h2>
          <div className="muted">Выберите камеру и день</div>
        </div>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <select
            className="input"
            value={cameraId ?? ""}
            onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : null)}
            style={{ minWidth: 200 }}
          >
            {cameras.map((c) => (
              <option key={c.camera_id} value={c.camera_id}>
                {c.name} (#{c.camera_id})
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

      {!loading && recordsForDay.length === 0 && <div className="card">Записей за выбранный день нет.</div>}

      {!loading && recordsForDay.length > 0 && (
        <>
          <div className="card">
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <div className="stack" style={{ gap: 4 }}>
                <h3 style={{ margin: 0 }}>Таймлайн</h3>
                <div className="muted">Метки распознанных/неизвестных лиц</div>
              </div>
              <button className="btn secondary" onClick={scrollToAllVideo}>
                Воспроизведение всех видео
              </button>
            </div>
            <div style={{ position: "relative", height: 28, marginTop: 12, background: "#0d1b2a", borderRadius: 8 }}>
              {timelineMarks.map((m, idx) => (
                <div
                  key={idx}
                  title={m.color === "#22c55e" ? "Распознано" : "Неизвестное лицо"}
                  style={{
                    position: "absolute",
                    left: `${m.left}%`,
                    top: 2,
                    width: 3,
                    height: 24,
                    background: m.color,
                    borderRadius: 2,
                  }}
                />
              ))}
            </div>
          </div>

          <div ref={allVideoRef} className="card" style={{ marginTop: 12 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <h3 style={{ margin: 0 }}>Все видео</h3>
              <span className="pill">{recordsForDay.length} клипов</span>
            </div>
            <div className="hour-grid">
              {Array.from({ length: 24 }).map((_, h) => {
                const recs = groupedByHour[h] || [];
                const hasFace = eventsByDay.some((e) => new Date(e.event_ts).getHours() === h && e.event_type.includes("face"));
                const active = selectedHour === h;
                return (
                  <button
                    key={h}
                    className={`hour-card${active ? " active" : ""}`}
                    onClick={() => recs.length > 0 && setSelectedHour(active ? null : h)}
                    disabled={recs.length === 0}
                  >
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <div className="muted">{h.toString().padStart(2, "0")}:00</div>
                      <span className="pill" style={{ background: hasFace ? "#22c55e22" : undefined, color: hasFace ? "#22c55e" : undefined }}>
                        {recs.length ? `${recs.length} шт` : "нет"}
                      </span>
                    </div>
                    <div className="muted" style={{ marginTop: 6 }}>{recs.length ? "Открыть" : "Клипов нет"}</div>
                  </button>
                );
              })}
            </div>

            {selectedHour !== null && (groupedByHour[selectedHour]?.length ?? 0) > 0 && (
              <div className="stack" style={{ marginTop: 16, gap: 8 }}>
                <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                  <h4 style={{ margin: 0 }}>Клипы за {selectedHour.toString().padStart(2, "0")}:00</h4>
                  <button className="btn secondary" onClick={() => setSelectedHour(null)}>Свернуть</button>
                </div>
                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 10 }}>
                  {(groupedByHour[selectedHour] || []).map((r) => {
                    const start = new Date(r.started_at);
                    const endMs = r.duration_seconds ? start.getTime() + r.duration_seconds * 1000 : start.getTime();
                    const recEvents = eventsByDay.filter(
                      (e) => new Date(e.event_ts).getTime() >= start.getTime() && new Date(e.event_ts).getTime() <= endMs
                    );
                    const hasFaceInClip = recEvents.some((e) => e.event_type.includes("face"));
                    const snapshot = recordingSnapshotUrl(
                      r.recording_file_id,
                      token || "",
                      r.duration_seconds ? Math.floor(r.duration_seconds / 2) : undefined
                    );
                    const fileUrl = `${API_URL}/recordings/file/${r.recording_file_id}?token=${encodeURIComponent(token || "")}`;
                    const mjpegUrl = `${API_URL}/recordings/file/${r.recording_file_id}/mjpeg?token=${encodeURIComponent(token || "")}`;
                    const fallback = fallbackMap[r.recording_file_id];
                    return (
                      <div
                        key={r.recording_file_id}
                        className="stack clip-card"
                        style={{
                          border: hasFaceInClip ? "1px solid #22c55e55" : undefined,
                        }}
                      >
                        <div className="muted" style={{ fontSize: 12 }}>
                          {start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                        </div>
                        {!fallback ? (
                          <video
                            controls
                            preload="none"
                            style={{ width: "100%", borderRadius: 10, background: "#0d1b2a" }}
                            poster={snapshot}
                            onError={() => setFallbackMap((p) => ({ ...p, [r.recording_file_id]: true }))}
                          >
                            <source src={fileUrl} type="video/mp4" />
                          </video>
                        ) : (
                          <div className="stack" style={{ gap: 4 }}>
                            <img
                              alt="mjpeg-stream"
                              style={{ width: "100%", borderRadius: 8, background: "#0d1b2a" }}
                              src={mjpegUrl}
                            />
                            <button className="btn secondary" onClick={() => setFallbackMap((p) => ({ ...p, [r.recording_file_id]: false }))}>
                              Попробовать MP4
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default RecordingsPage;
