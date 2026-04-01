import { useEffect, useMemo, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import {
  activateTotp,
  clearApiUrl,
  disableTotp,
  getApiUrl,
  getTotpStatus,
  setApiUrl,
  setupTotp,
  updateProfile,
} from "../lib/api";
import { useAuth } from "../context/AuthContext";
import {
  DEFAULT_PRIMARY_ACCENT,
  DEFAULT_SECONDARY_ACCENT,
  loadUiSettings,
  saveUiSettings,
  type LiveDensity,
  type ThemeMode,
  type UiSettings,
} from "../lib/uiSettings";

const NAV_OPTIONS = [
  { key: "/live", label: "Live" },
  { key: "/recordings", label: "Архив" },
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

const ACCENT_PRESETS = [
  { label: "Console", primary: DEFAULT_PRIMARY_ACCENT, secondary: DEFAULT_SECONDARY_ACCENT },
  { label: "Arctic", primary: "#4ad7ff", secondary: "#3b82f6" },
  { label: "Signal", primary: "#22c55e", secondary: "#14b8a6" },
  { label: "Ember", primary: "#f97316", secondary: "#ef4444" },
] as const;

function reorderList(items: string[], fromIndex: number, toIndex: number): string[] {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return items;
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
  const { user, token, refreshUser } = useAuth();
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

  const [profile, setProfile] = useState({
    last_name: user?.last_name ?? "",
    first_name: user?.first_name ?? "",
    middle_name: user?.middle_name ?? "",
  });
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [totpEnabled, setTotpEnabled] = useState<boolean>(!!user?.totp_enabled);
  const [totpSetupData, setTotpSetupData] = useState<{ secret: string; provisioning_uri: string } | null>(null);
  const [totpModalOpen, setTotpModalOpen] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const [totpBusy, setTotpBusy] = useState(false);
  const [totpMessage, setTotpMessage] = useState<string | null>(null);
  const [totpError, setTotpError] = useState<string | null>(null);

  useEffect(() => {
    setProfile({
      last_name: user?.last_name ?? "",
      first_name: user?.first_name ?? "",
      middle_name: user?.middle_name ?? "",
    });
    setTotpEnabled(!!user?.totp_enabled);
  }, [user?.first_name, user?.last_name, user?.middle_name, user?.totp_enabled]);

  useEffect(() => {
    saveUiSettings({
      ...settings,
      primaryNav: normalizePrimaryNav(settings.primaryNav, allowedNavKeys, fallbackPrimary),
    });
  }, [allowedNavKeys, fallbackPrimary, settings]);

  useEffect(() => {
    const loadTotp = async () => {
      if (!token) return;
      try {
        const status = await getTotpStatus(token);
        setTotpEnabled(status.enabled);
      } catch {
        // keep page usable even if backend is unavailable
      }
    };
    void loadTotp();
  }, [token]);

  const effectivePrimaryNav = useMemo(
    () => normalizePrimaryNav(settings.primaryNav, allowedNavKeys, fallbackPrimary),
    [allowedNavKeys, fallbackPrimary, settings.primaryNav]
  );

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
        return { ...prev, primaryNav: prev.primaryNav.filter((item) => item !== key) };
      }
      if (prev.primaryNav.length >= MAX_PRIMARY_NAV) return prev;
      return { ...prev, primaryNav: [...prev.primaryNav, key] };
    });
  };

  const movePrimary = (key: string, shift: -1 | 1) => {
    updateSettings((prev) => {
      const index = prev.primaryNav.indexOf(key);
      if (index === -1) return prev;
      const targetIndex = index + shift;
      if (targetIndex < 0 || targetIndex >= prev.primaryNav.length) return prev;
      return { ...prev, primaryNav: reorderList(prev.primaryNav, index, targetIndex) };
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
      return { ...prev, primaryNav: reorderList(prev.primaryNav, fromIndex, toIndex) };
    });
    setDraggedKey(null);
  };

  const handleProfileSave = async () => {
    if (!token) return;
    setProfileBusy(true);
    setProfileError(null);
    setProfileMessage(null);
    try {
      await updateProfile(token, {
        last_name: profile.last_name.trim() || null,
        first_name: profile.first_name.trim() || null,
        middle_name: profile.middle_name.trim() || null,
      });
      await refreshUser();
      setProfileMessage("Профиль обновлён");
    } catch (error: any) {
      setProfileError(error?.message || "Не удалось сохранить профиль");
    } finally {
      setProfileBusy(false);
    }
  };

  const handleTotpSetup = async () => {
    if (!token) return;
    setTotpBusy(true);
    setTotpError(null);
    setTotpMessage(null);
    try {
      const setup = await setupTotp(token);
      setTotpSetupData(setup);
      setTotpModalOpen(true);
      setTotpCode("");
    } catch (error: any) {
      setTotpError(error?.message || "Не удалось подготовить TOTP");
    } finally {
      setTotpBusy(false);
    }
  };

  const handleTotpActivate = async () => {
    if (!token || !totpCode.trim()) return;
    setTotpBusy(true);
    setTotpError(null);
    setTotpMessage(null);
    try {
      const status = await activateTotp(token, totpCode.trim());
      setTotpEnabled(status.enabled);
      setTotpSetupData(null);
      setTotpModalOpen(false);
      setTotpCode("");
      await refreshUser();
      setTotpMessage("Двухфакторная авторизация включена");
    } catch (error: any) {
      setTotpError(error?.message || "Некорректный проверочный код");
    } finally {
      setTotpBusy(false);
    }
  };

  const handleTotpDisable = async () => {
    if (!token) return;
    setTotpBusy(true);
    setTotpError(null);
    setTotpMessage(null);
    try {
      await disableTotp(token);
      setTotpEnabled(false);
      setTotpSetupData(null);
      setTotpModalOpen(false);
      setTotpCode("");
      await refreshUser();
      setTotpMessage("Двухфакторная авторизация отключена");
    } catch (error: any) {
      setTotpError(error?.message || "Не удалось отключить TOTP");
    } finally {
      setTotpBusy(false);
    }
  };

  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <div className="page-hero">
        <div className="page-hero__content">
          <h2 className="title">Настройки</h2>
          <div className="muted">Управление профилем, внешним видом интерфейса и подключением к backend Console.</div>
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Профиль</h3>
        <div className="muted">Эти данные отображаются в интерфейсе и входят в отчёты.</div>
        <label className="field">
          <span className="label">Фамилия</span>
          <input className="input" value={profile.last_name} onChange={(event) => setProfile((prev) => ({ ...prev, last_name: event.target.value }))} />
        </label>
        <label className="field">
          <span className="label">Имя</span>
          <input className="input" value={profile.first_name} onChange={(event) => setProfile((prev) => ({ ...prev, first_name: event.target.value }))} />
        </label>
        <label className="field">
          <span className="label">Отчество</span>
          <input className="input" value={profile.middle_name} onChange={(event) => setProfile((prev) => ({ ...prev, middle_name: event.target.value }))} />
        </label>
        {profileError && <div className="danger">{profileError}</div>}
        {profileMessage && <div className="success">{profileMessage}</div>}
        <div className="row" style={{ gap: 8 }}>
          <button className="btn" onClick={handleProfileSave} type="button" disabled={profileBusy}>
            {profileBusy ? "Сохранение..." : "Сохранить профиль"}
          </button>
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Двухфакторная авторизация</h3>
        <div className="muted">Для входа используется TOTP-код из приложения-аутентификатора.</div>
        <div className="row" style={{ gap: 8, alignItems: "center" }}>
          <span className="pill" style={{ color: totpEnabled ? "#22c55e" : "#f87171" }}>
            {totpEnabled ? "Включена" : "Отключена"}
          </span>
          {totpEnabled ? (
            <button className="btn secondary" onClick={handleTotpDisable} type="button" disabled={totpBusy}>
              Отключить
            </button>
          ) : (
            <>
              <button className="btn" onClick={handleTotpSetup} type="button" disabled={totpBusy}>
                Подключить TOTP
              </button>
              {totpSetupData && (
                <button className="btn secondary" onClick={() => setTotpModalOpen(true)} type="button" disabled={totpBusy}>
                  Показать QR-код
                </button>
              )}
            </>
          )}
        </div>

        {totpError && <div className="danger">{totpError}</div>}
        {totpMessage && <div className="success">{totpMessage}</div>}
      </div>

      {totpModalOpen && totpSetupData && !totpEnabled && (
        <div className="modal-backdrop" onClick={() => setTotpModalOpen(false)}>
          <div className="modal settings-totp-modal" onClick={(event) => event.stopPropagation()}>
            <div className="stack" style={{ gap: 14 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                <div className="stack" style={{ gap: 6 }}>
                  <h3 style={{ margin: 0 }}>Подключение TOTP</h3>
                  <div className="muted">Отсканируйте QR-код в приложении-аутентификаторе, затем введите код подтверждения для завершения настройки.</div>
                </div>
                <button className="btn secondary" onClick={() => setTotpModalOpen(false)} type="button">
                  Закрыть
                </button>
              </div>

              <div className="settings-totp-qr-card">
                <QRCodeSVG value={totpSetupData.provisioning_uri} size={220} bgColor="#ffffff" fgColor="#111827" includeMargin />
              </div>

              <div className="stack" style={{ gap: 8 }}>
                <div className="label">Секрет</div>
                <code className="settings-totp-secret">{totpSetupData.secret}</code>
              </div>

              <label className="field">
                <span className="label">Provisioning URI</span>
                <input className="input" readOnly value={totpSetupData.provisioning_uri} />
              </label>

              <label className="field">
                <span className="label">Проверочный код</span>
                <input className="input" placeholder="123456" value={totpCode} onChange={(event) => setTotpCode(event.target.value)} />
              </label>

              <div className="row" style={{ gap: 8 }}>
                <button className="btn" onClick={handleTotpActivate} type="button" disabled={totpBusy || !totpCode.trim()}>
                  Подтвердить подключение
                </button>
                <button
                  className="btn secondary"
                  onClick={() => {
                    setTotpModalOpen(false);
                    setTotpSetupData(null);
                    setTotpCode("");
                    setTotpError(null);
                    setTotpMessage(null);
                  }}
                  type="button"
                >
                  Отмена
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Подключение к backend</h3>
        <label className="field">
          <span className="label">API URL</span>
          <input className="input" value={apiUrl} onChange={(event) => setApiUrlDraft(event.target.value)} />
        </label>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn" onClick={() => setApiUrl(apiUrl)} type="button">Применить адрес</button>
          <button className="btn secondary" onClick={clearApiUrl} type="button">Сбросить</button>
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Тема интерфейса</h3>
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
      </div>

      <div className="card stack">
        <div className="stack" style={{ gap: 6 }}>
          <h3 style={{ margin: 0 }}>Акцентные цвета</h3>
          <div className="muted">Цвета и предустановки темы интерфейса для всех экранов Console.</div>
        </div>

        <div className="settings-theme-presets">
          {ACCENT_PRESETS.map((preset) => {
            const active =
              settings.primaryAccent === preset.primary.toLowerCase() &&
              settings.secondaryAccent === preset.secondary.toLowerCase();

            return (
              <button
                key={preset.label}
                className={`settings-theme-preset${active ? " active" : ""}`}
                onClick={() =>
                  updateSettings((prev) => ({
                    ...prev,
                    primaryAccent: preset.primary,
                    secondaryAccent: preset.secondary,
                  }))
                }
                type="button"
              >
                <span className="settings-theme-preset__swatch" style={{ background: `linear-gradient(135deg, ${preset.primary}, ${preset.secondary})` }} />
                <span className="settings-theme-preset__title">{preset.label}</span>
                <span className="muted">{preset.primary.toUpperCase()} / {preset.secondary.toUpperCase()}</span>
              </button>
            );
          })}
        </div>

        <div className="settings-theme-grid">
          <label className="settings-theme-color-card">
            <span className="label">Основной цвет</span>
            <div className="settings-theme-color-row">
              <input className="settings-theme-color-input" onChange={(event) => updateSettings((prev) => ({ ...prev, primaryAccent: event.target.value }))} type="color" value={settings.primaryAccent} />
              <code className="settings-theme-color-value">{settings.primaryAccent.toUpperCase()}</code>
            </div>
          </label>

          <label className="settings-theme-color-card">
            <span className="label">Вторичный цвет</span>
            <div className="settings-theme-color-row">
              <input className="settings-theme-color-input" onChange={(event) => updateSettings((prev) => ({ ...prev, secondaryAccent: event.target.value }))} type="color" value={settings.secondaryAccent} />
              <code className="settings-theme-color-value">{settings.secondaryAccent.toUpperCase()}</code>
            </div>
          </label>
        </div>

        <div className="settings-theme-preview" style={{ background: `linear-gradient(135deg, ${settings.primaryAccent}, ${settings.secondaryAccent})` }}>
          <div className="settings-theme-preview__badge">Live Preview</div>
          <div className="settings-theme-preview__title">Console Palette</div>
          <div className="settings-theme-preview__text">Пример того, как выбранная палитра будет выглядеть на карточках и управляющих элементах интерфейса.</div>
        </div>

        <div className="row" style={{ gap: 8 }}>
          <button
            className="btn secondary"
            onClick={() =>
              updateSettings((prev) => ({
                ...prev,
                primaryAccent: DEFAULT_PRIMARY_ACCENT,
                secondaryAccent: DEFAULT_SECONDARY_ACCENT,
              }))
            }
            type="button"
          >
            Сбросить цвета
          </button>
        </div>
      </div>

      <div className="card stack">
        <div className="stack" style={{ gap: 6 }}>
          <h3 style={{ margin: 0 }}>Главная навигация</h3>
          <div className="muted">До {MAX_PRIMARY_NAV} вкладок в шапке. Остальные разделы остаются доступными через меню.</div>
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
                  <div className="muted">Эта вкладка отображается в верхней панели навигации.</div>
                </div>
              </div>
              <div className="page-actions">
                <button className="btn secondary" onClick={() => movePrimary(option.key, -1)} disabled={index === 0} type="button">Выше</button>
                <button className="btn secondary" onClick={() => movePrimary(option.key, 1)} disabled={index === selectedNavOptions.length - 1} type="button">Ниже</button>
                <button className="btn secondary" onClick={() => togglePrimary(option.key)} type="button">Убрать</button>
              </div>
            </article>
          ))}
        </div>

        <div className="stack" style={{ gap: 10 }}>
          <div className="label">Доступные разделы</div>
          <div className="settings-nav-palette">
            {availableNavOptions.map((option) => (
              <button key={option.key} className="hour-card" onClick={() => togglePrimary(option.key)} disabled={selectedNavOptions.length >= MAX_PRIMARY_NAV} type="button">
                + {option.label}
              </button>
            ))}
          </div>
          {selectedNavOptions.length >= MAX_PRIMARY_NAV && (
            <div className="muted">Достигнут лимит главных вкладок. Уберите одну из текущих, чтобы добавить новую.</div>
          )}
        </div>
      </div>

      <div className="card stack">
        <h3 style={{ margin: 0 }}>Плотность Live</h3>
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
        <div className="muted">Управляет размером карточек и плотностью сетки на экране Live.</div>
      </div>
    </div>
  );
};

export default SettingsPage;
