"""Launch the processor GUI or headless runtime."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CCTV Processor launcher")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run processor service in background mode without GUI",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run processor command-line utility",
    )
    args, rest = parser.parse_known_args()
    args.cli_args = rest
    return args


if __name__ == "__main__":
    args = _parse_args()
    if args.cli:
        from processor.cli import main as cli_main

        raise SystemExit(cli_main(args.cli_args))
    if args.headless:
        from processor.runtime import run_headless

        run_headless()
    else:
        from processor.gui.app import run

        run()
