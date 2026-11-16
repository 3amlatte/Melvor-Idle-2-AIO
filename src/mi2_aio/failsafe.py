"""Idle failsafe: start a fallback action when the character has nothing to do.

The save header's ``active_entity`` / ``active_action`` are empty while the
character is idle. When that is detected, the bot opens the configured skill
page and presses the configured action button, so the account keeps gaining XP
instead of standing still.

The action is intentionally just a page icon + a button coordinate at the UI
reference size; a future settings UI can let the user pick an action and record
those two points.
"""

from __future__ import annotations

import time

from . import ui
from .config import Settings
from .input import click_game
from .tasks.base import TaskContext
from .window import capture_client, is_minimized


class IdleFailsafe:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings.failsafe
        self._last_attempt = 0.0
        self._pending = False

    def poll(self, ctx: TaskContext) -> None:
        if not self.settings.enabled:
            return
        header = ctx.header
        if header is None or is_minimized(ctx.window.hwnd):
            return

        active = header.active_action.strip()
        if active:
            if self._pending:
                ctx.logger.info(
                    "Fallback action is running: %s.",
                    header.active_action or header.active_entity,
                )
                self._pending = False
            return

        now = time.monotonic()
        if now - self._last_attempt < self.settings.cooldown_seconds:
            return
        self._start(ctx)

    def ensure_active(self, ctx: TaskContext) -> None:
        """Start the fallback after a run unless an action is visibly running."""
        if not self.settings.enabled or is_minimized(ctx.window.hwnd):
            return
        try:
            image = ui.normalize(capture_client(ctx.window))
        except Exception:
            image = None
        if image is not None and ui.action_panel_title(image) is not None:
            return
        header = ctx.header
        if (
            header is not None
            and header.active_action.strip()
            and header.active_entity.strip().lower() != "combat"
        ):
            return
        self._start(ctx)

    def _start(self, ctx: TaskContext) -> None:
        self._last_attempt = time.monotonic()
        ctx.logger.warning(
            "Character is not running an action; starting the fallback %r.",
            self.settings.action,
        )
        if ctx.dry_run:
            ctx.logger.info(
                "DRY RUN: click the %s page and its action button.",
                self.settings.action,
            )
            return

        self._click(ctx, self.settings.page)
        time.sleep(1.4)
        self._click(ctx, self.settings.button)
        time.sleep(1.0)
        self._pending = True

    def _click(self, ctx: TaskContext, point: tuple[int, int]) -> None:
        x, y = ui.to_client(*point, ctx.window.client_area)
        click_game(ctx.window, x, y, ctx.settings.automation)
