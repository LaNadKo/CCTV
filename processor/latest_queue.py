"""Bounded queue helpers used by real-time Processor pipelines."""
from __future__ import annotations

import queue
from typing import TypeVar

T = TypeVar("T")


def put_latest(target: queue.Queue[T], item: T) -> None:
    """Insert an item, replacing the oldest queued item when the queue is full."""
    try:
        target.put_nowait(item)
        return
    except queue.Full:
        pass
    try:
        target.get_nowait()
        target.task_done()
    except queue.Empty:
        pass
    try:
        target.put_nowait(item)
    except queue.Full:
        pass


def drain(target: queue.Queue[T]) -> None:
    while True:
        try:
            target.get_nowait()
            target.task_done()
        except queue.Empty:
            return

