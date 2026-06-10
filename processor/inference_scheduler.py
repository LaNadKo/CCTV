"""Priority gate for shared GPU inference models."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class PriorityInferenceGate:
    """Prefer live inference over background embedding extraction."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = False
        self._waiting_live = 0

    @contextmanager
    def live(self) -> Iterator[None]:
        with self._condition:
            self._waiting_live += 1
            try:
                while self._active:
                    self._condition.wait()
                self._active = True
            finally:
                self._waiting_live -= 1
        try:
            yield
        finally:
            with self._condition:
                self._active = False
                self._condition.notify_all()

    @contextmanager
    def background(self) -> Iterator[None]:
        with self._condition:
            while self._active or self._waiting_live:
                self._condition.wait()
            self._active = True
        try:
            yield
        finally:
            with self._condition:
                self._active = False
                self._condition.notify_all()


gpu_inference_gate = PriorityInferenceGate()

