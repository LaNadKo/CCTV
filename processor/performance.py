"""Lightweight rolling performance metrics for Processor pipelines."""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class MetricSummary:
    count: int
    average_ms: float
    p95_ms: float
    maximum_ms: float


class PerformanceMetrics:
    """Collect bounded timing samples without blocking the video pipeline."""

    def __init__(
        self,
        namespace: str,
        *,
        logger: logging.Logger | None = None,
        sample_limit: int = 240,
        log_interval: float = 30.0,
    ) -> None:
        self.namespace = namespace
        self._logger = logger or logging.getLogger(__name__)
        self._samples: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=sample_limit)
        )
        self._lock = threading.Lock()
        self._last_log = time.monotonic()
        self._log_interval = max(5.0, float(log_interval))

    def observe(self, name: str, elapsed_seconds: float) -> None:
        elapsed_ms = max(0.0, float(elapsed_seconds) * 1000.0)
        should_log = False
        with self._lock:
            self._samples[name].append(elapsed_ms)
            now = time.monotonic()
            if now - self._last_log >= self._log_interval:
                self._last_log = now
                should_log = True
        if should_log:
            self.log_summary()

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - started)

    def snapshot(self) -> dict[str, MetricSummary]:
        with self._lock:
            samples = {name: list(values) for name, values in self._samples.items()}
        return {
            name: self._summarize(values)
            for name, values in samples.items()
            if values
        }

    def slowest(self) -> tuple[str, MetricSummary] | None:
        summaries = self.snapshot()
        if not summaries:
            return None
        return max(
            summaries.items(),
            key=lambda item: (item[1].p95_ms, item[1].maximum_ms),
        )

    def bottleneck_text(self) -> str:
        slowest = self.slowest()
        if slowest is None:
            return "нет данных"
        name, summary = slowest
        return f"{name}: p95 {summary.p95_ms:.0f} мс, max {summary.maximum_ms:.0f} мс"

    def log_summary(self) -> None:
        summaries = self.snapshot()
        if not summaries:
            return
        payload = " ".join(
            (
                f"{name}=avg:{summary.average_ms:.1f}/"
                f"p95:{summary.p95_ms:.1f}/max:{summary.maximum_ms:.1f}ms"
            )
            for name, summary in sorted(summaries.items())
        )
        self._logger.info("Performance %s %s", self.namespace, payload)

    @staticmethod
    def _summarize(values: list[float]) -> MetricSummary:
        ordered = sorted(values)
        p95_index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
        return MetricSummary(
            count=len(ordered),
            average_ms=sum(ordered) / len(ordered),
            p95_ms=ordered[p95_index],
            maximum_ms=ordered[-1],
        )
