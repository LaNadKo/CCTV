import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import {
  API_URL,
  addPersonEmbeddingFromPhoto,
  createPerson,
  deletePerson,
  getCameras,
  listPersons,
  updatePerson,
} from "../lib/api";
import { fuzzyFilter } from "../lib/fuzzy";
import { finalizePersonNamePart, PERSON_NAME_HINT, sanitizePersonNamePart } from "../lib/personNames";

type Person = {
  person_id: number;
  first_name?: string | null;
  last_name?: string | null;
  middle_name?: string | null;
  embeddings_count: number;
  created_at: string | null;
};

type CameraOption = {
  camera_id: number;
  name: string;
};

function personLabel(person: Person): string {
  return [person.last_name, person.first_name, person.middle_name].filter(Boolean).join(" ") || `ID ${person.person_id}`;
}

const PersonsPage = () => {
  const { token } = useAuth();
  const [persons, setPersons] = useState<Person[]>([]);
  const [cameras, setCameras] = useState<CameraOption[]>([]);
  const [search, setSearch] = useState("");
  const [liveCameraId, setLiveCameraId] = useState<number | null>(null);
  const [selectedPersonId, setSelectedPersonId] = useState<number | null>(null);
  const [autoCapture, setAutoCapture] = useState(false);
  const [autoIntervalMs, setAutoIntervalMs] = useState(1500);
  const [autoTarget, setAutoTarget] = useState(8);
  const [autoAdded, setAutoAdded] = useState(0);
  const [captureBusy, setCaptureBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [createFirst, setCreateFirst] = useState("");
  const [createLast, setCreateLast] = useState("");
  const [createMiddle, setCreateMiddle] = useState("");
  const [editFirst, setEditFirst] = useState("");
  const [editLast, setEditLast] = useState("");
  const [editMiddle, setEditMiddle] = useState("");

  const liveImgRef = useRef<HTMLImageElement | null>(null);
  const liveCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const filteredPersons = useMemo(
    () => fuzzyFilter(persons, search, (person) => [personLabel(person), String(person.person_id)]),
    [persons, search]
  );

  const selectedPerson = useMemo(
    () => persons.find((person) => person.person_id === selectedPersonId) || null,
    [persons, selectedPersonId]
  );

  const liveHint = autoCapture
    ? "Автосбор активен: держите лицо в рамке и плавно меняйте ракурс."
    : "Держите лицо внутри рамки. Можно добавлять кадры вручную или запустить автосбор.";

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const [personItems, cameraItems] = await Promise.all([listPersons(token), getCameras(token)]);
      setPersons(personItems);
      setCameras(cameraItems.map((camera) => ({ camera_id: camera.camera_id, name: camera.name })));

      if (!selectedPersonId && personItems.length > 0) {
        setSelectedPersonId(personItems[0].person_id);
      } else if (selectedPersonId && !personItems.some((person) => person.person_id === selectedPersonId)) {
        setSelectedPersonId(personItems[0]?.person_id ?? null);
      }

      if (!liveCameraId && cameraItems.length > 0) {
        setLiveCameraId(cameraItems[0].camera_id);
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Не удалось загрузить список персон.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [liveCameraId, selectedPersonId, token]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selectedPerson) return;
    setEditFirst(selectedPerson.first_name || "");
    setEditLast(selectedPerson.last_name || "");
    setEditMiddle(selectedPerson.middle_name || "");
  }, [selectedPerson]);

  const handleCreate = async () => {
    if (!token) return;
    setError(null);
    setSuccess(null);
    try {
      const created = await createPerson(token, {
        first_name: finalizePersonNamePart(createFirst) || undefined,
        last_name: finalizePersonNamePart(createLast) || undefined,
        middle_name: finalizePersonNamePart(createMiddle) || undefined,
      });
      setCreateFirst("");
      setCreateLast("");
      setCreateMiddle("");
      setSelectedPersonId(created.person_id);
      setSuccess(`Персона создана: ID ${created.person_id}.`);
      await load();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Не удалось создать персону.";
      setError(message);
    }
  };

  const handleUpdate = async () => {
    if (!token || !selectedPersonId) return;
    setError(null);
    setSuccess(null);
    try {
      await updatePerson(token, selectedPersonId, {
        first_name: finalizePersonNamePart(editFirst) || undefined,
        last_name: finalizePersonNamePart(editLast) || undefined,
        middle_name: finalizePersonNamePart(editMiddle) || undefined,
      });
      setSuccess("Данные персоны обновлены.");
      await load();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Не удалось обновить персону.";
      setError(message);
    }
  };

  const handleDelete = async () => {
    if (!token || !selectedPerson) return;
    if (!window.confirm(`Удалить персону "${personLabel(selectedPerson)}"?`)) return;
    setError(null);
    setSuccess(null);
    try {
      await deletePerson(token, selectedPerson.person_id);
      setSuccess("Персона удалена.");
      setSelectedPersonId(null);
      await load();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Не удалось удалить персону.";
      setError(message);
    }
  };

  const captureFromLive = useCallback(async () => {
    if (!token || !selectedPersonId || !liveCameraId || captureBusy) return;
    const img = liveImgRef.current;
    if (!img || !img.complete) return;

    setCaptureBusy(true);
    setError(null);
    try {
      let canvas = liveCanvasRef.current;
      if (!canvas) {
        canvas = document.createElement("canvas");
        liveCanvasRef.current = canvas;
      }

      const width = img.naturalWidth || img.width;
      const height = img.naturalHeight || img.height;
      if (!width || !height) return;

      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      ctx.drawImage(img, 0, 0, width, height);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.95));
      if (!blob) return;

      const file = new File([blob], `live_${Date.now()}.jpg`, { type: "image/jpeg" });
      const result = await addPersonEmbeddingFromPhoto(token, selectedPersonId, file, liveCameraId);

      if (result.status === "added") {
        setAutoAdded((value) => value + 1);
        setSuccess("Эмбеддинг добавлен из live-потока.");
      } else if (result.status === "duplicate") {
        setSuccess(`Похожий ракурс уже есть: sim=${result.max_similarity?.toFixed(3) ?? "?"}.`);
      } else if (result.status === "mismatch") {
        setError(`Лицо не похоже на выбранную персону: sim=${result.max_similarity?.toFixed(3) ?? "?"}. Автосбор остановлен.`);
        setAutoCapture(false);
      }

      await load();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Не удалось добавить снимок из live-потока.";
      setError(message);
      setAutoCapture(false);
    } finally {
      setCaptureBusy(false);
    }
  }, [captureBusy, liveCameraId, load, selectedPersonId, token]);

  useEffect(() => {
    if (!autoCapture) return undefined;
    if (autoAdded >= autoTarget) {
      setAutoCapture(false);
      setSuccess("Автосбор завершён.");
      return undefined;
    }
    const timer = window.setInterval(() => {
      captureFromLive();
    }, autoIntervalMs);
    return () => window.clearInterval(timer);
  }, [autoAdded, autoCapture, autoIntervalMs, autoTarget, captureFromLive]);

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <h2 className="title">Персоны</h2>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={load} disabled={loading}>
            Обновить
          </button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Всего персон</div>
          <div className="summary-card__value">{persons.length}</div>
          <div className="summary-card__hint">Карточки людей, которые доступны для распознавания и отчётности.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">В поиске</div>
          <div className="summary-card__value">{filteredPersons.length}</div>
          <div className="summary-card__hint">Используется неточный поиск по ФИО и ID.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Автосбор</div>
          <div className="summary-card__value">
            {autoAdded}/{autoTarget}
          </div>
          <div className="summary-card__hint">Сколько новых эмбеддингов уже удалось добавить в текущей сессии.</div>
        </div>
      </section>

      {error && <div className="danger">{error}</div>}
      {success && <div className="success">{success}</div>}

      <section className="persons-shell">
        <div className="panel-card stack">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Список персон</h3>
              <div className="panel-card__lead">Поиск, выбор и быстрый обзор базы эмбеддингов.</div>
            </div>
            <span className="pill">{filteredPersons.length}</span>
          </div>

          <label className="field">
            <span className="label">Поиск по ФИО или ID</span>
            <input className="input" value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>

          {loading && <div className="muted">Загрузка...</div>}
          {!loading && filteredPersons.length === 0 && <div className="muted">Совпадений не найдено.</div>}

          <div className="list-shell">
            {filteredPersons.map((person) => (
              <button
                key={person.person_id}
                className={`list-item${person.person_id === selectedPersonId ? " active" : ""}`}
                onClick={() => setSelectedPersonId(person.person_id)}
                type="button"
              >
                <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                  <div className="list-item__title">{personLabel(person)}</div>
                  <span className="pill">{person.embeddings_count} emb</span>
                </div>
                <div className="list-item__meta">
                  ID {person.person_id} • {person.created_at ? new Date(person.created_at).toLocaleString() : "—"}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="stack-grid">
          <div className="panel-card stack">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Карточка персоны</h3>
                <div className="panel-card__lead">
                  {selectedPerson ? "Редактирование текущей карточки и контроль качества базы." : "Выберите персону в списке слева."}
                </div>
              </div>
              {selectedPerson && (
                <button className="btn secondary" onClick={handleDelete}>
                  Удалить
                </button>
              )}
            </div>

            {selectedPerson ? (
              <>
                <div className="persons-meta">
                  <div className="persons-meta__tile">
                    <div className="persons-meta__label">ФИО</div>
                    <div className="persons-meta__value">{personLabel(selectedPerson)}</div>
                  </div>
                  <div className="persons-meta__tile">
                    <div className="persons-meta__label">ID</div>
                    <div className="persons-meta__value">{selectedPerson.person_id}</div>
                  </div>
                  <div className="persons-meta__tile">
                    <div className="persons-meta__label">Эмбеддингов</div>
                    <div className="persons-meta__value">{selectedPerson.embeddings_count}</div>
                  </div>
                </div>

                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
                  <label className="field">
                    <span className="label">Фамилия</span>
                    <input
                      className="input"
                      value={editLast}
                      onChange={(event) => setEditLast(sanitizePersonNamePart(event.target.value))}
                      autoComplete="family-name"
                      inputMode="text"
                    />
                  </label>
                  <label className="field">
                    <span className="label">Имя</span>
                    <input
                      className="input"
                      value={editFirst}
                      onChange={(event) => setEditFirst(sanitizePersonNamePart(event.target.value))}
                      autoComplete="given-name"
                      inputMode="text"
                    />
                  </label>
                  <label className="field">
                    <span className="label">Отчество</span>
                    <input
                      className="input"
                      value={editMiddle}
                      onChange={(event) => setEditMiddle(sanitizePersonNamePart(event.target.value))}
                      autoComplete="additional-name"
                      inputMode="text"
                    />
                  </label>
                </div>
                <div className="muted">{PERSON_NAME_HINT}</div>

                <div className="page-actions">
                  <button className="btn" onClick={handleUpdate}>
                    Сохранить
                  </button>
                </div>
              </>
            ) : (
              <div className="muted">Персона пока не выбрана.</div>
            )}
          </div>

          <div className="panel-card stack">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Создать персону</h3>
                <div className="panel-card__lead">Создайте карточку до начала сбора эмбеддингов.</div>
              </div>
            </div>

            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
              <label className="field">
                <span className="label">Фамилия</span>
                <input
                  className="input"
                  value={createLast}
                  onChange={(event) => setCreateLast(sanitizePersonNamePart(event.target.value))}
                  autoComplete="family-name"
                  inputMode="text"
                />
              </label>
              <label className="field">
                <span className="label">Имя</span>
                <input
                  className="input"
                  value={createFirst}
                  onChange={(event) => setCreateFirst(sanitizePersonNamePart(event.target.value))}
                  autoComplete="given-name"
                  inputMode="text"
                />
              </label>
              <label className="field">
                <span className="label">Отчество</span>
                <input
                  className="input"
                  value={createMiddle}
                  onChange={(event) => setCreateMiddle(sanitizePersonNamePart(event.target.value))}
                  autoComplete="additional-name"
                  inputMode="text"
                />
              </label>
            </div>
            <div className="muted">{PERSON_NAME_HINT}</div>

            <button className="btn" onClick={handleCreate}>
              Создать
            </button>
          </div>

          <div className="panel-card stack persons-live-card">
            <div className="panel-card__header">
              <div>
                <h3 className="panel-card__title">Live-сбор эмбеддингов</h3>
                <div className="panel-card__lead">
                  Ручной снимок и обычный автосбор без фиксированного сценария. Меняйте ракурс и дистанцию так, как это бывает в реальной сцене.
                </div>
              </div>
            </div>

            {!selectedPerson ? (
              <div className="muted">Сначала выберите персону.</div>
            ) : (
              <>
                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
                  <label className="field">
                    <span className="label">Камера</span>
                    <select
                      className="input"
                      value={liveCameraId ?? ""}
                      onChange={(event) => setLiveCameraId(event.target.value ? Number(event.target.value) : null)}
                    >
                      {cameras.map((camera) => (
                        <option key={camera.camera_id} value={camera.camera_id}>
                          {camera.name} (#{camera.camera_id})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span className="label">Интервал автосбора (мс)</span>
                    <input
                      className="input"
                      type="number"
                      min={500}
                      step={100}
                      value={autoIntervalMs}
                      onChange={(event) => setAutoIntervalMs(Math.max(500, Number(event.target.value) || 1500))}
                    />
                  </label>
                  <label className="field">
                    <span className="label">Цель (шт.)</span>
                    <input
                      className="input"
                      type="number"
                      min={1}
                      step={1}
                      value={autoTarget}
                      onChange={(event) => setAutoTarget(Math.max(1, Number(event.target.value) || 8))}
                    />
                  </label>
                </div>

                <div className="hero-badges">
                  <span className="hero-badge">
                    Персона <strong>{personLabel(selectedPerson)}</strong>
                  </span>
                  <span className="hero-badge">
                    Прогресс <strong>{autoAdded} / {autoTarget}</strong>
                  </span>
                  <span className="hero-badge">
                    Режим <strong>{autoCapture ? "автосбор" : "ручной"}</strong>
                  </span>
                </div>

                <div className="media-frame persons-capture-stage persons-live-preview">
                  {liveCameraId && token ? (
                    <>
                      <img
                        ref={liveImgRef}
                        crossOrigin="anonymous"
                        alt="live"
                        src={`${API_URL}/cameras/${liveCameraId}/stream?annotate=false&token=${encodeURIComponent(token)}`}
                        style={{ width: "100%", maxHeight: 560, objectFit: "contain", background: "rgba(8,18,33,0.84)" }}
                      />
                      <div className="persons-capture-guide" aria-hidden="true">
                        <div className="persons-capture-guide__frame" />
                        <div className="persons-capture-guide__hint">{liveHint}</div>
                      </div>
                    </>
                  ) : (
                    <div className="muted" style={{ padding: 20 }}>
                      Выберите камеру для live-сбора.
                    </div>
                  )}
                </div>

                <div className="page-actions">
                  <button className="btn secondary" onClick={captureFromLive} disabled={captureBusy || !liveCameraId}>
                    Снимок из live
                  </button>
                  <button
                    className="btn"
                    onClick={() => {
                      if (!autoCapture) {
                        setAutoAdded(0);
                        setError(null);
                        setSuccess("Автосбор запущен. Держите лицо в рамке и постепенно меняйте ракурс.");
                      }
                      setAutoCapture((value) => !value);
                    }}
                    disabled={!liveCameraId}
                  >
                    {autoCapture ? "Остановить автосбор" : "Запустить автосбор"}
                  </button>
                </div>

                <div className="muted">
                  Сбор лучше проводить в привычном виде пользователя: если человек часто носит очки или головной убор, часть кадров тоже должна быть с ними.
                </div>
              </>
            )}
          </div>
        </div>
      </section>
    </div>
  );
};

export default PersonsPage;
