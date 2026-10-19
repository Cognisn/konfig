"""Cross-process advisory file locking for the encrypted file backend.

A sidecar lock file (never deleted) is locked rather than the data file
itself, because the data file's inode is replaced on every atomic save.

* POSIX: ``fcntl.lockf`` record locks, shared for reads and exclusive for
  writes. Record locks (not ``flock``) are what NFS, including Amazon EFS,
  honours.
* Windows: ``msvcrt.locking`` on byte 0. It has no shared mode, so reads
  and writes both take an exclusive lock.

POSIX record locks belong to the process, not the thread, and closing any
descriptor for the file releases every lock the process holds on it. To
cope, each lock path has one process-wide ``threading.RLock`` that is held
for the whole of each locked operation, so only one thread at a time owns
the operating-system lock for a given path.
"""

from __future__ import annotations

import errno
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TIMEOUT = 30.0

_INITIAL_BACKOFF = 0.01
_MAX_BACKOFF = 0.25

# errno values meaning "someone else holds the lock" rather than a real failure.
_CONTENDED = {
    errno.EAGAIN,
    errno.EACCES,
    getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
    getattr(errno, "EDEADLK", errno.EAGAIN),
    getattr(errno, "EDEADLOCK", errno.EAGAIN),
}


class _PathState:
    """Per-process state for one lock path, shared by all FileLock instances."""

    def __init__(self) -> None:
        self.rlock = threading.RLock()
        self.depth = 0
        self.exclusive = False


_registry_guard = threading.Lock()
_registry: dict[str, _PathState] = {}


def _state_for(path: Path) -> _PathState:
    key = os.path.normcase(os.path.realpath(path))
    with _registry_guard:
        state = _registry.get(key)
        if state is None:
            state = _PathState()
            _registry[key] = state
        return state


if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int, exclusive: bool) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int, exclusive: bool) -> None:
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.lockf(fd, mode | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.lockf(fd, fcntl.LOCK_UN)


class FileLock:
    """Bounded-wait advisory lock on a sidecar lock file.

    Args:
        lock_path: The lock file. Created owner-only (0600) if missing and
            never deleted.
        timeout: Seconds to wait for the lock before raising ``TimeoutError``.
        label: Path named in timeout errors (normally the data file).
    """

    def __init__(
        self,
        lock_path: Path,
        timeout: float = DEFAULT_LOCK_TIMEOUT,
        label: Path | None = None,
    ) -> None:
        self._path = Path(lock_path)
        self._timeout = timeout
        self._label = label if label is not None else self._path
        self._state = _state_for(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def shared(self) -> AbstractContextManager[None]:
        """Hold a shared (read) lock; exclusive on Windows."""
        return self._acquire(exclusive=False)

    def exclusive(self) -> AbstractContextManager[None]:
        """Hold an exclusive (write) lock."""
        return self._acquire(exclusive=True)

    @contextmanager
    def thread_guard(self) -> Iterator[None]:
        """Exclude other threads in this process without taking the OS lock.

        Locks taken inside the guard by the same thread nest normally.
        """
        if not self._state.rlock.acquire(timeout=max(self._timeout, 0)):
            raise self._timeout_error()
        try:
            yield
        finally:
            self._state.rlock.release()

    def _timeout_error(self) -> TimeoutError:
        return TimeoutError(
            f"Timed out after {self._timeout:g}s waiting for the lock on "
            f"secrets file {self._label}"
        )

    @contextmanager
    def _acquire(self, exclusive: bool) -> Iterator[None]:
        deadline = time.monotonic() + self._timeout
        state = self._state
        if not state.rlock.acquire(timeout=max(self._timeout, 0)):
            raise self._timeout_error()
        try:
            if state.depth:
                # This thread already holds the OS lock for this path.
                if exclusive and not state.exclusive:
                    raise RuntimeError(
                        f"Cannot upgrade a shared lock to exclusive on {self._label}"
                    )
                state.depth += 1
                try:
                    yield
                finally:
                    state.depth -= 1
                return

            fd = self._open(exclusive)
            if fd is None:
                # Read-only location with no lock file: proceed unlocked.
                yield
                return
            try:
                self._lock_fd(fd, exclusive or sys.platform == "win32", deadline)
                state.depth = 1
                state.exclusive = exclusive or sys.platform == "win32"
                try:
                    yield
                finally:
                    state.depth = 0
                    state.exclusive = False
                    _unlock(fd)
            finally:
                os.close(fd)
        finally:
            state.rlock.release()

    def _open(self, exclusive: bool) -> int | None:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            return os.open(self._path, flags, 0o600)
        except OSError as exc:
            if exclusive or sys.platform == "win32":
                raise
            if exc.errno not in (errno.EACCES, errno.EPERM, errno.EROFS):
                raise
        # A reader on a read-only mount: a read lock needs only read access.
        try:
            return os.open(self._path, os.O_RDONLY)
        except FileNotFoundError:
            logger.debug(
                "Lock file %s cannot be created (read-only location); "
                "reading without a lock",
                self._path,
            )
            return None

    def _lock_fd(self, fd: int, exclusive: bool, deadline: float) -> None:
        delay = _INITIAL_BACKOFF
        while True:
            try:
                _try_lock(fd, exclusive)
                return
            except OSError as exc:
                if exc.errno not in _CONTENDED:
                    raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._timeout_error()
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, _MAX_BACKOFF)
