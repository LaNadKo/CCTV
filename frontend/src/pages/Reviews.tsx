import { useEffect, useState } from "react";
import {
  API_URL,
  enrollPersonFromPhoto,
  enrollPersonFromSnapshot,
  getPending,
  rejectAllPendingReviews,
  reviewEvent,
} from "../lib/api";
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
  const [bulkBusy, setBulkBusy] = useState(false);
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
      setItems(await getPending(token));
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить ревью.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const handleReview = async (eventId: number, status: "approved" | "rejected") => {
    if (!token) return;
    try {
      const personId = personMap[eventId] ? Number(personMap[eventId]) : undefined;
      await reviewEvent(token, eventId, status, personId);
      setItems((prev) => prev.filter((item) => item.event_id !== eventId));
    } catch (e: any) {
      alert(e?.message || "Ошибка при обработке ревью.");
    }
  };

  const handleRejectAll = async () => {
    if (!token || !items.length) return;
    if (!window.confirm(`Отклонить все события ревью (${items.length})?`)) return;
    setBulkBusy(true);
    try {
      const result = await rejectAllPendingReviews(token);
      await load();
      alert(`Отклонено событий: ${result.updated}`);
    } catch (e: any) {
      alert(e?.message || "Не удалось отклонить все события.");
    } finally {
      setBulkBusy(false);
    }
  };

  const handleEnroll = async () => {
    if (!token || !file) {
      setEnrollMsg("Выберите файл.");
      return;
    }
    try {
      setEnrollMsg("Отправка...");
      const result = await enrollPersonFromPhoto(
        token,
        file,
        firstName || undefined,
        lastName || undefined,
        middleName || undefined
      );
      setEnrollMsg(`Создана персона ID ${result.person_id}`);
      setFile(null);
      setFirstName("");
      setLastName("");
      setMiddleName("");
      await load();
    } catch (e: any) {
      setEnrollMsg(e?.message || "Ошибка при загрузке снимка.");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="title">Ревью</h2>
          <div className="muted">
            Здесь остаются только неизвестные лица. Подтверждённые появления уходят в отчётность, а в карточках ревью
            больше не показываются имена распознанных персон.
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
          <button className="btn secondary" onClick={handleRejectAll} disabled={bulkBusy || items.length === 0}>
            {bulkBusy ? "Отклонение..." : "Отклонить всё"}
          </button>
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Добавить персону из файла</h3>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
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
        <button className="btn" onClick={handleEnroll} disabled={!file}>
          Загрузить и создать персону
        </button>
        {enrollMsg && <div className="muted">{enrollMsg}</div>}
      </div>

      {error && <div className="danger">{error}</div>}

      {loading ? (
        <div className="card">Загрузка...</div>
      ) : items.length === 0 ? (
        <div className="card">Событий на ревью пока нет.</div>
      ) : (
        <div className="grid">
          {items.map((event) => {
            const snapshotAvailable = !!event.snapshot_url && !snapshotErrorMap[event.event_id];
            const recordingUrl = event.recording_file_id
              ? `${API_URL}/recordings/file/${event.recording_file_id}?token=${encodeURIComponent(token || "")}`
              : null;
            return (
              <div key={event.event_id} className="card stack review-card">
                <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div className="stack" style={{ gap: 2 }}>
                    <div className="muted">Event #{event.event_id}</div>
                    <h3 style={{ margin: 0 }}>{event.camera_name || `Камера ${event.camera_id}`}</h3>
                    <div className="muted">{event.camera_location || "Локация не указана"}</div>
                  </div>
                  <span className="pill">{new Date(event.event_ts).toLocaleString()}</span>
                </div>

                <div className="muted">
                  Confidence: {event.confidence != null ? `${Number(event.confidence).toFixed(1)}%` : "n/a"}
                </div>

                {snapshotAvailable ? (
                  <img
                    src={`${API_URL}${event.snapshot_url}`}
                    alt={`event-${event.event_id}`}
                    loading="lazy"
                    className="review-snapshot"
                    onError={() =>
                      setSnapshotErrorMap((prev) => ({
                        ...prev,
                        [event.event_id]: true,
                      }))
                    }
                  />
                ) : (
                  <div className="review-snapshot review-snapshot-empty">Снимок пока недоступен.</div>
                )}

                {event.recording_file_id && (
                  videoOpenMap[event.event_id] ? (
                    <div className="stack" style={{ gap: 8 }}>
                      <video
                        src={recordingUrl || undefined}
                        className="review-video"
                        controls
                        preload="metadata"
                        playsInline
                      />
                      <a className="btn secondary" href={recordingUrl || undefined} target="_blank" rel="noreferrer">
                        Оригинальный файл
                      </a>
                    </div>
                  ) : (
                    <button
                      className="btn secondary"
                      onClick={() => setVideoOpenMap((prev) => ({ ...prev, [event.event_id]: true }))}
                    >
                      Открыть видео
                    </button>
                  )
                )}

                <label className="field">
                  <span className="label">Назначить person_id (если знаете)</span>
                  <input
                    className="input"
                    value={personMap[event.event_id] || ""}
                    onChange={(e) => setPersonMap((prev) => ({ ...prev, [event.event_id]: e.target.value }))}
                    placeholder="ID персоны"
                  />
                </label>

                {event.snapshot_url && !snapshotErrorMap[event.event_id] && (
                  <div className="stack">
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
                          const result = await enrollPersonFromSnapshot(token, {
                            event_id: event.event_id,
                            last_name: fio[0],
                            first_name: fio[1],
                            middle_name: fio[2],
                          });
                          alert(`Создана персона ID ${result.person_id}`);
                          await load();
                        } catch (e: any) {
                          alert(e?.message || "Не удалось создать персону.");
                        }
                      }}
                    >
                      Персона из снимка
                    </button>
                  </div>
                )}

                <div className="row" style={{ gap: 8 }}>
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
        </div>
      )}
    </div>
  );
};

export default ReviewsPage;
