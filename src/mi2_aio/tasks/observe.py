"""Safe default task: watch the save header and log meaningful changes."""

from __future__ import annotations

import time

from ..savefile import SaveHeader
from .base import Task, TaskContext


class ObserveTask(Task):
    name = "observe"
    description = "Watch the save header and log changes. Sends no input."
    changes_action = False

    def __init__(self) -> None:
        self._previous: SaveHeader | None = None
        self._last_gp_log = 0.0

    def start(self, ctx: TaskContext) -> None:
        ctx.logger.info("Watching: %s", ctx.window.describe())
        self._previous = ctx.header
        self._last_gp_log = time.monotonic()
        if ctx.header is not None:
            ctx.logger.info(
                "Character %s | level %d | %s (%s)",
                ctx.header.character_name,
                ctx.header.total_level,
                ctx.header.active_action or "idle",
                ctx.header.active_entity or "unknown",
            )
        else:
            ctx.logger.warning("No save header decoded yet; will keep trying.")

    def on_save(self, ctx: TaskContext, header: SaveHeader) -> None:
        previous = self._previous
        self._previous = header
        if previous is None:
            return
        if header.active_action != previous.active_action:
            ctx.logger.info(
                "action %r -> %r", previous.active_action, header.active_action
            )
        if header.total_level != previous.total_level:
            ctx.logger.info(
                "total level %d -> %d (+%d)",
                previous.total_level,
                header.total_level,
                header.total_level - previous.total_level,
            )
        if header.gp != previous.gp and time.monotonic() - self._last_gp_log >= 60:
            delta = header.gp - previous.gp
            ctx.logger.info(
                "gp %s -> %s (%+d)", f"{previous.gp:,}", f"{header.gp:,}", delta
            )
            self._last_gp_log = time.monotonic()
