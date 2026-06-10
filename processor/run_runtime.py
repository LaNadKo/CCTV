"""Launch the headless Processor runtime used by the Flutter GUI."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import traceback
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CCTV Processor headless runtime")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Accepted for compatibility; this launcher is always headless.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run processor command-line utility from the runtime executable.",
    )
    parser.add_argument(
        "--cli-capture-file",
        help="Write CLI stdout/stderr/exit code to this JSON file. Used by the native GUI.",
    )
    args, rest = parser.parse_known_args()
    args.cli_args = rest
    return args


if __name__ == "__main__":
    args = _parse_args()
    if args.cli:
        from processor.cli import main as cli_main

        if args.cli_capture_file:
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            exit_code = 0
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                try:
                    result = cli_main(args.cli_args)
                    exit_code = int(result or 0)
                except SystemExit as exc:
                    try:
                        exit_code = int(exc.code or 0)
                    except (TypeError, ValueError):
                        exit_code = 1
                except Exception:
                    traceback.print_exc()
                    exit_code = 1
            Path(args.cli_capture_file).write_text(
                json.dumps(
                    {
                        "exit_code": exit_code,
                        "stdout": stdout_buffer.getvalue(),
                        "stderr": stderr_buffer.getvalue(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            raise SystemExit(exit_code)

        raise SystemExit(cli_main(args.cli_args))
    from processor.runtime import run_headless

    run_headless()
