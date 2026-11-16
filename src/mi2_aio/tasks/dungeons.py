"""Raid a standard dungeon from the combat area menu.

The dungeon is selected in the Combat page's area menu (Select Area ->
Standard Dungeons). Once started, the game keeps the dungeon running: after the
last enemy of a wave it grants the completion loot and spawns the next wave, so
the task only has to stay in the dungeon, keep the character alive and counter
the enemies' combat styles.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PIL import Image

from .. import equipment, ui
from ..paths import resolve_resource
from ..savefile import SaveHeader
from ..style_switch import StyleSwitcher
from ..window import capture_client
from .base import Task, TaskContext

STYLE_LABEL = {"melee": "Melee", "ranged": "Ranged", "magic": "Magic"}
SWITCH_VERIFY_SECONDS = 3.0
SWITCH_BACKOFF_SECONDS = 600.0
NO_FOOD_POLLS = 2


class DungeonTask(Task):
    name = "dungeons"
    description = (
        "Enter a standard dungeon, keep fighting through its waves and collect "
        "the completion loot."
    )
    page = "combat"

    def __init__(self) -> None:
        self._template: np.ndarray | None = None
        self._template_missing = False
        self._last_switch_at = float("-inf")
        self._switch_blocked_until = 0.0
        self._pending_style: str | None = None
        self._pending_since = 0.0
        self._no_food_polls = 0
        self._last_page_click = float("-inf")
        self._page_fix_stage = 0
        self._last_nav_attempt = float("-inf")
        self._warned_at: dict[str, float] = {}
        self._started = False
        self._style_switcher: StyleSwitcher | None = None

    # -- plumbing --------------------------------------------------------
    def _warn(
        self,
        ctx: TaskContext,
        key: str,
        message: str,
        *args: object,
        every: float = 300.0,
    ) -> None:
        now = time.monotonic()
        if now - self._warned_at.get(key, 0.0) < every:
            return
        self._warned_at[key] = now
        ctx.logger.warning(message, *args)

    def _capture(self, ctx: TaskContext) -> Image.Image:
        x, y = ui.to_client(*ui.CURSOR_PARK, ctx.window.client_area)
        try:
            from ..input import background_move

            background_move(ctx.window, x, y, ctx.settings.automation, settle=False)
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

    def _fix_combat_page(self, ctx: TaskContext) -> None:
        if not self._act(ctx, "open the Combat page"):
            return
        if self._page_fix_stage == 0:
            self._click(ctx, ui.NAV_COMBAT)
            self._page_fix_stage = 1
        else:
            self._click(ctx, ui.COMBAT_STATS_TAB)
            self._page_fix_stage = 0

    # -- lifecycle -------------------------------------------------------
    def start(self, ctx: TaskContext) -> None:
        dungeon = ctx.settings.dungeons
        ctx.logger.info(
            "Dungeon automation: %r, stop_when_out_of_food=%s, "
            "switch cooldown=%.1f min",
            dungeon.dungeon,
            dungeon.stop_when_out_of_food,
            dungeon.switch_cooldown_minutes,
        )
        self._template = self._load_template(ctx, dungeon.template)
        self._style_switcher = StyleSwitcher(
            auto_style=dungeon.auto_style,
            auto_armour=dungeon.auto_armour,
            armour_check_minutes=dungeon.armour_check_minutes,
            switch_cooldown_seconds=dungeon.style_switch_cooldown_seconds,
        )
        ctx.logger.info(
            "Dungeon melee style choice: %s (save wave enemy + "
            "data/enemies.json); armour upgrades: %s.",
            "on" if dungeon.auto_style else "off",
            "on" if dungeon.auto_armour else "off",
        )

    def on_save(self, ctx: TaskContext, header: SaveHeader) -> None:
        pass

    def stop(self, ctx: TaskContext) -> None:
        ctx.logger.info("Dungeon task stopped.")

    def _load_template(self, ctx: TaskContext, raw: str) -> np.ndarray | None:
        path = Path(raw)
        path = resolve_resource(path)
        if not path.exists():
            self._template_missing = True
            ctx.logger.warning(
                "Dungeon name template %s is missing; the bot cannot select a "
                "dungeon. Re-capture it with `python -m mi2_aio capture`.",
                path,
            )
            return None
        image = Image.open(path).convert("L")
        return (np.asarray(image) > 0).astype(np.float32)

    # -- main loop -------------------------------------------------------
    def step(self, ctx: TaskContext) -> float | None:
        now = time.monotonic()
        image = self._capture(ctx)

        # The area menu is full-screen and covers the stats panel, so handle it
        # before trying to read the combat style.
        if ui.area_menu_open(image):
            self._navigate(ctx, now)
            return ctx.settings.dungeons.poll_seconds

        style = ui.read_combat_style(image)
        if not style.readable:
            if now - self._last_page_click >= 5.0:
                self._last_page_click = now
                self._fix_combat_page(ctx)
            return 1.5

        if ui.dungeon_active(image) or self._header_in_dungeon(ctx):
            if not self._started:
                ctx.logger.info("In dungeon %r.", ctx.settings.dungeons.dungeon)
                self._started = True
            return self._combat_step(ctx, image, style, now)

        # Not in a dungeon: open the area menu.
        self._open_menu(ctx, now)
        return ctx.settings.dungeons.poll_seconds

    def _header_in_dungeon(self, ctx: TaskContext) -> bool:
        """The save header names the current dungeon while it is running.

        This covers short moments where the on-screen progress label is hidden
        (wave transition, menu dimming) and prevents re-entering the dungeon
        and resetting its progress.
        """
        header = ctx.header
        if header is None:
            return False
        return (
            header.active_action.strip().lower()
            == ctx.settings.dungeons.dungeon.strip().lower()
        )

    # -- navigation ------------------------------------------------------
    def _open_menu(self, ctx: TaskContext, now: float) -> None:
        if now - self._last_nav_attempt < 5.0:
            return
        self._last_nav_attempt = now
        if not self._act(ctx, "open the combat area menu"):
            return
        self._click(ctx, ui.AREA_BUTTON)
        time.sleep(1.2)
        if not ui.area_menu_open(self._capture(ctx)):
            self._click(ctx, ui.AREA_PROMPT)
            time.sleep(1.2)

    def _navigate(self, ctx: TaskContext, now: float) -> None:
        if now - self._last_nav_attempt < 4.0:
            return
        self._last_nav_attempt = now
        if not self._act(ctx, "select the dungeon and start it"):
            return

        self._click(ctx, ui.DUNGEON_TAB)
        time.sleep(1.0)
        image = self._capture(ctx)
        if self._template is None:
            return
        point = ui.find_dungeon_row(image, self._template)
        if point is None:
            self._warn(
                ctx,
                "row",
                "Could not find %r in the Standard Dungeons list; is it "
                "unlocked and visible?",
                ctx.settings.dungeons.dungeon,
            )
            return
        self._click(ctx, point)
        time.sleep(0.8)
        self._click(ctx, ui.START_DUNGEON)
        time.sleep(2.0)
        if ui.dungeon_active(self._capture(ctx)):
            ctx.logger.info(
                "Dungeon %r started.", ctx.settings.dungeons.dungeon
            )
            self._started = True
        else:
            ctx.logger.warning(
                "Start Dungeon did not start %r; will retry.",
                ctx.settings.dungeons.dungeon,
            )

    # -- combat ----------------------------------------------------------
    def _combat_step(
        self, ctx: TaskContext, image: Image.Image, style: ui.CombatStyle, now: float
    ) -> float:
        settings = ctx.settings.dungeons

        food = ui.eat_button_state(image)
        if food == "disabled":
            self._no_food_polls += 1
            if self._no_food_polls >= NO_FOOD_POLLS:
                if settings.stop_when_out_of_food:
                    self._flee(ctx, image)
                    ctx.logger.error(
                        "Out of food in the dungeon; stopping the run."
                    )
                    ctx.stop.set()
                    return 5.0
                self._warn(
                    ctx,
                    "food",
                    "Out of food but stop_when_out_of_food is false; continuing.",
                )
        elif food == "enabled":
            self._no_food_polls = 0

        ratio = ui.hp_ratio(image)
        if ratio is not None:
            critical = max(0.05, min(0.25, ctx.min_hp_ratio * 0.25))
            if ratio < critical:
                self._flee(ctx, image)
                ctx.logger.error(
                    "HP at %.0f%% in the dungeon (safety floor %.0f%%); stopping.",
                    ratio * 100,
                    critical * 100,
                )
                ctx.stop.set()
                return 5.0

        handled = False
        if self._style_switcher is not None:
            handled = self._style_switcher.maybe_apply(ctx, image, style)
        # Melee is handled by the style engine when it recognised the enemy;
        # otherwise keep the old triangle switch as the fallback.
        if not (
            handled
            and self._style_switcher is not None
            and self._style_switcher.auto_style
            and style.word == "melee"
        ):
            self._evaluate_switch(ctx, image, style, now)
        return settings.poll_seconds
    def _flee(self, ctx: TaskContext, image: Image.Image) -> None:
        if not ctx.settings.dungeons.flee_when_out_of_food:
            return
        if not ui.run_from_combat_ready(image):
            return
        ctx.logger.warning("Leaving the dungeon to avoid a death.")
        if self._act(ctx, "click Run from Combat"):
            self._click(ctx, ui.RUN_FROM_COMBAT)
            time.sleep(1.5)

    def _evaluate_switch(
        self, ctx: TaskContext, image: Image.Image, style: ui.CombatStyle, now: float
    ) -> None:
        settings = ctx.settings.dungeons
        if self._pending_style is not None:
            if now - self._pending_since < SWITCH_VERIFY_SECONDS:
                return
            target = self._pending_style
            self._pending_style = None
            if style.word == target:
                ctx.logger.info(
                    "Weapon switch verified: now %s (%s).",
                    STYLE_LABEL.get(target, target),
                    style.advantage,
                )
            else:
                ctx.logger.warning(
                    "Weapon switch to %s did not take effect; backing off.",
                    STYLE_LABEL.get(target, target),
                )
                self._switch_blocked_until = now + SWITCH_BACKOFF_SECONDS
            return

        if style.advantage != ui.DISADVANTAGED:
            return
        target = ui.COUNTER_STYLE.get(style.word or "")
        if target is None:
            return
        weapon = settings.weapons.get(target, "").strip()
        if not weapon:
            return
        if target == "ranged" and not ui.ammo_available(image):
            self._warn(
                ctx,
                "ammo",
                "Ranged is the counter style but the ammo slot is empty; "
                "staying on %s.",
                STYLE_LABEL.get(style.word or "", style.word or "?"),
            )
            return
        if now < self._switch_blocked_until:
            return
        if now - self._last_switch_at < settings.switch_cooldown_minutes * 60.0:
            return

        self._last_switch_at = now
        ctx.logger.info(
            "%s is disadvantaged in the dungeon; equipping %r (%s).",
            STYLE_LABEL.get(style.word or "", style.word or "?"),
            weapon,
            STYLE_LABEL.get(target, target),
        )
        if not self._act(ctx, f"equip {weapon!r} through the bank"):
            return
        try:
            equipment.switch_weapon(ctx.window, ctx.settings.automation, weapon)
        except Exception:
            ctx.logger.exception("Could not equip %r.", weapon)
            self._switch_blocked_until = now + SWITCH_BACKOFF_SECONDS
            return
        self._pending_style = target
        self._pending_since = time.monotonic()
