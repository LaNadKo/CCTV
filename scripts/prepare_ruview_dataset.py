from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL row") from exc


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _rows_in_window(path: Path, start_at: datetime, stop_at: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _iter_jsonl(path) or []:
        ts = _parse_ts(row.get("ts"))
        if ts is None:
            continue
        if start_at <= ts < stop_at:
            rows.append(row)
    return rows


def _dataset_stats(csi_rows: list[dict[str, Any]], camera_rows: list[dict[str, Any]]) -> dict[str, Any]:
    node_counts: Counter[str] = Counter()
    rssi_values: dict[str, list[float]] = {}
    for row in csi_rows:
        node_id = str(row.get("node_id") or "unknown")
        node_counts[node_id] += 1
        try:
            rssi_values.setdefault(node_id, []).append(float(row["rssi"]))
        except (KeyError, TypeError, ValueError):
            pass

    track_histogram: Counter[str] = Counter()
    samples_with_tracks = 0
    samples_with_keypoints = 0
    max_tracks = 0
    max_keypoints = 0
    recognized_track_rows = 0
    unknown_track_rows = 0
    keypoint_conf_values: list[float] = []

    for row in camera_rows:
        tracks = row.get("tracks") or []
        if not isinstance(tracks, list):
            tracks = []
        track_count = len(tracks)
        track_histogram[str(track_count)] += 1
        max_tracks = max(max_tracks, track_count)
        if track_count:
            samples_with_tracks += 1
        row_has_keypoints = False
        for track in tracks:
            if not isinstance(track, dict):
                continue
            if track.get("recognized"):
                recognized_track_rows += 1
            else:
                unknown_track_rows += 1
            keypoints = track.get("keypoints") or []
            if isinstance(keypoints, list) and keypoints:
                row_has_keypoints = True
                max_keypoints = max(max_keypoints, len(keypoints))
            for confidence in track.get("keypoint_conf") or []:
                try:
                    keypoint_conf_values.append(float(confidence))
                except (TypeError, ValueError):
                    pass
        if row_has_keypoints:
            samples_with_keypoints += 1

    node_avg_rssi = {
        node_id: round(sum(values) / len(values), 1)
        for node_id, values in sorted(rssi_values.items())
        if values
    }
    avg_keypoint_conf = (
        round(sum(keypoint_conf_values) / len(keypoint_conf_values), 3)
        if keypoint_conf_values
        else None
    )
    return {
        "csi_samples": len(csi_rows),
        "camera_samples": len(camera_rows),
        "samples_with_tracks": samples_with_tracks,
        "samples_with_keypoints": samples_with_keypoints,
        "max_tracks": max_tracks,
        "max_keypoints": max_keypoints,
        "recognized_track_rows": recognized_track_rows,
        "unknown_track_rows": unknown_track_rows,
        "node_counts": dict(sorted(node_counts.items())),
        "node_avg_rssi": node_avg_rssi,
        "camera_track_count_histogram": dict(sorted(track_histogram.items())),
        "avg_keypoint_conf": avg_keypoint_conf,
        "keypoint_conf_samples": len(keypoint_conf_values),
    }


def prepare_dataset(
    source: Path,
    output: Path,
    first_seconds: float | None = None,
    start_offset_seconds: float = 0.0,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    manifest_path = source / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {source}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    start_at = _parse_ts(manifest.get("started_at"))
    if start_at is None:
        raise ValueError("manifest.started_at is required")
    if first_seconds is not None:
        start_offset_seconds = 0.0
        duration_seconds = first_seconds
    if duration_seconds is None:
        duration_seconds = float(manifest.get("duration_seconds") or 0.0) - start_offset_seconds
    if duration_seconds <= 0:
        raise ValueError("duration must be positive")
    source_start_at = start_at
    start_at = source_start_at + timedelta(seconds=start_offset_seconds)
    stop_at = start_at + timedelta(seconds=duration_seconds)

    output.mkdir(parents=True, exist_ok=True)
    csi_rows = _rows_in_window(source / "csi.jsonl", start_at, stop_at)
    camera_rows = _rows_in_window(source / "camera.jsonl", start_at, stop_at)
    _write_jsonl(output / "csi.jsonl", csi_rows)
    _write_jsonl(output / "camera.jsonl", camera_rows)

    stats = _dataset_stats(csi_rows, camera_rows)
    out_manifest = dict(manifest)
    out_manifest.update(
        {
            "active": False,
            "source_session_id": manifest.get("session_id"),
            "session_id": output.name,
            "label": f"{manifest.get('label') or output.name}-offset-{int(start_offset_seconds)}s-duration-{int(duration_seconds)}s",
            "scenario": f"{manifest.get('scenario') or 'ruview-calibration'}-trimmed",
            "notes": (
                f"Trimmed offset {start_offset_seconds:g}s duration {duration_seconds:g}s "
                f"from {manifest.get('session_id') or source.name}. "
                f"Source notes: {manifest.get('notes') or ''}"
            ).strip(),
            "directory": str(output).replace("\\", "/"),
            "started_at": start_at.isoformat(),
            "stopped_at": stop_at.isoformat(),
            "duration_seconds": round(duration_seconds, 3),
            "csi_samples": stats["csi_samples"],
            "camera_samples": stats["camera_samples"],
            "latest_tracks": 0,
        }
    )
    (output / "manifest.json").write_text(
        json.dumps(out_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"output": str(output), "manifest": out_manifest, "stats": stats}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a trimmed RuView calibration dataset.")
    parser.add_argument("source", type=Path, help="Source calibration session directory")
    parser.add_argument("--first-seconds", type=float, default=None, help="Keep only first N seconds")
    parser.add_argument("--start-offset-seconds", type=float, default=0.0, help="Start offset from session start")
    parser.add_argument("--duration-seconds", type=float, help="Trim duration")
    parser.add_argument("--output", type=Path, help="Output dataset directory")
    args = parser.parse_args()

    source = args.source
    output = args.output
    if output is None:
        effective_duration = args.first_seconds if args.first_seconds is not None else args.duration_seconds
        if effective_duration is None:
            suffix = f"offset-{int(args.start_offset_seconds)}s"
        elif args.start_offset_seconds == 0 and args.first_seconds is not None:
            suffix = f"first-{int(effective_duration // 60)}min" if effective_duration % 60 == 0 else f"first-{int(effective_duration)}s"
        else:
            suffix = f"offset-{int(args.start_offset_seconds)}s-duration-{int(effective_duration)}s"
        output = source.with_name(f"{source.name}-{suffix}")
    result = prepare_dataset(
        source,
        output,
        first_seconds=args.first_seconds,
        start_offset_seconds=args.start_offset_seconds,
        duration_seconds=args.duration_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
