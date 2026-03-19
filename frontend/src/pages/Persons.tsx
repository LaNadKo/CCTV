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

const PersonsPage: React.FC = () => {
  const { token } = useAuth();
  const [persons, setPersons] = useState<Person[]>([]);
  const [cameras, setCameras] = useState<CameraOption[]>([]);
  const [search, setSearch] = useState("");
  const [liveCameraId, setLiveCameraId] = useState<number | null>(null);
  const [selectedPersonId, setSelectedPersonId] = useState<number | null>(null);
  const [autoCapture, setAutoCapture] = useState(false);
  const [autoIntervalMs, setAutoIntervalMs] = useState(1200);
  const [autoTarget, setAutoTarget] = useState(6);
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
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить список персон.");
    } finally {
      setLoading(false);
    }
  }, [token, selectedPersonId, liveCameraId]);

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
        first_name: createFirst || undefined,
        last_name: createLast || undefined,
        middle_name: createMiddle || undefined,
      });
      setCreateFirst("");
      setCreateLast("");
      setCreateMiddle("");
      setSelectedPersonId(created.person_id);
      setSuccess(`Персона создана: ID ${created.person_id}.`);
      await load();
    } catch (e: any) {
      setError(e?.message || "Не удалось создать персону.");
    }
  };

  const handleUpdate = async () => {
    if (!token || !selectedPersonId) return;
    setError(null);
    setSuccess(null);
    try {
      await updatePerson(token, selectedPersonId, {
        first_name: editFirst || undefined,
        last_name: editLast || undefined,
        middle_name: editMiddle || undefined,
      });
      setSuccess("Данные персоны обновлены.");
      await load();
    } catch (e: any) {
      setError(e?.message || "Не удалось обновить персону.");
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
    } catch (e: any) {
      setError(e?.message || "Не удалось удалить персону.");
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
      const blob = await new Promise<Blob | null>((resolve) => canvas!.toBlob(resolve, "image/jpeg", 0.95));
      if (!blob) return;

      const file = new File([blob], `live_${Date.now()}.jpg`, { type: "image/jpeg" });
      const result = await addPersonEmbeddingFromPhoto(token, selectedPersonId, file, liveCameraId);

      if (result.status === "added") {
        setAutoAdded((value) => value + 1);
        setSuccess("Эмбеддинг добавлен из Live.");
      } else if (result.status === "duplicate") {
        setSuccess(`Похожий ракурс уже есть: sim=${result.max_similarity?.toFixed(3) ?? "?"}.`);
      } else if (result.status === "mismatch") {
        setError(
          `Лицо не похоже на выбранную персону: sim=${result.max_similarity?.toFixed(3) ?? "?"}. Автосбор остановлен.`
        );
        setAutoCapture(false);
      }

      await load();
    } catch (e: any) {
      setError(e?.message || "Не удалось добавить снимок из Live.");
    } finally {
      setCaptureBusy(false);
    }
  }, [token, selectedPersonId, liveCameraId, captureBusy, load]);

  useEffect(() => {
    if (!autoCapture) return;
    if (autoAdded >= autoTarget) {
      setAutoCapture(false);
      return;
    }
    const timer = window.setInterval(() => {
      captureFromLive();
    }, autoIntervalMs);
    return () => window.clearInterval(timer);
  }, [autoCapture, autoAdded, autoIntervalMs, autoTarget, captureFromLive]);

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="title">Персоны</h2>
          <div className="muted">Создание, поиск, редактирование и сбор эмбеддингов из живого потока.</div>
        </div>
        <button className="btn secondary" onClick={load} disabled={loading}>
          Обновить
        </button>
      </div>

      {error && <div className="danger">{error}</div>}
      {success && <div className="success">{success}</div>}

      <div className="grid">
        <div className="card stack">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0 }}>Список персон</h3>
            <span className="pill">{filteredPersons.length}</span>
          </div>
          <label className="field">
            <span className="label">Поиск по ФИО или ID</span>
            <input
              className="input"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Неточный поиск"
            />
          </label>
          {loading && <div className="muted">Загрузка...</div>}
          {!loading && filteredPersons.length === 0 && <div className="muted">Совпадений не найдено.</div>}
          <div className="stack" style={{ gap: 8 }}>
            {filteredPersons.map((person) => {
              const active = person.person_id === selectedPersonId;
              return (
                <button
                  key={person.person_id}
                  className={`hour-card${active ? " active" : ""}`}
                  onClick={() => setSelectedPersonId(person.person_id)}
                  style={{ color: "var(--text)" }}
                >
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ color: "var(--text)", fontWeight: 600 }}>{personLabel(person)}</div>
                    <span className="pill">{person.embeddings_count} emb</span>
                  </div>
                  <div className="muted" style={{ marginTop: 6 }}>
                    ID {person.person_id} · {person.created_at ? new Date(person.created_at).toLocaleString() : "—"}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="card stack">
          <h3 style={{ margin: 0 }}>Создать персону</h3>
          <label className="field">
            <span className="label">Фамилия</span>
            <input className="input" value={createLast} onChange={(e) => setCreateLast(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Имя</span>
            <input className="input" value={createFirst} onChange={(e) => setCreateFirst(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Отчество</span>
            <input className="input" value={createMiddle} onChange={(e) => setCreateMiddle(e.target.value)} />
          </label>
          <button className="btn" onClick={handleCreate}>
            Создать
          </button>
        </div>

        <div className="card stack">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0 }}>Редактирование</h3>
            {selectedPerson && (
              <button className="btn secondary" onClick={handleDelete}>
                Удалить
              </button>
            )}
          </div>
          {!selectedPerson && <div className="muted">Выберите персону в списке слева.</div>}
          {selectedPerson && (
            <>
              <label className="field">
                <span className="label">Фамилия</span>
                <input className="input" value={editLast} onChange={(e) => setEditLast(e.target.value)} />
              </label>
              <label className="field">
                <span className="label">Имя</span>
                <input className="input" value={editFirst} onChange={(e) => setEditFirst(e.target.value)} />
              </label>
              <label className="field">
                <span className="label">Отчество</span>
                <input className="input" value={editMiddle} onChange={(e) => setEditMiddle(e.target.value)} />
              </label>
              <button className="btn secondary" onClick={handleUpdate}>
                Сохранить
              </button>
            </>
          )}
        </div>
      </div>

      <div className="card stack persons-live-card">
        <h3 style={{ margin: 0 }}>Live-сбор эмбеддингов</h3>
        {!selectedPerson && <div className="muted">Сначала выберите персону.</div>}
        {selectedPerson && (
          <>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
              <label className="field">
                <span className="label">Камера</span>
                <select
                  className="input"
                  value={liveCameraId ?? ""}
                  onChange={(e) => setLiveCameraId(e.target.value ? Number(e.target.value) : null)}
                >
                  {cameras.map((camera) => (
                    <option key={camera.camera_id} value={camera.camera_id}>
                      {camera.name} (#{camera.camera_id})
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="label">Интервал (мс)</span>
                <input
                  className="input"
                  value={autoIntervalMs}
                  onChange={(e) => setAutoIntervalMs(Number(e.target.value) || 1200)}
                />
              </label>
              <label className="field">
                <span className="label">Цель (шт.)</span>
                <input
                  className="input"
                  value={autoTarget}
                  onChange={(e) => setAutoTarget(Number(e.target.value) || 6)}
                />
              </label>
            </div>

            <div className="live-preview persons-live-preview">
              {liveCameraId && token ? (
                <img
                  ref={liveImgRef}
                  crossOrigin="anonymous"
                  alt="live"
                  src={`${API_URL}/cameras/${liveCameraId}/stream?annotate=false&token=${encodeURIComponent(token)}`}
                />
              ) : (
                <div className="muted" style={{ padding: 20 }}>
                  Выберите камеру для live-сбора.
                </div>
              )}
            </div>

            <div className="row" style={{ gap: 10 }}>
              <button className="btn secondary" onClick={captureFromLive} disabled={captureBusy || !liveCameraId}>
                Снимок из Live
              </button>
              <button
                className="btn"
                onClick={() => {
                  setAutoAdded(0);
                  setAutoCapture((value) => !value);
                }}
                disabled={!liveCameraId}
              >
                {autoCapture ? "Остановить автосбор" : "Запустить автосбор"}
              </button>
              <div className="muted">Добавлено: {autoAdded} / {autoTarget}</div>
            </div>

            <div className="muted">
              Для более качественной базы слегка меняйте угол головы, наклон и дистанцию до камеры.
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default PersonsPage;
