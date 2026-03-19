"""Command-line utility for operating and testing CCTV Processor."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import cv2


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _load_runtime():
    from processor import runtime

    return runtime


def _read_config() -> dict[str, Any]:
    runtime = _load_runtime()
    return runtime.apply_env_overrides(runtime.load_config())


def _save_config(config: dict[str, Any]) -> None:
    runtime = _load_runtime()
    runtime.save_config(config)


def _log_file() -> Path:
    runtime = _load_runtime()
    return runtime.LOG_FILE


def _base_dir() -> Path:
    runtime = _load_runtime()
    return runtime.base_dir()


def _json_request(
    method: str,
    base_url: str,
    path: str,
    *,
    api_key: str | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"Accept": "application/json"}
    data = None
    if api_key:
        headers["X-Api-Key"] = api_key
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(json_body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.reason
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
            detail = payload.get("detail", detail)
        except Exception:
            pass
        raise RuntimeError(f"{method.upper()} {path} failed: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"{method.upper()} {path} failed: {exc}") from exc


def _backend_health(base_url: str) -> dict[str, Any]:
    return _json_request("GET", base_url, "/health", timeout=10.0)


def _require_connection(config: dict[str, Any]) -> tuple[str, str, int]:
    base_url = str(config.get("backend_url") or "").strip().rstrip("/")
    api_key = str(config.get("api_key") or "").strip()
    processor_id = config.get("processor_id")
    if not base_url:
        raise RuntimeError("Processor is not configured: backend_url is empty")
    if not api_key:
        raise RuntimeError("Processor is not connected: api_key is missing")
    if processor_id in (None, ""):
        raise RuntimeError("Processor is not connected: processor_id is missing")
    return base_url, api_key, int(processor_id)


def _get_assignments(config: dict[str, Any]) -> list[dict[str, Any]]:
    base_url, api_key, processor_id = _require_connection(config)
    return _json_request("GET", base_url, f"/processors/{processor_id}/assignments", api_key=api_key)


def _get_gallery(config: dict[str, Any]) -> list[dict[str, Any]]:
    base_url, api_key, processor_id = _require_connection(config)
    return _json_request("GET", base_url, f"/processors/{processor_id}/gallery", api_key=api_key)


def _get_storage_config(config: dict[str, Any]) -> dict[str, Any]:
    base_url, api_key, processor_id = _require_connection(config)
    return _json_request("GET", base_url, f"/processors/{processor_id}/storage-config", api_key=api_key)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _pick_source(
    config: dict[str, Any],
    *,
    source: str | None,
    camera_id: int | None,
) -> tuple[str | int, dict[str, Any] | None]:
    if source:
        return source, None

    assignments = _get_assignments(config)
    if not assignments:
        raise RuntimeError("No assigned cameras found for this processor")

    selected = None
    if camera_id is not None:
        for item in assignments:
            if int(item["camera_id"]) == int(camera_id):
                selected = item
                break
        if selected is None:
            raise RuntimeError(f"Camera {camera_id} is not assigned to this processor")
    else:
        selected = assignments[0]

    from processor.camera_utils import resolve_source

    resolved = resolve_source(selected)
    if resolved is None:
        raise RuntimeError(f"Could not resolve source for camera {selected['camera_id']}")
    return resolved, selected


def _open_capture(source: str | int) -> cv2.VideoCapture:
    if isinstance(source, str) and source.lower().startswith("rtsp://"):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0|buffer_size;102400"
        )
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        cap = cv2.VideoCapture(source)

    for prop, value in (
        (getattr(cv2, "CAP_PROP_BUFFERSIZE", None), 1),
        (getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), 5000),
        (getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), 5000),
    ):
        if prop is None:
            continue
        try:
            cap.set(prop, value)
        except Exception:
            pass
    return cap


def _tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        data = handle.readlines()
    return data[-lines:]


def cmd_config_show(args: argparse.Namespace) -> int:
    config = _read_config()
    if args.json:
        _print_json(config)
    else:
        for key in sorted(config.keys()):
            print(f"{key}: {config[key]}")
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    runtime = _load_runtime()
    config = runtime.load_config()
    updates = {
        "backend_url": args.backend_url,
        "processor_name": args.name,
        "max_workers": args.max_workers,
        "motion_threshold": args.motion_threshold,
        "face_scan_interval": args.face_scan_interval,
        "recording_segment_seconds": args.recording_segment_seconds,
        "recordings_dir": args.recordings_dir,
        "snapshots_dir": args.snapshots_dir,
        "media_port": args.media_port,
        "media_token": args.media_token,
    }
    for key, value in updates.items():
        if value is not None:
            config[key] = value
    runtime.save_config(config)
    print("Config updated.")
    return 0


def cmd_config_reset(args: argparse.Namespace) -> int:
    runtime = _load_runtime()
    runtime.save_config(runtime.default_config())
    print("Config reset to defaults.")
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    runtime = _load_runtime()
    config = runtime.load_config()
    if args.backend_url:
        config["backend_url"] = args.backend_url.rstrip("/")
    if args.name:
        config["processor_name"] = args.name
    if args.media_port is not None:
        config["media_port"] = args.media_port
    if args.media_token:
        config["media_token"] = args.media_token
    if args.recordings_dir:
        config["recordings_dir"] = args.recordings_dir
    if args.snapshots_dir:
        config["snapshots_dir"] = args.snapshots_dir
    if args.max_workers is not None:
        config["max_workers"] = args.max_workers
    if args.motion_threshold is not None:
        config["motion_threshold"] = args.motion_threshold
    if args.face_scan_interval is not None:
        config["face_scan_interval"] = args.face_scan_interval
    if args.recording_segment_seconds is not None:
        config["recording_segment_seconds"] = args.recording_segment_seconds

    connected = runtime.connect_with_code(config, args.code)
    if args.json:
        _print_json(
            {
                "backend_url": connected.get("backend_url"),
                "processor_id": connected.get("processor_id"),
                "processor_name": connected.get("processor_name"),
            }
        )
    else:
        print(f"Connected to {connected.get('backend_url')}")
        print(f"processor_id: {connected.get('processor_id')}")
        print(f"processor_name: {connected.get('processor_name')}")
    return 0


def cmd_disconnect(args: argparse.Namespace) -> int:
    runtime = _load_runtime()
    config = runtime.load_config()
    config["api_key"] = ""
    config["processor_id"] = None
    runtime.save_config(config)
    print("Processor credentials cleared from local config.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = _read_config()
    payload: dict[str, Any] = {
        "base_dir": str(_base_dir()),
        "config_file": str(_load_runtime().CONFIG_FILE),
        "log_file": str(_log_file()),
        "configured": bool(config.get("backend_url")),
        "connected": bool(config.get("api_key") and config.get("processor_id")),
        "processor_name": config.get("processor_name"),
        "processor_id": config.get("processor_id"),
        "backend_url": config.get("backend_url"),
    }
    if config.get("backend_url"):
        try:
            payload["health"] = _backend_health(str(config["backend_url"]))
        except Exception as exc:
            payload["health_error"] = str(exc)
    if payload["connected"]:
        try:
            assignments = _get_assignments(config)
            payload["assignments_count"] = len(assignments)
            payload["assignments"] = [
                {"camera_id": item["camera_id"], "name": item["name"]}
                for item in assignments
            ]
        except Exception as exc:
            payload["assignments_error"] = str(exc)
        try:
            gallery = _get_gallery(config)
            payload["gallery_count"] = len(gallery)
        except Exception as exc:
            payload["gallery_error"] = str(exc)
        try:
            payload["storage"] = _get_storage_config(config)
        except Exception as exc:
            payload["storage_error"] = str(exc)
    if args.json:
        _print_json(payload)
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


def cmd_assignments(args: argparse.Namespace) -> int:
    assignments = _get_assignments(_read_config())
    if args.json:
        _print_json(assignments)
        return 0
    if not assignments:
        print("No assignments.")
        return 0
    for item in assignments:
        print(f"[{item['camera_id']}] {item['name']}")
        print(f"  source: {item.get('stream_url') or item.get('ip_address') or '-'}")
        print(f"  detection_enabled: {item.get('detection_enabled')}")
        print(f"  recording_mode: {item.get('recording_mode')}")
        if item.get("endpoints"):
            print(f"  endpoints: {len(item['endpoints'])}")
    return 0


def cmd_gallery(args: argparse.Namespace) -> int:
    gallery = _get_gallery(_read_config())
    if args.json:
        _print_json(gallery)
        return 0
    if not gallery:
        print("Gallery is empty.")
        return 0
    for item in gallery[: args.limit]:
        print(f"[{item['person_id']}] {item['label']}")
    if len(gallery) > args.limit:
        print(f"... and {len(gallery) - args.limit} more")
    return 0


def cmd_system_info(args: argparse.Namespace) -> int:
    from processor.monitor import get_system_info

    payload = get_system_info()
    if args.json:
        _print_json(payload)
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


def cmd_test_stream(args: argparse.Namespace) -> int:
    config = _read_config()
    source, assignment = _pick_source(config, source=args.source, camera_id=args.camera_id)
    cap = _open_capture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source: {source}")
    frames = []
    try:
        for _ in range(max(args.warmup, 0)):
            cap.grab()
            cap.retrieve()
        started = time.perf_counter()
        first_frame_at = None
        last_frame = None
        for _ in range(max(args.frames, 1)):
            ok, frame = cap.read()
            if not ok or frame is None:
                raise RuntimeError("Failed to read frame from source")
            if first_frame_at is None:
                first_frame_at = time.perf_counter()
            frames.append(time.perf_counter())
            last_frame = frame
        finished = time.perf_counter()
        if args.save_frame and last_frame is not None:
            target = Path(args.save_frame)
            target.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(target), last_frame)
    finally:
        cap.release()

    elapsed = max(finished - started, 1e-6)
    fps = len(frames) / elapsed
    width = int(last_frame.shape[1]) if last_frame is not None else None
    height = int(last_frame.shape[0]) if last_frame is not None else None
    payload = {
        "source": str(source),
        "camera_id": assignment.get("camera_id") if assignment else None,
        "camera_name": assignment.get("name") if assignment else None,
        "frames_read": len(frames),
        "first_frame_seconds": round((first_frame_at - started) if first_frame_at else elapsed, 3),
        "elapsed_seconds": round(elapsed, 3),
        "estimated_fps": round(fps, 2),
        "width": width,
        "height": height,
    }
    if args.json:
        _print_json(payload)
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
        if args.save_frame:
            print(f"saved_frame: {args.save_frame}")
    return 0


def cmd_detect_once(args: argparse.Namespace) -> int:
    config = _read_config()
    source, assignment = _pick_source(config, source=args.source, camera_id=args.camera_id)
    cap = _open_capture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source: {source}")
    try:
        for _ in range(max(args.warmup, 0)):
            cap.grab()
            cap.retrieve()
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to read frame from source")
    finally:
        cap.release()

    from processor.vision import detect_faces, match_embedding

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    detected = detect_faces(rgb)
    gallery = []
    gallery_labels: dict[int, str] = {}
    if args.match_gallery:
        try:
            gallery = _get_gallery(config)
            gallery_labels = {int(item["person_id"]): item["label"] for item in gallery}
        except Exception:
            gallery = []

    results: list[dict[str, Any]] = []
    annotated = frame.copy()
    for item in detected:
        person_id = None
        similarity = None
        label = None
        if gallery:
            person_id, similarity = match_embedding(item["embedding"], gallery)
            if person_id is not None:
                label = gallery_labels.get(int(person_id))
        box = [int(v) for v in item["box"]]
        results.append(
            {
                "box": box,
                "confidence": round(float(item["confidence"]), 4),
                "person_id": person_id,
                "label": label,
                "similarity": round(float(similarity), 4) if similarity is not None else None,
            }
        )
        if args.save_frame:
            color = (0, 255, 0) if person_id is not None else (0, 165, 255)
            cv2.rectangle(annotated, (box[0], box[1]), (box[2], box[3]), color, 2)
            text = label or ("Unknown" if person_id is None else str(person_id))
            cv2.putText(annotated, text, (box[0], max(20, box[1] - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    if args.save_frame:
        target = Path(args.save_frame)
        target.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(target), annotated)

    payload = {
        "source": str(source),
        "camera_id": assignment.get("camera_id") if assignment else None,
        "camera_name": assignment.get("name") if assignment else None,
        "faces_detected": len(results),
        "results": results,
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"faces_detected: {len(results)}")
        for result in results:
            print(result)
        if args.save_frame:
            print(f"saved_frame: {args.save_frame}")
    return 0


def cmd_tail_log(args: argparse.Namespace) -> int:
    path = _log_file()
    if not path.exists():
        print(f"Log file not found: {path}")
        return 1
    lines = _tail_lines(path, args.lines)
    for line in lines:
        print(line.rstrip())
    if not args.follow:
        return 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        while True:
            line = handle.readline()
            if line:
                print(line.rstrip())
                continue
            time.sleep(0.5)


def cmd_run(args: argparse.Namespace) -> int:
    runtime = _load_runtime()
    runtime.run_headless()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CCTV Processor CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config", help="Show or modify local processor config")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    config_show = config_sub.add_parser("show", help="Show local config")
    config_show.add_argument("--json", action="store_true")
    config_show.set_defaults(func=cmd_config_show)

    config_set = config_sub.add_parser("set", help="Update local config values")
    config_set.add_argument("--backend-url")
    config_set.add_argument("--name")
    config_set.add_argument("--max-workers", type=int)
    config_set.add_argument("--motion-threshold", type=float)
    config_set.add_argument("--face-scan-interval", type=float)
    config_set.add_argument("--recording-segment-seconds", type=int)
    config_set.add_argument("--recordings-dir")
    config_set.add_argument("--snapshots-dir")
    config_set.add_argument("--media-port", type=int)
    config_set.add_argument("--media-token")
    config_set.set_defaults(func=cmd_config_set)

    config_reset = config_sub.add_parser("reset", help="Reset local config to defaults")
    config_reset.set_defaults(func=cmd_config_reset)

    connect = subparsers.add_parser("connect", help="Connect processor to backend using a connection code")
    connect.add_argument("--backend-url", required=False)
    connect.add_argument("--code", required=True)
    connect.add_argument("--name")
    connect.add_argument("--max-workers", type=int)
    connect.add_argument("--motion-threshold", type=float)
    connect.add_argument("--face-scan-interval", type=float)
    connect.add_argument("--recording-segment-seconds", type=int)
    connect.add_argument("--recordings-dir")
    connect.add_argument("--snapshots-dir")
    connect.add_argument("--media-port", type=int)
    connect.add_argument("--media-token")
    connect.add_argument("--json", action="store_true")
    connect.set_defaults(func=cmd_connect)

    disconnect = subparsers.add_parser("disconnect", help="Remove saved processor credentials from local config")
    disconnect.set_defaults(func=cmd_disconnect)

    status = subparsers.add_parser("status", help="Show backend reachability and processor status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    assignments = subparsers.add_parser("assignments", help="List current camera assignments")
    assignments.add_argument("--json", action="store_true")
    assignments.set_defaults(func=cmd_assignments)

    gallery = subparsers.add_parser("gallery", help="List active person gallery entries")
    gallery.add_argument("--limit", type=int, default=20)
    gallery.add_argument("--json", action="store_true")
    gallery.set_defaults(func=cmd_gallery)

    system_info = subparsers.add_parser("system-info", help="Show local system information used by processor")
    system_info.add_argument("--json", action="store_true")
    system_info.set_defaults(func=cmd_system_info)

    run = subparsers.add_parser("run", help="Run processor in headless mode")
    run.set_defaults(func=cmd_run)

    test_stream = subparsers.add_parser("test-stream", help="Open a source and measure frame read performance")
    test_stream.add_argument("--source")
    test_stream.add_argument("--camera-id", type=int)
    test_stream.add_argument("--frames", type=int, default=30)
    test_stream.add_argument("--warmup", type=int, default=10)
    test_stream.add_argument("--save-frame")
    test_stream.add_argument("--json", action="store_true")
    test_stream.set_defaults(func=cmd_test_stream)

    detect_once = subparsers.add_parser("detect-once", help="Grab one frame and run face detection/matching")
    detect_once.add_argument("--source")
    detect_once.add_argument("--camera-id", type=int)
    detect_once.add_argument("--warmup", type=int, default=10)
    detect_once.add_argument("--save-frame")
    detect_once.add_argument("--match-gallery", dest="match_gallery", action="store_true", default=True)
    detect_once.add_argument("--no-match-gallery", dest="match_gallery", action="store_false")
    detect_once.add_argument("--json", action="store_true")
    detect_once.set_defaults(func=cmd_detect_once)

    tail_log = subparsers.add_parser("tail-log", help="Print processor log tail")
    tail_log.add_argument("--lines", type=int, default=50)
    tail_log.add_argument("--follow", action="store_true")
    tail_log.set_defaults(func=cmd_tail_log)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
