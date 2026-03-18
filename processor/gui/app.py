"""Main processor desktop application — CustomTkinter GUI."""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import platform
import secrets
import socket
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from processor.monitor import SystemMonitor, get_system_info, Metrics

# ── Paths ──
def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

CONFIG_FILE = _base_dir() / "processor_config.json"
LOGO_TEXT = "CCTV Processor"
VERSION = "1.0.0"


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

# ── Config persistence ──
def load_config() -> dict:
    defaults = {
        "backend_url": "",
        "api_key": "",
        "processor_id": None,
        "processor_name": socket.gethostname(),
        "max_workers": 4,
        "motion_threshold": 25.0,
        "face_scan_interval": 2,
        "recording_segment_seconds": 300,
        "recordings_dir": str(_base_dir() / "media" / "recordings"),
        "snapshots_dir": str(_base_dir() / "media" / "snapshots"),
        "media_port": 8777,
        "media_token": secrets.token_urlsafe(24),
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**defaults, **json.load(f)}
        except Exception:
            pass
    return defaults

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ── Theme ──
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ProcessorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(LOGO_TEXT)
        self.geometry("900x620")
        self.minsize(780, 500)
        self._apply_window_icon()

        self.config_data = load_config()
        self.monitor = SystemMonitor()
        self._svc = None
        self._svc_loop = None
        self._svc_thread = None
        self._running = False
        self._metrics: Metrics | None = None

        # Layout: sidebar + content
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=180, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(self.sidebar, text=LOGO_TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(20, 5))
        ctk.CTkLabel(self.sidebar, text=f"v{VERSION}", text_color="gray50").pack(pady=(0, 20))

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for name, label in [("connect", "Подключение"), ("dashboard", "Дашборд"), ("settings", "Настройки"), ("logs", "Логи")]:
            btn = ctk.CTkButton(self.sidebar, text=label, command=lambda n=name: self._show_page(n),
                                fg_color="transparent", text_color="white", anchor="w", height=36,
                                hover_color=("gray70", "gray30"))
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_buttons[name] = btn

        # Status indicator at bottom of sidebar
        self.status_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.status_frame.pack(side="bottom", fill="x", padx=10, pady=10)
        self.status_dot = ctk.CTkLabel(self.status_frame, text="●", text_color="gray50", font=ctk.CTkFont(size=14))
        self.status_dot.pack(side="left")
        self.status_text = ctk.CTkLabel(self.status_frame, text="Отключен", text_color="gray50")
        self.status_text.pack(side="left", padx=5)

        # Content area
        self.content = ctk.CTkFrame(self, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self._pages: dict[str, ctk.CTkFrame] = {}
        self._build_connect_page()
        self._build_dashboard_page()
        self._build_settings_page()
        self._build_logs_page()

        # Show initial page
        if self.config_data.get("api_key") and self.config_data.get("backend_url"):
            self._show_page("dashboard")
        else:
            self._show_page("connect")

        # Start metrics update timer
        self._update_metrics()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Navigation ──

    def _apply_window_icon(self) -> None:
        icon_path = _asset_path("icon.ico")
        try:
            if icon_path.exists():
                self.iconbitmap(str(icon_path))
        except Exception:
            pass

    def _show_page(self, name: str):
        for n, page in self._pages.items():
            page.grid_remove()
        self._pages[name].grid(row=0, column=0, sticky="nsew")
        for n, btn in self._nav_buttons.items():
            btn.configure(fg_color=("gray75", "gray25") if n == name else "transparent")

    # ── Connect Page ──

    def _build_connect_page(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._pages["connect"] = page

        inner = ctk.CTkFrame(page, width=420)
        inner.place(relx=0.5, rely=0.45, anchor="center")

        ctk.CTkLabel(inner, text="Подключение к серверу", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(25, 5))
        ctk.CTkLabel(inner, text="Введите адрес сервера и код подключения", text_color="gray60").pack(pady=(0, 20))

        ctk.CTkLabel(inner, text="Адрес сервера", anchor="w").pack(fill="x", padx=30)
        self.conn_url = ctk.CTkEntry(inner, placeholder_text="http://192.168.50.62:8000", height=36)
        self.conn_url.pack(fill="x", padx=30, pady=(2, 10))
        if self.config_data.get("backend_url"):
            self.conn_url.insert(0, self.config_data["backend_url"])

        ctk.CTkLabel(inner, text="Код подключения", anchor="w").pack(fill="x", padx=30)
        self.conn_code = ctk.CTkEntry(inner, placeholder_text="ABCD1234", height=36, font=ctk.CTkFont(size=16, weight="bold"))
        self.conn_code.pack(fill="x", padx=30, pady=(2, 10))

        ctk.CTkLabel(inner, text="Имя процессора", anchor="w").pack(fill="x", padx=30)
        self.conn_name = ctk.CTkEntry(inner, height=36)
        self.conn_name.pack(fill="x", padx=30, pady=(2, 15))
        self.conn_name.insert(0, self.config_data.get("processor_name", socket.gethostname()))

        self.conn_status = ctk.CTkLabel(inner, text="", text_color="gray60")
        self.conn_status.pack(pady=(0, 5))

        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(pady=(0, 25))

        self.conn_test_btn = ctk.CTkButton(btn_frame, text="Проверить", width=130, command=self._test_connection)
        self.conn_test_btn.pack(side="left", padx=5)

        self.conn_btn = ctk.CTkButton(btn_frame, text="Подключиться", width=130, fg_color="#28a745", hover_color="#218838", command=self._connect)
        self.conn_btn.pack(side="left", padx=5)

        # If already connected, show reconnect info
        if self.config_data.get("api_key"):
            self.conn_status.configure(text="Уже подключен. Можно переподключиться с новым кодом.", text_color="#28a745")

    def _test_connection(self):
        url = self.conn_url.get().strip().rstrip("/")
        if not url:
            self.conn_status.configure(text="Введите адрес сервера", text_color="#dc3545")
            return
        self.conn_status.configure(text="Проверка...", text_color="gray60")
        self.update()
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"{url}/health", timeout=5)
            if resp.status == 200:
                self.conn_status.configure(text="Сервер доступен", text_color="#28a745")
            else:
                self.conn_status.configure(text=f"Ошибка: статус {resp.status}", text_color="#dc3545")
        except Exception as e:
            self.conn_status.configure(text=f"Ошибка: {e}", text_color="#dc3545")

    def _connect(self):
        url = self.conn_url.get().strip().rstrip("/")
        code = self.conn_code.get().strip()
        name = self.conn_name.get().strip() or socket.gethostname()
        if not url:
            self.conn_status.configure(text="Введите адрес сервера", text_color="#dc3545")
            return
        if not code:
            self.conn_status.configure(text="Введите код подключения", text_color="#dc3545")
            return
        self.conn_status.configure(text="Подключение...", text_color="gray60")
        self.conn_btn.configure(state="disabled")
        self.update()

        def do_connect():
            try:
                import urllib.request
                sysinfo = get_system_info()
                payload = json.dumps({
                    "code": code,
                    "name": name,
                    "hostname": sysinfo.get("hostname"),
                    "os_info": sysinfo.get("os"),
                    "version": VERSION,
                    "capabilities": {
                        **sysinfo,
                        "media_port": int(self.config_data.get("media_port", 8777)),
                        "media_token": self.config_data.get("media_token"),
                    },
                }).encode()
                req = urllib.request.Request(f"{url}/processors/connect", data=payload, method="POST",
                                            headers={"Content-Type": "application/json"})
                resp = urllib.request.urlopen(req, timeout=10)
                data = json.loads(resp.read().decode())
                # Save config
                self.config_data["backend_url"] = url
                self.config_data["api_key"] = data["api_key"]
                self.config_data["processor_id"] = data["processor_id"]
                self.config_data["processor_name"] = data["name"]
                save_config(self.config_data)
                self.after(0, lambda: self.conn_status.configure(
                    text=f"Подключен! ID: {data['processor_id']}", text_color="#28a745"))
                self.after(0, lambda: self.conn_btn.configure(state="normal"))
                self.after(500, lambda: self._show_page("dashboard"))
            except Exception as e:
                err = str(e)
                try:
                    err = json.loads(e.read().decode()).get("detail", str(e))
                except Exception:
                    pass
                self.after(0, lambda: self.conn_status.configure(text=f"Ошибка: {err}", text_color="#dc3545"))
                self.after(0, lambda: self.conn_btn.configure(state="normal"))

        threading.Thread(target=do_connect, daemon=True).start()

    # ── Dashboard Page ──

    def _build_dashboard_page(self):
        page = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._pages["dashboard"] = page

        ctk.CTkLabel(page, text="Дашборд", font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))

        # Start/Stop controls
        ctrl = ctk.CTkFrame(page, fg_color="transparent")
        ctrl.pack(fill="x", padx=20, pady=(0, 10))
        self.start_btn = ctk.CTkButton(ctrl, text="Запустить обработку", fg_color="#28a745", hover_color="#218838",
                                       command=self._start_processing, width=180)
        self.start_btn.pack(side="left")
        self.stop_btn = ctk.CTkButton(ctrl, text="Остановить", fg_color="#dc3545", hover_color="#c82333",
                                      command=self._stop_processing, width=130, state="disabled")
        self.stop_btn.pack(side="left", padx=10)
        self.proc_status_label = ctk.CTkLabel(ctrl, text="Остановлен", text_color="gray50")
        self.proc_status_label.pack(side="left", padx=10)

        # Metrics cards grid
        cards_frame = ctk.CTkFrame(page, fg_color="transparent")
        cards_frame.pack(fill="x", padx=20, pady=5)
        cards_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self._metric_cards: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel, ctk.CTkProgressBar | None]] = {}
        card_defs = [
            ("cpu", "CPU", "0%", True),
            ("ram", "RAM", "0 / 0 GB", True),
            ("gpu", "GPU", "Нет данных", True),
            ("net", "Сеть", "↑0 ↓0 Мбит/с", False),
        ]
        for i, (key, title, default, has_bar) in enumerate(card_defs):
            card = ctk.CTkFrame(cards_frame)
            card.grid(row=0, column=i, padx=5, pady=5, sticky="nsew")
            lbl_title = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12), text_color="gray60")
            lbl_title.pack(padx=10, pady=(10, 2))
            lbl_val = ctk.CTkLabel(card, text=default, font=ctk.CTkFont(size=15, weight="bold"))
            lbl_val.pack(padx=10)
            bar = None
            if has_bar:
                bar = ctk.CTkProgressBar(card, width=120, height=8)
                bar.set(0)
                bar.pack(padx=10, pady=(5, 10))
            else:
                ctk.CTkLabel(card, text="").pack(pady=(0, 5))  # spacer
            self._metric_cards[key] = (lbl_title, lbl_val, bar)

        # Second row: disk + cameras + uptime + gpu temp
        cards2 = ctk.CTkFrame(page, fg_color="transparent")
        cards2.pack(fill="x", padx=20, pady=5)
        cards2.grid_columnconfigure((0, 1, 2, 3), weight=1)

        card_defs2 = [
            ("disk", "Диск", "0 / 0 GB", True),
            ("cameras", "Камеры", "0", False),
            ("uptime", "Аптайм", "0:00:00", False),
            ("gpu_temp", "GPU Temp", "—", False),
        ]
        for i, (key, title, default, has_bar) in enumerate(card_defs2):
            card = ctk.CTkFrame(cards2)
            card.grid(row=0, column=i, padx=5, pady=5, sticky="nsew")
            lbl_title = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12), text_color="gray60")
            lbl_title.pack(padx=10, pady=(10, 2))
            lbl_val = ctk.CTkLabel(card, text=default, font=ctk.CTkFont(size=15, weight="bold"))
            lbl_val.pack(padx=10)
            bar = None
            if has_bar:
                bar = ctk.CTkProgressBar(card, width=120, height=8)
                bar.set(0)
                bar.pack(padx=10, pady=(5, 10))
            else:
                ctk.CTkLabel(card, text="").pack(pady=(0, 5))
            self._metric_cards[key] = (lbl_title, lbl_val, bar)

        # Connection info
        info_frame = ctk.CTkFrame(page)
        info_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(info_frame, text="Информация о подключении", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=15, pady=(10, 5))
        self.info_labels: dict[str, ctk.CTkLabel] = {}
        for key, label in [("server", "Сервер"), ("proc_id", "Processor ID"), ("name", "Имя"), ("os", "ОС")]:
            row = ctk.CTkFrame(info_frame, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=1)
            ctk.CTkLabel(row, text=f"{label}:", text_color="gray60", width=120, anchor="w").pack(side="left")
            val = ctk.CTkLabel(row, text="—")
            val.pack(side="left")
            self.info_labels[key] = val

        self._update_info_labels()

    def _update_info_labels(self):
        self.info_labels["server"].configure(text=self.config_data.get("backend_url", "—"))
        self.info_labels["proc_id"].configure(text=str(self.config_data.get("processor_id", "—")))
        self.info_labels["name"].configure(text=self.config_data.get("processor_name", "—"))
        self.info_labels["os"].configure(text=f"{platform.system()} {platform.release()}")

    # ── Settings Page ──

    def _build_settings_page(self):
        page = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._pages["settings"] = page

        ctk.CTkLabel(page, text="Настройки обработки", font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=20, pady=(15, 15))

        self._settings_entries: dict[str, ctk.CTkEntry] = {}
        fields = [
            ("max_workers", "Макс. камер (workers)", "4"),
            ("motion_threshold", "Порог движения", "25.0"),
            ("face_scan_interval", "Интервал сканирования лиц (сек)", "2"),
            ("recording_segment_seconds", "Длина сегмента записи (сек)", "300"),
        ]
        for key, label, default in fields:
            ctk.CTkLabel(page, text=label, anchor="w").pack(fill="x", padx=30, pady=(10, 2))
            entry = ctk.CTkEntry(page, height=34)
            entry.pack(fill="x", padx=30)
            entry.insert(0, str(self.config_data.get(key, default)))
            self._settings_entries[key] = entry

        ctk.CTkButton(page, text="Сохранить настройки", command=self._save_settings, width=200).pack(padx=30, pady=20, anchor="w")
        for key, label, default in [
            ("recordings_dir", "Папка для записей", str(_base_dir() / "media" / "recordings")),
            ("snapshots_dir", "Папка для снимков", str(_base_dir() / "media" / "snapshots")),
        ]:
            ctk.CTkLabel(page, text=label, anchor="w").pack(fill="x", padx=30, pady=(10, 2))
            row = ctk.CTkFrame(page, fg_color="transparent")
            row.pack(fill="x", padx=30)
            entry = ctk.CTkEntry(row, height=34)
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, str(self.config_data.get(key, default)))
            ctk.CTkButton(
                row,
                text="Выбрать",
                width=96,
                command=lambda k=key, e=entry: self._browse_directory(k, e),
            ).pack(side="left", padx=(8, 0))
            self._settings_entries[key] = entry

        ctk.CTkButton(page, text="Сохранить пути и настройки", command=self._save_settings, width=240).pack(padx=30, pady=(16, 8), anchor="w")
        self.settings_status = ctk.CTkLabel(page, text="", text_color="#28a745")
        self.settings_status.pack(padx=30, anchor="w")

    def _browse_directory(self, key: str, entry: ctk.CTkEntry):
        initial = entry.get().strip() or str(_base_dir())
        chosen = filedialog.askdirectory(initialdir=initial)
        if not chosen:
            return
        entry.delete(0, "end")
        entry.insert(0, chosen)
        self.config_data[key] = chosen

    def _save_settings(self):
        for key, entry in self._settings_entries.items():
            val = entry.get().strip()
            if key in ("max_workers", "face_scan_interval", "recording_segment_seconds"):
                self.config_data[key] = int(val)
            elif key == "motion_threshold":
                self.config_data[key] = float(val)
            else:
                self.config_data[key] = val
        save_config(self.config_data)
        self.settings_status.configure(text="Сохранено!")
        self.after(2000, lambda: self.settings_status.configure(text=""))

    # ── Logs Page ──

    def _build_logs_page(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, weight=1)
        self._pages["logs"] = page

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 5))
        ctk.CTkLabel(header, text="Логи", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Очистить", width=80, command=self._clear_logs).pack(side="right")

        self.log_box = ctk.CTkTextbox(page, font=ctk.CTkFont(family="Consolas", size=12), state="disabled",
                                      fg_color=("#f0f0f0", "#1a1a2e"), text_color=("#333", "#e0e0e0"))
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 15))

    def _append_log(self, text: str):
        try:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", text)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except Exception:
            pass

    def _clear_logs(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ── Processing control ──

    def _start_processing(self):
        if not self.config_data.get("api_key") or not self.config_data.get("backend_url"):
            self._show_page("connect")
            return

        if not self.config_data.get("media_token"):
            self.config_data["media_token"] = secrets.token_urlsafe(24)
            save_config(self.config_data)

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.proc_status_label.configure(text="Запуск...", text_color="#ffc107")
        self._set_status("online")

        # Set env vars
        os.environ["BACKEND_URL"] = self.config_data["backend_url"]
        os.environ["API_KEY"] = self.config_data["api_key"]
        os.environ["PROCESSOR_ID"] = str(self.config_data.get("processor_id") or "")
        os.environ["PROCESSOR_NAME"] = self.config_data.get("processor_name", "processor-1")
        os.environ["MAX_WORKERS"] = str(self.config_data.get("max_workers", 4))
        os.environ["MOTION_THRESHOLD"] = str(self.config_data.get("motion_threshold", 25.0))
        os.environ["FACE_SCAN_INTERVAL"] = str(self.config_data.get("face_scan_interval", 5))
        os.environ["RECORDING_SEGMENT_SECONDS"] = str(self.config_data.get("recording_segment_seconds", 300))
        os.environ["RECORDINGS_DIR"] = str(self.config_data.get("recordings_dir", _base_dir() / "media" / "recordings"))
        os.environ["SNAPSHOTS_DIR"] = str(self.config_data.get("snapshots_dir", _base_dir() / "media" / "snapshots"))
        os.environ["MEDIA_PORT"] = str(self.config_data.get("media_port", 8777))
        os.environ["MEDIA_TOKEN"] = self.config_data.get("media_token") or secrets.token_urlsafe(24)

        def run():
            try:
                # Setup logging to GUI
                root_logger = logging.getLogger()
                root_logger.setLevel(logging.INFO)
                handler = _GuiLogHandler(self)
                root_logger.addHandler(handler)

                # Reload config module
                from processor import config as proc_cfg
                importlib.reload(proc_cfg)
                from processor.main import ProcessorService

                self._svc_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._svc_loop)
                self._svc = ProcessorService()
                self._running = True

                self.after(0, lambda: self.proc_status_label.configure(text="Работает", text_color="#28a745"))
                self._svc_loop.run_until_complete(self._svc.start())
            except Exception as e:
                self.after(0, lambda: self.proc_status_label.configure(text=f"Ошибка: {e}", text_color="#dc3545"))
                self.after(0, lambda: self._append_log(f"ERROR: {e}\n"))
                import traceback
                self.after(0, lambda: self._append_log(traceback.format_exc()))
            finally:
                self._running = False
                self.after(0, lambda: self._set_status("offline"))
                self.after(0, lambda: self.start_btn.configure(state="normal"))
                self.after(0, lambda: self.stop_btn.configure(state="disabled"))
                self.after(0, lambda: self.proc_status_label.configure(text="Остановлен", text_color="gray50"))

        self._svc_thread = threading.Thread(target=run, daemon=True)
        self._svc_thread.start()

    def _stop_processing(self):
        if self._svc and self._svc_loop and self._svc_loop.is_running():
            asyncio.run_coroutine_threadsafe(self._svc.stop(), self._svc_loop)
        self._running = False
        self._set_status("offline")
        self.stop_btn.configure(state="disabled")
        self.proc_status_label.configure(text="Останавливается...", text_color="#ffc107")

    # ── Metrics update loop ──

    def _update_metrics(self):
        active = len(self._svc.workers) if self._svc else 0
        m = self.monitor.collect(active)
        self._metrics = m

        # CPU
        _, lbl, bar = self._metric_cards["cpu"]
        lbl.configure(text=f"{m.cpu_percent:.0f}%")
        if bar:
            bar.set(m.cpu_percent / 100)

        # RAM
        _, lbl, bar = self._metric_cards["ram"]
        lbl.configure(text=f"{m.ram_used_gb:.1f} / {m.ram_total_gb:.1f} GB")
        if bar:
            bar.set(m.ram_percent / 100 if m.ram_total_gb > 0 else 0)

        # GPU
        _, lbl, bar = self._metric_cards["gpu"]
        if m.gpu_name:
            short = m.gpu_name[:20] if len(m.gpu_name) > 20 else m.gpu_name
            util = m.gpu_util_percent or 0
            lbl.configure(text=f"{short} {util:.0f}%")
            if bar:
                bar.set(util / 100)
        else:
            lbl.configure(text="CPU mode")
            if bar:
                bar.set(0)

        # Network
        _, lbl, _ = self._metric_cards["net"]
        lbl.configure(text=f"↑{m.net_sent_mbps:.1f} ↓{m.net_recv_mbps:.1f} Мбит/с")

        # Disk
        _, lbl, bar = self._metric_cards["disk"]
        lbl.configure(text=f"{m.disk_used_gb:.0f} / {m.disk_total_gb:.0f} GB")
        if bar and m.disk_total_gb > 0:
            bar.set(m.disk_used_gb / m.disk_total_gb)

        # Cameras
        _, lbl, _ = self._metric_cards["cameras"]
        lbl.configure(text=str(active))

        # Uptime
        _, lbl, _ = self._metric_cards["uptime"]
        s = int(m.uptime_seconds)
        h, remainder = divmod(s, 3600)
        mi, sec = divmod(remainder, 60)
        lbl.configure(text=f"{h}:{mi:02d}:{sec:02d}")

        # GPU Temp
        _, lbl, _ = self._metric_cards["gpu_temp"]
        if m.gpu_temp_c is not None:
            lbl.configure(text=f"{m.gpu_temp_c}°C")
        else:
            lbl.configure(text="—")

        self.after(2000, self._update_metrics)

    def _set_status(self, s: str):
        if s == "online":
            self.status_dot.configure(text_color="#28a745")
            self.status_text.configure(text="Онлайн", text_color="#28a745")
        else:
            self.status_dot.configure(text_color="gray50")
            self.status_text.configure(text="Отключен", text_color="gray50")

    def _on_close(self):
        if self._running:
            self._stop_processing()
        self.destroy()


class _GuiLogHandler(logging.Handler):
    def __init__(self, app: ProcessorApp):
        super().__init__()
        self.app = app
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record):
        try:
            msg = self.format(record) + "\n"
            self.app.after(0, self.app._append_log, msg)
        except Exception:
            pass


def run():
    app = ProcessorApp()
    app.mainloop()


if __name__ == "__main__":
    run()
