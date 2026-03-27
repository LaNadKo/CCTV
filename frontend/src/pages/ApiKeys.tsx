import { useEffect, useMemo, useState } from "react";
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
    setError(null);
    try {
      setKeys(await listApiKeys(token));
    } catch (event: any) {
      setError(event?.message || "Не удалось загрузить ключи.");
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
        scopes
          .split(",")
          .map((scope) => scope.trim())
          .filter(Boolean)
      );
      setRawKey(result.api_key);
      setDescription("");
      await load();
    } catch (event: any) {
      setError(event?.message || "Ошибка создания ключа.");
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
    } catch (event: any) {
      alert(event?.message || "Не удалось обновить ключ.");
    } finally {
      setSavingId(null);
    }
  };

  const handleDelete = async (keyId: number) => {
    if (!token || !window.confirm("Удалить API-ключ?")) return;
    try {
      await deleteApiKey(token, keyId);
      await load();
    } catch (event: any) {
      alert(event?.message || "Не удалось удалить ключ.");
    }
  };

  const stats = useMemo(
    () => ({
      active: keys.filter((key) => key.is_active).length,
      inactive: keys.filter((key) => !key.is_active).length,
    }),
    [keys]
  );

  return (
    <div className="stack">
      <section className="page-hero">
        <div className="page-hero__content">
          <div className="page-hero__eyebrow">Administration</div>
          <h2 className="title">API-ключи</h2>
        </div>
        <div className="page-actions">
          <button className="btn secondary" onClick={load}>
            Обновить
          </button>
        </div>
      </section>

      <section className="summary-grid">
        <div className="summary-card">
          <div className="summary-card__label">Всего ключей</div>
          <div className="summary-card__value">{keys.length}</div>
          <div className="summary-card__hint">Список всех сервисных ключей, заведённых в backend.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Активные</div>
          <div className="summary-card__value">{stats.active}</div>
          <div className="summary-card__hint">Используются текущими сервисами и модулями.</div>
        </div>
        <div className="summary-card">
          <div className="summary-card__label">Отключённые</div>
          <div className="summary-card__value">{stats.inactive}</div>
          <div className="summary-card__hint">Остаются в истории, но не дают доступа после деактивации.</div>
        </div>
      </section>

      {error && <div className="danger">{error}</div>}

      <section className="admin-two-column">
        <div className="panel-card stack">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Создать ключ</h3>
              <div className="panel-card__lead">Выберите готовый профиль доступа или задайте свой набор scopes.</div>
            </div>
          </div>

          <div className="page-actions">
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
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Например: ключ ноутбука с Processor"
            />
          </label>
          <label className="field">
            <span className="label">Scopes</span>
            <input
              className="input"
              value={scopes}
              onChange={(event) => {
                setScopes(event.target.value);
                setSelectedPreset(2);
              }}
            />
          </label>
          <button className="btn" onClick={handleCreate}>
            Сгенерировать ключ
          </button>

          {rawKey && (
            <div className="panel-card" style={{ background: "rgba(34,197,94,0.08)", borderColor: "rgba(34,197,94,0.22)" }}>
              <div className="panel-card__header" style={{ marginBottom: 8 }}>
                <div>
                  <h3 className="panel-card__title">Ключ создан</h3>
                  <div className="panel-card__lead">Полное значение показывается только один раз. Сохраните его сразу.</div>
                </div>
              </div>
              <code style={{ wordBreak: "break-all", fontSize: 13 }}>{rawKey}</code>
            </div>
          )}
        </div>

        <div className="panel-card">
          <div className="panel-card__header">
            <div>
              <h3 className="panel-card__title">Существующие ключи</h3>
              <div className="panel-card__lead">Описание, scopes и статус без необходимости проваливаться в отдельные формы.</div>
            </div>
            <span className="pill">{keys.length}</span>
          </div>

          {keys.length === 0 ? (
            <div className="muted">Ключей пока нет.</div>
          ) : (
            <div className="list-shell">
              {keys.map((key) => (
                <div key={key.api_key_id} className="list-item" style={{ cursor: "default" }}>
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                    <div className="list-item__title">#{key.api_key_id} · {key.description || "Без описания"}</div>
                    <span className="pill" style={{ color: key.is_active ? "#22c55e" : "#f87171" }}>
                      {key.is_active ? "активен" : "отключён"}
                    </span>
                  </div>
                  <div className="list-item__meta">
                    Создан: {key.created_at ? new Date(key.created_at).toLocaleString() : "—"}
                    {key.expires_at ? ` · Истекает: ${new Date(key.expires_at).toLocaleString()}` : ""}
                  </div>
                  <div className="chip-row">
                    {key.scopes.length ? key.scopes.map((scope) => <span key={scope} className="pill">{scope}</span>) : <span className="muted">Нет scopes</span>}
                  </div>
                  <div className="page-actions">
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
          )}
        </div>
      </section>
    </div>
  );
};

export default ApiKeysPage;
