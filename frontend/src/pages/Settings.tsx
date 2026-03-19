import { useState } from "react";
import { clearApiUrl, getApiUrl, setApiUrl } from "../lib/api";
import { defaultUiSettings, loadUiSettings, saveUiSettings, type LiveDensity } from "../lib/uiSettings";

const NAV_OPTIONS = [
  { key: "/live", label: "Live" },
  { key: "/reviews", label: "Ревью" },
  { key: "/reports", label: "Отчёты" },
  { key: "/persons", label: "Персоны" },
  { key: "/recordings", label: "Записи" },
  { key: "/groups", label: "Группы" },
  { key: "/cameras", label: "Камеры" },
  { key: "/processors", label: "Процессоры" },
  { key: "/users", label: "Пользователи" },
  { key: "/apikeys", label: "API-ключи" },
];

const DENSITY_LABELS: Record<LiveDensity, string> = {
  compact: "Компактно",
  comfortable: "Стандартно",
  focus: "Крупно",
};

const SettingsPage: React.FC = () => {
  const [apiUrl, setApiUrlDraft] = useState(getApiUrl());
  const [settings, setSettings] = useState(loadUiSettings());
  const [saved, setSaved] = useState<string | null>(null);

  const togglePrimary = (key: string) => {
    setSettings((prev) => {
      const exists = prev.primaryNav.includes(key);
      const nextPrimary = exists
        ? prev.primaryNav.filter((item) => item !== key)
        : [...prev.primaryNav, key];
      return {
        ...prev,
        primaryNav: nextPrimary.length ? nextPrimary : defaultUiSettings.primaryNav,
      };
    });
  };

  const persistUi = () => {
    saveUiSettings(settings);
    setSaved("Настройки интерфейса сохранены. Перезапустите окно, если нужно полностью пересобрать навигацию.");
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div>
        <h2 className="title">Настройки</h2>
        <div className="muted">Кастомизация интерфейса desktop-клиента и адреса backend.</div>
      </div>

      {saved && <div className="success">{saved}</div>}

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Подключение к backend</h3>
        <label className="field">
          <span className="label">API URL</span>
          <input className="input" value={apiUrl} onChange={(e) => setApiUrlDraft(e.target.value)} />
        </label>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn" onClick={() => setApiUrl(apiUrl)}>
            Сохранить адрес
          </button>
          <button className="btn secondary" onClick={clearApiUrl}>
            Сбросить
          </button>
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Главные вкладки</h3>
        <div className="muted">Выберите, какие разделы держать в верхней панели. Остальные будут жить в меню.</div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
          {NAV_OPTIONS.map((option) => {
            const active = settings.primaryNav.includes(option.key);
            return (
              <button
                key={option.key}
                className={active ? "hour-card active" : "hour-card"}
                onClick={() => togglePrimary(option.key)}
                type="button"
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Вид Live</h3>
        <div className="row" style={{ gap: 8 }}>
          {(["compact", "comfortable", "focus"] as LiveDensity[]).map((density) => (
            <button
              key={density}
              className={settings.liveDensity === density ? "btn" : "btn secondary"}
              onClick={() => setSettings((prev) => ({ ...prev, liveDensity: density }))}
            >
              {DENSITY_LABELS[density]}
            </button>
          ))}
        </div>
        <div className="muted">Компактный режим ближе к сетке Hik-Connect, крупный режим делает карточки больше.</div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Поведение desktop-приложения</h3>
        <div className="muted">
          Если окно скрыто в трей, повторный запуск должен поднимать уже работающий экземпляр. После обновления desktop переустановите его поверх текущего.
        </div>
      </div>

      <div className="row" style={{ gap: 8 }}>
        <button className="btn" onClick={persistUi}>
          Сохранить интерфейс
        </button>
      </div>
    </div>
  );
};

export default SettingsPage;
