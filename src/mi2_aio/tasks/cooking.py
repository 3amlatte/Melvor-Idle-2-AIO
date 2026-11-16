"""Cook a Basic Food recipe, optionally stopping after a product count.

The Cooking page has a recipe grid, a **Selected** panel and a **Creating**
panel. The task opens Cooking, selects the Basic Food recipe by its demo grid
slot, expands **Manage Stop Conditions**, chooses **Products Gained**, types the
requested amount and presses **Create**.

The in-game stop condition stops the action exactly after that many products.
The save header is used as a safety net: if it reports at least the requested
bank gain while the action is still running, the task clicks the red Stop
button. A wrong recipe (the save header names a different cooking product) or a
run that stops early is logged and ends the task so the queue can continue.

Options (``ctx.options``):

``recipe``
    Recipe id or display name (for example ``Glowfin``).
``amount``
    Products to cook. ``0`` (or missing) cooks until the run is stopped.
"""

from __future__ import annotations

import time

from .. import ui
from ..cooking_db import CookingDatabase, CookingRecipe, load_cooking
from ..window import capture_client, is_minimized
from .base import Task, TaskContext

POLL_SECONDS = 2.0
# The save header lags behind the rendered action; give it time before judging
# whether the created recipe was the requested one.
START_CONFIRM_SECONDS = 15.0
# Extra time after action stop before reading the bank delta for the log.
STOP_SETTLE_SECONDS = 2.0


class CookingTask(Task):
    name = "cooking"
    description = (
        "Open Cooking, select a Basic Food recipe, optionally set a Products "
        "Gained stop condition and press Create."
    )
    page = "cooking"
    changes_action = True

    def __init__(self) -> None:
        self._db: CookingDatabase | None = None
        self._recipe: CookingRecipe | None = None
        self._amount = 0
        self._created = False
        self._created_at = 0.0
        self._baseline = 0
        self._condition_set = False
        self._category_clicked = False
        self._dry_run_logged = False
        self._start_error = ""
        self._done = False

    # -- lifecycle -------------------------------------------------------
    def start(self, ctx: TaskContext) -> None:
        db = load_cooking()
        recipe = self._pick_recipe(db, str(ctx.options.get("recipe", "")))
        try:
            amount = int(ctx.options.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0
        self._db = db
        self._recipe = recipe
        self._amount = max(0, amount)
        target = (
            f"{self._amount} products" if self._amount else "until stopped"
        )
        ctx.logger.info(
            "Cooking: %s (%s -> %s, level %d, XP %d, %s) | cook %s",
            recipe.name,
            recipe.ingredients_label,
            recipe.product_name,
            recipe.level,
            recipe.experience,
            recipe.interval_label,
            target,
        )

    def stop(self, ctx: TaskContext) -> None:
        ctx.logger.info("Cooking task stopped.")

    def _pick_recipe(
        self, db: CookingDatabase, wanted: str
    ) -> CookingRecipe:
        available = db.available_recipes()
        if wanted:
            found = db.recipe(wanted)
            if found is not None and not found.demo_locked:
                return found
        return available[0]

    # -- main loop -------------------------------------------------------
    def step(self, ctx: TaskContext) -> float | None:
        if self._recipe is None:
            return None
        if self._done:
            ctx.stop.set()
            return 5.0
        if is_minimized(ctx.window.hwnd):
            ctx.logger.error(
                "Game window is minimized; the cooking page cannot be read or "
                "clicked. Stopping."
            )
            ctx.stop.set()
            return 5.0

        image = self._capture(ctx)
        if not ui.cooking_page_open(image):
            if self._act(ctx, "open the Cooking page"):
                self._click(ctx, ui.COOK_ICON)
            return 1.4

        if ctx.dry_run:
            self._log_dry_run(ctx)
            return 5.0

        if not self._created:
            return self._prepare_and_create(ctx, image)

        return self._monitor(ctx, image)

    # -- preparation -----------------------------------------------------
    def _prepare_and_create(self, ctx: TaskContext, image):
        assert self._recipe is not None
        stopped = ui.cooking_stop_point(image)
        if stopped is not None:
            ctx.logger.info("Stopping the active cooking action first.")
            self._click(ctx, stopped)
            time.sleep(1.6)
            image = self._capture(ctx)

        if not self._category_clicked:
            self._click(ctx, ui.COOK_BASIC_FOOD)
            self._category_clicked = True
            time.sleep(1.0)
            image = self._capture(ctx)

        slot = self._recipe.grid_slot
        if slot is None:
            ctx.logger.error(
                "No grid slot is known for %s; stopping.", self._recipe.name
            )
            self._done = True
            return 5.0
        self._scroll_grid_to_top(ctx)
        ctx.logger.info(
            "Selecting %s (grid slot %d).", self._recipe.name, slot + 1
        )
        self._click(ctx, ui.cooking_recipe_point(slot))
        time.sleep(1.0)

        condition_set = False
        if self._amount > 0:
            condition_set = self._set_stop_condition(ctx)
            if not condition_set:
                ctx.logger.warning(
                    "Could not set the Products Gained stop condition; the "
                    "bot will stop after the bank shows %d product(s).",
                    self._amount,
                )
        self._condition_set = condition_set

        header = self._read_header(ctx)
        product = self._recipe.product
        self._baseline = (
            int(header.bank_stacks.get(product.id, 0))
            if header is not None and product is not None
            else 0
        )

        image = self._capture(ctx)
        footer = ui.cooking_footer(image)
        if footer is None:
            ctx.logger.warning(
                "Could not find the Create button; will retry the selection."
            )
            return 2.0
        self._click(ctx, footer.create)
        time.sleep(1.4)
        after = self._capture(ctx)
        if ui.cooking_stop_point(after) is None:
            ctx.logger.warning(
                "Create did not start the recipe; retrying the selection."
            )
            return 2.0

        self._created = True
        self._created_at = time.monotonic()
        ctx.logger.info(
            "Cooking started: %s (%s).",
            self._recipe.product_name,
            "stop after %d" % self._amount
            if self._amount
            else "until stopped",
        )
        return 2.0

    def _set_stop_condition(self, ctx: TaskContext) -> bool:
        assert self._recipe is not None
        image = self._capture(ctx)
        footer = ui.cooking_footer(image)
        if footer is None:
            return False
        if not ui.cooking_stop_panel_open(image, footer):
            self._click(ctx, footer.manage)
            time.sleep(1.0)
            image = self._capture(ctx)
            footer = ui.cooking_footer(image)
            if footer is None:
                return False
            if not ui.cooking_stop_panel_open(image, footer):
                return False

        self._click(ctx, footer.condition)
        time.sleep(0.8)
        self._click(ctx, footer.condition_menu)
        time.sleep(1.0)
        image = self._capture(ctx)
        if not ui.cooking_stop_item_open(image, footer):
            # Retry the condition menu once; the first click can be swallowed
            # while the foldable animates.
            self._click(ctx, footer.condition)
            time.sleep(0.8)
            self._click(ctx, footer.condition_menu)
            time.sleep(1.0)
            image = self._capture(ctx)
            if not ui.cooking_stop_item_open(image, footer):
                return False

        self._click(ctx, footer.quantity)
        time.sleep(0.3)
        self._type_amount(ctx, self._amount)
        time.sleep(0.5)
        return True

    def _scroll_grid_to_top(self, ctx: TaskContext) -> None:
        """Reset the recipe grid before clicking a slot.

        The grid scrolls independently of the Selected panel; a wheel-up over
        it puts the first row back at the known reference position.
        """
        try:
            import pyautogui

            from ..window import focus

            if not focus(ctx.window.hwnd):
                return
            x, y = ui.to_client(900, 600, ctx.window.client_area)
            screen_x, screen_y = ctx.window.client_to_screen(x, y)
            pyautogui.moveTo(screen_x, screen_y, duration=0.15)
            pyautogui.scroll(10)
            time.sleep(0.3)
        except Exception:
            ctx.logger.debug("Could not reset the recipe grid scroll", exc_info=True)

    def _type_amount(self, ctx: TaskContext, amount: int) -> None:
        text = str(max(1, amount))
        if ctx.settings.automation.background_input:
            from ..input import background_key, background_type

            background_type(
                ctx.window, text, ctx.settings.automation, clear=4
            )
            background_key(ctx.window, 0x0D, ctx.settings.automation)
            return
        try:
            import pyautogui

            pyautogui.hotkey("ctrl", "a")
            pyautogui.write(text)
            pyautogui.press("enter")
        except Exception:
            ctx.logger.debug("Could not type the cooking amount", exc_info=True)

    # -- monitoring ------------------------------------------------------
    def _monitor(self, ctx: TaskContext, image):
        assert self._recipe is not None
        product = self._recipe.product
        if product is None:
            self._done = True
            return 5.0

        elapsed = time.monotonic() - self._created_at
        header = self._read_header(ctx)
        action = (header.active_action if header is not None else "").strip()
        bank = int(header.bank_stacks.get(product.id, 0)) if header else 0
        gained = max(0, bank - self._baseline)
        stop_button = ui.cooking_stop_point(image)

        if self._amount and gained >= self._amount:
            if not self._condition_set:
                # No in-game stop condition: the bank delta is the only stop
                # signal, so press Stop ourselves.
                if stop_button is not None:
                    self._click(ctx, stop_button)
                    time.sleep(1.0)
                self._finish(
                    ctx,
                    f"Cooked {gained} {product.name} (target {self._amount}); "
                    "bank count reached the target.",
                )
            # With the in-game condition set, let the game stop the action.
            return 5.0

        if stop_button is None and elapsed > 6.0:
            gained = self._settled_gain(ctx, product, gained)
            header = self._read_header(ctx)
            short = self._ingredients_short(ctx, header)
            if self._amount and gained >= self._amount:
                self._finish(
                    ctx,
                    f"Cooked {gained} {product.name}; the game stopped the "
                    f"action at the requested {self._amount}.",
                )
            elif self._amount and self._condition_set and not short:
                # The game condition counts products exactly; the save file can
                # lag behind the final bank count.
                self._finish(
                    ctx,
                    f"Cooked the requested {self._amount} {product.name} "
                    f"(Products Gained); the save currently shows +{gained}.",
                )
            elif self._amount:
                ctx.logger.warning(
                    "Cooking stopped after %d of %d requested %s; the "
                    "ingredients may have run out.",
                    gained,
                    self._amount,
                    product.name,
                )
                self._finish(ctx, "Cooking stopped early.")
            else:
                self._finish(
                    ctx, f"Cooking stopped; bank gained {gained} {product.name}."
                )
            return 5.0

        known = set(self._db.product_names() if self._db else ())
        if (
            action
            and action.lower() != product.name.lower()
            and action in known
        ):
            ctx.logger.error(
                "Cooking selected the wrong recipe: the game is cooking %r, "
                "expected %r. Stopping and ending the task.",
                action,
                product.name,
            )
            if stop_button is not None:
                self._click(ctx, stop_button)
            self._finish(ctx, "Wrong recipe selected.")
            return 5.0

        if self._amount:
            interval = max(0.5, self._recipe.interval_ms / 1000.0)
            max_wait = max(120.0, self._amount * interval * 4.0)
            if elapsed > max_wait:
                ctx.logger.warning(
                    "Cooking did not stop after %.0fs; clicking Stop. "
                    "Gained %d of %d.",
                    elapsed,
                    gained,
                    self._amount,
                )
                if stop_button is not None:
                    self._click(ctx, stop_button)
                self._finish(ctx, "Cooking timed out.")

        return 3.0

    def _finish(self, ctx: TaskContext, message: str) -> None:
        if self._done:
            return
        self._done = True
        ctx.logger.info("Cooking task finished: %s", message)
        ctx.stop.set()

    def _settled_gain(self, ctx: TaskContext, product, gained: int) -> int:
        """Give the save file time to catch up after the action stops."""
        for _ in range(5):
            time.sleep(STOP_SETTLE_SECONDS)
            header = self._read_header(ctx)
            if header is None:
                break
            current = int(header.bank_stacks.get(product.id, 0)) - self._baseline
            if current > gained:
                gained = current
            else:
                break
        return max(0, gained)

    def _ingredients_short(self, ctx: TaskContext, header) -> bool:
        """True when the save shows too few ingredients to have kept cooking."""
        if header is None or self._recipe is None:
            return False
        for item in self._recipe.ingredients:
            if int(header.bank_stacks.get(item.id, 0)) < item.quantity:
                return True
        return False

    # -- helpers ---------------------------------------------------------
    def _read_header(self, ctx: TaskContext):
        try:
            from ..savefile import read_header

            return read_header(settings=ctx.settings)
        except Exception:
            return ctx.header

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
            self._log_dry_run(ctx)
            return False
        return True

    def _log_dry_run(self, ctx: TaskContext) -> None:
        if self._dry_run_logged or self._recipe is None:
            return
        self._dry_run_logged = True
        if self._amount:
            detail = f"Products Gained = {self._amount}"
        else:
            detail = "no stop condition"
        ctx.logger.info(
            "DRY RUN: would open Cooking -> Basic Food, select %s, set %s and "
            "press Create.",
            self._recipe.name,
            detail,
        )
