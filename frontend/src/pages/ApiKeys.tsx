import { useEffect, useState } from "react";
import { createApiKey, deleteApiKey, listApiKeys, updateApiKey } from "../lib/api";
import { useAuth } from "../context/AuthContext";

type Key = {
  api_key_id: number;
  description?: string;
  scopes: string[];
  is_active: boolean;
  expires_at?: string | null;
  created_at?: string | null;
};

const SCOPE_PRESETS: { label: string; description: string; scopes: string[] }[] = [
  {
    label: "Processor",
    description: "Ключ для подключения и работы модуля Processor.",
    scopes: ["processor:register", "processor:heartbeat", "processor:read", "processor:write"],
  },
  {
    label: "Детекции",
    description: "Сервисная запись событий детекции.",
    scopes: ["detections:create"],
  },
  {
    label: "Свои scopes",
    description: "Произвольный набор прав.",
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
  const [savingId, setSavingId] = useState<number | null>(null);

  const load = async () => {
    if (!token) return;
    try {
      setKeys(await listApiKeys(token));
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить ключи.");
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const applyPreset = (index: number) => {
    const preset = SCOPE_PRESETS[index];
    setSelectedPreset(index);
    if (preset.scopes.length) {
      setScopes(preset.scopes.join(","));
    }
    setDescription(preset.description);
  };

  const handleCreate = async () => {
    if (!token) return;
    setError(null);
    try {
      const result = await createApiKey(
        token,
        description,
        scopes.split(",").map((scope) => scope.trim()).filter(Boolean)
      );
      setRawKey(result.api_key);
      setDescription("");
      await load();
    } catch (e: any) {
      setError(e?.message || "Ошибка создания ключа.");
    }
  };

  const handleUpdate = async (key: Key, patch: Partial<Key>) => {
    if (!token) return;
    setSavingId(key.api_key_id);
    try {
      await updateApiKey(token, key.api_key_id, {
        description: patch.description ?? key.description,
        scopes: patch.scopes ?? key.scopes,
        is_active: patch.is_active ?? key.is_active,
        expires_at: patch.expires_at ?? key.expires_at ?? null,
      });
      await load();
    } catch (e: any) {
      alert(e?.message || "Не удалось обновить ключ.");
    } finally {
      setSavingId(null);
    }
  };

  const handleDelete = async (keyId: number) => {
    if (!token || !window.confirm("Удалить API-ключ?")) return;
    try {
      await deleteApiKey(token, keyId);
      await load();
    } catch (e: any) {
      alert(e?.message || "Не удалось удалить ключ.");
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div>
        <h2 className="title">API-ключи</h2>
        <div className="muted">
          Ключи нужны для внешних сервисов: Processor, интеграций и служебных модулей. Ключ показывается целиком только
          в момент создания.
        </div>
      </div>

      {error && <div className="danger">{error}</div>}

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Создать ключ</h3>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          {SCOPE_PRESETS.map((preset, index) => (
            <button
              key={preset.label}
              className={`btn ${selectedPreset === index ? "" : "secondary"}`}
              style={{ fontSize: 12, padding: "6px 12px" }}
              onClick={() => applyPreset(index)}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <label className="field">
          <span className="label">Описание</span>
          <input
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Например: ключ ноутбука с Processor"
          />
        </label>
        <label className="field">
          <span className="label">Scopes (через запятую)</span>
          <input
            className="input"
            value={scopes}
            onChange={(e) => {
              setScopes(e.target.value);
              setSelectedPreset(2);
            }}
          />
        </label>
        <button className="btn" onClick={handleCreate}>
          Сгенерировать
        </button>

        {rawKey && (
          <div className="card" style={{ background: "rgba(101,255,160,0.08)", border: "1px solid rgba(101,255,160,0.25)" }}>
            <div className="label" style={{ marginBottom: 6 }}>Ключ (сохраните сразу)</div>
            <code style={{ wordBreak: "break-all", fontSize: 13 }}>{rawKey}</code>
          </div>
        )}
      </div>

      <div className="card stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>Существующие ключи</h3>
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
        </div>

        {keys.length === 0 && <div className="muted">Ключей пока нет.</div>}

        <div className="stack" style={{ gap: 10 }}>
          {keys.map((key) => (
            <div key={key.api_key_id} className="hour-card" style={{ cursor: "default" }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <div className="stack" style={{ gap: 4 }}>
                  <div style={{ fontWeight: 700 }}>#{key.api_key_id} · {key.description || "Без описания"}</div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Создан: {key.created_at ? new Date(key.created_at).toLocaleString() : "—"}
                    {key.expires_at ? ` · Истекает: ${new Date(key.expires_at).toLocaleString()}` : ""}
                  </div>
                </div>
                <span className="pill" style={{ color: key.is_active ? "#22c55e" : "#f87171" }}>
                  {key.is_active ? "активен" : "отключён"}
                </span>
              </div>

              <div className="muted" style={{ marginTop: 8 }}>{key.scopes.join(", ") || "Нет scopes"}</div>

              <div className="row" style={{ marginTop: 10, gap: 8 }}>
                <button
                  className="btn secondary"
                  onClick={() => handleUpdate(key, { is_active: !key.is_active })}
                  disabled={savingId === key.api_key_id}
                >
                  {key.is_active ? "Отключить" : "Включить"}
                </button>
                <button
                  className="btn secondary"
                  onClick={() => {
                    const next = window.prompt("Новое описание ключа", key.description || "");
                    if (next === null) return;
                    handleUpdate(key, { description: next });
                  }}
                  disabled={savingId === key.api_key_id}
                >
                  Изменить описание
                </button>
                <button className="btn secondary" onClick={() => handleDelete(key.api_key_id)}>
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ApiKeysPage;
