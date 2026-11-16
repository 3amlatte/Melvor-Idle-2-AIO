"""Task plugin contract.

A task receives a fresh ``TaskContext`` and is called in a loop. Keep each
``step`` short (sub-second to a few seconds) so stop signals stay responsive.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..config import Settings
from ..modes import GameModeProfile
from ..savefile import SaveHeader
from ..window import WindowInfo


@dataclass
class TaskContext:
    settings: Settings
    window: WindowInfo
    logger: logging.Logger
    stop: threading.Event
    # Set while the user has paused the run. Maintenance passes check it
    # between actions so a pause is honoured without killing the process.
    pause: threading.Event | None = None
    dry_run: bool = False
    header: SaveHeader | None = None
    mode: GameModeProfile | None = None
    mode_raw: str = ""
    mode_matched: bool = True
    # UI page the main task needs (e.g. "combat"); maintenance restores it.
    page: str | None = None
    # Per-run choices such as the fishing location and spot. Tasks read only
    # the keys they understand and fall back to safe defaults.
    options: Mapping[str, str] = field(default_factory=dict)

    @property
    def min_hp_ratio(self) -> float:
        """Mode-aware HP floor that tasks should respect."""
        return self.mode.min_hp_ratio if self.mode else 0.75


class Task:
    name = "base"
    description = "Base task"
    # None = compatible with every mode. Otherwise a set of profile keys.
    supported_modes: frozenset[str] | None = None
    # Risky tasks are refused on modes that do not allow them (e.g. hardcore).
    risky = False
    # UI page the task reads (see ui.PAGE_TARGETS). Maintenance restores it.
    page: str | None = None
    # Whether the task replaces the character's active action. Used by the
    # previous-action restore; observe-only tasks leave it alone.
    changes_action = True
    # Completed units this run (Slayer tasks). Other tasks leave this at zero.
    completed_tasks = 0

    def start(self, ctx: TaskContext) -> None:
        """Called once before the loop."""

    def step(self, ctx: TaskContext) -> float | None:
        """Perform one unit of work. Return seconds to sleep, or None."""
        return None

    def on_save(self, ctx: TaskContext, header: SaveHeader) -> None:
        """Called when a newly decoded save differs from the previous one."""

    def stop(self, ctx: TaskContext) -> None:
        """Called once after the loop, including on errors."""
