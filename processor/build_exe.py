"""Build processor desktop app as a standalone .exe using PyInstaller."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ASSETS_DIR = HERE / "assets"


def build() -> None:
    cmd = [
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
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(HERE.parent), check=True)
    print(f"\nBuild complete: {HERE / 'dist' / 'CCTV-Processor'}")


if __name__ == "__main__":
    build()
