import { useEffect, useState } from "react";
import { createApiKey, listApiKeys } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Key = { api_key_id: number; description?: string; scopes: string[]; is_active: boolean };

const SCOPE_PRESETS: { label: string; description: string; scopes: string[] }[] = [
  {
    label: "Процессор (полный)",
    description: "Processor service",
    scopes: ["processor:register", "processor:heartbeat", "processor:read", "processor:write"],
  },
  {
    label: "Детекции (запись)",
    description: "Detection writer",
    scopes: ["detections:create"],
  },
  {
    label: "Пользовательский",
    description: "",
    scopes: [],
  },
];

const ApiKeysPage: React.FC = () => {
  const { token } = useAuth();
  const [keys, setKeys] = useState<Key[]>([]);
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [scopes, setScopes] = useState("processor:register,processor:heartbeat,processor:read,processor:write");
  const [selectedPreset, setSelectedPreset] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!token) return;
    try {
      const res = await listApiKeys(token);
      setKeys(res);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить ключи");
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const applyPreset = (idx: number) => {
    setSelectedPreset(idx);
    const p = SCOPE_PRESETS[idx];
    if (p.scopes.length > 0) {
      setScopes(p.scopes.join(","));
    }
    if (p.description) {
      setDescription(p.description);
    }
  };

  const create = async () => {
    if (!token) return;
    setError(null);
    try {
      const res = await createApiKey(token, description, scopes.split(",").map((s) => s.trim()).filter(Boolean));
      setRawKey(res.api_key);
      setDescription("");
      await load();
    } catch (e: any) {
      setError(e?.message || "Ошибка создания ключа");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div>
        <h2 className="title">API-ключи</h2>
        <div className="muted">Ключи для внешних сервисов. Скопируйте ключ сразу — повторно не показывается.</div>
      </div>
      {error && <div className="danger">{error}</div>}
      <div className="card stack">
        <h3 style={{ margin: 0 }}>Создать ключ</h3>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          {SCOPE_PRESETS.map((p, i) => (
            <button
              key={i}
              className={`btn ${selectedPreset === i ? "" : "secondary"}`}
              style={{ fontSize: 12, padding: "6px 12px" }}
              onClick={() => applyPreset(i)}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="field">
          <label className="label">Описание</label>
          <input
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Для чего этот ключ"
          />
        </div>
        <div className="field">
          <label className="label">Scopes (через запятую)</label>
          <input
            className="input"
            value={scopes}
            onChange={(e) => { setScopes(e.target.value); setSelectedPreset(2); }}
            placeholder="processor:register,processor:heartbeat"
          />
        </div>
        <button className="btn" onClick={create}>
          Сгенерировать
        </button>
        {rawKey && (
          <div className="card" style={{ background: "rgba(101,255,160,0.08)", border: "1px solid rgba(101,255,160,0.3)" }}>
            <div className="label" style={{ marginBottom: 4 }}>Ключ (скопируйте и сохраните!)</div>
            <code style={{ wordBreak: "break-all", fontSize: 13 }}>{rawKey}</code>
            <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
              Пропишите в <code>.env</code>: <code>PROCESSOR_API_KEY={rawKey}</code>
            </div>
          </div>
        )}
      </div>
      <div className="card stack">
        <h3 style={{ margin: 0 }}>Существующие ключи</h3>
        {keys.length === 0 && <div className="muted">Нет ключей.</div>}
        <div className="stack" style={{ gap: 8 }}>
          {keys.map((k) => (
            <div key={k.api_key_id} className="hour-card">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ fontWeight: 600 }}>#{k.api_key_id} — {k.description || "без описания"}</div>
                <span className="pill" style={{ color: k.is_active ? "#65ffa0" : "#ff6b6b" }}>
                  {k.is_active ? "active" : "inactive"}
                </span>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                {k.scopes.join(", ") || "нет скоупов"}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ApiKeysPage;
