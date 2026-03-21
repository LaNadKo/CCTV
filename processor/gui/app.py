"""CustomTkinter desktop GUI for CCTV Processor."""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import platform
import secrets
import socket
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk

from processor.monitor import Metrics, SystemMonitor, get_system_info
from processor.runtime import (
    base_dir as runtime_base_dir,
    connect_with_code,
    export_env,
    load_config,
    normalize_config,
    save_config,
)

LOGO_TEXT = "CCTV Processor"
VERSION = "1.0.0"
_PROCESSING_BASE_FPS = 24.0
_MAX_FRAME_INTERVAL_SECONDS = 5.0
_FREQUENCY_PRESETS: list[tuple[str, int]] = [
    ("Покадровая", 1),
    ("/2", 2),
    ("/4", 4),
    ("/8", 8),
    ("/16", 16),
    ("/32", 32),
    ("/64", 64),
    ("1 кадр / 5 сек", 120),
]
_LABEL_TO_DIVISOR = {label: divisor for label, divisor in _FREQUENCY_PRESETS}
_DIVISOR_TO_LABEL = {divisor: label for label, divisor in _FREQUENCY_PRESETS}
_QUICK_PERFORMANCE_PRESETS: list[tuple[str, int, int, str]] = [
    ("Экономия", 32, 8, "Редкое сканирование и облегчённый оверлей для слабых систем и фона."),
    ("Сбалансированный", 8, 1, "Основной рабочий режим: умеренная нагрузка и плавный live-оверлей."),
    ("Максимум", 1, 1, "Покадровая аналитика и покадровый оверлей для приоритета качества."),
]
_DEFAULT_THEME_PRIMARY = "#49C8E8"
_DEFAULT_THEME_SECONDARY = "#4C6FFF"
_THEME_PRESETS: list[tuple[str, str, str]] = [
    ("Processor", _DEFAULT_THEME_PRIMARY, _DEFAULT_THEME_SECONDARY),
    ("Console", "#5EF0FF", "#6F7BFF"),
    ("Signal", "#22C55E", "#14B8A6"),
    ("Ember", "#F97316", "#EF4444"),
]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _base_dir() -> Path:
    return runtime_base_dir()


def _asset_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates = [
            base / "processor" / "assets" / name,
            base / "assets" / name,
            Path(sys.executable).parent / name,
        ]
    else:
        candidates = [Path(__file__).resolve().parent.parent / "assets" / name]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _sanitize_divisor(value: object, fallback: int) -> int:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        raw = fallback
    if raw <= 0:
        raw = fallback
    for _, candidate in _FREQUENCY_PRESETS:
        if raw <= candidate:
            return candidate
    return _FREQUENCY_PRESETS[-1][1]


def _divisor_interval_seconds(divisor: int) -> float:
    return min(_MAX_FRAME_INTERVAL_SECONDS, divisor / _PROCESSING_BASE_FPS)


def _divisor_label(divisor: int) -> str:
    divisor = _sanitize_divisor(divisor, 1)
    return _DIVISOR_TO_LABEL.get(divisor, f"/{divisor}")


def _frequency_description(divisor: int) -> str:
    divisor = _sanitize_divisor(divisor, 1)
    interval = _divisor_interval_seconds(divisor)
    if divisor == 1:
        return "Обновление на каждом кадре. Максимальная плавность, максимальная нагрузка."
    if interval >= 4.9:
        return "Ограничено до 1 кадра за 5 секунд. Режим для экономии ресурсов."
    fps = 1.0 / interval if interval > 0 else _PROCESSING_BASE_FPS
    return f"Примерно 1 кадр каждые {interval:.2f} сек, около {fps:.1f} кадр/с."


def _normalize_hex_color(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    compact = value.strip().replace("#", "")
    if len(compact) == 3 and all(ch in "0123456789abcdefABCDEF" for ch in compact):
        compact = "".join(ch * 2 for ch in compact)
    if len(compact) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in compact):
        return fallback
    return f"#{compact.upper()}"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    color = _normalize_hex_color(value, "#000000")
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _mix_hex(base: str, tint: str, tint_ratio: float) -> str:
    ratio = max(0.0, min(1.0, tint_ratio))
    base_r, base_g, base_b = _hex_to_rgb(base)
    tint_r, tint_g, tint_b = _hex_to_rgb(tint)
    return "#{:02X}{:02X}{:02X}".format(
        round(base_r * (1.0 - ratio) + tint_r * ratio),
        round(base_g * (1.0 - ratio) + tint_g * ratio),
        round(base_b * (1.0 - ratio) + tint_b * ratio),
    )


def _darken_hex(value: str, amount: float) -> str:
    return _mix_hex(value, "#000000", amount)


def _contrast_text(value: str) -> str:
    red, green, blue = _hex_to_rgb(value)
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
    return "#04131A" if luminance >= 0.62 else "#F4F7FB"


def _build_theme_palette(primary: str, secondary: str) -> dict[str, str]:
    primary = _normalize_hex_color(primary, _DEFAULT_THEME_PRIMARY)
    secondary = _normalize_hex_color(secondary, _DEFAULT_THEME_SECONDARY)
    bg = "#08111E"
    return {
        "bg": bg,
        "panel": _mix_hex(bg, secondary, 0.14),
        "card": _mix_hex(bg, secondary, 0.2),
        "card_alt": _mix_hex(bg, secondary, 0.12),
        "border": _mix_hex(bg, secondary, 0.3),
        "text": "#F4F7FB",
        "muted": "#8CA0BC",
        "accent": primary,
        "accent_hover": _darken_hex(primary, 0.16),
        "accent_soft": _mix_hex(bg, primary, 0.24),
        "success": "#33C28E",
        "success_hover": "#26A576",
        "warning": "#E6B85C",
        "danger": "#E56D74",
        "danger_hover": "#C7565D",
    }


_THEME = _build_theme_palette(_DEFAULT_THEME_PRIMARY, _DEFAULT_THEME_SECONDARY)


def _match_quick_preset(scan_divisor: int, overlay_divisor: int) -> str | None:
    scan_divisor = _sanitize_divisor(scan_divisor, 8)
    overlay_divisor = _sanitize_divisor(overlay_divisor, 1)
    for label, preset_scan, preset_overlay, _description in _QUICK_PERFORMANCE_PRESETS:
        if preset_scan == scan_divisor and preset_overlay == overlay_divisor:
            return label
    return None


def _open_path(target: Path) -> None:
    path = Path(target)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if sys.platform.startswith("win"):
        os.startfile(str(path))
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path)])


def _safe_text(value: object, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


class ProcessorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.config_data = normalize_config(load_config())
        self.config_data["theme_primary_color"] = _normalize_hex_color(
            self.config_data.get("theme_primary_color"),
            _DEFAULT_THEME_PRIMARY,
        )
        self.config_data["theme_secondary_color"] = _normalize_hex_color(
            self.config_data.get("theme_secondary_color"),
            _DEFAULT_THEME_SECONDARY,
        )
        self._apply_theme_palette()

        self.title(LOGO_TEXT)
        self.geometry("1320x820")
        self.minsize(1100, 720)
        self.configure(fg_color=_THEME["bg"])
        self._apply_window_icon()

        if not self.config_data.get("processor_name"):
            self.config_data["processor_name"] = socket.gethostname()
        if not self.config_data.get("media_token"):
            self.config_data["media_token"] = secrets.token_urlsafe(24)
            save_config(self.config_data)

        self.system_info = get_system_info()
        self.monitor = SystemMonitor()
        self._svc = None
        self._svc_loop = None
        self._svc_thread = None
        self._running = False
        self._metrics: Metrics | None = None
        self._gui_log_handler: _GuiLogHandler | None = None
        self._current_page = "connect"

        self._pages: dict[str, ctk.CTkBaseClass] = {}
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._metric_cards: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel, ctk.CTkProgressBar | None]] = {}
        self._summary_labels: dict[str, ctk.CTkLabel] = {}
        self._connect_summary_labels: dict[str, ctk.CTkLabel] = {}
        self._settings_entries: dict[str, ctk.CTkEntry] = {}
        self.info_labels: dict[str, ctk.CTkLabel] = {}

        self.face_scan_divisor_var = ctk.StringVar(value=_divisor_label(self.config_data.get("face_scan_divisor", 8)))
        self.overlay_frame_divisor_var = ctk.StringVar(
            value=_divisor_label(self.config_data.get("overlay_frame_divisor", 1))
        )
        self.quick_preset_hint: ctk.CTkLabel | None = None
        self.theme_primary_preview: ctk.CTkFrame | None = None
        self.theme_secondary_preview: ctk.CTkFrame | None = None
        self.theme_preview_card: ctk.CTkFrame | None = None
        self.theme_preview_badge: ctk.CTkLabel | None = None
        self.theme_preview_title: ctk.CTkLabel | None = None
        self.theme_preview_text: ctk.CTkLabel | None = None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._build_sidebar()
        self._build_content()

        if self.config_data.get("api_key") and self.config_data.get("backend_url"):
            self._show_page("dashboard")
        else:
            self._show_page("connect")

        self._sync_ui_from_config()
        self._update_metrics()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_window_icon(self) -> None:
        icon_path = _asset_path("icon.ico")
        try:
            if icon_path.exists():
                self.iconbitmap(str(icon_path))
        except Exception:
            pass

    def _apply_theme_palette(self) -> None:
        primary = _normalize_hex_color(self.config_data.get("theme_primary_color"), _DEFAULT_THEME_PRIMARY)
        secondary = _normalize_hex_color(self.config_data.get("theme_secondary_color"), _DEFAULT_THEME_SECONDARY)
        self.config_data["theme_primary_color"] = primary
        self.config_data["theme_secondary_color"] = secondary
        _THEME.clear()
        _THEME.update(_build_theme_palette(primary, secondary))
        self.configure(fg_color=_THEME["bg"])

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=248, corner_radius=0, fg_color=_THEME["panel"], border_width=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(
            self.sidebar,
            fg_color=_THEME["card"],
            corner_radius=22,
            border_width=1,
            border_color=_THEME["border"],
        )
        brand.pack(fill="x", padx=18, pady=(18, 16))
        ctk.CTkLabel(brand, text="PROCESSOR", text_color=_THEME["accent"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(brand, text=LOGO_TEXT, text_color=_THEME["text"], font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", padx=18)
        ctk.CTkLabel(
            brand,
            text="Локальный интерфейс управления обработчиком и его ресурсами.",
            text_color=_THEME["muted"],
            justify="left",
            wraplength=190,
        ).pack(anchor="w", padx=18, pady=(6, 16))

        for name, label in [
            ("connect", "Подключение"),
            ("dashboard", "Монитор"),
            ("settings", "Настройки"),
            ("help", "Справка"),
            ("logs", "Журнал"),
        ]:
            button = ctk.CTkButton(
                self.sidebar,
                text=label,
                command=lambda target=name: self._show_page(target),
                height=44,
                corner_radius=14,
                anchor="w",
                fg_color="transparent",
                hover_color=_THEME["card"],
                border_width=0,
                text_color=_THEME["text"],
                font=ctk.CTkFont(size=15, weight="bold"),
            )
            button.pack(fill="x", padx=18, pady=4)
            self._nav_buttons[name] = button

        status_card = ctk.CTkFrame(
            self.sidebar,
            fg_color=_THEME["card_alt"],
            corner_radius=20,
            border_width=1,
            border_color=_THEME["border"],
        )
        status_card.pack(side="bottom", fill="x", padx=18, pady=18)
        ctk.CTkLabel(status_card, text="Состояние сервиса", text_color=_THEME["muted"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=16, pady=(14, 6))
        row = ctk.CTkFrame(status_card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))
        self.status_dot = ctk.CTkLabel(row, text="●", text_color=_THEME["muted"], font=ctk.CTkFont(size=16, weight="bold"))
        self.status_dot.pack(side="left")
        self.status_text = ctk.CTkLabel(row, text="Отключен", text_color=_THEME["muted"], font=ctk.CTkFont(size=14, weight="bold"))
        self.status_text.pack(side="left", padx=(8, 0))

    def _create_card(self, parent, title: str, subtitle: str | None = None, *, fg_color: str | None = None):
        card = ctk.CTkFrame(parent, fg_color=fg_color or _THEME["card"], corner_radius=22, border_width=1, border_color=_THEME["border"])
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(20, 0))
        ctk.CTkLabel(header, text=title, text_color=_THEME["text"], anchor="w", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(header, text=subtitle, text_color=_THEME["muted"], justify="left", wraplength=820).pack(anchor="w", pady=(6, 0))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(18, 22))
        return card, body

    def _create_action_button(self, parent, text: str, command, *, tone: str = "accent", width: int = 150, height: int = 40) -> ctk.CTkButton:
        palette = {
            "accent": (_THEME["accent"], _THEME["accent_hover"], "#04131A"),
            "success": (_THEME["success"], _THEME["success_hover"], "#04130D"),
            "danger": (_THEME["danger"], _THEME["danger_hover"], "#19080A"),
            "ghost": (_THEME["card_alt"], _THEME["card"], _THEME["text"]),
        }
        fg_color, hover_color, text_color = palette[tone]
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=height, corner_radius=14, fg_color=fg_color, hover_color=hover_color, text_color=text_color, font=ctk.CTkFont(size=14, weight="bold"))

    def _show_page(self, name: str) -> None:
        self._current_page = name
        for page in self._pages.values():
            page.grid_remove()
        self._pages[name].grid(row=0, column=0, sticky="nsew")
        for button_name, button in self._nav_buttons.items():
            active = button_name == name
            button.configure(
                fg_color=_THEME["accent_soft"] if active else "transparent",
                border_width=1 if active else 0,
                border_color=_THEME["border"],
                text_color=_THEME["accent"] if active else _THEME["text"],
            )

    def _create_settings_entry(self, parent, key: str, label: str, value: str) -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label, text_color=_THEME["muted"], anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(0, 6))
        entry = ctk.CTkEntry(parent, height=42, corner_radius=14, fg_color=_THEME["card_alt"], border_color=_THEME["border"], text_color=_THEME["text"])
        entry.pack(fill="x", pady=(0, 14))
        entry.insert(0, value)
        self._settings_entries[key] = entry
        return entry

    def _create_path_entry(self, parent, key: str, label: str, value: str) -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label, text_color=_THEME["muted"], anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(0, 6))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 14))
        entry = ctk.CTkEntry(row, height=42, corner_radius=14, fg_color=_THEME["panel"], border_color=_THEME["border"], text_color=_THEME["text"])
        entry.pack(side="left", fill="x", expand=True)
        entry.insert(0, value)
        self._settings_entries[key] = entry
        self._create_action_button(row, "Выбрать", lambda target=key, item=entry: self._browse_directory(target, item), tone="ghost", width=110, height=42).pack(side="left", padx=(10, 0))
        self._create_action_button(row, "Открыть", lambda item=entry: self._open_runtime_path(Path(item.get().strip())), tone="ghost", width=100, height=42).pack(side="left", padx=(10, 0))
        return entry

    def _create_color_entry(self, parent, label: str, value: str, fallback: str) -> tuple[ctk.CTkEntry, ctk.CTkFrame]:
        ctk.CTkLabel(parent, text=label, text_color=_THEME["muted"], anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(0, 6))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 14))
        swatch = ctk.CTkFrame(
            row,
            width=42,
            height=42,
            corner_radius=14,
            fg_color=_normalize_hex_color(value, fallback),
            border_width=1,
            border_color=_THEME["border"],
        )
        swatch.pack(side="left")
        swatch.pack_propagate(False)
        entry = ctk.CTkEntry(row, height=42, corner_radius=14, fg_color=_THEME["panel"], border_color=_THEME["border"], text_color=_THEME["text"])
        entry.pack(side="left", fill="x", expand=True, padx=(10, 0))
        entry.insert(0, _normalize_hex_color(value, fallback))
        entry.bind("<KeyRelease>", lambda _event, item=entry, preview=swatch, default=fallback: self._refresh_theme_preview(item, preview, default))
        self._create_action_button(
            row,
            "Выбрать",
            lambda item=entry, preview=swatch, default=fallback: self._pick_theme_color(item, preview, default),
            tone="ghost",
            width=110,
            height=42,
        ).pack(side="left", padx=(10, 0))
        return entry, swatch

    def _set_theme_entry(self, entry: ctk.CTkEntry, swatch: ctk.CTkFrame, value: str, fallback: str) -> None:
        normalized = _normalize_hex_color(value, fallback)
        entry.delete(0, "end")
        entry.insert(0, normalized)
        self._refresh_theme_preview(entry, swatch, fallback)

    def _refresh_theme_preview(self, entry: ctk.CTkEntry, swatch: ctk.CTkFrame, fallback: str) -> None:
        color = _normalize_hex_color(entry.get().strip(), fallback)
        swatch.configure(fg_color=color, border_color=_THEME["border"])
        if not self.theme_preview_card or not self.theme_preview_badge or not self.theme_preview_title or not self.theme_preview_text:
            return
        primary = _normalize_hex_color(self.theme_primary_entry.get().strip(), _DEFAULT_THEME_PRIMARY)
        secondary = _normalize_hex_color(self.theme_secondary_entry.get().strip(), _DEFAULT_THEME_SECONDARY)
        preview_bg = _mix_hex(primary, secondary, 0.34)
        preview_fg = _contrast_text(preview_bg)
        badge_fg = _contrast_text(secondary)
        self.theme_preview_card.configure(fg_color=preview_bg, border_color=secondary)
        self.theme_preview_badge.configure(fg_color=secondary, text_color=badge_fg)
        self.theme_preview_title.configure(text_color=preview_fg)
        self.theme_preview_text.configure(text_color=preview_fg)

    def _pick_theme_color(self, entry: ctk.CTkEntry, swatch: ctk.CTkFrame, fallback: str) -> None:
        initial = _normalize_hex_color(entry.get().strip(), fallback)
        _rgb, color = colorchooser.askcolor(color=initial, title="Выбор цвета интерфейса")
        if not color:
            return
        self._set_theme_entry(entry, swatch, color, fallback)

    def _apply_theme_preset(self, primary: str, secondary: str) -> None:
        self._set_theme_entry(self.theme_primary_entry, self.theme_primary_preview, primary, _DEFAULT_THEME_PRIMARY)
        self._set_theme_entry(self.theme_secondary_entry, self.theme_secondary_preview, secondary, _DEFAULT_THEME_SECONDARY)
        self.settings_status.configure(
            text="Палитра обновлена в форме. Сохраните настройки, чтобы сразу применить её к Processor GUI.",
            text_color=_THEME["muted"],
        )

    def _reset_theme_colors(self) -> None:
        self._apply_theme_preset(_DEFAULT_THEME_PRIMARY, _DEFAULT_THEME_SECONDARY)

    def _add_help_section(self, parent, title: str, lines: list[str]) -> None:
        card, body = self._create_card(parent, title)
        card.pack(fill="x", padx=18, pady=18)
        for line in lines:
            ctk.CTkLabel(body, text=f"• {line}", text_color=_THEME["text"], justify="left", anchor="w", wraplength=900).pack(fill="x", pady=4)

    def _build_content(self) -> None:
        super_build = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.content = super_build
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self._build_connect_page()
        self._build_dashboard_page()
        self._build_settings_page()
        self._build_help_page()
        self._build_logs_page()

    def _build_connect_page(self) -> None:
        page = ctk.CTkScrollableFrame(self.content, fg_color="transparent", corner_radius=0)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._pages["connect"] = page

        hero = ctk.CTkFrame(page, fg_color=_THEME["card"], corner_radius=26, border_width=1, border_color=_THEME["border"])
        hero.pack(fill="x", padx=24, pady=(24, 18))
        ctk.CTkLabel(hero, text="PROCESSOR LINK", text_color=_THEME["accent"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=26, pady=(24, 4))
        ctk.CTkLabel(hero, text="Подключение к серверу", text_color=_THEME["text"], font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w", padx=26)
        ctk.CTkLabel(
            hero,
            text="Введите адрес backend и код подключения. После привязки Processor сохранит локальный API-ключ и сможет запускаться без повторного ввода кода.",
            text_color=_THEME["muted"],
            wraplength=980,
            justify="left",
        ).pack(anchor="w", padx=26, pady=(10, 24))

        grid = ctk.CTkFrame(page, fg_color="transparent")
        grid.pack(fill="x", padx=24, pady=(0, 24))
        grid.grid_columnconfigure(0, weight=3)
        grid.grid_columnconfigure(1, weight=2)

        form_card, form_body = self._create_card(grid, "Данные подключения", "Backend уже рабочий, поэтому тут только привязка Processor.")
        form_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ctk.CTkLabel(form_body, text="Адрес сервера", text_color=_THEME["muted"], anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(0, 6))
        self.conn_url = ctk.CTkEntry(form_body, height=42, corner_radius=14, fg_color=_THEME["card_alt"], border_color=_THEME["border"], text_color=_THEME["text"], placeholder_text="http://192.168.50.62:8000", placeholder_text_color=_THEME["muted"])
        self.conn_url.pack(fill="x", pady=(0, 14))
        self.conn_url.insert(0, str(self.config_data.get("backend_url") or ""))
        ctk.CTkLabel(form_body, text="Код подключения", text_color=_THEME["muted"], anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(0, 6))
        self.conn_code = ctk.CTkEntry(form_body, height=42, corner_radius=14, fg_color=_THEME["card_alt"], border_color=_THEME["border"], text_color=_THEME["text"], placeholder_text="ABCD1234", placeholder_text_color=_THEME["muted"])
        self.conn_code.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(form_body, text="Имя Processor", text_color=_THEME["muted"], anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(0, 6))
        self.conn_name = ctk.CTkEntry(form_body, height=42, corner_radius=14, fg_color=_THEME["card_alt"], border_color=_THEME["border"], text_color=_THEME["text"])
        self.conn_name.pack(fill="x", pady=(0, 14))
        self.conn_name.insert(0, str(self.config_data.get("processor_name") or socket.gethostname()))
        self.conn_status = ctk.CTkLabel(form_body, text="", text_color=_THEME["muted"], justify="left", wraplength=540)
        self.conn_status.pack(anchor="w", pady=(2, 12))
        buttons = ctk.CTkFrame(form_body, fg_color="transparent")
        buttons.pack(fill="x", pady=(4, 0))
        self.conn_test_btn = self._create_action_button(buttons, "Проверить", self._test_connection, tone="ghost")
        self.conn_test_btn.pack(side="left")
        self.conn_btn = self._create_action_button(buttons, "Подключить", self._connect, tone="success", width=160)
        self.conn_btn.pack(side="left", padx=(10, 0))

        summary_card, summary_body = self._create_card(grid, "Локальная конфигурация", "Сводка по текущему ПК и уже сохранённой привязке.")
        summary_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        for key, label in [("server", "Текущий backend"), ("processor_id", "Processor ID"), ("name", "Имя"), ("advertised_ip", "Публикуемый IP"), ("os", "ОС"), ("gpu", "GPU / инференс")]:
            row = ctk.CTkFrame(summary_body, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=label, text_color=_THEME["muted"], width=148, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            value_label = ctk.CTkLabel(row, text="—", text_color=_THEME["text"], anchor="w", justify="left", wraplength=260)
            value_label.pack(side="left", fill="x", expand=True)
            self._connect_summary_labels[key] = value_label
        ctk.CTkLabel(summary_body, text="Пути записей и снимков не сохраняются в backend и остаются локальной настройкой Processor.", text_color=_THEME["muted"], wraplength=320, justify="left").pack(anchor="w", pady=(18, 0))

    def _build_dashboard_page(self) -> None:
        page = ctk.CTkScrollableFrame(self.content, fg_color="transparent", corner_radius=0)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._pages["dashboard"] = page

        hero = ctk.CTkFrame(page, fg_color=_THEME["card"], corner_radius=26, border_width=1, border_color=_THEME["border"])
        hero.pack(fill="x", padx=24, pady=(24, 18))
        top = ctk.CTkFrame(hero, fg_color="transparent")
        top.pack(fill="x", padx=26, pady=(24, 0))
        left = ctk.CTkFrame(top, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text="PROCESSOR CONTROL", text_color=_THEME["accent"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 4))
        self.hero_title = ctk.CTkLabel(left, text="Монитор Processor", text_color=_THEME["text"], font=ctk.CTkFont(size=30, weight="bold"))
        self.hero_title.pack(anchor="w")
        self.hero_subtitle = ctk.CTkLabel(left, text="Управление запуском, мониторингом нагрузки и быстрым доступом к локальным данным.", text_color=_THEME["muted"], justify="left", wraplength=760)
        self.hero_subtitle.pack(anchor="w", pady=(10, 0))
        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.pack(side="right", anchor="ne")
        self.start_btn = self._create_action_button(actions, "Запустить обработку", self._start_processing, tone="success", width=190, height=44)
        self.start_btn.pack(side="left")
        self.stop_btn = self._create_action_button(actions, "Остановить", self._stop_processing, tone="danger", width=140, height=44)
        self.stop_btn.pack(side="left", padx=(10, 0))
        self.stop_btn.configure(state="disabled")
        summary_row = ctk.CTkFrame(hero, fg_color="transparent")
        summary_row.pack(fill="x", padx=26, pady=(18, 24))
        for key, title in [("status", "Сервис"), ("server", "Backend"), ("scan", "Сканирование"), ("overlay", "Оверлей")]:
            pill = ctk.CTkFrame(summary_row, fg_color=_THEME["accent_soft"] if key in {"scan", "overlay"} else _THEME["card_alt"], corner_radius=16, border_width=1, border_color=_THEME["border"])
            pill.pack(side="left", padx=(0, 10))
            ctk.CTkLabel(pill, text=title, text_color=_THEME["muted"], font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=14, pady=(10, 2))
            label = ctk.CTkLabel(pill, text="—", text_color=_THEME["text"], font=ctk.CTkFont(size=15, weight="bold"))
            label.pack(anchor="w", padx=14, pady=(0, 10))
            self._summary_labels[key] = label

        metrics_grid = ctk.CTkFrame(page, fg_color="transparent")
        metrics_grid.pack(fill="x", padx=24, pady=(0, 12))
        metrics_grid.grid_columnconfigure((0, 1, 2, 3), weight=1)
        metric_defs = [("cpu", "CPU", "0%", True), ("ram", "RAM", "0 / 0 GB", True), ("gpu", "GPU", "Нет данных", True), ("net", "Сеть", "↑0 ↓0 Мбит/с", False), ("disk", "Диск", "0 / 0 GB", True), ("cameras", "Камеры", "0", False), ("uptime", "Аптайм", "0:00:00", False), ("gpu_temp", "Температура GPU", "—", False)]
        for index, (key, title, default, has_bar) in enumerate(metric_defs):
            row = index // 4
            column = index % 4
            card = ctk.CTkFrame(metrics_grid, fg_color=_THEME["card_alt"] if row == 1 else _THEME["card"], corner_radius=20, border_width=1, border_color=_THEME["border"])
            card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
            title_label = ctk.CTkLabel(card, text=title, text_color=_THEME["muted"], font=ctk.CTkFont(size=12, weight="bold"))
            title_label.pack(anchor="w", padx=18, pady=(16, 4))
            value_label = ctk.CTkLabel(card, text=default, text_color=_THEME["text"], font=ctk.CTkFont(size=20, weight="bold"))
            value_label.pack(anchor="w", padx=18)
            progress = None
            if has_bar:
                progress = ctk.CTkProgressBar(card, height=10, corner_radius=8, fg_color=_THEME["panel"], progress_color=_THEME["accent"])
                progress.set(0)
                progress.pack(fill="x", padx=18, pady=(14, 16))
            else:
                ctk.CTkLabel(card, text="", height=22).pack(pady=(0, 10))
            self._metric_cards[key] = (title_label, value_label, progress)

        lower = ctk.CTkFrame(page, fg_color="transparent")
        lower.pack(fill="x", padx=24, pady=(0, 24))
        lower.grid_columnconfigure(0, weight=2)
        lower.grid_columnconfigure(1, weight=1)
        info_card, info_body = self._create_card(lower, "Связка и система", "Ключевые данные по Processor и его связке с сервером.")
        info_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        for key, label in [("server", "Backend"), ("proc_id", "Processor ID"), ("name", "Имя"), ("os", "ОС"), ("arch", "Архитектура"), ("gpu", "GPU / инференс")]:
            row = ctk.CTkFrame(info_body, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=label, text_color=_THEME["muted"], width=136, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            value = ctk.CTkLabel(row, text="—", text_color=_THEME["text"], justify="left", wraplength=500, anchor="w")
            value.pack(side="left", fill="x", expand=True)
            self.info_labels[key] = value
        quick_card, quick_body = self._create_card(lower, "Быстрые действия", "Открытие локальных папок и файлов без ручного поиска.")
        quick_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._create_action_button(quick_body, "Открыть записи", lambda: self._open_runtime_path(Path(str(self.config_data.get("recordings_dir") or ""))), tone="ghost", width=220).pack(fill="x", pady=(0, 10))
        self._create_action_button(quick_body, "Открыть снимки", lambda: self._open_runtime_path(Path(str(self.config_data.get("snapshots_dir") or ""))), tone="ghost", width=220).pack(fill="x", pady=(0, 10))
        self._create_action_button(quick_body, "Открыть лог", lambda: self._open_runtime_path(_base_dir() / "processor.log"), tone="ghost", width=220).pack(fill="x", pady=(0, 10))
        self._create_action_button(quick_body, "Открыть конфиг", lambda: self._open_runtime_path(_base_dir() / "processor_config.json"), tone="ghost", width=220).pack(fill="x")
        ctk.CTkLabel(quick_body, text="Пути записей и снимков применяются только локально на Processor. На backend/БД они сейчас не отправляются.", text_color=_THEME["muted"], wraplength=320, justify="left").pack(anchor="w", pady=(16, 0))

    def _build_settings_page(self) -> None:
        page = ctk.CTkScrollableFrame(self.content, fg_color="transparent", corner_radius=0)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._pages["settings"] = page

        header = ctk.CTkFrame(page, fg_color=_THEME["card"], corner_radius=26, border_width=1, border_color=_THEME["border"])
        header.pack(fill="x", padx=24, pady=(24, 18))
        ctk.CTkLabel(header, text="PROCESSOR SETUP", text_color=_THEME["accent"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=26, pady=(24, 4))
        ctk.CTkLabel(header, text="Настройки обработки", text_color=_THEME["text"], font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w", padx=26)
        ctk.CTkLabel(
            header,
            text="Здесь собраны параметры нагрузки, длительности записи и локальных каталогов. Частоты сканирования и оверлея управляются отдельными профилями.",
            text_color=_THEME["muted"],
            wraplength=960,
            justify="left",
        ).pack(anchor="w", padx=26, pady=(10, 24))

        grid = ctk.CTkFrame(page, fg_color="transparent")
        grid.pack(fill="x", padx=24, pady=(0, 12))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        perf_card, perf_body = self._create_card(grid, "Производительность и обработка", "Чем меньше делитель, тем выше плавность и нагрузка на систему.")
        perf_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.max_workers_entry = self._create_settings_entry(perf_body, "max_workers", "Макс. камер (workers)", str(self.config_data.get("max_workers", 4)))
        self.motion_threshold_entry = self._create_settings_entry(perf_body, "motion_threshold", "Порог движения", str(self.config_data.get("motion_threshold", 25.0)))
        self.recording_segment_entry = self._create_settings_entry(perf_body, "recording_segment_seconds", "Длина сегмента записи (сек)", str(self.config_data.get("recording_segment_seconds", 300)))

        ctk.CTkLabel(perf_body, text="Быстрые пресеты", text_color=_THEME["muted"], anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(2, 8))
        presets_row = ctk.CTkFrame(perf_body, fg_color="transparent")
        presets_row.pack(fill="x", pady=(0, 8))
        for index, (label, scan_divisor, overlay_divisor, description) in enumerate(_QUICK_PERFORMANCE_PRESETS):
            card = ctk.CTkFrame(
                presets_row,
                fg_color=_THEME["card_alt"],
                corner_radius=18,
                border_width=1,
                border_color=_THEME["border"],
            )
            card.pack(side="left", fill="both", expand=True, padx=(0, 8 if index < len(_QUICK_PERFORMANCE_PRESETS) - 1 else 0))
            ctk.CTkLabel(card, text=label, text_color=_THEME["text"], anchor="w", font=ctk.CTkFont(size=15, weight="bold")).pack(fill="x", padx=14, pady=(14, 4))
            ctk.CTkLabel(card, text=f"Сканирование {_divisor_label(scan_divisor)} • оверлей {_divisor_label(overlay_divisor)}", text_color=_THEME["accent"], anchor="w", wraplength=150, justify="left", font=ctk.CTkFont(size=12, weight="bold")).pack(fill="x", padx=14)
            ctk.CTkLabel(card, text=description, text_color=_THEME["muted"], anchor="w", wraplength=170, justify="left").pack(fill="x", padx=14, pady=(8, 10))
            self._create_action_button(
                card,
                "Выбрать",
                lambda current_label=label, current_scan=scan_divisor, current_overlay=overlay_divisor: self._apply_quick_preset(
                    current_label,
                    current_scan,
                    current_overlay,
                ),
                tone="ghost",
                width=150,
                height=38,
            ).pack(anchor="w", padx=14, pady=(0, 14))
        self.quick_preset_hint = ctk.CTkLabel(perf_body, text="", text_color=_THEME["muted"], justify="left", wraplength=500)
        self.quick_preset_hint.pack(anchor="w", pady=(0, 14))

        ctk.CTkLabel(perf_body, text="Частота сканирования лиц", text_color=_THEME["muted"], anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(2, 6))
        self.face_scan_menu = ctk.CTkOptionMenu(
            perf_body,
            values=[label for label, _ in _FREQUENCY_PRESETS],
            variable=self.face_scan_divisor_var,
            command=lambda _value: self._update_frequency_labels(),
            height=42,
            corner_radius=14,
            fg_color=_THEME["accent_soft"],
            button_color=_THEME["accent"],
            button_hover_color=_THEME["accent_hover"],
            text_color=_THEME["text"],
            dropdown_fg_color=_THEME["card"],
            dropdown_hover_color=_THEME["card_alt"],
            dropdown_text_color=_THEME["text"],
        )
        self.face_scan_menu.pack(fill="x", pady=(0, 6))
        self.face_scan_info = ctk.CTkLabel(perf_body, text="", text_color=_THEME["muted"], justify="left", wraplength=500)
        self.face_scan_info.pack(anchor="w", pady=(0, 14))

        ctk.CTkLabel(perf_body, text="Частота отрисовки оверлея", text_color=_THEME["muted"], anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(0, 6))
        self.overlay_menu = ctk.CTkOptionMenu(
            perf_body,
            values=[label for label, _ in _FREQUENCY_PRESETS],
            variable=self.overlay_frame_divisor_var,
            command=lambda _value: self._update_frequency_labels(),
            height=42,
            corner_radius=14,
            fg_color=_THEME["accent_soft"],
            button_color=_THEME["accent"],
            button_hover_color=_THEME["accent_hover"],
            text_color=_THEME["text"],
            dropdown_fg_color=_THEME["card"],
            dropdown_hover_color=_THEME["card_alt"],
            dropdown_text_color=_THEME["text"],
        )
        self.overlay_menu.pack(fill="x", pady=(0, 6))
        self.overlay_info = ctk.CTkLabel(perf_body, text="", text_color=_THEME["muted"], justify="left", wraplength=500)
        self.overlay_info.pack(anchor="w", pady=(0, 14))
        self.frequency_summary = ctk.CTkLabel(perf_body, text="", text_color=_THEME["text"], wraplength=500, justify="left", font=ctk.CTkFont(size=14, weight="bold"))
        self.frequency_summary.pack(anchor="w")

        storage_card, storage_body = self._create_card(grid, "Локальное хранилище", "Папки записей и снимков меняют только локальный runtime текущего Processor.")
        storage_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.recordings_dir_entry = self._create_path_entry(storage_body, "recordings_dir", "Папка для записей", str(self.config_data.get("recordings_dir") or ""))
        self.snapshots_dir_entry = self._create_path_entry(storage_body, "snapshots_dir", "Папка для снимков", str(self.config_data.get("snapshots_dir") or ""))
        ctk.CTkLabel(storage_body, text="Эти пути не записываются в backend и не сохраняются в БД. Они используются только на текущем ПК, где запущен Processor.", text_color=_THEME["muted"], wraplength=500, justify="left").pack(anchor="w", pady=(8, 0))

        theme_card, theme_body = self._create_card(grid, "Тема интерфейса", "Можно менять основной и дополнительный цвет локального Processor GUI. Тема применяется сразу после сохранения.")
        theme_card.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=0, pady=(20, 0))

        presets_row = ctk.CTkFrame(theme_body, fg_color="transparent")
        presets_row.pack(fill="x", pady=(0, 14))
        for index, (label, primary, secondary) in enumerate(_THEME_PRESETS):
            self._create_action_button(
                presets_row,
                label,
                lambda preset_primary=primary, preset_secondary=secondary: self._apply_theme_preset(preset_primary, preset_secondary),
                tone="ghost",
                width=150,
                height=40,
            ).pack(side="left", padx=(0, 10 if index < len(_THEME_PRESETS) - 1 else 0))

        colors_grid = ctk.CTkFrame(theme_body, fg_color="transparent")
        colors_grid.pack(fill="x")
        colors_grid.grid_columnconfigure(0, weight=1)
        colors_grid.grid_columnconfigure(1, weight=1)

        primary_wrap = ctk.CTkFrame(colors_grid, fg_color="transparent")
        primary_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.theme_primary_entry, self.theme_primary_preview = self._create_color_entry(
            primary_wrap,
            "Основной цвет",
            str(self.config_data.get("theme_primary_color") or _DEFAULT_THEME_PRIMARY),
            _DEFAULT_THEME_PRIMARY,
        )

        secondary_wrap = ctk.CTkFrame(colors_grid, fg_color="transparent")
        secondary_wrap.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.theme_secondary_entry, self.theme_secondary_preview = self._create_color_entry(
            secondary_wrap,
            "Дополнительный цвет",
            str(self.config_data.get("theme_secondary_color") or _DEFAULT_THEME_SECONDARY),
            _DEFAULT_THEME_SECONDARY,
        )

        preview_row = ctk.CTkFrame(theme_body, fg_color="transparent")
        preview_row.pack(fill="x", pady=(0, 14))
        self.theme_preview_card = ctk.CTkFrame(
            preview_row,
            fg_color=_mix_hex(
                str(self.config_data.get("theme_primary_color") or _DEFAULT_THEME_PRIMARY),
                str(self.config_data.get("theme_secondary_color") or _DEFAULT_THEME_SECONDARY),
                0.34,
            ),
            corner_radius=20,
            border_width=1,
            border_color=str(self.config_data.get("theme_secondary_color") or _DEFAULT_THEME_SECONDARY),
        )
        self.theme_preview_card.pack(side="left", fill="x", expand=True)
        self.theme_preview_badge = ctk.CTkLabel(
            self.theme_preview_card,
            text="Preview",
            fg_color=str(self.config_data.get("theme_secondary_color") or _DEFAULT_THEME_SECONDARY),
            corner_radius=999,
            padx=10,
            pady=4,
        )
        self.theme_preview_badge.pack(anchor="w", padx=18, pady=(18, 8))
        self.theme_preview_title = ctk.CTkLabel(
            self.theme_preview_card,
            text="Processor Palette",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self.theme_preview_title.pack(anchor="w", padx=18)
        self.theme_preview_text = ctk.CTkLabel(
            self.theme_preview_card,
            text="Кнопки, карточки и активная навигация подстроятся под выбранную палитру после сохранения.",
            wraplength=560,
            justify="left",
        )
        self.theme_preview_text.pack(anchor="w", padx=18, pady=(8, 18))
        self._refresh_theme_preview(self.theme_primary_entry, self.theme_primary_preview, _DEFAULT_THEME_PRIMARY)

        theme_actions = ctk.CTkFrame(theme_body, fg_color="transparent")
        theme_actions.pack(fill="x")
        self._create_action_button(theme_actions, "Сбросить тему", self._reset_theme_colors, tone="ghost", width=160, height=40).pack(side="left")

        footer = ctk.CTkFrame(page, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=(0, 24))
        self._create_action_button(footer, "Сохранить настройки", self._save_settings, tone="accent", width=220, height=44).pack(side="left")
        self.settings_status = ctk.CTkLabel(footer, text="", text_color=_THEME["muted"], justify="left", wraplength=720)
        self.settings_status.pack(side="left", padx=(14, 0))

    def _build_help_page(self) -> None:
        page = ctk.CTkScrollableFrame(self.content, fg_color="transparent", corner_radius=0)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._pages["help"] = page

        header = ctk.CTkFrame(page, fg_color=_THEME["card"], corner_radius=26, border_width=1, border_color=_THEME["border"])
        header.pack(fill="x", padx=24, pady=(24, 18))
        ctk.CTkLabel(header, text="PROCESSOR GUIDE", text_color=_THEME["accent"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=26, pady=(24, 4))
        ctk.CTkLabel(header, text="Справка по работе с программой", text_color=_THEME["text"], font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w", padx=26)
        ctk.CTkLabel(header, text="Справка разделена по задачам: подключение, мониторинг, частоты, локальное хранилище и журнал.", text_color=_THEME["muted"], wraplength=980, justify="left").pack(anchor="w", padx=26, pady=(10, 24))

        tabs = ctk.CTkTabview(
            page,
            corner_radius=22,
            fg_color=_THEME["card"],
            segmented_button_fg_color=_THEME["card_alt"],
            segmented_button_selected_color=_THEME["accent"],
            segmented_button_selected_hover_color=_THEME["accent_hover"],
            segmented_button_unselected_color=_THEME["card_alt"],
            segmented_button_unselected_hover_color=_THEME["panel"],
            text_color=_THEME["text"],
            border_width=1,
            border_color=_THEME["border"],
        )
        tabs.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        for name in ["Старт", "Монитор", "Частоты", "Хранилище", "Журнал"]:
            tabs.add(name)

        self._add_help_section(tabs.tab("Старт"), "Первое подключение", [
            "На вкладке «Подключение» укажите адрес backend и код подключения, который выдаётся из Console.",
            "После успешной привязки Processor получает API-ключ и сохраняет его локально в processor_config.json.",
            "Кнопка «Проверить» обращается к /health и нужна только для быстрой проверки доступности backend.",
            "Если меняете имя Processor после привязки, надёжнее переподключить его заново тем же интерфейсом.",
        ])
        self._add_help_section(tabs.tab("Монитор"), "Запуск и контроль", [
            "Вкладка «Монитор» управляет локальным запуском обработчика на этом ПК.",
            "Карточки CPU, RAM, GPU, сети, диска и камер показывают текущую локальную нагрузку.",
            "Быстрые действия открывают папки записей, снимков, конфиг и лог без ручного поиска на диске.",
            "Статус в боковой панели показывает, работает ли локальный сервис Processor прямо сейчас.",
        ])
        self._add_help_section(tabs.tab("Частоты"), "Сканирование и оверлей", [
            "Сканирование лиц и отрисовка оверлея теперь настраиваются раздельными профилями.",
            "Покадровый режим даёт максимум плавности, но сильнее нагружает CPU/GPU.",
            "Профили /2, /4, /8 и далее уменьшают частоту в геометрической прогрессии.",
            "Максимально редкий режим ограничен одним кадром за 5 секунд.",
            "После сохранения новых частот перезапустите локальную обработку, если она уже была запущена.",
        ])
        self._add_help_section(tabs.tab("Хранилище"), "Локальные папки", [
            "Пути записей и снимков задаются только для текущего Processor и текущего компьютера.",
            "Эти каталоги используются runtime-частью через локальные переменные окружения и не пишутся в backend/БД.",
            "Для быстрой проверки результата откройте нужные каталоги из блока «Быстрые действия».",
        ])
        self._add_help_section(tabs.tab("Журнал"), "Работа с логом", [
            "Журнал показывает live-вывод запуска, ошибки соединения, heartbeat, назначения камер и события обработки.",
            "Кнопка «Очистить» очищает только окно журнала в интерфейсе и не удаляет сам файл processor.log.",
            "Если нужно передать лог на анализ, откройте файл processor.log через вкладку «Монитор» или «Журнал».",
        ])

    def _build_logs_page(self) -> None:
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, weight=1)
        self._pages["logs"] = page

        header = ctk.CTkFrame(page, fg_color=_THEME["card"], corner_radius=24, border_width=1, border_color=_THEME["border"])
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 12))
        header_row = ctk.CTkFrame(header, fg_color="transparent")
        header_row.pack(fill="x", padx=24, pady=20)
        left = ctk.CTkFrame(header_row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text="SERVICE LOG", text_color=_THEME["accent"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(left, text="Журнал работы Processor", text_color=_THEME["text"], font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(left, text="Отсюда удобно смотреть ошибки запуска, heartbeat, назначения камер и запись событий.", text_color=_THEME["muted"], wraplength=780, justify="left").pack(anchor="w", pady=(8, 0))
        buttons = ctk.CTkFrame(header_row, fg_color="transparent")
        buttons.pack(side="right")
        self._create_action_button(buttons, "Открыть log", lambda: self._open_runtime_path(_base_dir() / "processor.log"), tone="ghost", width=120).pack(side="left")
        self._create_action_button(buttons, "Очистить", self._clear_logs, tone="danger", width=120).pack(side="left", padx=(10, 0))

        log_frame = ctk.CTkFrame(page, fg_color=_THEME["card_alt"], corner_radius=22, border_width=1, border_color=_THEME["border"])
        log_frame.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        self.log_box = ctk.CTkTextbox(log_frame, corner_radius=18, fg_color=_THEME["panel"], border_width=0, text_color=_THEME["text"], font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.log_box.configure(state="disabled")

    def _set_connect_status(self, text: str, color: str) -> None:
        self.conn_status.configure(text=text, text_color=color)

    def _test_connection(self) -> None:
        url = self.conn_url.get().strip().rstrip("/")
        if not url:
            self._set_connect_status("Введите адрес сервера.", _THEME["danger"])
            return
        self.conn_test_btn.configure(state="disabled")
        self._set_connect_status("Проверка backend...", _THEME["muted"])

        def worker() -> None:
            try:
                response = urllib.request.urlopen(f"{url}/health", timeout=5)
                if response.status == 200:
                    self.after(0, lambda: self._set_connect_status("Сервер доступен и отвечает на /health.", _THEME["success"]))
                else:
                    self.after(0, lambda: self._set_connect_status(f"Получен статус {response.status}.", _THEME["danger"]))
            except Exception as exc:
                self.after(0, lambda: self._set_connect_status(f"Ошибка проверки: {exc}", _THEME["danger"]))
            finally:
                self.after(0, lambda: self.conn_test_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _connect(self) -> None:
        url = self.conn_url.get().strip().rstrip("/")
        code = self.conn_code.get().strip()
        name = self.conn_name.get().strip() or socket.gethostname()
        if not url:
            self._set_connect_status("Введите адрес backend.", _THEME["danger"])
            return
        if not code:
            self._set_connect_status("Введите код подключения.", _THEME["danger"])
            return

        self.conn_btn.configure(state="disabled")
        self._set_connect_status("Подключение к backend...", _THEME["muted"])

        def worker() -> None:
            try:
                config = dict(self.config_data)
                config["backend_url"] = url
                config["processor_name"] = name
                connected = connect_with_code(config, code)
                self.config_data = normalize_config(connected)
                save_config(self.config_data)
                self.after(0, lambda: self._set_connect_status(f"Подключение выполнено. Processor ID: {self.config_data.get('processor_id')}.", _THEME["success"]))
                self.after(0, self._sync_ui_from_config)
                self.after(350, lambda: self._show_page("dashboard"))
            except Exception as exc:
                self.after(0, lambda: self._set_connect_status(f"Ошибка подключения: {exc}", _THEME["danger"]))
            finally:
                self.after(0, lambda: self.conn_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _browse_directory(self, key: str, entry: ctk.CTkEntry) -> None:
        initial = entry.get().strip() or str(_base_dir())
        selected = filedialog.askdirectory(initialdir=initial)
        if not selected:
            return
        entry.delete(0, "end")
        entry.insert(0, selected)
        self.config_data[key] = selected

    def _save_settings(self) -> None:
        try:
            previous_primary = _normalize_hex_color(self.config_data.get("theme_primary_color"), _DEFAULT_THEME_PRIMARY)
            previous_secondary = _normalize_hex_color(self.config_data.get("theme_secondary_color"), _DEFAULT_THEME_SECONDARY)
            self.config_data["max_workers"] = max(1, int(self.max_workers_entry.get().strip() or "1"))
            self.config_data["motion_threshold"] = float(self.motion_threshold_entry.get().strip() or "25.0")
            self.config_data["recording_segment_seconds"] = max(30, int(self.recording_segment_entry.get().strip() or "300"))
            self.config_data["recordings_dir"] = self.recordings_dir_entry.get().strip() or str(_base_dir() / "media" / "recordings")
            self.config_data["snapshots_dir"] = self.snapshots_dir_entry.get().strip() or str(_base_dir() / "media" / "snapshots")
            self.config_data["face_scan_divisor"] = _LABEL_TO_DIVISOR.get(self.face_scan_divisor_var.get(), 8)
            self.config_data["overlay_frame_divisor"] = _LABEL_TO_DIVISOR.get(self.overlay_frame_divisor_var.get(), 1)
            self.config_data["theme_primary_color"] = _normalize_hex_color(
                self.theme_primary_entry.get().strip(),
                _DEFAULT_THEME_PRIMARY,
            )
            self.config_data["theme_secondary_color"] = _normalize_hex_color(
                self.theme_secondary_entry.get().strip(),
                _DEFAULT_THEME_SECONDARY,
            )
            self.config_data = normalize_config(self.config_data)
            save_config(self.config_data)
            theme_changed = (
                self.config_data["theme_primary_color"] != previous_primary
                or self.config_data["theme_secondary_color"] != previous_secondary
            )
            if theme_changed:
                self._apply_theme_palette()
                self._rebuild_ui("settings")
            self._sync_ui_from_config()
            restart_note = " Перезапустите обработку, если сервис уже запущен." if self._running else ""
            theme_note = " Тема GUI обновлена." if theme_changed else ""
            self.settings_status.configure(text=f"Настройки сохранены.{theme_note}{restart_note}", text_color=_THEME["success"])
            self.after(5000, lambda: self.settings_status.configure(text=""))
        except Exception as exc:
            self.settings_status.configure(text=f"Ошибка сохранения: {exc}", text_color=_THEME["danger"])

    def _start_processing(self) -> None:
        if not self.config_data.get("api_key") or not self.config_data.get("backend_url"):
            self._show_page("connect")
            self._set_connect_status("Сначала подключите Processor к backend и получите API-ключ.", _THEME["warning"])
            return

        if not self.config_data.get("media_token"):
            self.config_data["media_token"] = secrets.token_urlsafe(24)
            save_config(self.config_data)

        self.config_data = normalize_config(self.config_data)
        export_env(self.config_data)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_status("starting")
        self._summary_labels["status"].configure(text="Запуск")
        self.hero_subtitle.configure(text="Processor запускается локально. После старта здесь будут видны heartbeat и активные камеры.")

        def run() -> None:
            try:
                root_logger = logging.getLogger()
                root_logger.setLevel(logging.INFO)
                if self._gui_log_handler:
                    root_logger.removeHandler(self._gui_log_handler)
                self._gui_log_handler = _GuiLogHandler(self)
                root_logger.addHandler(self._gui_log_handler)

                from processor import config as proc_cfg

                importlib.reload(proc_cfg)

                from processor.main import ProcessorService

                self._svc_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._svc_loop)
                self._svc = ProcessorService()
                self._running = True

                self.after(0, lambda: self._set_status("online"))
                self.after(0, lambda: self._summary_labels["status"].configure(text="Работает"))
                self.after(0, lambda: self.hero_subtitle.configure(text="Локальный Processor запущен. Монитор показывает нагрузку системы и активность камеры."))
                self._svc_loop.run_until_complete(self._svc.start())
            except Exception as exc:
                self.after(0, lambda: self._append_log(f"ERROR: {exc}\n"))
                self.after(0, lambda: self._set_status("offline"))
                self.after(0, lambda: self._summary_labels["status"].configure(text="Ошибка"))
                self.after(0, lambda: self.hero_subtitle.configure(text=f"Во время запуска возникла ошибка: {exc}"))
            finally:
                self._running = False
                self.after(0, lambda: self.start_btn.configure(state="normal"))
                self.after(0, lambda: self.stop_btn.configure(state="disabled"))
                if self._summary_labels["status"].cget("text") != "Ошибка":
                    self.after(0, lambda: self._summary_labels["status"].configure(text="Остановлен"))

        self._svc_thread = threading.Thread(target=run, daemon=True)
        self._svc_thread.start()

    def _stop_processing(self) -> None:
        if self._svc and self._svc_loop and self._svc_loop.is_running():
            asyncio.run_coroutine_threadsafe(self._svc.stop(), self._svc_loop)
        self._running = False
        self.stop_btn.configure(state="disabled")
        self._set_status("offline")
        self._summary_labels["status"].configure(text="Останавливается")
        self.hero_subtitle.configure(text="Остановка локального Processor уже отправлена. Дождитесь завершения фоновых задач.")

    def _update_metrics(self) -> None:
        active = len(self._svc.workers) if self._svc else 0
        metrics = self.monitor.collect(active)
        self._metrics = metrics

        _, cpu_label, cpu_bar = self._metric_cards["cpu"]
        cpu_label.configure(text=f"{metrics.cpu_percent:.0f}%")
        if cpu_bar:
            cpu_bar.set(metrics.cpu_percent / 100)

        _, ram_label, ram_bar = self._metric_cards["ram"]
        ram_label.configure(text=f"{metrics.ram_used_gb:.1f} / {metrics.ram_total_gb:.1f} GB")
        if ram_bar:
            ram_bar.set(metrics.ram_percent / 100 if metrics.ram_total_gb > 0 else 0)

        _, gpu_label, gpu_bar = self._metric_cards["gpu"]
        if metrics.gpu_name:
            util = metrics.gpu_util_percent or 0.0
            short_name = metrics.gpu_name[:22] if len(metrics.gpu_name) > 22 else metrics.gpu_name
            gpu_label.configure(text=f"{short_name} {util:.0f}%")
            if gpu_bar:
                gpu_bar.set(util / 100)
        else:
            gpu_label.configure(text="GPU не обнаружена / CPU")
            if gpu_bar:
                gpu_bar.set(0)

        _, net_label, _ = self._metric_cards["net"]
        net_label.configure(text=f"↑{metrics.net_sent_mbps:.1f} ↓{metrics.net_recv_mbps:.1f} Мбит/с")

        _, disk_label, disk_bar = self._metric_cards["disk"]
        disk_label.configure(text=f"{metrics.disk_used_gb:.0f} / {metrics.disk_total_gb:.0f} GB")
        if disk_bar and metrics.disk_total_gb > 0:
            disk_bar.set(metrics.disk_used_gb / metrics.disk_total_gb)

        _, cameras_label, _ = self._metric_cards["cameras"]
        cameras_label.configure(text=str(active))

        _, uptime_label, _ = self._metric_cards["uptime"]
        total = int(metrics.uptime_seconds)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_label.configure(text=f"{hours}:{minutes:02d}:{seconds:02d}")

        _, temp_label, _ = self._metric_cards["gpu_temp"]
        temp_label.configure(text=f"{metrics.gpu_temp_c}°C" if metrics.gpu_temp_c is not None else "—")
        self.after(2000, self._update_metrics)

    def _set_status(self, state: str) -> None:
        if state == "online":
            self.status_dot.configure(text_color=_THEME["success"])
            self.status_text.configure(text="Работает", text_color=_THEME["success"])
        elif state == "starting":
            self.status_dot.configure(text_color=_THEME["warning"])
            self.status_text.configure(text="Запуск", text_color=_THEME["warning"])
        else:
            self.status_dot.configure(text_color=_THEME["muted"])
            self.status_text.configure(text="Отключен", text_color=_THEME["muted"])

    def _apply_quick_preset(self, label: str, scan_divisor: int, overlay_divisor: int) -> None:
        self.face_scan_divisor_var.set(_divisor_label(scan_divisor))
        self.overlay_frame_divisor_var.set(_divisor_label(overlay_divisor))
        self._update_frequency_labels()
        self.settings_status.configure(
            text=f"Выбран пресет «{label}». Сохраните настройки, чтобы записать его в конфиг и runtime.",
            text_color=_THEME["muted"],
        )

    def _update_frequency_labels(self) -> None:
        scan_divisor = _LABEL_TO_DIVISOR.get(self.face_scan_divisor_var.get(), 8)
        overlay_divisor = _LABEL_TO_DIVISOR.get(self.overlay_frame_divisor_var.get(), 1)
        matched_preset = _match_quick_preset(scan_divisor, overlay_divisor)
        self.face_scan_info.configure(text=_frequency_description(scan_divisor))
        self.overlay_info.configure(text=_frequency_description(overlay_divisor))
        if self.quick_preset_hint is not None:
            if matched_preset:
                self.quick_preset_hint.configure(text=f"Активный профиль: {matched_preset}. Можно сохранить его как готовый режим без ручной подстройки.")
            else:
                self.quick_preset_hint.configure(text="Сейчас выбрана ручная комбинация. При необходимости можно вернуться к одному из быстрых пресетов.")
        summary = f"Текущий набор: сканирование {_divisor_label(scan_divisor)}, оверлей {_divisor_label(overlay_divisor)}."
        if matched_preset:
            summary += f" Профиль: {matched_preset}."
        else:
            summary += " Профиль: ручной."
        self.frequency_summary.configure(text=summary)

    def _update_info_labels(self) -> None:
        self.info_labels["server"].configure(text=_safe_text(self.config_data.get("backend_url")))
        self.info_labels["proc_id"].configure(text=_safe_text(self.config_data.get("processor_id")))
        self.info_labels["name"].configure(text=_safe_text(self.config_data.get("processor_name")))
        self.info_labels["os"].configure(text=_safe_text(self.system_info.get("os"), f"{platform.system()} {platform.release()}"))
        self.info_labels["arch"].configure(text=_safe_text(self.system_info.get("arch")))
        gpu_name = self.system_info.get("gpu") or "GPU не обнаружена"
        device = self.system_info.get("inference_device") or "cpu"
        self.info_labels["gpu"].configure(text=f"{gpu_name} / {device}")

    def _update_connect_summary(self) -> None:
        advertised_ip = self.config_data.get("advertised_ip") or "Будет определён автоматически"
        gpu_name = self.system_info.get("gpu") or "GPU не обнаружена"
        device = self.system_info.get("inference_device") or "cpu"
        values = {
            "server": _safe_text(self.config_data.get("backend_url")),
            "processor_id": _safe_text(self.config_data.get("processor_id")),
            "name": _safe_text(self.config_data.get("processor_name")),
            "advertised_ip": _safe_text(advertised_ip),
            "os": _safe_text(self.system_info.get("os"), f"{platform.system()} {platform.release()}"),
            "gpu": f"{gpu_name} / {device}",
        }
        for key, label in self._connect_summary_labels.items():
            label.configure(text=values.get(key, "—"))

    def _update_dashboard_summary(self) -> None:
        backend_url = _safe_text(self.config_data.get("backend_url"))
        scan_label = _divisor_label(self.config_data.get("face_scan_divisor", 8))
        overlay_label = _divisor_label(self.config_data.get("overlay_frame_divisor", 1))
        self._summary_labels["server"].configure(text=backend_url)
        self._summary_labels["scan"].configure(text=scan_label)
        self._summary_labels["overlay"].configure(text=overlay_label)
        self._summary_labels["status"].configure(text="Работает" if self._running else "Отключен")

        processor_name = _safe_text(self.config_data.get("processor_name"), socket.gethostname())
        processor_id = _safe_text(self.config_data.get("processor_id"), "не назначен")
        self.hero_title.configure(text=f"{processor_name} • ID {processor_id}")
        self.hero_subtitle.configure(text=f"Backend: {backend_url}. Сканирование {scan_label}, оверлей {overlay_label}. Управляйте запуском и нагрузкой отсюда.")

    def _refresh_settings_form(self) -> None:
        def _replace(entry: ctk.CTkEntry, value: object) -> None:
            entry.delete(0, "end")
            entry.insert(0, str(value))

        _replace(self.max_workers_entry, self.config_data.get("max_workers", 4))
        _replace(self.motion_threshold_entry, self.config_data.get("motion_threshold", 25.0))
        _replace(self.recording_segment_entry, self.config_data.get("recording_segment_seconds", 300))
        _replace(self.recordings_dir_entry, self.config_data.get("recordings_dir", _base_dir() / "media" / "recordings"))
        _replace(self.snapshots_dir_entry, self.config_data.get("snapshots_dir", _base_dir() / "media" / "snapshots"))
        self._set_theme_entry(
            self.theme_primary_entry,
            self.theme_primary_preview,
            str(self.config_data.get("theme_primary_color") or _DEFAULT_THEME_PRIMARY),
            _DEFAULT_THEME_PRIMARY,
        )
        self._set_theme_entry(
            self.theme_secondary_entry,
            self.theme_secondary_preview,
            str(self.config_data.get("theme_secondary_color") or _DEFAULT_THEME_SECONDARY),
            _DEFAULT_THEME_SECONDARY,
        )
        self.face_scan_divisor_var.set(_divisor_label(self.config_data.get("face_scan_divisor", 8)))
        self.overlay_frame_divisor_var.set(_divisor_label(self.config_data.get("overlay_frame_divisor", 1)))
        self._update_frequency_labels()

    def _sync_runtime_controls(self) -> None:
        if self._running:
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self._set_status("online")
            if "status" in self._summary_labels:
                self._summary_labels["status"].configure(text="Работает")
        else:
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self._set_status("offline")
            if "status" in self._summary_labels:
                self._summary_labels["status"].configure(text="Отключен")

    def _rebuild_ui(self, preferred_page: str | None = None) -> None:
        log_snapshot = ""
        if hasattr(self, "log_box"):
            try:
                log_snapshot = self.log_box.get("1.0", "end-1c")
            except Exception:
                log_snapshot = ""

        for container_name in ("sidebar", "content"):
            container = getattr(self, container_name, None)
            if container is not None:
                container.destroy()

        self._pages = {}
        self._nav_buttons = {}
        self._metric_cards = {}
        self._summary_labels = {}
        self._connect_summary_labels = {}
        self._settings_entries = {}
        self.info_labels = {}
        self.quick_preset_hint = None
        self.theme_primary_preview = None
        self.theme_secondary_preview = None
        self.theme_preview_card = None
        self.theme_preview_badge = None
        self.theme_preview_title = None
        self.theme_preview_text = None

        self._build_sidebar()
        self._build_content()
        self._show_page(preferred_page or self._current_page)
        self._sync_ui_from_config()
        self._sync_runtime_controls()
        if log_snapshot:
            self._append_log(log_snapshot + ("\n" if not log_snapshot.endswith("\n") else ""))

    def _sync_ui_from_config(self) -> None:
        self.config_data = normalize_config(self.config_data)
        self._update_connect_summary()
        self._update_info_labels()
        self._update_dashboard_summary()
        self._refresh_settings_form()
        self._sync_runtime_controls()

    def _open_runtime_path(self, path: Path) -> None:
        try:
            _open_path(path)
        except Exception as exc:
            messagebox.showerror("Ошибка открытия", f"Не удалось открыть путь:\n{path}\n\n{exc}")

    def _append_log(self, text: str) -> None:
        try:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", text)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def _clear_logs(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _on_close(self) -> None:
        if self._running:
            self._stop_processing()
        self.destroy()


class _GuiLogHandler(logging.Handler):
    def __init__(self, app: ProcessorApp):
        super().__init__()
        self.app = app
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) + "\n"
            self.app.after(0, self.app._append_log, message)
        except Exception:
            pass


def run() -> None:
    app = ProcessorApp()
    app.mainloop()


if __name__ == "__main__":
    run()
