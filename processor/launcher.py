"""GUI launcher for CCTV Processor.

Build:
  pip install pyinstaller
  cd processor
  python build_exe.py
"""
import json
import os
import sys
import asyncio
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path

CONFIG_FILE = "processor_config.json"
DEFAULT_CONFIG = {
    "backend_url": "http://192.168.1.100:8000",
    "api_key": "processor-secret-key-2026",
    "processor_name": "",
    "max_workers": 4,
}


def _base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_config_path():
    return _base_dir() / CONFIG_FILE


def load_config():
    path = get_config_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def detect_gpu():
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Log handler that forwards log records to a tkinter callback
# ---------------------------------------------------------------------------
class _TkLogHandler(logging.Handler):
    """Sends log lines to a tkinter widget via .after() to be thread-safe."""

    def __init__(self, widget, append_fn):
        super().__init__()
        self.widget = widget
        self.append_fn = append_fn
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record):
        try:
            msg = self.format(record) + "\n"
            self.widget.after(0, self.append_fn, msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Setup screen
# ---------------------------------------------------------------------------
class SetupFrame(ttk.Frame):
    def __init__(self, master, on_start):
        super().__init__(master, padding=20)
        self.on_start = on_start
        self.config = load_config()
        if not self.config["processor_name"]:
            import socket
            self.config["processor_name"] = socket.gethostname()

        ttk.Label(self, text="CCTV Processor", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 15)
        )

        # GPU info
        gpu = detect_gpu()
        gpu_text = f"GPU: {gpu}" if gpu else "GPU: не обнаружена (CPU режим)"
        lbl = ttk.Label(self, text=gpu_text, foreground="green" if gpu else "orange")
        lbl.grid(row=1, column=0, columnspan=2, pady=(0, 15), sticky="w")

        # Fields
        fields = [
            ("IP-адрес сервера:", "backend_url", "http://192.168.1.100:8000"),
            ("API-ключ:", "api_key", "processor-secret-key-2026"),
            ("Имя процессора:", "processor_name", "my-pc"),
            ("Max workers:", "max_workers", "4"),
        ]
        self.entries = {}
        for i, (label, key, placeholder) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=i + 2, column=0, sticky="w", pady=4)
            entry = ttk.Entry(self, width=40)
            entry.insert(0, str(self.config.get(key, "")))
            entry.grid(row=i + 2, column=1, sticky="ew", pady=4, padx=(10, 0))
            self.entries[key] = entry

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=len(fields) + 2, column=0, columnspan=2, pady=(20, 0))

        self.test_btn = ttk.Button(btn_frame, text="Проверить соединение", command=self.test_connection)
        self.test_btn.pack(side="left", padx=5)

        self.start_btn = ttk.Button(btn_frame, text="Запустить", command=self.start)
        self.start_btn.pack(side="left", padx=5)

        self.status_label = ttk.Label(self, text="", foreground="gray")
        self.status_label.grid(row=len(fields) + 3, column=0, columnspan=2, pady=(10, 0))

        self.columnconfigure(1, weight=1)

    def get_values(self):
        return {k: e.get().strip() for k, e in self.entries.items()}

    def test_connection(self):
        self.status_label.config(text="Проверка...", foreground="gray")
        self.update()
        vals = self.get_values()
        url = vals["backend_url"].rstrip("/") + "/health"
        try:
            import urllib.request
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status == 200:
                self.status_label.config(text="OK — сервер доступен", foreground="green")
            else:
                self.status_label.config(text=f"Ошибка: статус {resp.status}", foreground="red")
        except Exception as e:
            self.status_label.config(text=f"Ошибка: {e}", foreground="red")

    def start(self):
        vals = self.get_values()
        if not vals["backend_url"]:
            messagebox.showerror("Ошибка", "Укажите IP-адрес сервера")
            return
        vals["max_workers"] = int(vals.get("max_workers") or 4)
        save_config(vals)
        self.on_start(vals)


# ---------------------------------------------------------------------------
# Run screen — runs processor inline in a background thread
# ---------------------------------------------------------------------------
class RunFrame(ttk.Frame):
    def __init__(self, master, config, on_stop):
        super().__init__(master, padding=20)
        self.on_stop = on_stop
        self._svc = None
        self._loop = None
        self._thread = None

        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text="CCTV Processor", font=("Segoe UI", 14, "bold")).pack(side="left")
        self.stop_btn = ttk.Button(header, text="Остановить", command=self.stop)
        self.stop_btn.pack(side="right")

        info_text = f"Сервер: {config['backend_url']}  |  Имя: {config['processor_name']}"
        ttk.Label(self, text=info_text, foreground="gray").pack(anchor="w", pady=(5, 10))

        self.log_area = scrolledtext.ScrolledText(
            self, height=20, width=80, state="disabled",
            font=("Consolas", 9), bg="#1e1e1e", fg="#cccccc",
        )
        self.log_area.pack(fill="both", expand=True)

        self.status_label = ttk.Label(self, text="Запуск...", foreground="orange")
        self.status_label.pack(anchor="w", pady=(5, 0))

        self._start_processor(config)

    def _append_log(self, text):
        self.log_area.config(state="normal")
        self.log_area.insert("end", text)
        self.log_area.see("end")
        self.log_area.config(state="disabled")

    def _start_processor(self, config):
        # Set env vars BEFORE importing processor modules (they read env at import time)
        os.environ["BACKEND_URL"] = config["backend_url"]
        os.environ["API_KEY"] = config["api_key"]
        os.environ["PROCESSOR_NAME"] = config["processor_name"]
        os.environ["MAX_WORKERS"] = str(config["max_workers"])

        def run():
            try:
                # Redirect all logging to the GUI
                root_logger = logging.getLogger()
                root_logger.setLevel(logging.INFO)
                tk_handler = _TkLogHandler(self, self._append_log)
                root_logger.addHandler(tk_handler)

                # Import processor modules AFTER env vars are set
                # Reload config so it picks up new env values
                from processor import config as proc_cfg
                import importlib
                importlib.reload(proc_cfg)

                from processor.main import ProcessorService

                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

                self._svc = ProcessorService()

                self.after(0, lambda: self.status_label.config(text="Работает", foreground="green"))
                self._loop.run_until_complete(self._svc.start())
            except Exception as e:
                self.after(0, lambda: self.status_label.config(text=f"Ошибка: {e}", foreground="red"))
                self.after(0, self._append_log, f"ERROR: {e}\n")
                import traceback
                self.after(0, self._append_log, traceback.format_exc())
            finally:
                self.after(0, lambda: self.status_label.config(text="Остановлен", foreground="red"))

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._svc and self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._svc.stop(), self._loop)
        self.on_stop()


# ---------------------------------------------------------------------------
# Main app window
# ---------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CCTV Processor")
        self.geometry("600x500")
        self.resizable(True, True)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass
        self.show_setup()

    def show_setup(self):
        for w in self.winfo_children():
            w.destroy()
        self.geometry("500x350")
        frame = SetupFrame(self, on_start=self.show_run)
        frame.pack(fill="both", expand=True)

    def show_run(self, config):
        for w in self.winfo_children():
            w.destroy()
        self.geometry("700x500")
        frame = RunFrame(self, config, on_stop=self.show_setup)
        frame.pack(fill="both", expand=True)


if __name__ == "__main__":
    app = App()
    app.mainloop()
