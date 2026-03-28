import { useEffect, useMemo, useState } from "react";
import { clearApiUrl, getApiUrl, setApiUrl } from "../lib/api";
import { loadUiSettings, saveUiSettings, type LiveDensity, type ThemeMode, type UiSettings } from "../lib/uiSettings";
import { useAuth } from "../context/AuthContext";

const NAV_OPTIONS = [
  { key: "/live", label: "Live" },
  { key: "/recordings", label: "Записи" },
  { key: "/reviews", label: "Ревью" },
  { key: "/reports", label: "Отчёты" },
  { key: "/persons", label: "Персоны" },
  { key: "/groups", label: "Группы" },
  { key: "/cameras", label: "Камеры" },
  { key: "/processors", label: "Процессоры" },
  { key: "/users", label: "Пользователи" },
  { key: "/apikeys", label: "API-ключи" },
  { key: "/help", label: "Справка" },
] as const;

const MAX_PRIMARY_NAV = 5;

const DENSITY_LABELS: Record<LiveDensity, string> = {
  compact: "Компактно",
  comfortable: "Стандартно",
  focus: "Крупно",
};

const THEME_LABELS: Record<ThemeMode, string> = {
  system: "Как в системе",
  dark: "Тёмная",
  light: "Светлая",
};

function reorderList(items: string[], fromIndex: number, toIndex: number): string[] {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) {
    return items;
  }

  const next = [...items];
  const [moved] = next.splice(fromIndex, 1);
  if (!moved) return items;
  next.splice(toIndex, 0, moved);
  return next;
}

function normalizePrimaryNav(primaryNav: string[], allowedNavKeys: string[], fallbackPrimary: string[]): string[] {
  const allowed = primaryNav
    .filter((key, index, items) => allowedNavKeys.includes(key) && items.indexOf(key) === index)
    .slice(0, MAX_PRIMARY_NAV);
  return allowed.length ? allowed : fallbackPrimary;
}

const SettingsPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role_id === 1;
  const isUser = user?.role_id === 1 || user?.role_id === 2;

  const allowedNavOptions = useMemo(
    () =>
      NAV_OPTIONS.filter((option) => {
        if (option.key === "/reviews" || option.key === "/reports") return isUser;
        if (["/persons", "/cameras", "/processors", "/users", "/apikeys"].includes(option.key)) return isAdmin;
        return true;
      }),
    [isAdmin, isUser]
  );

  const allowedNavKeys = useMemo<string[]>(() => allowedNavOptions.map((option) => option.key), [allowedNavOptions]);
  const fallbackPrimary = useMemo(
    () => ["/live", "/recordings", "/reviews", "/reports"].filter((key) => allowedNavKeys.includes(key)).slice(0, 4),
    [allowedNavKeys]
  );

  const [apiUrl, setApiUrlDraft] = useState(getApiUrl());
  const [draggedKey, setDraggedKey] = useState<string | null>(null);
  const [settings, setSettings] = useState<UiSettings>(() => {
    const loaded = loadUiSettings();
    return {
      ...loaded,
      primaryNav: normalizePrimaryNav(loaded.primaryNav, allowedNavKeys, fallbackPrimary),
    };
  });

  const effectivePrimaryNav = useMemo(
    () => normalizePrimaryNav(settings.primaryNav, allowedNavKeys, fallbackPrimary),
    [allowedNavKeys, fallbackPrimary, settings.primaryNav]
  );

  useEffect(() => {
    saveUiSettings({
      ...settings,
      primaryNav: effectivePrimaryNav,
    });
  }, [effectivePrimaryNav, settings]);

  const selectedNavOptions = useMemo(
    () =>
      effectivePrimaryNav
        .map((key) => allowedNavOptions.find((option) => option.key === key))
        .filter((option): option is (typeof allowedNavOptions)[number] => Boolean(option)),
    [allowedNavOptions, effectivePrimaryNav]
  );

  const availableNavOptions = useMemo(
    () => allowedNavOptions.filter((option) => !effectivePrimaryNav.includes(option.key)),
    [allowedNavOptions, effectivePrimaryNav]
  );

  const updateSettings = (updater: (prev: UiSettings) => UiSettings) => {
    setSettings((prev) => {
      const next = updater(prev);
      return {
        ...next,
        primaryNav: normalizePrimaryNav(next.primaryNav, allowedNavKeys, fallbackPrimary),
      };
    });
  };

  const togglePrimary = (key: string) => {
    updateSettings((prev) => {
      if (prev.primaryNav.includes(key)) {
        return {
          ...prev,
          primaryNav: prev.primaryNav.filter((item) => item !== key),
        };
      }

      if (prev.primaryNav.length >= MAX_PRIMARY_NAV) {
        return prev;
      }

      return {
        ...prev,
        primaryNav: [...prev.primaryNav, key],
      };
    });
  };

  const movePrimary = (key: string, shift: -1 | 1) => {
    updateSettings((prev) => {
      const index = prev.primaryNav.indexOf(key);
      if (index === -1) return prev;
      const targetIndex = index + shift;
      if (targetIndex < 0 || targetIndex >= prev.primaryNav.length) return prev;
      return {
        ...prev,
        primaryNav: reorderList(prev.primaryNav, index, targetIndex),
      };
    });
  };

  const movePrimaryByDrop = (targetKey: string) => {
    if (!draggedKey || draggedKey === targetKey) {
      setDraggedKey(null);
      return;
    }

    updateSettings((prev) => {
      const fromIndex = prev.primaryNav.indexOf(draggedKey);
      const toIndex = prev.primaryNav.indexOf(targetKey);
      if (fromIndex === -1 || toIndex === -1) return prev;
      return {
        ...prev,
        primaryNav: reorderList(prev.primaryNav, fromIndex, toIndex),
      };
    });

    setDraggedKey(null);
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="page-hero">
        <div className="page-hero__content">
          <h2 className="title">Настройки</h2>
          <div className="muted">Тема, состав быстрого доступа и плотность Live применяются сразу после изменения.</div>
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Подключение к backend</h3>
        <label className="field">
          <span className="label">API URL</span>
          <input className="input" value={apiUrl} onChange={(event) => setApiUrlDraft(event.target.value)} />
        </label>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn" onClick={() => setApiUrl(apiUrl)} type="button">
            Сохранить адрес
          </button>
          <button className="btn secondary" onClick={clearApiUrl} type="button">
            Сбросить
          </button>
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Тема приложения</h3>
        <div className="row" style={{ gap: 8 }}>
          {(["system", "dark", "light"] as ThemeMode[]).map((mode) => (
            <button
              key={mode}
              className={settings.themeMode === mode ? "btn" : "btn secondary"}
              onClick={() => updateSettings((prev) => ({ ...prev, themeMode: mode }))}
              type="button"
            >
              {THEME_LABELS[mode]}
            </button>
          ))}
        </div>
        <div className="muted">Режим «Как в системе» автоматически синхронизируется с настройками Windows и macOS.</div>
      </div>

      <div className="card stack">
        <div className="stack" style={{ gap: 6 }}>
          <h3 style={{ margin: 0 }}>Быстрый доступ</h3>
          <div className="muted">
            До {MAX_PRIMARY_NAV} вкладок в шапке. Перетаскивайте карточки мышью или меняйте порядок стрелками.
          </div>
        </div>

        <div className="settings-nav-order">
          {selectedNavOptions.map((option, index) => (
            <article
              key={option.key}
              className={`settings-nav-item${draggedKey === option.key ? " dragging" : ""}`}
              draggable
              onDragStart={() => setDraggedKey(option.key)}
              onDragEnd={() => setDraggedKey(null)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => movePrimaryByDrop(option.key)}
            >
              <div className="settings-nav-item__meta">
                <span className="pill">#{index + 1}</span>
                <div>
                  <div className="settings-nav-item__title">{option.label}</div>
                  <div className="muted">Эта вкладка отображается в панели быстрого доступа.</div>
                </div>
              </div>
              <div className="page-actions">
                <button
                  className="btn secondary"
                  onClick={() => movePrimary(option.key, -1)}
                  disabled={index === 0}
                  type="button"
                >
                  ←
                </button>
                <button
                  className="btn secondary"
                  onClick={() => movePrimary(option.key, 1)}
                  disabled={index === selectedNavOptions.length - 1}
                  type="button"
                >
                  →
                </button>
                <button className="btn secondary" onClick={() => togglePrimary(option.key)} type="button">
                  Убрать
                </button>
              </div>
            </article>
          ))}
        </div>

        <div className="stack" style={{ gap: 10 }}>
          <div className="label">Остальные вкладки</div>
          <div className="settings-nav-palette">
            {availableNavOptions.map((option) => (
              <button
                key={option.key}
                className="hour-card"
                onClick={() => togglePrimary(option.key)}
                disabled={selectedNavOptions.length >= MAX_PRIMARY_NAV}
                type="button"
              >
                + {option.label}
              </button>
            ))}
          </div>
          {selectedNavOptions.length >= MAX_PRIMARY_NAV && (
            <div className="muted">Достигнут лимит быстрого доступа. Уберите одну вкладку, чтобы добавить другую.</div>
          )}
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Вид Live</h3>
        <div className="row" style={{ gap: 8 }}>
          {(["compact", "comfortable", "focus"] as LiveDensity[]).map((density) => (
            <button
              key={density}
              className={settings.liveDensity === density ? "btn" : "btn secondary"}
              onClick={() => updateSettings((prev) => ({ ...prev, liveDensity: density }))}
              type="button"
            >
              {DENSITY_LABELS[density]}
            </button>
          ))}
        </div>
        <div className="muted">Компактный режим ближе к мониторной сетке, крупный фокусируется на меньшем числе камер.</div>
      </div>
    </div>
  );
};

export default SettingsPage;
