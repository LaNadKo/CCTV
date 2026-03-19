import { useEffect, useState } from "react";
import { API_URL, enrollPersonFromPhoto, enrollPersonFromSnapshot, getPending, reviewEvent } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Pending = {
  event_id: number;
  camera_id: number;
  camera_name?: string | null;
  camera_location?: string | null;
  event_type_id: number;
  event_ts: string;
  person_id?: number;
  person_label?: string;
  recording_file_id?: number;
  confidence?: number | null;
  snapshot_url?: string | null;
};

const ReviewsPage: React.FC = () => {
  const { token } = useAuth();
  const [items, setItems] = useState<Pending[]>([]);
  const [personMap, setPersonMap] = useState<Record<number, string>>({});
  const [fioMap, setFioMap] = useState<Record<number, string>>({});
  const [videoOpenMap, setVideoOpenMap] = useState<Record<number, boolean>>({});
  const [snapshotErrorMap, setSnapshotErrorMap] = useState<Record<number, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [middleName, setMiddleName] = useState("");
  const [enrollMsg, setEnrollMsg] = useState<string | null>(null);

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getPending(token);
      setItems(res);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить ревью");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const handleReview = async (eventId: number, status: "approved" | "rejected") => {
    if (!token) return;
    const personId = personMap[eventId] ? Number(personMap[eventId]) : undefined;
    try {
      await reviewEvent(token, eventId, status, personId);
      setItems((prev) => prev.filter((item) => item.event_id !== eventId));
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  const handleEnroll = async () => {
    if (!token || !file) {
      setEnrollMsg("Выберите файл");
      return;
    }
    try {
      setEnrollMsg("Отправка...");
      const res = await enrollPersonFromPhoto(
        token,
        file,
        firstName || undefined,
        lastName || undefined,
        middleName || undefined
      );
      setEnrollMsg(`Создан person_id=${res.person_id}`);
      setFile(null);
      setFirstName("");
      setLastName("");
      setMiddleName("");
      await load();
    } catch (e: any) {
      setEnrollMsg(e?.message || "Ошибка при загрузке");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h2 className="title">Ревью</h2>
          <div className="muted">Сюда попадают только неизвестные лица. После подтверждения событие попадет в отчётность.</div>
        </div>
        <button className="btn secondary" onClick={load}>
          Обновить
        </button>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <h3 style={{ marginTop: 0 }}>Добавить персону из файла</h3>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 8 }}>
          <label className="field">
            <span className="label">Файл (jpg/png)</span>
            <input className="input" type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <label className="field">
            <span className="label">Фамилия</span>
            <input className="input" value={lastName} onChange={(e) => setLastName(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Имя</span>
            <input className="input" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Отчество</span>
            <input className="input" value={middleName} onChange={(e) => setMiddleName(e.target.value)} />
          </label>
        </div>
        <button className="btn" style={{ marginTop: 10 }} onClick={handleEnroll} disabled={!file}>
          Загрузить и создать персону
        </button>
        {enrollMsg && (
          <div className="muted" style={{ marginTop: 6 }}>
            {enrollMsg}
          </div>
        )}
      </div>

      {error && <div className="danger">{error}</div>}
      {loading ? (
        <div className="card">Загрузка...</div>
      ) : (
        <div className="grid">
          {items.map((event) => {
            const cameraLabel = event.camera_name || `Камера ${event.camera_id}`;
            const snapshotAvailable = !!event.snapshot_url && !snapshotErrorMap[event.event_id];
            return (
              <div key={event.event_id} className="card">
                <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div className="stack" style={{ gap: 2 }}>
                    <div className="muted">Событие #{event.event_id}</div>
                    <h3 style={{ margin: 0 }}>{cameraLabel}</h3>
                    <div className="muted">{event.camera_location || "Локация не указана"}</div>
                  </div>
                  <span className="pill">{new Date(event.event_ts).toLocaleString()}</span>
                </div>

                <div className="muted" style={{ marginTop: 8 }}>
                  Уверенность детекции: {event.confidence != null ? event.confidence.toFixed(2) : "n/a"}
                </div>

                <div className="grid" style={{ marginTop: 10, gap: 8, gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))" }}>
                  {snapshotAvailable ? (
                    <div className="stack">
                      <span className="label">Снимок</span>
                      <img
                        src={`${API_URL}${event.snapshot_url}`}
                        alt={`event-${event.event_id}`}
                        loading="lazy"
                        style={{ width: "100%", minHeight: 180, borderRadius: 8, background: "#0d1b2a", objectFit: "cover" }}
                        onError={() =>
                          setSnapshotErrorMap((prev) => ({
                            ...prev,
                            [event.event_id]: true,
                          }))
                        }
                      />
                    </div>
                  ) : (
                    <div className="stack">
                      <span className="label">Снимок</span>
                      <div
                        className="muted"
                        style={{
                          minHeight: 180,
                          borderRadius: 8,
                          border: "1px dashed var(--border)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          padding: 12,
                          background: "#0d1b2a",
                          textAlign: "center",
                        }}
                      >
                        Снимок пока недоступен.
                      </div>
                    </div>
                  )}

                  {event.recording_file_id && (
                    <div className="stack">
                      <span className="label">Видео</span>
                      {videoOpenMap[event.event_id] ? (
                        <video controls preload="none" style={{ width: "100%", borderRadius: 8, background: "#0d1b2a", minHeight: 180 }}>
                          <source
                            src={`${API_URL}/recordings/file/${event.recording_file_id}?token=${encodeURIComponent(token || "")}`}
                            type="video/mp4"
                          />
                        </video>
                      ) : (
                        <button
                          className="btn secondary"
                          style={{ minHeight: 180 }}
                          onClick={() => setVideoOpenMap((prev) => ({ ...prev, [event.event_id]: true }))}
                        >
                          Открыть видео
                        </button>
                      )}
                    </div>
                  )}
                </div>

                <div className="field" style={{ marginTop: 10 }}>
                  <span className="label">Назначить person_id (если знаете)</span>
                  <input
                    className="input"
                    value={personMap[event.event_id] || ""}
                    onChange={(e) => setPersonMap((prev) => ({ ...prev, [event.event_id]: e.target.value }))}
                    placeholder="ID персоны"
                  />
                </div>

                {event.snapshot_url && !snapshotErrorMap[event.event_id] && (
                  <div className="stack" style={{ marginTop: 10 }}>
                    <span className="label">Создать персону из снимка (ФИО опционально)</span>
                    <input
                      className="input"
                      placeholder="Фамилия Имя Отчество"
                      value={fioMap[event.event_id] || ""}
                      onChange={(e) => setFioMap((prev) => ({ ...prev, [event.event_id]: e.target.value }))}
                    />
                    <button
                      className="btn secondary"
                      onClick={async () => {
                        if (!token) return;
                        const fio = (fioMap[event.event_id] || "").trim().split(" ").filter(Boolean);
                        try {
                          const res = await enrollPersonFromSnapshot(token, {
                            event_id: event.event_id,
                            last_name: fio[0],
                            first_name: fio[1],
                            middle_name: fio[2],
                          });
                          alert(`Создан person_id=${res.person_id}`);
                          await load();
                        } catch (err: any) {
                          alert(err?.message || "Не удалось создать персону");
                        }
                      }}
                    >
                      Персона из снимка
                    </button>
                  </div>
                )}

                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn" onClick={() => handleReview(event.event_id, "approved")}>
                    Одобрить
                  </button>
                  <button className="btn secondary" onClick={() => handleReview(event.event_id, "rejected")}>
                    Отклонить
                  </button>
                </div>
              </div>
            );
          })}
          {items.length === 0 && <div className="card">Пока нет событий на ревью.</div>}
        </div>
      )}
    </div>
  );
};

export default ReviewsPage;
