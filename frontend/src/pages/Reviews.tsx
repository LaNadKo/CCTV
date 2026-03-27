import { useEffect, useMemo, useState } from "react";
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
    } catch (event: any) {
      setError(event?.message || "Не удалось загрузить ревью.");
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
    } catch (event: any) {
      alert(event?.message || "Ошибка при обработке ревью.");
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
    } catch (event: any) {
      alert(event?.message || "Не удалось отклонить все события.");
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
    } catch (event: any) {
      setEnrollMsg(event?.message || "Ошибка при загрузке снимка.");
    }
  };

  const stats = useMemo(
    () => ({
      withSnapshots: items.filter((item) => item.snapshot_url).length,
      withVideo: items.filter((item) => item.recording_file_id).length,
    }),
    [items]
  );

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Review Flow</div>
          <h2 className="title">Ревью</h2>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
          <button className="btn secondary" onClick={handleRejectAll} disabled={bulkBusy || items.length === 0}>
            {bulkBusy ? "Отклоняем..." : "Отклонить всё"}
          </button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Ожидают ревью</div>
          <div className="summary-card__value">{items.length}</div>
          <div className="summary-card__hint">Все текущие события, которые ещё не были подтверждены или отклонены.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Со снимком</div>
          <div className="summary-card__value">{stats.withSnapshots}</div>
          <div className="summary-card__hint">Карточки, где уже есть snapshot для быстрого решения по событию.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">С видео</div>
          <div className="summary-card__value">{stats.withVideo}</div>
          <div className="summary-card__hint">События, для которых доступна запись и можно открыть первоисточник.</div>
        </div>
      </section>

      <section className="admin-two-column">
        <div className="panel-card stack">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Добавить персону из файла</h3>
              <div className="panel-card__lead">Если нужно быстро завести человека без текущего snapshot из ревью.</div>
            </div>
          </div>

          <label className="field">
            <span className="label">Файл (jpg/png)</span>
            <input className="input" type="file" accept="image/*" onChange={(event) => setFile(event.target.files?.[0] || null)} />
          </label>
          <label className="field">
            <span className="label">Фамилия</span>
            <input className="input" value={lastName} onChange={(event) => setLastName(event.target.value)} />
          </label>
          <label className="field">
            <span className="label">Имя</span>
            <input className="input" value={firstName} onChange={(event) => setFirstName(event.target.value)} />
          </label>
          <label className="field">
            <span className="label">Отчество</span>
            <input className="input" value={middleName} onChange={(event) => setMiddleName(event.target.value)} />
          </label>
          <button className="btn" onClick={handleEnroll} disabled={!file}>
            Загрузить и создать персону
          </button>
          {enrollMsg && <div className="muted">{enrollMsg}</div>}
        </div>

        <div className="panel-card">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Очередь событий</h3>
              <div className="panel-card__lead">Снимки, видео и быстрые действия по каждой карточке ревью.</div>
            </div>
            <span className="pill">{items.length}</span>
          </div>

          {error && <div className="danger">{error}</div>}

          {loading ? (
            <div className="muted">Загрузка...</div>
          ) : items.length === 0 ? (
            <div className="muted">Событий на ревью пока нет.</div>
          ) : (
            <div className="review-grid">
              {items.map((item) => {
                const snapshotAvailable = !!item.snapshot_url && !snapshotErrorMap[item.event_id];
                const recordingUrl = item.recording_file_id
                  ? `${API_URL}/recordings/file/${item.recording_file_id}?token=${encodeURIComponent(token || "")}`
                  : null;

                return (
                  <article key={item.event_id} className="panel-card review-card">
                    <div className="panel-card__header">
                      <div>
                        <div className="muted">Event #{item.event_id}</div>
                        <h3 className="panel-card__title">{item.camera_name || `Камера ${item.camera_id}`}</h3>
                        <div className="panel-card__lead">{item.camera_location || "Локация не указана"}</div>
                      </div>
                      <span className="pill">{new Date(item.event_ts).toLocaleString()}</span>
                    </div>

                    <div className="hero-badges">
                      <span className="hero-badge">
                        Confidence <strong>{item.confidence != null ? `${Number(item.confidence).toFixed(1)}%` : "n/a"}</strong>
                      </span>
                      {item.recording_file_id && (
                        <span className="hero-badge">
                          Видео <strong>есть</strong>
                        </span>
                      )}
                    </div>

                    <div className="review-card__media media-frame">
                      {snapshotAvailable ? (
                        <img
                          src={`${API_URL}${item.snapshot_url}`}
                          alt={`event-${item.event_id}`}
                          loading="lazy"
                          className="review-snapshot"
                          onError={() => setSnapshotErrorMap((prev) => ({ ...prev, [item.event_id]: true }))}
                        />
                      ) : (
                        <div className="review-snapshot review-snapshot-empty">Снимок пока недоступен.</div>
                      )}
                    </div>

                    {item.recording_file_id && (
                      videoOpenMap[item.event_id] ? (
                        <div className="stack" style={{ marginTop: 12 }}>
                          <div className="media-frame">
                            <video src={recordingUrl || undefined} className="review-video" controls preload="metadata" playsInline />
                          </div>
                          <a className="btn secondary" href={recordingUrl || undefined} target="_blank" rel="noreferrer">
                            Оригинальный файл
                          </a>
                        </div>
                      ) : (
                        <button
                          className="btn secondary"
                          style={{ marginTop: 12 }}
                          onClick={() => setVideoOpenMap((prev) => ({ ...prev, [item.event_id]: true }))}
                        >
                          Открыть видео
                        </button>
                      )
                    )}

                    <label className="field" style={{ marginTop: 12 }}>
                      <span className="label">Назначить person_id</span>
                      <input
                        className="input"
                        value={personMap[item.event_id] || ""}
                        onChange={(event) => setPersonMap((prev) => ({ ...prev, [item.event_id]: event.target.value }))}
                        placeholder="ID персоны"
                      />
                    </label>

                    {item.snapshot_url && !snapshotErrorMap[item.event_id] && (
                      <div className="stack">
                        <span className="label">Создать персону из снимка</span>
                        <input
                          className="input"
                          placeholder="Фамилия Имя Отчество"
                          value={fioMap[item.event_id] || ""}
                          onChange={(event) => setFioMap((prev) => ({ ...prev, [item.event_id]: event.target.value }))}
                        />
                        <button
                          className="btn secondary"
                          onClick={async () => {
                            if (!token) return;
                            const fio = (fioMap[item.event_id] || "").trim().split(" ").filter(Boolean);
                            try {
                              const result = await enrollPersonFromSnapshot(token, {
                                event_id: item.event_id,
                                last_name: fio[0],
                                first_name: fio[1],
                                middle_name: fio[2],
                              });
                              alert(`Создана персона ID ${result.person_id}`);
                              await load();
                            } catch (event: any) {
                              alert(event?.message || "Не удалось создать персону.");
                            }
                          }}
                        >
                          Персона из снимка
                        </button>
                      </div>
                    )}

                    <div className="review-card__actions" style={{ marginTop: 12 }}>
                      <button className="btn" onClick={() => handleReview(item.event_id, "approved")}>
                        Одобрить
                      </button>
                      <button className="btn secondary" onClick={() => handleReview(item.event_id, "rejected")}>
                        Отклонить
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default ReviewsPage;
