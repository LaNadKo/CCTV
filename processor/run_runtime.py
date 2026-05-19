"""Launch the headless Processor runtime used by the Flutter GUI."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("ORT_LOG_SEVERITY_LEVEL", "3")
os.environ.setdefault("GLOG_minloglevel", "2")

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _parse_args() -> None:
    parser = argparse.ArgumentParser(description="CCTV Processor headless runtime")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Accepted for compatibility; this launcher is always headless.",
    )
    parser.parse_args()


if __name__ == "__main__":
    _parse_args()
    from processor.runtime import run_headless

    run_headless()
