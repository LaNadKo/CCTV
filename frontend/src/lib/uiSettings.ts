export type LiveDensity = "compact" | "comfortable" | "focus";
export type ThemeMode = "system" | "dark" | "light";

export type UiSettings = {
  version: number;
  primaryNav: string[];
  liveDensity: LiveDensity;
  themeMode: ThemeMode;
  closeToTrayHintDismissed: boolean;
};

const STORAGE_KEY = "cctv_ui_settings";
const UI_SETTINGS_VERSION = 3;

export const UI_SETTINGS_EVENT = "cctv-ui-settings-changed";

export const defaultUiSettings: UiSettings = {
  version: UI_SETTINGS_VERSION,
  primaryNav: ["/live", "/recordings", "/reviews", "/reports"],
  liveDensity: "comfortable",
  themeMode: "system",
  closeToTrayHintDismissed: false,
};

function normalizePrimaryNav(value: unknown): string[] {
  if (!Array.isArray(value)) return defaultUiSettings.primaryNav;
  const items = value.filter((item: unknown): item is string => typeof item === "string").slice(0, 5);
  return items.length ? items : defaultUiSettings.primaryNav;
}

export function loadUiSettings(): UiSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultUiSettings;

    const parsed = JSON.parse(raw);
    const merged = { ...defaultUiSettings, ...parsed };
    const themeMode: ThemeMode =
      merged.themeMode === "dark" || merged.themeMode === "light" || merged.themeMode === "system"
        ? merged.themeMode
        : defaultUiSettings.themeMode;

    return {
      ...merged,
      version: UI_SETTINGS_VERSION,
      primaryNav: normalizePrimaryNav(merged.primaryNav),
      themeMode,
      liveDensity:
        merged.liveDensity === "compact" || merged.liveDensity === "comfortable" || merged.liveDensity === "focus"
          ? merged.liveDensity
          : defaultUiSettings.liveDensity,
      closeToTrayHintDismissed: Boolean(merged.closeToTrayHintDismissed),
    };
  } catch {
    return defaultUiSettings;
  }
}

export function saveUiSettings(next: UiSettings): void {
  const normalized: UiSettings = {
    ...defaultUiSettings,
    ...next,
    version: UI_SETTINGS_VERSION,
    primaryNav: normalizePrimaryNav(next.primaryNav),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  window.dispatchEvent(new CustomEvent(UI_SETTINGS_EVENT));
}
