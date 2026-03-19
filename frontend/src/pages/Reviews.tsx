import { useEffect, useState } from "react";
import { getPending, reviewEvent, enrollPersonFromPhoto, enrollPersonFromSnapshot, API_URL } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Pending = {
  event_id: number;
  camera_id: number;
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // enroll form
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

  const handleReview = async (event_id: number, status: "approved" | "rejected") => {
    if (!token) return;
    const person_id = personMap[event_id] ? Number(personMap[event_id]) : undefined;
    try {
      await reviewEvent(token, event_id, status, person_id);
      // удаляем карточку локально, без полного refetch
      setItems((prev) => prev.filter((i) => i.event_id !== event_id));
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
      const res = await enrollPersonFromPhoto(token, file, firstName || undefined, lastName || undefined, middleName || undefined);
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
          <h2 className="title">Ревью событий</h2>
          <div className="muted">Неопознанные лица попадают сюда. Можно привязать person_id.</div>
        </div>
        <button className="btn secondary" onClick={load}>
          Обновить
        </button>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <h3 style={{ marginTop: 0 }}>Добавить персону из фото</h3>
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
        {enrollMsg && <div className="muted" style={{ marginTop: 6 }}>{enrollMsg}</div>}
      </div>

      {error && <div className="danger">{error}</div>}
      {loading ? (
        <div className="card">Загрузка...</div>
      ) : (
        <div className="grid">
          {items.map((ev) => (
            <div key={ev.event_id} className="card">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <div className="muted">Event #{ev.event_id}</div>
                  <h3 style={{ margin: 0 }}>Камера {ev.camera_id}</h3>
                </div>
                <span className="pill">ts {new Date(ev.event_ts).toLocaleString()}</span>
              </div>
              <div className="muted" style={{ marginTop: 8 }}>
                Персона: {ev.person_label || (ev.person_id ? `ID ${ev.person_id}` : "неизвестно")} | confidence: {ev.confidence ?? "n/a"}
              </div>
              {token && (ev.snapshot_url || ev.recording_file_id) && (
                <div className="grid" style={{ marginTop: 10, gap: 8, gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))" }}>
                  {ev.snapshot_url && (
                    <div className="stack">
                      <span className="label" style={{ color: "#9aa4b5" }}>Снимок</span>
                      <img
                        src={`${API_URL}${ev.snapshot_url}?t=${Date.now()}`}
                        alt="snapshot"
                        style={{ width: "100%", borderRadius: 8, background: "#0d1b2a" }}
                      />
                    </div>
                  )}
                  {ev.recording_file_id && (
                    <div className="stack">
                      <span className="label" style={{ color: "#9aa4b5" }}>Открыть видео</span>
                      <video controls style={{ width: "100%", borderRadius: 8, background: "#0d1b2a" }}>
                        <source
                          src={`${API_URL}/recordings/file/${ev.recording_file_id}?token=${encodeURIComponent(token)}`}
                          type="video/mp4"
                        />
                      </video>
                    </div>
                  )}
                </div>
              )}
              <div className="field" style={{ marginTop: 10 }}>
                <span className="label">Назначить person_id (если знаете)</span>
                <input
                  className="input"
                  value={personMap[ev.event_id] || ""}
                  onChange={(e) => setPersonMap((prev) => ({ ...prev, [ev.event_id]: e.target.value }))}
                  placeholder="ID персоны"
                />
              </div>
              {ev.snapshot_url && (
                <div className="stack" style={{ marginTop: 10 }}>
                  <span className="label">Создать персону из снимка (ФИО опционально)</span>
                  <input
                    className="input"
                    placeholder="Фамилия Имя Отчество"
                    value={fioMap[ev.event_id] || ""}
                    onChange={(e) => setFioMap((p) => ({ ...p, [ev.event_id]: e.target.value }))}
                  />
                  <button
                    className="btn secondary"
                    onClick={async () => {
                      if (!token) return;
                      const fio = (fioMap[ev.event_id] || "").trim().split(" ").filter(Boolean);
                      const last_name = fio[0];
                      const first_name = fio[1];
                      const middle_name = fio[2];
                      try {
                        const res = await enrollPersonFromSnapshot(token, {
                          event_id: ev.event_id,
                          first_name,
                          last_name,
                          middle_name,
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
                <button className="btn" onClick={() => handleReview(ev.event_id, "approved")}>
                  Одобрить
                </button>
                <button className="btn secondary" onClick={() => handleReview(ev.event_id, "rejected")}>
                  Отклонить
                </button>
              </div>
            </div>
          ))}
          {items.length === 0 && <div className="card">Пока нет событий.</div>}
        </div>
      )}
    </div>
  );
};

export default ReviewsPage;
