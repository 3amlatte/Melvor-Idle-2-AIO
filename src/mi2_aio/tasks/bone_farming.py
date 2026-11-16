"""Farm the best Prayer-points-per-hour bone monster with the current setup.

Giant Chicken in Corrupted Farmlands always drops a Big Bone (6 Prayer points)
for 50 HP. A regular Bone gives 1 Prayer point for 20 HP, so Giant Chicken is
2.4x more Prayer points per HP even though each kill takes longer. Hobgolbin
also drops a Big Bone but has 70 HP, making it slower than Giant Chicken.

The task only navigates and monitors combat. Gear, stance, auto-eat and the
existing prayer maintenance (which buries banked bones for Prayer points) run
exactly as they do during Slayer/Dungeons.
"""

from __future__ import annotations

import time

from .. import ui
from ..window import capture_client, is_minimized
from .base import Task, TaskContext

# All enemies in Golbin Forest drop a bone (Bone or Big Bone), so any of them
# keeps the bone farm working after the first Golbin is killed.
TARGET = "GiantChicken"
BONE_ENEMIES = frozenset({TARGET})
POLL_SECONDS = 2.0
# Give the save a moment to report the new enemy before deciding the Fight
# click failed and reopening the area menu.
FIGHT_CONFIRM_SECONDS = 10.0


class BoneFarmingTask(Task):
    name = "farm_bones"
    description = (
        "Farm Giant Chicken in Corrupted Farmlands for Prayer points; each "
        "kill drops a Big Bone and prayer maintenance buries the bones."
    )
    page = "combat"
    # Farm Bones is explicitly for Prayer points, so keep bone burying on even
    # if the user disabled it for other tasks.
    force_prayer = True
    # A idle fallback would interrupt the fight loop; the user asked for
    # continuous killing. "Run farming now" still queues a manual pass, and the
    # failsafe runs again after the task stops.
    skip_failsafe = True

    def __init__(self) -> None:
        self._last_nav_at = float("-inf")
        self._fight_clicked_at = 0.0
        self._dry_run_logged = False
        self._target_logged = False

    def start(self, ctx: TaskContext) -> None:
        ctx.logger.info(
            "Bone farm: target Giant Chicken (Corrupted Farmlands). Giant "
            "Chicken has 50 HP and always drops a Big Bone (6 Prayer points); "
            "Prayer maintenance will bury banked bones for Prayer points."
        )

    def stop(self, ctx: TaskContext) -> None:
        ctx.logger.info("Bone farm stopped.")

    # -- main loop -------------------------------------------------------
    def step(self, ctx: TaskContext) -> float | None:
        now = time.monotonic()
        if is_minimized(ctx.window.hwnd):
            ctx.logger.error(
                "Game window is minimized. Restore it; the bone farm cannot "
                "read or click the combat page. Stopping."
            )
            ctx.stop.set()
            return 5.0

        image = self._capture(ctx)

        if ui.area_menu_open(image):
            if ctx.dry_run:
                self._log_dry_run(ctx)
                return POLL_SECONDS
            if now - self._last_nav_at >= 3.0:
                self._last_nav_at = now
                self._navigate_menu(ctx)
            return POLL_SECONDS

        if self._target_active(ctx, image):
            if not self._target_logged:
                self._target_logged = True
                enemy = (
                    ctx.header.active_enemy_id
                    if ctx.header and ctx.header.active_enemy_id
                    else "Giant Chicken"
                )
                ctx.logger.info(
                    "Bone farm active: fighting %s; food is %s. Prayer "
                    "maintenance keeps burying bones in the background.",
                    enemy,
                    ui.eat_button_state(image),
                )
            food = ui.eat_button_state(image)
            if food == "disabled":
                ctx.logger.info(
                    "Bone farm stopping: the Eat button is disabled (out of "
                    "food)."
                )
                ctx.stop.set()
                return 5.0
            return POLL_SECONDS

        # The player HP bar only exists on the Combat page, so it is a cheap
        # page detector that does not depend on the style panel being visible.
        if ui.hp_ratio(image) is None:
            if ctx.dry_run:
                self._log_dry_run(ctx)
                return POLL_SECONDS
            if now - self._last_nav_at >= 5.0:
                self._last_nav_at = now
                self._fix_combat_page(ctx)
            return POLL_SECONDS

        if (
            self._fight_clicked_at
            and now - self._fight_clicked_at < FIGHT_CONFIRM_SECONDS
        ):
            # The Fight click has just happened; the save header can lag by a
            # poll or two, so do not immediately reopen the menu.
            return POLL_SECONDS

        if ctx.dry_run:
            self._log_dry_run(ctx)
            return POLL_SECONDS

        if now - self._last_nav_at >= 4.0:
            self._last_nav_at = now
            self._open_menu(ctx)
        return 1.5

    def _target_active(self, ctx: TaskContext, image) -> bool:
        header = ctx.header
        if header is not None:
            enemy = header.active_enemy_id.strip()
            if enemy:
                return enemy in BONE_ENEMIES
            return False
        return ui.run_from_combat_ready(image)

    # -- navigation ------------------------------------------------------
    def _open_menu(self, ctx: TaskContext) -> None:
        if not self._act(ctx, "open the combat area menu"):
            return
        self._click(ctx, ui.AREA_BUTTON)
        time.sleep(1.2)
        if not ui.area_menu_open(self._capture(ctx)):
            self._click(ctx, ui.AREA_PROMPT)
            time.sleep(1.2)

    def _navigate_menu(self, ctx: TaskContext) -> None:
        if not self._act(ctx, "select Golbin Forest and fight Golbin"):
            return
        ctx.logger.info(
            "Selecting Combat Areas -> Corrupted Farmlands -> Giant Chicken "
            "-> Fight."
        )
        self._click(ctx, ui.BONE_FARM_AREA_TAB)
        time.sleep(0.9)
        self._click(ctx, ui.BONE_FARM_AREA_ROW)
        time.sleep(1.0)
        self._click(ctx, ui.BONE_FARM_FIGHT)
        self._fight_clicked_at = time.monotonic()
        time.sleep(1.5)

    def _fix_combat_page(self, ctx: TaskContext) -> None:
        if not self._act(ctx, "open the Combat page"):
            return
        self._click(ctx, ui.NAV_COMBAT)

    # -- helpers ---------------------------------------------------------
    def _capture(self, ctx: TaskContext):
        x, y = ui.to_client(*ui.CURSOR_PARK, ctx.window.client_area)
        try:
            from ..input import background_move

            background_move(
                ctx.window, x, y, ctx.settings.automation, settle=False
            )
        except Exception:
            pass
        time.sleep(0.25)
        return ui.normalize(capture_client(ctx.window))

    def _click(self, ctx: TaskContext, point: tuple[int, int]) -> None:
        x, y = ui.to_client(*point, ctx.window.client_area)
        from ..input import click_game

        click_game(ctx.window, x, y, ctx.settings.automation)

    def _act(self, ctx: TaskContext, description: str) -> bool:
        if ctx.dry_run:
            ctx.logger.info("DRY RUN: %s", description)
            return False
        return True

    def _log_dry_run(self, ctx: TaskContext) -> None:
        if self._dry_run_logged:
            return
        self._dry_run_logged = True
        ctx.logger.info(
            "DRY RUN: would open Combat Areas -> Corrupted Farmlands -> Giant "
            "Chicken -> Fight, then monitor food and Prayer upkeep."
        )
