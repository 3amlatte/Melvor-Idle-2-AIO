"""Run controller: one background bot run with pause/stop/status listeners.

The CLI can keep calling :func:`mi2_aio.runner.run` directly. The desktop app
uses this controller so it never blocks the Qt event loop and can observe a
structured status stream.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from . import status as st
from .config import Settings
from .instance import SingleInstance
from .status import RunStatus

StatusListener = Callable[[RunStatus], None]


class AlreadyRunning(RuntimeError):
    """Raised when a second run is requested while one is active."""


@dataclass
class RunHandle:
    """Cooperative control flags passed into the runner."""

    stop_event: threading.Event = field(default_factory=threading.Event)
    pause_event: threading.Event = field(default_factory=threading.Event)
    # Set by a manual "Farm Run" while a run is active. The runner services it
    # between task steps, then continues the same task.
    farm_event: threading.Event = field(default_factory=threading.Event)

    @property
    def paused(self) -> bool:
        return self.pause_event.is_set()

    def request_stop(self) -> None:
        self.pause_event.clear()
        self.stop_event.set()

    def pause(self) -> None:
        self.pause_event.set()

    def resume(self) -> None:
        self.pause_event.clear()

    def request_farming(self) -> None:
        self.farm_event.set()


@dataclass(frozen=True)
class RunRequest:
    settings: Settings
    task_name: str
    duration_minutes: float | None = None
    dry_run: bool = False
    max_tasks: int | None = None
    # Task-specific choices (fishing location/spot). Immutable so the request
    # can be shared with the run thread without further locking.
    options: Mapping[str, str] = field(default_factory=dict)


class RunController:
    """Owns at most one bot run thread.

    Status listeners are called from the run thread. Qt consumers must bounce
    them onto the GUI thread through a signal (see ``mi2_aio.app``).
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        *,
        bot_lock_name: str = "MI2_AIO_Bot",
    ) -> None:
        self._logger = logger
        self._lock = threading.RLock()
        self._listeners: list[StatusListener] = []
        self._status = RunStatus()
        self._handle: RunHandle | None = None
        self._thread: threading.Thread | None = None
        self._request: RunRequest | None = None
        self._last_error: str | None = None
        self._bot_lock = SingleInstance(bot_lock_name)

    # -- observation -----------------------------------------------------
    @property
    def status(self) -> RunStatus:
        with self._lock:
            return self._status

    @property
    def active(self) -> bool:
        with self._lock:
            thread = self._thread
            return thread is not None and thread.is_alive()

    def subscribe(self, listener: StatusListener) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def unsubscribe(self, listener: StatusListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def publish(self, status: RunStatus) -> None:
        with self._lock:
            self._status = status
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(status)
            except Exception:  # a broken UI listener must not kill the run
                if self._logger is not None:
                    self._logger.exception("Status listener failed")

    # -- lifecycle -------------------------------------------------------
    def start(self, request: RunRequest) -> RunStatus:
        with self._lock:
            if self.active:
                raise AlreadyRunning("A bot run is already active.")
            if not self._bot_lock.acquire():
                raise AlreadyRunning(
                    "Another MI2 AIO bot run is already active."
                )
            handle = RunHandle()
            self._handle = handle
            self._request = request
            self._last_error = None
            started = RunStatus(
                state=st.STARTING,
                task=request.task_name,
                started_at=datetime.now(),
                dry_run=request.dry_run,
                message="Starting",
            )
            self._status = started
            thread = threading.Thread(
                target=self._run,
                args=(request, handle),
                name="mi2-aio-run",
                daemon=True,
            )
            self._thread = thread
        self.publish(started)
        thread.start()
        return started

    def _run(self, request: RunRequest, handle: RunHandle) -> None:
        from .runner import run

        try:
            exit_code = run(
                task_name=request.task_name,
                settings=request.settings,
                duration_minutes=request.duration_minutes,
                dry_run=request.dry_run,
                max_tasks=request.max_tasks,
                options=request.options,
                control=handle,
                on_status=self.publish,
                logger=self._logger,
                configure_logging=self._logger is None,
            )
        except Exception as exc:
            self._last_error = str(exc)
            if self._logger is not None:
                self._logger.exception("Bot run crashed")
            self.publish(
                self.status.with_state(
                    st.FAILED,
                    last_error=str(exc),
                    message="Run crashed",
                )
            )
            self._bot_lock.release()
            return

        current = self.status
        if current.state not in {st.STOPPED, st.FAILED}:
            state = st.STOPPED if exit_code == 0 else st.FAILED
            self.publish(
                current.with_state(
                    state,
                    exit_code=exit_code,
                    message=(
                        "Stopped"
                        if exit_code == 0
                        else f"Stopped with exit code {exit_code}"
                    ),
                    last_error=(
                        None if exit_code == 0 else current.last_error
                    ),
                )
            )
        else:
            self.publish(
                current.with_state(
                    current.state,
                    exit_code=exit_code,
                    last_error=self._last_error,
                )
            )
        self._bot_lock.release()

    # -- controls --------------------------------------------------------
    def request_stop(self) -> bool:
        with self._lock:
            handle = self._handle
            if handle is None or not self.active:
                return False
            handle.request_stop()
            self._status = self._status.with_state(
                st.STOPPING, message="Stopping"
            )
            status = self._status
        self.publish(status)
        return True

    def pause(self) -> bool:
        with self._lock:
            handle = self._handle
            if handle is None or not self.active:
                return False
            handle.pause()
            self._status = self._status.with_state(
                st.PAUSED, message="Pausing"
            )
            status = self._status
        self.publish(status)
        return True

    def request_farming(self) -> bool:
        """Queue a manual farming pass for the active run."""
        with self._lock:
            handle = self._handle
            if handle is None or not self.active:
                return False
            handle.request_farming()
            return True

    def resume(self) -> bool:
        with self._lock:
            handle = self._handle
            if handle is None or not self.active:
                return False
            handle.resume()
            self._status = self._status.with_state(
                st.RUNNING, message="Running"
            )
            status = self._status
        self.publish(status)
        return True

    def wait(self, timeout: float | None = None) -> bool:
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()
