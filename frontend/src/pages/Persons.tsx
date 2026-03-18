import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import {
  listPersons,
  createPerson,
  updatePerson,
  addPersonEmbeddingFromPhoto,
  getCameras,
  API_URL,
} from "../lib/api";

type Person = {
  person_id: number;
  first_name?: string | null;
  last_name?: string | null;
  middle_name?: string | null;
  embeddings_count: number;
  created_at: string | null;
};

const PersonsPage: React.FC = () => {
  const { token } = useAuth();
  const [persons, setPersons] = useState<Person[]>([]);
  const [cameras, setCameras] = useState<{ camera_id: number; name: string }[]>([]);
  const [liveCameraId, setLiveCameraId] = useState<number | null>(null);
  const liveImgRef = useRef<HTMLImageElement | null>(null);
  const liveCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [autoCapture, setAutoCapture] = useState(false);
  const [autoIntervalMs, setAutoIntervalMs] = useState(1500);
  const [autoTarget, setAutoTarget] = useState(5);
  const [autoAdded, setAutoAdded] = useState(0);
  const [captureBusy, setCaptureBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [selectedPersonId, setSelectedPersonId] = useState<number | null>(null);

  const [createFirst, setCreateFirst] = useState("");
  const [createLast, setCreateLast] = useState("");
  const [createMiddle, setCreateMiddle] = useState("");

  const [editFirst, setEditFirst] = useState("");
  const [editLast, setEditLast] = useState("");
  const [editMiddle, setEditMiddle] = useState("");

  const selectedPerson = useMemo(
    () => persons.find((p) => p.person_id === selectedPersonId) || null,
    [persons, selectedPersonId]
  );

  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const items = await listPersons(token);
      setPersons(items);
      if (!selectedPersonId && items.length > 0) {
        setSelectedPersonId(items[0].person_id);
      }
      const cams = await getCameras(token);
      setCameras(cams.map((c) => ({ camera_id: c.camera_id, name: c.name })));
      if (!liveCameraId && cams.length > 0) {
        setLiveCameraId(cams[0].camera_id);
      }
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить список персон.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (selectedPerson) {
      setEditFirst(selectedPerson.first_name || "");
      setEditLast(selectedPerson.last_name || "");
      setEditMiddle(selectedPerson.middle_name || "");
    }
  }, [selectedPerson]);

  const handleCreate = async () => {
    if (!token) return;
    setError(null);
    setSuccess(null);
    try {
      const res = await createPerson(token, {
        first_name: createFirst || undefined,
        last_name: createLast || undefined,
        middle_name: createMiddle || undefined,
      });
      setCreateFirst("");
      setCreateLast("");
      setCreateMiddle("");
      setSuccess(`Персона создана (ID ${res.person_id}).`);
      await load();
      setSelectedPersonId(res.person_id);
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


  const captureFromLive = useCallback(async () => {
    if (!token || !selectedPersonId || !liveCameraId || captureBusy) return;
    const img = liveImgRef.current;
    if (!img || !img.complete) return;
    setCaptureBusy(true);
    try {
      let canvas = liveCanvasRef.current;
      if (!canvas) {
        canvas = document.createElement("canvas");
        liveCanvasRef.current = canvas;
      }
      const width = img.naturalWidth || img.width;
      const height = img.naturalHeight || img.height;
      if (!width || !height) {
        setCaptureBusy(false);
        return;
      }
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        setCaptureBusy(false);
        return;
      }
      ctx.drawImage(img, 0, 0, width, height);
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas!.toBlob(resolve, "image/jpeg", 0.95)
      );
      if (!blob) {
        setCaptureBusy(false);
        return;
      }
      const file = new File([blob], `live_${Date.now()}.jpg`, { type: "image/jpeg" });
      const res = await addPersonEmbeddingFromPhoto(token, selectedPersonId, file, liveCameraId);
      if (res.status === "added") {
        setAutoAdded((v) => v + 1);
        setSuccess("Эмбеддинг добавлен из Live.");
      } else if (res.status === "duplicate") {
        setSuccess(`Дубликат (sim=${res.max_similarity?.toFixed(3) ?? "?"}).`);
      } else if (res.status === "mismatch") {
        setError(`Лицо не похоже на выбранную персону (sim=${res.max_similarity?.toFixed(3) ?? "?"}). Автосбор остановлен.`);
        setAutoCapture(false);
      }
      await load();
    } catch (e: any) {
      setError(e?.message || "Не удалось добавить из Live.");
    } finally {
      setCaptureBusy(false);
    }
  }, [token, selectedPersonId, liveCameraId, captureBusy]);

  useEffect(() => {
    if (!autoCapture) return;
    if (autoAdded >= autoTarget) {
      setAutoCapture(false);
      return;
    }
    const id = setInterval(() => {
      captureFromLive();
    }, autoIntervalMs);
    return () => clearInterval(id);
  }, [autoCapture, autoIntervalMs, autoTarget, autoAdded, captureFromLive]);

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="title">Персоны</h2>
          <div className="muted">Создание и управление эмбеддингами</div>
        </div>
        <button className="btn secondary" onClick={load} disabled={loading}>
          Обновить
        </button>
      </div>

      {error && <div className="danger">{error}</div>}
      {success && <div className="success">{success}</div>}

      <div className="grid">
        <div className="card stack">
          <h3 style={{ margin: 0 }}>Список персон</h3>
          {loading && <div className="muted">Загрузка...</div>}
          {!loading && persons.length === 0 && <div className="muted">Персон пока нет.</div>}
          <div className="stack" style={{ gap: 8 }}>
            {persons.map((p) => {
              const label = [p.last_name, p.first_name, p.middle_name].filter(Boolean).join(" ") || `ID ${p.person_id}`;
              const active = p.person_id === selectedPersonId;
              return (
                <button
                  key={p.person_id}
                  className={`hour-card${active ? " active" : ""}`}
                  onClick={() => setSelectedPersonId(p.person_id)}
                >
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <div>{label}</div>
                    <span className="pill">{p.embeddings_count} emb</span>
                  </div>
                  <div className="muted" style={{ marginTop: 4 }}>
                    ID {p.person_id} • {p.created_at ? new Date(p.created_at).toLocaleString() : "—"}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="card stack">
          <h3 style={{ margin: 0 }}>Создать персону</h3>
          <div className="field">
            <label className="label">Фамилия</label>
            <input className="input" value={createLast} onChange={(e) => setCreateLast(e.target.value)} />
          </div>
          <div className="field">
            <label className="label">Имя</label>
            <input className="input" value={createFirst} onChange={(e) => setCreateFirst(e.target.value)} />
          </div>
          <div className="field">
            <label className="label">Отчество</label>
            <input className="input" value={createMiddle} onChange={(e) => setCreateMiddle(e.target.value)} />
          </div>
          <button className="btn" onClick={handleCreate}>
            Создать
          </button>
        </div>

        <div className="card stack">
          <h3 style={{ margin: 0 }}>Редактировать</h3>
          {!selectedPerson && <div className="muted">Выберите персону в списке.</div>}
          {selectedPerson && (
            <>
              <div className="field">
                <label className="label">Фамилия</label>
                <input className="input" value={editLast} onChange={(e) => setEditLast(e.target.value)} />
              </div>
              <div className="field">
                <label className="label">Имя</label>
                <input className="input" value={editFirst} onChange={(e) => setEditFirst(e.target.value)} />
              </div>
              <div className="field">
                <label className="label">Отчество</label>
                <input className="input" value={editMiddle} onChange={(e) => setEditMiddle(e.target.value)} />
              </div>
              <button className="btn secondary" onClick={handleUpdate}>
                Сохранить
              </button>
            </>
          )}
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Live-сбор эмбеддингов</h3>
        {!selectedPerson && <div className="muted">Сначала выберите персону.</div>}
        {selectedPerson && (
          <>
            <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
              <select
                className="input"
                value={liveCameraId ?? ""}
                onChange={(e) => setLiveCameraId(e.target.value ? Number(e.target.value) : null)}
              >
                {cameras.map((c) => (
                  <option key={c.camera_id} value={c.camera_id}>
                    {c.name} (#{c.camera_id})
                  </option>
                ))}
              </select>
              <div className="field" style={{ minWidth: 140 }}>
                <label className="label">Интервал (мс)</label>
                <input
                  className="input"
                  value={autoIntervalMs}
                  onChange={(e) => setAutoIntervalMs(Number(e.target.value) || 1500)}
                />
              </div>
              <div className="field" style={{ minWidth: 120 }}>
                <label className="label">Цель (шт.)</label>
                <input
                  className="input"
                  value={autoTarget}
                  onChange={(e) => setAutoTarget(Number(e.target.value) || 5)}
                />
              </div>
            </div>
            <div className="live-preview">
              {liveCameraId && token ? (
                <img
                  ref={liveImgRef}
                  crossOrigin="anonymous"
                  alt="live"
                  src={`${API_URL}/cameras/${liveCameraId}/stream?annotate=false&token=${encodeURIComponent(token)}`}
                />
              ) : (
                <div className="muted" style={{ padding: 16 }}>
                  Выберите камеру.
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
                  setAutoCapture((v) => !v);
                }}
                disabled={!liveCameraId}
              >
                {autoCapture ? "Остановить автосбор" : "Запустить автосбор"}
              </button>
              <div className="muted" style={{ alignSelf: "center" }}>
                Добавлено: {autoAdded} / {autoTarget}
              </div>
            </div>
            <div className="muted">
              Советы: поверни голову влево/вправо и немного меняй расстояние — автосбор добавит разные эмбеддинги.
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default PersonsPage;
