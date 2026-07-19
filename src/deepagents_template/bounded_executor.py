"""Thread-pool wrapper with a bounded outstanding-work capacity."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore
from typing import Callable


class QueueFullError(RuntimeError):
    pass


class BoundedExecutor:
    def __init__(self, *, max_workers: int, max_queued: int, thread_name_prefix: str) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._capacity = BoundedSemaphore(max_workers + max_queued)

    def submit(self, fn: Callable, /, *args, **kwargs) -> Future:
        if not self._capacity.acquire(blocking=False):
            raise QueueFullError("The conversion queue is full.")
        try:
            future = self._executor.submit(fn, *args, **kwargs)
        except Exception:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _: self._capacity.release())
        return future

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
