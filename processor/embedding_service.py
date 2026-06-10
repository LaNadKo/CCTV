"""Low-priority embedding extraction isolated from the live CUDA runtime."""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass

import cv2
import numpy as np

from cctv_ai.face_onnx import BackgroundFaceExtractor
from processor.inference_scheduler import gpu_inference_gate
from processor.performance import PerformanceMetrics


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EmbeddingTask:
    image: np.ndarray
    result: Future[list[dict]]


class EmbeddingService:
    """Serialize CPU embedding work on a below-normal worker thread."""

    def __init__(self, *, queue_size: int = 2) -> None:
        self._queue: queue.Queue[_EmbeddingTask | None] = queue.Queue(
            maxsize=max(1, queue_size)
        )
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._extractor: BackgroundFaceExtractor | None = None
        self._startup_error: BaseException | None = None
        self._metrics = PerformanceMetrics("embedding", logger=log)

    def start(self) -> None:
        if not (self._thread and self._thread.is_alive()):
            self._stop.clear()
            self._ready.clear()
            self._startup_error = None
            self._thread = threading.Thread(
                target=self._worker,
                name="embedding-cpu-worker",
                daemon=True,
            )
            self._thread.start()
        if not self._ready.wait(timeout=30.0):
            raise RuntimeError("Embedding runtime initialization timed out")
        if self._startup_error is not None:
            raise RuntimeError("Embedding runtime initialization failed") from self._startup_error

    def stop(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self._ready.clear()

    def extract(self, image: np.ndarray, *, timeout: float = 90.0) -> list[dict]:
        self.start()
        future: Future[list[dict]] = Future()
        task = _EmbeddingTask(image=image.copy(), result=future)
        try:
            self._queue.put(task, timeout=1.0)
        except queue.Full as exc:
            raise RuntimeError("Embedding queue is busy") from exc
        return future.result(timeout=timeout)

    def _worker(self) -> None:
        self._set_low_thread_priority()
        try:
            with self._metrics.measure("runtime_init"):
                self._extractor = BackgroundFaceExtractor(cpu_threads=1)
            log.info(
                "Background embedding runtime initialized on %s",
                self._extractor.device_name,
            )
        except BaseException as exc:
            self._startup_error = exc
            log.exception("Background embedding runtime initialization failed")
        finally:
            self._ready.set()
        if self._startup_error is not None:
            return

        while not self._stop.is_set():
            try:
                task = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if task is None:
                    break
                if task.result.cancelled():
                    continue
                if self._extractor is None:
                    raise RuntimeError("Embedding runtime is unavailable")
                with self._metrics.measure("decode_and_inference"):
                    with gpu_inference_gate.background():
                        faces = self._extractor.detect_faces(
                            cv2.cvtColor(task.image, cv2.COLOR_BGR2RGB),
                            build_variants=True,
                            max_num=3,
                        )
                task.result.set_result(faces)
            except Exception as exc:
                if task is not None and not task.result.done():
                    task.result.set_exception(exc)
                log.exception("Background embedding extraction failed")
            finally:
                self._queue.task_done()

    @staticmethod
    def _set_low_thread_priority() -> None:
        if os.name != "nt":
            return
        try:
            thread_handle = ctypes.windll.kernel32.GetCurrentThread()
            ctypes.windll.kernel32.SetThreadPriority(thread_handle, -1)
        except Exception:
            log.debug("Unable to lower embedding worker priority", exc_info=True)

