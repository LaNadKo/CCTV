export type LiveDensity = "compact" | "comfortable" | "focus";

export type UiSettings = {
  version: number;
  primaryNav: string[];
  liveDensity: LiveDensity;
  closeToTrayHintDismissed: boolean;
};

const STORAGE_KEY = "cctv_ui_settings";
const UI_SETTINGS_VERSION = 2;

export const defaultUiSettings: UiSettings = {
  version: UI_SETTINGS_VERSION,
  primaryNav: ["/live", "/reviews", "/reports", "/persons"],
  liveDensity: "compact",
  closeToTrayHintDismissed: false,
};

export function loadUiSettings(): UiSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultUiSettings;
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.version !== UI_SETTINGS_VERSION) {
      return {
        ...defaultUiSettings,
        liveDensity: parsed?.liveDensity ?? defaultUiSettings.liveDensity,
        closeToTrayHintDismissed:
          parsed?.closeToTrayHintDismissed ?? defaultUiSettings.closeToTrayHintDismissed,
      };
    }
    const merged = { ...defaultUiSettings, ...parsed };
    const primaryNav = Array.isArray(merged.primaryNav)
      ? merged.primaryNav.filter((item: unknown): item is string => typeof item === "string").slice(0, 4)
      : defaultUiSettings.primaryNav;
    return {
      ...merged,
      version: UI_SETTINGS_VERSION,
      primaryNav: primaryNav.length ? primaryNav : defaultUiSettings.primaryNav,
    };
  } catch {
    return defaultUiSettings;
  }
}

export function saveUiSettings(next: UiSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...next, version: UI_SETTINGS_VERSION }));
}
