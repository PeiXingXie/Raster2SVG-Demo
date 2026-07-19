"""Atomic file replacement helpers for concurrently observed artifacts."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


_WINDOWS_RETRY_TIMEOUT_SECONDS = 5.0


def _retry_delay(attempt: int) -> float:
    return min(0.01 * (2 ** min(attempt, 4)), 0.16)


def atomic_write_bytes(path: str | Path, content: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        deadline = time.monotonic() + _WINDOWS_RETRY_TIMEOUT_SECONDS
        attempt = 0
        while True:
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if os.name != "nt" or time.monotonic() >= deadline:
                    raise
                time.sleep(_retry_delay(attempt))
                attempt += 1
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(path: str | Path, content: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, content.encode(encoding))


def read_text_with_retry(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    errors: str | None = None,
) -> str:
    target = Path(path)
    deadline = time.monotonic() + _WINDOWS_RETRY_TIMEOUT_SECONDS
    attempt = 0
    while True:
        try:
            return target.read_text(encoding=encoding, errors=errors)
        except PermissionError:
            if os.name != "nt" or time.monotonic() >= deadline:
                raise
            time.sleep(_retry_delay(attempt))
            attempt += 1
