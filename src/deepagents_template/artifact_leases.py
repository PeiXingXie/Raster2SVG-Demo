"""Process-local exclusive leases for mutable artifact directories."""

from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import BinaryIO


@dataclass(frozen=True)
class ArtifactLease:
    artifact_key: str
    owner_id: str
    operation: str
    acquired_at: datetime
    lock_path: str
    lock_handle: BinaryIO


def _try_lock_file(lock_path: Path) -> BinaryIO | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except (BlockingIOError, OSError):
        handle.close()
        return None


def _unlock_file(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class ArtifactLeaseRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._leases: dict[str, ArtifactLease] = {}

    @staticmethod
    def normalize(artifact_dir: str | Path) -> str:
        return str(Path(artifact_dir).expanduser().resolve())

    def try_acquire(
        self,
        artifact_dir: str | Path,
        *,
        owner_id: str,
        operation: str,
    ) -> ArtifactLease | None:
        key = self.normalize(artifact_dir)
        with self._lock:
            if key in self._leases:
                return None
            lock_name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".lock"
            lock_path = Path(key).parent / ".shape-studio-locks" / lock_name
            lock_handle = _try_lock_file(lock_path)
            if lock_handle is None:
                return None
            lease = ArtifactLease(
                artifact_key=key,
                owner_id=owner_id,
                operation=operation,
                acquired_at=datetime.now(UTC),
                lock_path=str(lock_path),
                lock_handle=lock_handle,
            )
            self._leases[key] = lease
            return lease

    def release(self, lease: ArtifactLease | None) -> None:
        if lease is None:
            return
        with self._lock:
            current = self._leases.get(lease.artifact_key)
            if current == lease:
                self._leases.pop(lease.artifact_key, None)
                _unlock_file(lease.lock_handle)

    def get(self, artifact_dir: str | Path) -> ArtifactLease | None:
        key = self.normalize(artifact_dir)
        with self._lock:
            return self._leases.get(key)

    def clear(self) -> None:
        with self._lock:
            for lease in self._leases.values():
                _unlock_file(lease.lock_handle)
            self._leases.clear()


artifact_leases = ArtifactLeaseRegistry()
