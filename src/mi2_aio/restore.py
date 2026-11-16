"""Remember and restore the action the game was doing before a run.

A test or combat task changes the character's active action. When the run ends,
the bot should leave the game as it found it: for example, it was cutting a
Willow Tree, the bot raided a dungeon, and afterwards Woodcutting resumes.

The restore works from the rendered UI only:

1. At run start, the bot opens the current action's page (the sidebar's
   "return to this page" button), captures the page header icon and the action
   name from the active panel's banner.
2. It matches the header icon against the sidebar to remember which page button
   to click later, and keeps the name mask as a template.
3. At run end, it opens that page, finds the same name on an action card (the
   banner font is larger, so the match runs across scales) and clicks the green
   start button below it.

If any step cannot be identified the restore logs a warning and leaves the game
alone instead of clicking blindly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from PIL import Image

from . import ui
from .config import RestoreSettings
from .paths import ERRORS_DIR
from .savefile import SaveFileError, SaveHeader, read_header
from .tasks.base import TaskContext
from .window import capture_client


@dataclass
class RestoreState:
    """What the bot needs to resume the pre-run action."""

    entity: str
    action: str
    # Sidebar button for the action's page, in reference coordinates.
    page_icon: tuple[int, int] | None
    # Binary mask of the action name from the active panel banner.
    title_template: np.ndarray | None

    @property
    def is_combat(self) -> bool:
        return self.entity.strip().lower() == "combat"


class PreviousActionRestore:
    """Capture the pre-run action and resume it when the run ends."""

    def __init__(self, settings: RestoreSettings) -> None:
        self.settings = settings
        self._state: RestoreState | None = None
        self._changed = False

    # -- plumbing --------------------------------------------------------
    def _capture(self, ctx: TaskContext) -> Image.Image:
        x, y = ui.to_client(*ui.CURSOR_PARK, ctx.window.client_area)
        try:
            from .input import background_move

            background_move(
                ctx.window, x, y, ctx.settings.automation, settle=False
            )
        except Exception:
            pass
        time.sleep(0.25)
        return ui.normalize(capture_client(ctx.window))

    def _click(self, ctx: TaskContext, point: tuple[int, int]) -> None:
        x, y = ui.to_client(*point, ctx.window.client_area)
        from .input import click_game

        click_game(ctx.window, x, y, ctx.settings.automation)

    def _header(self, ctx: TaskContext) -> SaveHeader | None:
        if ctx.header is not None:
            return ctx.header
        return self._read_header(ctx)

    def _read_header(self, ctx: TaskContext) -> SaveHeader | None:
        try:
            return read_header(settings=ctx.settings)
        except SaveFileError:
            return None

    # -- capture ---------------------------------------------------------
    def capture(self, ctx: TaskContext, *, changes_action: bool = True) -> None:
        """Learn how to return to the action that is active right now.

        ``changes_action`` is the task's expectation: combat and skilling tasks
        replace the active action, so a stale save header must not make the
        restore think the old action is still running.
        """
        if not self.settings.enabled:
            return
        if ctx.dry_run:
            ctx.logger.info(
                "DRY RUN: would remember the current action for restore."
            )
            return

        header = self._header(ctx)
        if header is None:
            ctx.logger.info(
                "Restore: no save header yet; the pre-run action cannot be "
                "remembered."
            )
            return

        self._changed = changes_action

        action = header.active_action.strip()
        entity = header.active_entity.strip()
        if not action:
            ctx.logger.info(
                "Restore: the character is idle; there is no action to "
                "remember."
            )
            return

        if entity.lower() == "combat":
            self._state = RestoreState(
                entity="Combat", action=action, page_icon=None, title_template=None
            )
            ctx.logger.info(
                "Restore: previous action was combat (%r); the Combat page can "
                "be restored, but the enemy/dungeon is not re-entered "
                "automatically.",
                action,
            )
            return

        # Open the action's page without changing the action.
        self._click(ctx, ui.ACTIVE_ACTION_BUTTON)
        time.sleep(1.4)
        image = self._capture(ctx)
        page_icon = ui.find_page_icon(image)
        title = ui.action_panel_title(image)
        if page_icon is None or title is None:
            ctx.logger.warning(
                "Restore: could not learn how to return to %r (%s); it will "
                "not be restored at the end of the run.",
                action,
                entity,
            )
            return

        self._state = RestoreState(
            entity=entity, action=action, page_icon=page_icon, title_template=title
        )
        ctx.logger.info(
            "Restore: remembered %r (%s) for the end of the run.", action, entity
        )

    # -- restore ---------------------------------------------------------
    def observe(self, header: SaveHeader) -> None:
        """Track whether the task changed the active action during the run."""
        if self._state is None:
            return
        action = header.active_action.strip()
        if action and action.lower() != self._state.action.strip().lower():
            self._changed = True

    def restore(self, ctx: TaskContext) -> None:
        """Resume the action remembered by :meth:`capture`, if it changed."""
        state = self._state
        if state is None:
            return
        if ctx.dry_run:
            ctx.logger.info(
                "DRY RUN: would restore %r at the end of the run.", state.action
            )
            return

        if state.is_combat:
            self._click(ctx, ui.NAV_COMBAT)
            ctx.logger.info(
                "Restore: previous action was combat; returned to the Combat "
                "page."
            )
            return

        header = self._read_header(ctx)
        image = self._capture(ctx)

        # If the action is visibly running, there is nothing to do. This also
        # protects a running action when the save header is stale.
        running_title = ui.action_panel_title(image)
        if (
            running_title is not None
            and state.title_template is not None
            and ui.same_title(running_title, state.title_template)
        ):
            ctx.logger.info("Restore: %r is already running.", state.action)
            return

        # The save header is exact but delayed (10 s autosave), so only trust
        # it when the task was not expected to replace the action.
        if (
            not self._changed
            and header is not None
            and header.active_action.strip().lower()
            == state.action.strip().lower()
        ):
            ctx.logger.info("Restore: %r is already running.", state.action)
            return

        in_combat = ui.dungeon_active(image) or ui.run_from_combat_ready(image)
        if (
            not in_combat
            and header is not None
            and header.active_entity.strip().lower() == "combat"
            and header.active_action.strip()
        ):
            in_combat = True
        if in_combat:
            self._leave_combat(ctx)

        if state.page_icon is None or state.title_template is None:
            return

        self._click(ctx, state.page_icon)
        time.sleep(1.6)
        image = self._capture(ctx)

        running_title = ui.action_panel_title(image)
        if (
            running_title is not None
            and state.title_template is not None
            and ui.same_title(running_title, state.title_template)
        ):
            ctx.logger.info("Restore: %r is already running.", state.action)
            return

        match = ui.find_action_title(image, state.title_template)
        if match is None:
            # The page may still have been opening; click the page icon again
            # before giving up.
            self._click(ctx, state.page_icon)
            time.sleep(1.8)
            image = self._capture(ctx)
            running_title = ui.action_panel_title(image)
            if (
                running_title is not None
                and state.title_template is not None
                and ui.same_title(running_title, state.title_template)
            ):
                ctx.logger.info("Restore: %r is already running.", state.action)
                return
            match = ui.find_action_title(image, state.title_template)
        if match is None:
            try:
                ERRORS_DIR.mkdir(parents=True, exist_ok=True)
                path = ERRORS_DIR / "restore_failed.png"
                image.save(path)
                ctx.logger.warning(
                    "Restore: could not find %r on its page (page icon %s); "
                    "leaving the game as it is. Screenshot: %s",
                    state.action,
                    state.page_icon,
                    path,
                )
            except Exception:
                ctx.logger.warning(
                    "Restore: could not find %r on its page (page icon %s); "
                    "leaving the game as it is.",
                    state.action,
                    state.page_icon,
                )
            return

        name_point, score = match
        buttons = ui.find_action_buttons(image)
        button = ui.choose_action_button(buttons, name_point)
        if button is None:
            ctx.logger.warning(
                "Restore: found %r but no start button below it; leaving the "
                "game as it is.",
                state.action,
            )
            return

        ctx.logger.info(
            "Restore: starting %r (name match %.2f).", state.action, score
        )
        self._click(ctx, button)
        if self._verify(ctx, state):
            ctx.logger.info("Restore: %r is running again.", state.action)
        else:
            ctx.logger.warning(
                "Restore: clicked %r but could not confirm it started; check "
                "the game.",
                state.action,
            )

    # -- helpers ---------------------------------------------------------
    def _leave_combat(self, ctx: TaskContext) -> None:
        self._click(ctx, ui.NAV_COMBAT)
        time.sleep(1.2)
        image = self._capture(ctx)
        if not ui.run_from_combat_ready(image):
            return
        ctx.logger.info("Restore: leaving combat before restoring the action.")
        self._click(ctx, ui.RUN_FROM_COMBAT)
        time.sleep(2.5)

    def _verify(self, ctx: TaskContext, state: RestoreState) -> bool:
        """Confirm the action restarted, from the screen first, then the save."""
        time.sleep(1.5)
        image = self._capture(ctx)
        title = ui.action_panel_title(image)
        if (
            title is not None
            and state.title_template is not None
            and ui.same_title(title, state.title_template)
        ):
            return True

        deadline = time.monotonic() + max(1.0, self.settings.verify_seconds)
        while time.monotonic() < deadline:
            header = self._read_header(ctx)
            if header is not None and (
                header.active_action.strip().lower()
                == state.action.strip().lower()
            ):
                return True
            time.sleep(max(0.5, self.settings.poll_seconds))
        return False
