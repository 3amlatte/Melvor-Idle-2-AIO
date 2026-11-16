"""Farming maintenance that runs alongside the main task.

The main task keeps its action running (combat, woodcutting, ...) while this
module periodically checks the farming page, harvests grown plots, applies the
selected compost, replants the selected crop and waters it.

Trigger: the farming skill icon shows the game's attention badge when a plot is
harvestable (``ActiveFarmingCategory.RequiresAttention``). The badge is visible
from any page, so most polls cost one screenshot and nothing else. By default a
pass runs **only** when that badge is present. ``check_minutes`` can add a
safety full pass for users who want a periodic fallback.

The pass switches pages, so it only runs between main-task steps and restores
the page the main task declared (``Task.page``).
"""

from __future__ import annotations

import time

from PIL import Image

from . import ui
from .config import Settings
from .input import click_game, hold_game
from .tasks.base import TaskContext
from .window import capture_client, is_minimized

# How long a hold-to-act button needs. Watering uses the game's
# HoldForActionButton; 1.4 s already fires it, but a longer press is safer on
# slow frames and matches the in-game "hold for a few seconds" prompt.
HOLD_SECONDS = 2.5


class FarmingMaintenance:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings.farming
        self._last_check = 0.0
        self._last_badge_poll = 0.0
        self._last_badge = False

    # -- polling ---------------------------------------------------------
    def poll(self, ctx: TaskContext) -> None:
        if not self.settings.enabled:
            return
        if is_minimized(ctx.window.hwnd):
            return

        now = time.monotonic()
        due = (
            self.settings.check_minutes > 0
            and now - self._last_check >= self.settings.check_minutes * 60.0
        )
        badge = False
        if due or now - self._last_badge_poll >= self.settings.badge_poll_seconds:
            self._last_badge_poll = now
            try:
                badge = ui.farming_badge(self._capture(ctx))
            except Exception:
                ctx.logger.debug("Farming badge check failed", exc_info=True)

        if not badge and not due:
            return

        try:
            self.run_pass(ctx, reason="badge" if badge else "interval")
        except Exception:
            ctx.logger.exception("Farming pass failed; will retry later.")
            self._last_check = time.monotonic()

    # -- one full farming pass -------------------------------------------
    def run_pass(
        self,
        ctx: TaskContext,
        *,
        reason: str = "manual",
        restore: bool | None = None,
    ) -> dict[str, int]:
        self._last_check = time.monotonic()
        if ctx.stop.is_set():
            return {}
        if ctx.dry_run:
            ctx.logger.info(
                "DRY RUN: would service farming categories [%s] and The Mill.",
                ", ".join(self.settings.categories),
            )
            return {}
        ctx.logger.info("Farming check (%s).", reason)

        image = self._capture(ctx)
        was_on_farming = ui.farming_page_open(image)
        if not was_on_farming:
            if ui.farming_tabs_visible(image) and ui.mill_open(image):
                # On the farming page with The Mill panel open: close it first.
                self._click(ctx, ui.MILL_PANEL_BUTTON)
                time.sleep(1.0)
            for _attempt in range(3):
                self._click(ctx, ui.FARM_ICON)
                time.sleep(1.4)
                if ui.farming_page_open(self._capture(ctx)):
                    break
        if not ui.farming_page_open(self._capture(ctx)):
            ctx.logger.warning("Could not open the farming page; skipping this pass.")
            return {}

        counts = {
            "harvested": 0,
            "composted": 0,
            "planted": 0,
            "watered": 0,
            "bins": 0,
            "mill": 0,
            "blocked": 0,
            "locked": 0,
        }
        for category in self.settings.categories:
            if ctx.stop.is_set():
                ctx.logger.info("Farming pass interrupted by stop request.")
                self._restore_action_page(ctx)
                return counts
            point = ui.FARM_CATEGORY_TABS.get(category)
            if point is None:
                continue
            self._wait_if_paused(ctx)
            self._click(ctx, point)
            time.sleep(1.0)
            image = self._capture(ctx)
            for card in ui.farm_cards(image):
                if ctx.stop.is_set():
                    ctx.logger.info("Farming pass interrupted by stop request.")
                    self._restore_action_page(ctx)
                    return counts
                self._wait_if_paused(ctx)
                self._handle_card(ctx, card, counts, category)

        if self.settings.mill:
            self._wait_if_paused(ctx)
            if not ctx.stop.is_set():
                self._handle_mill(ctx, counts)

        if counts["locked"]:
            ctx.logger.info(
                "Farming: skipped %d locked/unpurchased plot(s); level, demo "
                "or a plot purchase is required (not an error).",
                counts["locked"],
            )
        if counts["blocked"]:
            ctx.logger.info(
                "Farming: %d plot(s) could not be planted (no seeds or no "
                "product selected).",
                counts["blocked"],
            )

        if any(counts[key] for key in counts if key != "locked"):
            ctx.logger.info(
                "Farming pass done: %d harvested, %d composted, %d planted, "
                "%d watered, %d compost bins, %d blocked, mill %s.",
                counts["harvested"],
                counts["composted"],
                counts["planted"],
                counts["watered"],
                counts["bins"],
                counts["blocked"],
                "handled" if counts["mill"] else "ok",
            )
        else:
            ctx.logger.info("Farming pass done: nothing needed attention.")

        do_restore = self.settings.restore_page if restore is None else restore
        if do_restore:
            self._restore_action_page(ctx)
        return counts

    # -- per-plot state machine -----------------------------------------
    def _handle_card(
        self,
        ctx: TaskContext,
        card: ui.FarmCard,
        counts: dict[str, int],
        category: str = "allotments",
    ) -> None:
        expect_plant = False
        compost_tried = False
        compost_pending = False
        actions = 0
        for _ in range(6):
            if ctx.stop.is_set():
                return
            self._wait_if_paused(ctx)
            if ctx.stop.is_set():
                return
            image = self._capture(ctx)

            if compost_pending:
                # The next capture shows whether the Apply Compost press took
                # effect (the button disappears once compost is applied).
                compost_pending = False
                if not ui.card_compost_button(image, card):
                    counts["composted"] += 1
                    ctx.logger.info("Applied compost to an empty plot.")
                else:
                    ctx.logger.info(
                        "Compost was not applied (none selected or not "
                        "available); planting without it."
                    )

            state = ui.card_state(image, card)

            if state == "locked":
                counts["locked"] += 1
                return
            if state == "unknown":
                ctx.logger.debug("Farm card at %s is in an unknown state.", card)
                return

            if state == "growing":
                if (
                    category != "compost"
                    and self.settings.water
                    and ui.card_not_watered(image, card)
                    and not ui.card_watered(image, card)
                ):
                    self._hold(ctx, ui.card_water_point(image, card))
                    time.sleep(0.8)
                    after = self._capture(ctx)
                    if ui.card_watered(after, card) or not ui.card_not_watered(
                        after, card
                    ):
                        counts["watered"] += 1
                        ctx.logger.info("Watered a growing plot.")
                    else:
                        ctx.logger.info(
                            "Watering did not take effect; will retry next pass."
                        )
                return

            if category == "compost":
                # Compost bins: "Begin Compost" when empty, collect when ready.
                if actions >= 2:
                    return
                point = ui.card_action_button(image, card)
                if point is None:
                    return
                self._click(ctx, point)
                actions += 1
                counts["bins"] += 1
                ctx.logger.info("Handled a compost bin.")
                time.sleep(1.2)
                continue

            if state == "ready":
                point = ui.card_action_button(image, card)
                if point is None:
                    return
                self._click(ctx, point)
                actions += 1
                if expect_plant:
                    counts["planted"] += 1
                    ctx.logger.info("Planted the selected crop.")
                else:
                    counts["harvested"] += 1
                    expect_plant = True
                    ctx.logger.info("Harvested a ready plot.")
                time.sleep(1.0)
                continue

            if state == "empty":
                expect_plant = True
                if not self.settings.plant:
                    return
                # A plot with no seed/product cannot be planted; do not waste
                # compost on it. This is normal (for example the demo's tree
                # seeds run out), not an error.
                if not ui.card_plant_ready(image, card):
                    counts["blocked"] += 1
                    ctx.logger.info(
                        "Farm plot at %s cannot be planted (no seeds or no "
                        "product selected).",
                        card,
                    )
                    return
                if (
                    self.settings.compost
                    and not compost_tried
                    and ui.card_compost_button(image, card)
                ):
                    compost_tried = True
                    if self.settings.select_compost:
                        self._select_compost(ctx, card)
                        image = self._capture(ctx)
                    if ui.card_compost_button(image, card):
                        self._click(ctx, ui.card_compost_point(image, card))
                        compost_pending = True
                        time.sleep(0.9)
                        continue
                point = ui.card_action_button(image, card)
                if point is None:
                    return
                self._click(ctx, point)
                counts["planted"] += 1
                ctx.logger.info("Planted the selected crop.")
                time.sleep(1.1)
                continue
            return

    # -- the mill building ----------------------------------------------
    def _handle_mill(self, ctx: TaskContext, counts: dict[str, int]) -> None:
        """Deposit farmed storage items into The Mill and keep it running.

        The mill only consumes items stored inside it, so the pass deposits
        Wheat/Sugarcane/Corn/Flax from the bank, then starts the mill when it
        is stopped and has stock to work with.
        """
        image = self._capture(ctx)
        status = ui.mill_status(image)
        was_open = ui.mill_open(image)

        if not was_open:
            if ctx.stop.is_set():
                return
            self._click(ctx, ui.MILL_PANEL_BUTTON)
            time.sleep(1.2)
            image = self._capture(ctx)
            if not ui.mill_open(image):
                ctx.logger.warning("Could not open The Mill panel; skipping it.")
                return

        for point in ui.MILL_DEPOSIT_BUTTONS:
            if ctx.stop.is_set():
                break
            self._click(ctx, point)
            time.sleep(0.5)
        counts["mill"] += 1
        time.sleep(0.6)

        image = self._capture(ctx)
        fill = ui.mill_item_fill(image)
        if status != "running" and fill > 0.05:
            self._click(ctx, ui.MILL_TOGGLE)
            time.sleep(0.9)
            ctx.logger.info(
                "The Mill was %s; started it (stock present).", status
            )
        else:
            ctx.logger.info(
                "The Mill is %s (%s).",
                "running" if status == "running" else status,
                "stock present" if fill > 0.05 else "no stock",
            )

        if not was_open:
            self._click(ctx, ui.MILL_PANEL_BUTTON)
            time.sleep(0.8)

    # -- helpers ---------------------------------------------------------
    def _wait_if_paused(self, ctx: TaskContext) -> None:
        pause = ctx.pause
        if pause is None:
            return
        while pause.is_set() and not ctx.stop.is_set():
            time.sleep(0.2)

    def _capture(self, ctx: TaskContext) -> Image.Image:
        x, y = ui.to_client(*ui.CURSOR_PARK, ctx.window.client_area)
        try:
            from .input import background_move

            background_move(ctx.window, x, y, ctx.settings.automation, settle=False)
        except Exception:
            pass
        time.sleep(0.2)
        return ui.normalize(capture_client(ctx.window))

    def _click(self, ctx: TaskContext, point: tuple[int, int]) -> None:
        x, y = ui.to_client(*point, ctx.window.client_area)
        click_game(ctx.window, x, y, ctx.settings.automation)

    def _hold(self, ctx: TaskContext, point: tuple[int, int]) -> None:
        x, y = ui.to_client(*point, ctx.window.client_area)
        hold_game(ctx.window, x, y, ctx.settings.automation, seconds=HOLD_SECONDS)

    def _select_compost(self, ctx: TaskContext, card: ui.FarmCard) -> None:
        """Pick the configured compost type in the plot's header picker.

        The header's "Compost: Select" control opens a picker with the compost
        types; slot 1 is Fertiliser in the demo (slot 2 is Compost). Selecting
        the type enables the body's Apply Compost button.
        """
        image = self._capture(ctx)
        if not ui.card_compost_picker_open(image, card):
            self._click(ctx, ui.card_compost_select_point(card))
            time.sleep(1.1)
        self._click(
            ctx, ui.card_compost_picker_point(card, self.settings.compost_slot)
        )
        time.sleep(1.1)

    def _restore_action_page(self, ctx: TaskContext) -> None:
        """Return to the page of the action currently being performed.

        The sidebar's top button shows the current action's icon and the game
        navigates to that action's page when it is pressed (tooltip: "Click to
        return to this page."). This works for combat, woodcutting, mining and
        every other skill page, instead of always going back to one fixed page.
        """
        self._click(ctx, ui.ACTIVE_ACTION_BUTTON)
        time.sleep(1.5)
        if not ui.farming_page_open(self._capture(ctx)):
            return
        # The action button did not navigate (no active action); fall back to
        # the page the main task declared, if any.
        target = ui.PAGE_TARGETS.get(ctx.page or "")
        if target is None:
            return
        self._click(ctx, target)
        time.sleep(0.9)
