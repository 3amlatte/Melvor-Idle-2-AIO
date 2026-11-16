"""Single-instance guard.

Two bots clicking the same game window would fight each other. The desktop app
takes an application lock, and every bot run takes a separate bot lock, so a
CLI run is refused while the app is running a task (and vice versa).

Windows uses a named mutex; other platforms fall back to an exclusive lock file
in the user data directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO

from .paths import USER_DATA_DIR

ERROR_ALREADY_EXISTS = 183


class InstanceError(RuntimeError):
    """Raised when the lock cannot be created."""


class SingleInstance:
    def __init__(self, name: str, *, directory: Path | None = None) -> None:
        self.name = name
        self.directory = directory or USER_DATA_DIR
        self._handle = None
        self._file: IO[str] | None = None

    @property
    def acquired(self) -> bool:
        return self._handle is not None or self._file is not None

    def acquire(self) -> bool:
        """Return True when this process now owns the lock."""
        if self.acquired:
            return True
        if os.name == "nt":
            return self._acquire_windows()
        return self._acquire_file()

    def release(self) -> None:
        if self._handle is not None:
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    # -- Windows named mutex --------------------------------------------
    def _acquire_windows(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise InstanceError("Could not create the application mutex.")
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    # -- POSIX lock file -------------------------------------------------
    def _acquire_file(self) -> bool:
        import fcntl

        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{self.name}.lock"
        handle = path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._file = handle
        return True
