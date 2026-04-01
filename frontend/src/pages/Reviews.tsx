import { useCallback, useEffect, useMemo, useState } from "react";
import {
  API_URL,
  enrollPersonFromSnapshot,
  getPending,
  listPersons,
  rejectAllPendingReviews,
  reviewEvent,
} from "../lib/api";
import type { PersonOut } from "../lib/api";
import { fuzzyFilter } from "../lib/fuzzy";
import { finalizePersonNamePart, hasPersonName, PERSON_NAME_HINT, sanitizePersonNamePart } from "../lib/personNames";
import { useAuth } from "../context/AuthContext";

type Pending = {
  event_id: number;
  camera_id: number;
  camera_name?: string | null;
  camera_location?: string | null;
  event_type_id: number;
  event_ts: string;
  person_id?: number | null;
  person_label?: string | null;
  recording_file_id?: number;
  confidence?: number | null;
  snapshot_url?: string | null;
};

type SnapshotDraft = {
  firstName: string;
  lastName: string;
  middleName: string;
};

const EMPTY_SNAPSHOT_DRAFT: SnapshotDraft = {
  firstName: "",
  lastName: "",
  middleName: "",
};

function createEmptySnapshotDraft(): SnapshotDraft {
  return { ...EMPTY_SNAPSHOT_DRAFT };
}

function personLabel(person: Pick<PersonOut, "person_id" | "first_name" | "last_name" | "middle_name">): string {
  return [person.last_name, person.first_name, person.middle_name].filter(Boolean).join(" ") || `ID ${person.person_id}`;
}

const ReviewsPage = () => {
  const { token } = useAuth();
  const [items, setItems] = useState<Pending[]>([]);
  const [persons, setPersons] = useState<PersonOut[]>([]);
  const [personMap, setPersonMap] = useState<Record<number, number | null>>({});
  const [snapshotDrafts, setSnapshotDrafts] = useState<Record<number, SnapshotDraft>>({});
  const [videoOpenMap, setVideoOpenMap] = useState<Record<number, boolean>>({});
  const [snapshotErrorMap, setSnapshotErrorMap] = useState<Record<number, boolean>>({});
  const [pickerEventId, setPickerEventId] = useState<number | null>(null);
  const [pickerQuery, setPickerQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filteredPersons = useMemo(
    () => fuzzyFilter(persons, pickerQuery, (person) => [personLabel(person), String(person.person_id)]),
    [persons, pickerQuery]
  );

  const stats = useMemo(
    () => ({
      withSnapshots: items.filter((item) => item.snapshot_url).length,
      withVideo: items.filter((item) => item.recording_file_id).length,
    }),
    [items]
  );

  const closePicker = useCallback(() => {
    setPickerEventId(null);
    setPickerQuery("");
  }, []);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const [pendingItems, personItems] = await Promise.all([getPending(token), listPersons(token)]);
      setItems(pendingItems);
      setPersons(personItems);
      setPersonMap((prev) => {
        const next: Record<number, number | null> = {};
        pendingItems.forEach((item) => {
          const selectedId = prev[item.event_id];
          if (selectedId != null && personItems.some((person) => person.person_id === selectedId)) {
            next[item.event_id] = selectedId;
            return;
          }
          if (item.person_id != null) {
            next[item.event_id] = item.person_id;
          }
        });
        return next;
      });
      setSnapshotDrafts((prev) => {
        const next: Record<number, SnapshotDraft> = {};
        pendingItems.forEach((item) => {
          next[item.event_id] = prev[item.event_id] ?? createEmptySnapshotDraft();
        });
        return next;
      });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Не удалось загрузить очередь ревью.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (pickerEventId == null) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closePicker();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [closePicker, pickerEventId]);

  const updateSnapshotDraft = (eventId: number, field: keyof SnapshotDraft, value: string) => {
    setSnapshotDrafts((prev) => ({
      ...prev,
      [eventId]: {
        ...(prev[eventId] ?? createEmptySnapshotDraft()),
        [field]: sanitizePersonNamePart(value),
      },
    }));
  };

  const handleReview = async (eventId: number, status: "approved" | "rejected") => {
    if (!token) return;
    try {
      const personId = personMap[eventId] ?? undefined;
      await reviewEvent(token, eventId, status, personId);
      setItems((prev) => prev.filter((item) => item.event_id !== eventId));
      setPersonMap((prev) => {
        const next = { ...prev };
        delete next[eventId];
        return next;
      });
      setSnapshotDrafts((prev) => {
        const next = { ...prev };
        delete next[eventId];
        return next;
      });
      if (pickerEventId === eventId) {
        closePicker();
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Ошибка при обработке ревью.";
      alert(message);
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
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Не удалось отклонить все события.";
      alert(message);
    } finally {
      setBulkBusy(false);
    }
  };

  const handleSnapshotEnroll = async (item: Pending) => {
    if (!token) return;
    const draft = snapshotDrafts[item.event_id] ?? createEmptySnapshotDraft();
    const payload = {
      event_id: item.event_id,
      first_name: finalizePersonNamePart(draft.firstName) || undefined,
      last_name: finalizePersonNamePart(draft.lastName) || undefined,
      middle_name: finalizePersonNamePart(draft.middleName) || undefined,
    };

    if (!hasPersonName({ firstName: payload.first_name, lastName: payload.last_name, middleName: payload.middle_name })) {
      alert("Заполните хотя бы одно поле ФИО перед созданием персоны.");
      return;
    }

    try {
      const result = (await enrollPersonFromSnapshot(token, payload)) as { person_id: number };
      setPersonMap((prev) => ({ ...prev, [item.event_id]: result.person_id }));
      setSnapshotDrafts((prev) => ({ ...prev, [item.event_id]: createEmptySnapshotDraft() }));
      alert(`Создана персона ID ${result.person_id}`);
      await load();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Не удалось создать персону.";
      alert(message);
    }
  };

  const pickerTitle = pickerEventId == null ? "Выбор персоны" : `Выбор персоны для события #${pickerEventId}`;

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

      <section className="panel-card">
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
              const snapshotAvailable = Boolean(item.snapshot_url) && !snapshotErrorMap[item.event_id];
              const recordingUrl = item.recording_file_id
                ? `${API_URL}/recordings/file/${item.recording_file_id}?token=${encodeURIComponent(token || "")}`
                : null;
              const selectedPersonId = personMap[item.event_id] ?? null;
              const selectedPerson = selectedPersonId
                ? persons.find((person) => person.person_id === selectedPersonId) ?? null
                : null;
              const selectedPersonLabel = selectedPerson
                ? personLabel(selectedPerson)
                : item.person_label || (selectedPersonId ? `ID ${selectedPersonId}` : "Персона не выбрана");
              const snapshotDraft = snapshotDrafts[item.event_id] ?? EMPTY_SNAPSHOT_DRAFT;

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

                  {item.recording_file_id &&
                    (videoOpenMap[item.event_id] ? (
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
                    ))}

                  <div className="field" style={{ marginTop: 12 }}>
                    <span className="label">Назначить персону</span>
                    <button type="button" className={`review-picker-trigger${selectedPersonId ? " selected" : ""}`} onClick={() => setPickerEventId(item.event_id)}>
                      <span className="review-picker-trigger__name">{selectedPersonLabel}</span>
                      <span className="review-picker-trigger__meta">
                        {selectedPersonId ? `ID ${selectedPersonId}` : "Открыть список персон и поиск"}
                      </span>
                    </button>
                  </div>

                  <div className="page-actions">
                    <button className="btn secondary" onClick={() => setPickerEventId(item.event_id)}>
                      Выбрать из списка
                    </button>
                    <button
                      className="btn secondary"
                      onClick={() => setPersonMap((prev) => ({ ...prev, [item.event_id]: null }))}
                      disabled={!selectedPersonId}
                    >
                      Снять выбор
                    </button>
                  </div>

                  {item.snapshot_url && !snapshotErrorMap[item.event_id] && (
                    <div className="stack">
                      <span className="label">Создать новую персону из снимка</span>
                      <div className="review-name-grid">
                        <label className="field">
                          <span className="label">Фамилия</span>
                          <input
                            className="input"
                            value={snapshotDraft.lastName}
                            onChange={(event) => updateSnapshotDraft(item.event_id, "lastName", event.target.value)}
                            autoComplete="family-name"
                            inputMode="text"
                          />
                        </label>
                        <label className="field">
                          <span className="label">Имя</span>
                          <input
                            className="input"
                            value={snapshotDraft.firstName}
                            onChange={(event) => updateSnapshotDraft(item.event_id, "firstName", event.target.value)}
                            autoComplete="given-name"
                            inputMode="text"
                          />
                        </label>
                        <label className="field">
                          <span className="label">Отчество</span>
                          <input
                            className="input"
                            value={snapshotDraft.middleName}
                            onChange={(event) => updateSnapshotDraft(item.event_id, "middleName", event.target.value)}
                            autoComplete="additional-name"
                            inputMode="text"
                          />
                        </label>
                      </div>
                      <div className="muted">{PERSON_NAME_HINT}</div>
                      <button className="btn secondary" onClick={() => handleSnapshotEnroll(item)}>
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
      </section>

      {pickerEventId != null && (
        <div className="modal-backdrop" onClick={closePicker}>
          <div className="modal modal--wide" onClick={(event) => event.stopPropagation()}>
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">{pickerTitle}</h3>
                <div className="panel-card__lead">Выберите существующую карточку персоны и сразу назначьте её на событие.</div>
              </div>
              <button className="btn secondary" onClick={closePicker}>
                Закрыть
              </button>
            </div>

            <label className="field">
              <span className="label">Поиск по ФИО или ID</span>
              <input
                className="input"
                value={pickerQuery}
                onChange={(event) => setPickerQuery(event.target.value)}
                autoFocus
              />
            </label>

            <div className="review-picker-summary">
              <span className="pill">{filteredPersons.length}</span>
              <div className="muted">Поиск поддерживает неполные совпадения по ФИО и ID.</div>
            </div>

            <div className="person-picker-list">
              {filteredPersons.length === 0 ? (
                <div className="muted">Совпадений не найдено.</div>
              ) : (
                <div className="list-shell">
                  {filteredPersons.map((person) => {
                    const isSelected = person.person_id === (personMap[pickerEventId] ?? null);
                    return (
                      <button
                        key={person.person_id}
                        type="button"
                        className={`list-item${isSelected ? " active" : ""}`}
                        onClick={() => {
                          setPersonMap((prev) => ({ ...prev, [pickerEventId]: person.person_id }));
                          closePicker();
                        }}
                      >
                        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                          <div className="list-item__title">{personLabel(person)}</div>
                          <span className="pill">{person.embeddings_count} emb</span>
                        </div>
                        <div className="list-item__meta">
                          ID {person.person_id} • {person.created_at ? new Date(person.created_at).toLocaleString() : "—"}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ReviewsPage;
