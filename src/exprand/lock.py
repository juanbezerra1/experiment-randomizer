"""An advisory file lock that the operating system releases if the process dies.

Two people (or a window and a terminal) drawing a session at the same moment must not both read
"the last session is 7" and both write session 8. The critical section is therefore wrapped in an
exclusive lock on a small side file. The lock is taken with ``flock`` on POSIX and
``msvcrt.locking`` on Windows, so a crash or a power cut cannot leave a stale lock behind: the
operating system drops it with the process.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import TracebackType

__all__ = ["FileLock", "LockTimeout"]


class LockTimeout(TimeoutError):
    """The lock stayed taken for the whole waiting time."""


if sys.platform == "win32":  # pragma: no cover - exercised by the Windows CI job
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class FileLock:
    """``with FileLock(path): ...`` holds an exclusive lock on ``path`` (created if missing)."""

    def __init__(self, path: str | Path, timeout: float = 10.0, poll: float = 0.02) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.poll = poll
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            raise RuntimeError("this lock object is already held")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + self.timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                os.close(fd)
                raise LockTimeout(
                    f"could not lock {self.path} within {self.timeout:g} s; "
                    "is another copy of the program drawing a session?"
                )
            time.sleep(self.poll)
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            _unlock(self._fd)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
