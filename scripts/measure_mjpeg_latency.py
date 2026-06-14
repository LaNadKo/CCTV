"""Measure MJPEG stream startup and frame cadence.

Example:
  py -3.11 scripts/measure_mjpeg_latency.py ^
    --url live=http://127.0.0.1:8001/cameras/1/stream?annotate=false ^
    --url overlay=http://127.0.0.1:8001/cameras/1/stream?annotate=true ^
    --header "Authorization: Bearer TOKEN"
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from dataclasses import dataclass
from typing import Iterable


SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


@dataclass
class FrameSample:
    received_at: float
    received_wall: float
    sent_at: float | None
    size: int


def parse_headers(values: Iterable[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for value in values:
        name, sep, raw = value.partition(":")
        if not sep:
            raise SystemExit(f"Invalid header, expected 'Name: value': {value}")
        headers[name.strip()] = raw.strip()
    return headers


def split_label_url(value: str) -> tuple[str, str]:
    label, sep, url = value.partition("=")
    if sep and label and url:
        return label, url
    return value, value


def find_frame(buffer: bytearray) -> tuple[bytes, float | None] | None:
    start = buffer.find(SOI)
    if start < 0:
        if len(buffer) > 4096:
            del buffer[:-1024]
        return None

    end = buffer.find(EOI, start + 2)
    if end < 0:
        if start > 0:
            del buffer[:start]
        return None

    frame_end = end + 2
    header_blob = bytes(buffer[:start])
    frame = bytes(buffer[start:frame_end])
    del buffer[:frame_end]
    return frame, parse_sent_at(header_blob)


def parse_sent_at(header_blob: bytes) -> float | None:
    marker = b"x-cctv-sent-at:"
    lower = header_blob.lower()
    index = lower.rfind(marker)
    if index < 0:
        return None
    line = header_blob[index:].splitlines()[0]
    _, _, raw = line.partition(b":")
    try:
        return float(raw.strip())
    except ValueError:
        return None


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percent)))
    return ordered[index]


def measure(url: str, headers: dict[str, str], seconds: float, max_frames: int) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "multipart/x-mixed-replace,image/jpeg,*/*",
            **headers,
        },
    )
    started = time.perf_counter()
    samples: list[FrameSample] = []
    buffer = bytearray()

    with urllib.request.urlopen(request, timeout=10) as response:
        first_byte_at: float | None = None
        while time.perf_counter() - started < seconds and len(samples) < max_frames:
            chunk = response.read(16384)
            if not chunk:
                break
            if first_byte_at is None:
                first_byte_at = time.perf_counter()
            buffer.extend(chunk)
            while len(samples) < max_frames:
                extracted = find_frame(buffer)
                if extracted is None:
                    break
                frame, sent_at = extracted
                samples.append(
                    FrameSample(time.perf_counter(), time.time(), sent_at, len(frame))
                )

    first_frame_ms = (
        (samples[0].received_at - started) * 1000.0 if samples else None
    )
    intervals = [
        (right.received_at - left.received_at) * 1000.0
        for left, right in zip(samples, samples[1:])
    ]
    transit_lags = [
        (sample.received_wall - sample.sent_at) * 1000.0
        for sample in samples
        if sample.sent_at is not None
    ]
    elapsed = (
        samples[-1].received_at - samples[0].received_at
        if len(samples) > 1
        else 0.0
    )
    fps = (len(samples) - 1) / elapsed if elapsed > 0 else 0.0

    return {
        "url": url,
        "frames": len(samples),
        "fps": round(fps, 2),
        "first_frame_ms": round(first_frame_ms, 1) if first_frame_ms is not None else None,
        "interval_ms_p50": round(statistics.median(intervals), 1) if intervals else None,
        "interval_ms_p95": round(percentile(intervals, 0.95), 1) if intervals else None,
        "interval_ms_max": round(max(intervals), 1) if intervals else None,
        "gaps_over_250ms": sum(1 for value in intervals if value > 250.0),
        "gaps_over_300ms": sum(1 for value in intervals if value > 300.0),
        "transit_lag_ms_p50": round(statistics.median(transit_lags), 1) if transit_lags else None,
        "transit_lag_ms_p95": round(percentile(transit_lags, 0.95), 1) if transit_lags else None,
        "avg_frame_kb": round(
            statistics.mean(sample.size for sample in samples) / 1024.0,
            1,
        )
        if samples
        else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", action="append", required=True, help="URL or label=URL")
    parser.add_argument("--header", action="append", default=[], help="Extra HTTP header")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--max-frames", type=int, default=240)
    args = parser.parse_args()

    headers = parse_headers(args.header)
    results = {
        label: measure(url, headers, args.seconds, args.max_frames)
        for label, url in map(split_label_url, args.url)
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
