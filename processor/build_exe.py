"""Build processor desktop app as a standalone .exe using PyInstaller."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ASSETS_DIR = HERE / "assets"


def _run(cmd: list[str]) -> None:
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(HERE.parent), check=True)


def _gui_cmd() -> list[str]:
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--specpath",
        str(HERE),
        "--workpath",
        str(HERE / "build"),
        "--distpath",
        str(HERE / "dist"),
        "--name",
        "CCTV-Processor",
        "--icon",
        str(ASSETS_DIR / "icon.ico"),
        "--add-data",
        f"{ASSETS_DIR};processor/assets",
        "--hidden-import",
        "processor",
        "--hidden-import",
        "processor.main",
        "--hidden-import",
        "processor.client",
        "--hidden-import",
        "processor.config",
        "--hidden-import",
        "processor.detection",
        "--hidden-import",
        "processor.vision",
        "--hidden-import",
        "processor.camera_utils",
        "--hidden-import",
        "processor.monitor",
        "--hidden-import",
        "processor.media_server",
        "--hidden-import",
        "processor.cli",
        "--hidden-import",
        "processor.runtime",
        "--hidden-import",
        "processor.paths",
        "--hidden-import",
        "processor.tracker",
        "--hidden-import",
        "processor.tracking",
        "--hidden-import",
        "processor.body_detector",
        "--hidden-import",
        "processor.antispoof",
        "--hidden-import",
        "processor.gui",
        "--hidden-import",
        "processor.gui.app",
        "--hidden-import",
        "customtkinter",
        "--hidden-import",
        "pynvml",
        "--hidden-import",
        "psutil",
        "--hidden-import",
        "facenet_pytorch",
        "--collect-submodules",
        "facenet_pytorch",
        "--collect-data",
        "facenet_pytorch",
        "--collect-data",
        "customtkinter",
        str(HERE / "run_gui.py"),
    ]


def _cli_cmd() -> list[str]:
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--console",
        "--specpath",
        str(HERE),
        "--workpath",
        str(HERE / "build" / "cli"),
        "--distpath",
        str(HERE / "dist"),
        "--name",
        "CCTV-Processor-CLI",
        "--icon",
        str(ASSETS_DIR / "icon.ico"),
        "--add-data",
        f"{ASSETS_DIR};processor/assets",
        "--hidden-import",
        "processor",
        "--hidden-import",
        "processor.cli",
        "--hidden-import",
        "processor.runtime",
        "--hidden-import",
        "processor.client",
        "--hidden-import",
        "processor.config",
        "--hidden-import",
        "processor.camera_utils",
        "--hidden-import",
        "processor.monitor",
        "--hidden-import",
        "processor.vision",
        "--hidden-import",
        "cv2",
        "--hidden-import",
        "facenet_pytorch",
        "--collect-submodules",
        "facenet_pytorch",
        "--collect-data",
        "facenet_pytorch",
        str(HERE / "cli.py"),
    ]


def build() -> None:
    _run(_gui_cmd())
    skip_cli = os.environ.get("SKIP_PROCESSOR_CLI", "").strip().lower() in {"1", "true", "yes"}
    if not skip_cli:
        _run(_cli_cmd())
    print(f"\nBuild complete: {HERE / 'dist' / 'CCTV-Processor'}")


if __name__ == "__main__":
    build()
