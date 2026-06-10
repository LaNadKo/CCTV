"""Launch the resident Processor supervisor."""
from __future__ import annotations

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


if __name__ == "__main__":
    from processor.supervisor import run_supervisor

    run_supervisor()
