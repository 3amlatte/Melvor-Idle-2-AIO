"""Slayer task automation.

Every poll captures the combat page, then:

* task monster changed  -> click **Jump To Enemy**
* progress stalled      -> jump once per ``stall_minutes``; stop after
  ``max_stalls`` consecutive stalls
* combat style disadvantaged (orange-red label) -> equip the counter style's
  weapon through the bank, then verify the triangle flipped
* Eat button disabled   -> stop when ``stop_when_out_of_food`` is set

No OCR is involved: the style word is matched against three glyph templates and
the advantage colour comes from the game's own green/orange-red tint.
"""

from __future__ import annotations

import time

from .. import equipment, ui
from ..savefile import SaveHeader
from ..style_switch import StyleSwitcher
from ..window import capture_client, is_minimized
from .base import Task, TaskContext

STYLE_LABEL = {"melee": "Melee", "ranged": "Ranged", "magic": "Magic"}

# How long to wait after a weapon switch before judging the result.
SWITCH_VERIFY_SECONDS = 3.0
# After a failed switch, leave the weapon alone for this long.
SWITCH_BACKOFF_SECONDS = 600.0
# Consecutive polls that must see a disabled Eat button before stopping.
NO_FOOD_POLLS = 2
# Give up waiting for the combat page after this long.
INIT_TIMEOUT_SECONDS = 90.0


class SlayerTask(Task):
    name = "slayer"
    description = (
        "Keep the current slayer task running: jump to the task enemy, switch "
        "to a counter weapon when disadvantaged, stop when food runs out."
    )
    page = "combat"

    def __init__(self) -> None:
        self._initialized = False
        self._init_started_at = 0.0
        self._task_sig: bytes | None = None
        self._progress_sig: bytes | None = None
        self._last_progress_at = 0.0
        self._stalls = 0
        self._last_jump_at = float("-inf")
        self._last_switch_at = float("-inf")
        self._switch_blocked_until = 0.0
        self._pending_style: str | None = None
        self._pending_from: str | None = None
        self._pending_since = 0.0
        self._switch_from: str | None = None
        self._switch_to: str | None = None
        self._switch_at = 0.0
        self._switch_progress_sig: bytes | None = None
        self._blocked_targets: set[str] = set()
        self._no_food_polls = 0
        self._last_page_click = float("-inf")
        self._page_fix_stage = 0
        self._warned_at: dict[str, float] = {}
        self._last_header: SaveHeader | None = None
        self._style_switcher: StyleSwitcher | None = None
        self._slayer_key: tuple[str, str, int] | None = None
        self._slayer_progress = 0
        self._counted_complete_key: tuple[str, str, int] | None = None
        self._completed_tasks = 0

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

    def _capture(self, ctx: TaskContext):
        # Park the game's notion of the cursor so hover styles do not change
        # the colours we sample (buttons turn olive while hovered).
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

    # -- task completion -------------------------------------------------
    def _count_completion(
        self,
        ctx: TaskContext,
        state,
        reason: str,
        previous_key: tuple[str, str, int] | None,
    ) -> None:
        self._completed_tasks += 1
        max_tasks = ctx.settings.slayer.max_tasks
        suffix = f"/{max_tasks}" if max_tasks else ""
        prev_master, prev_enemy, prev_length = previous_key or (
            "?",
            "?",
            "?",
        )
        ctx.logger.info(
            "Slayer task completed (%d%s, %s): %s %s/%s -> %s %s/%s.",
            self._completed_tasks,
            suffix,
            reason,
            prev_master,
            prev_enemy,
            prev_length,
            state.master,
            state.enemy_id,
            state.length,
        )
        if max_tasks > 0 and self._completed_tasks >= max_tasks:
            ctx.logger.info(
                "Completed %d Slayer task(s); stopping the run.", max_tasks
            )
            ctx.stop.set()

    def _check_task_completion(self, ctx: TaskContext) -> None:
        """Track exact Slayer task progress from the save.

        The game immediately assigns a new task on completion. A new task is
        detected by a changed (master, enemy, length) key, a progress reset on
        the same key, or a saved progress equal to the task length.
        """
        header = ctx.header
        state = header.slayer_task if header is not None else None
        if state is None:
            return

        if self._slayer_key is None:
            self._slayer_key = state.key
            self._slayer_progress = state.progress
            ctx.logger.info(
                "Slayer task: %s %s %d/%d.",
                state.master,
                state.enemy_id,
                state.progress,
                state.length,
            )
            return

        # A completed task that is still visible in the save. Count it once.
        if self._counted_complete_key is not None:
            if state.key == self._counted_complete_key:
                self._slayer_progress = state.progress
                return
            # The completed task has been replaced; do not double-count it.
            self._counted_complete_key = None
            self._slayer_key = state.key
            self._slayer_progress = state.progress
            return

        if state.progress >= state.length:
            self._counted_complete_key = state.key
            self._count_completion(
                ctx, state, "progress reached length", self._slayer_key
            )
            self._slayer_key = state.key
            self._slayer_progress = state.progress
            return

        if state.key != self._slayer_key:
            self._count_completion(ctx, state, "new task", self._slayer_key)
        elif state.progress < self._slayer_progress:
            self._count_completion(
                ctx, state, "progress reset", self._slayer_key
            )
        self._slayer_key = state.key
        self._slayer_progress = state.progress

    def _fix_combat_page(self, ctx: TaskContext) -> None:
        """Open the Combat page, then its Offensive Stats tab.

        The stats panel (where the combat style is shown) is one tab of the
        combat page's middle panel; if another tab is selected the style is
        unreadable. Alternating the two clicks recovers both cases.
        """
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
        slayer = ctx.settings.slayer
        ctx.logger.info(
            "Slayer automation: jump_on_start=%s, stop_when_out_of_food=%s, "
            "stall=%.0f min x%d, switch cooldown=%.1f min",
            slayer.jump_on_start,
            slayer.stop_when_out_of_food,
            slayer.stall_minutes,
            slayer.max_stalls,
            slayer.switch_cooldown_minutes,
        )
        weapons = {key: name for key, name in slayer.weapons.items() if name.strip()}
        ctx.logger.info(
            "Counter weapons: %s",
            ", ".join(f"{key}={name!r}" for key, name in weapons.items()) or "none",
        )
        self._style_switcher = StyleSwitcher(
            auto_style=slayer.auto_style,
            auto_armour=slayer.auto_armour,
            armour_check_minutes=slayer.armour_check_minutes,
            switch_cooldown_seconds=slayer.style_switch_cooldown_seconds,
        )
        ctx.logger.info(
            "Melee style choice: %s (save enemy id + data/enemies.json); "
            "armour upgrades: %s.",
            "on" if slayer.auto_style else "off",
            "on" if slayer.auto_armour else "off",
        )
        if slayer.max_tasks:
            ctx.logger.info(
                "Stopping after %d completed Slayer task(s).",
                slayer.max_tasks,
            )
        self._slayer_key = None
        self._slayer_progress = 0
        self._counted_complete_key = None
        self._completed_tasks = 0
        self._init_started_at = time.monotonic()
        self._last_progress_at = self._init_started_at

    def on_save(self, ctx: TaskContext, header: SaveHeader) -> None:
        previous = self._last_header
        self._last_header = header
        if previous is not None and header.active_action != previous.active_action:
            ctx.logger.info(
                "Save: active action %r -> %r",
                previous.active_action,
                header.active_action,
            )

    def stop(self, ctx: TaskContext) -> None:
        ctx.logger.info("Slayer task stopped.")

    @property
    def completed_tasks(self) -> int:
        return self._completed_tasks

    # -- main loop -------------------------------------------------------
    def step(self, ctx: TaskContext) -> float | None:
        now = time.monotonic()
        if is_minimized(ctx.window.hwnd):
            ctx.logger.error(
                "Game window is minimized. Restore it (covered or off-screen "
                "is fine); minimized windows capture black and cannot receive "
                "clicks. Stopping."
            )
            ctx.stop.set()
            return 5.0
        self._check_task_completion(ctx)
        if ctx.stop.is_set():
            return 5.0
        image = self._capture(ctx)
        style = ui.read_combat_style(image)

        if not self._initialized:
            return self._initialize(ctx, image, style, now)

        if not style.readable:
            self._warn(
                ctx,
                "page",
                "Combat page not readable (bank, menu or another page open); "
                "opening the Combat tab.",
                every=20.0,
            )
            if now - self._last_page_click >= 5.0:
                self._last_page_click = now
                self._fix_combat_page(ctx)
            return 1.5

        # Food safety net: the game disables Eat when the selected food is gone.
        food = ui.eat_button_state(image)
        if food == "disabled":
            self._no_food_polls += 1
            if self._no_food_polls >= NO_FOOD_POLLS:
                if ctx.settings.slayer.stop_when_out_of_food:
                    self._flee(ctx, image)
                    ctx.logger.error(
                        "Out of food: the Eat button is disabled. Stopping the run."
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
        else:
            self._warn(
                ctx,
                "food_covered",
                "Eat button is covered (food picker or tooltip); cannot read the food state.",
                every=120.0,
            )

        # HP backstop. Auto-eat keeps HP near its threshold, so only a much
        # lower value means something is genuinely wrong.
        ratio = ui.hp_ratio(image)
        if ratio is not None:
            critical = max(0.05, min(0.25, ctx.min_hp_ratio * 0.25))
            if ratio < critical:
                self._flee(ctx, image)
                ctx.logger.error(
                    "HP at %.0f%% (safety floor %.0f%%). Stopping.",
                    ratio * 100,
                    critical * 100,
                )
                ctx.stop.set()
                return 5.0
            if ratio < ctx.min_hp_ratio:
                self._warn(
                    ctx,
                    "hp",
                    "HP at %.0f%% is below the mode floor %.0f%%; auto-eat is "
                    "handling it, watching for the critical floor.",
                    ratio * 100,
                    ctx.min_hp_ratio * 100,
                    every=300.0,
                )

        ammo_ok = ui.ammo_available(image)
        handled = False
        if self._style_switcher is not None:
            handled = self._style_switcher.maybe_apply(ctx, image, style)
        # When auto style is on and it recognised the enemy, melee is owned by
        # the style engine; otherwise the old triangle switch remains the
        # fallback.
        if not (
            handled
            and self._style_switcher is not None
            and self._style_switcher.auto_style
            and style.word == "melee"
        ):
            self._evaluate_switch(ctx, image, style, now, ammo_ok)
        self._track_task(ctx, image, now)
        self._check_switch_grace(ctx, image, now, ammo_ok)
        if style.word == "ranged" and not ammo_ok:
            self._recover_from_empty_ammo(ctx, style, now)
        return ctx.settings.slayer.poll_seconds

    # -- weapon switching ------------------------------------------------
    def _evaluate_switch(
        self,
        ctx: TaskContext,
        image,
        style: ui.CombatStyle,
        now: float,
        ammo_ok: bool,
    ) -> None:
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
                self._switch_from = self._pending_from
                self._switch_to = target
                self._switch_at = now
                self._switch_progress_sig = ui.region_hash(
                    image, ui.TASK_PROGRESS_BOX
                )
            else:
                ctx.logger.warning(
                    "Weapon switch to %s did not take effect "
                    "(style=%s, %s); backing off for %.0f minutes.",
                    STYLE_LABEL.get(target, target),
                    STYLE_LABEL.get(style.word or "unknown", "unknown"),
                    style.advantage,
                    SWITCH_BACKOFF_SECONDS / 60.0,
                )
                self._blocked_targets.add(target)
                self._switch_blocked_until = now + SWITCH_BACKOFF_SECONDS
            return

        if style.advantage != ui.DISADVANTAGED:
            return

        target = ui.COUNTER_STYLE.get(style.word or "")
        if target is None:
            self._warn(
                ctx,
                "unknown_style",
                "Combat style is disadvantaged but the style word was not "
                "recognised; cannot pick a counter weapon.",
                every=600.0,
            )
            return

        if target in self._blocked_targets:
            self._warn(
                ctx,
                f"blocked_{target}",
                "%s is disadvantaged but switching to %s did not help on this "
                "task; leaving the weapon alone.",
                STYLE_LABEL.get(style.word or "", style.word or "?"),
                STYLE_LABEL.get(target, target),
                every=600.0,
            )
            return

        weapon = ctx.settings.slayer.weapons.get(target, "").strip()
        if not weapon:
            self._warn(
                ctx,
                f"weapon_{target}",
                "%s is disadvantaged and no %s weapon is configured "
                "([slayer.weapons]); leaving the weapon alone.",
                STYLE_LABEL.get(style.word or "", style.word or "?"),
                STYLE_LABEL.get(target, target),
                every=600.0,
            )
            return

        if target == "ranged" and not ammo_ok:
            alternative = next(
                (s for s in ui.STYLES if s not in (style.word, target)), None
            )
            alt_weapon = (
                ctx.settings.slayer.weapons.get(alternative or "", "").strip()
            )
            if (
                alternative
                and alt_weapon
                and alternative not in self._blocked_targets
            ):
                ctx.logger.info(
                    "Ranged needs ammo and the ammo slot is empty; using %s "
                    "instead of Ranged.",
                    STYLE_LABEL.get(alternative, alternative),
                )
                target = alternative
                weapon = alt_weapon
            else:
                self._warn(
                    ctx,
                    "no_ammo",
                    "Ranged is the counter style but the ammo slot is empty; "
                    "staying on %s.",
                    STYLE_LABEL.get(style.word or "", style.word or "?"),
                    every=300.0,
                )
                return

        if now < self._switch_blocked_until:
            return
        cooldown = ctx.settings.slayer.switch_cooldown_minutes * 60.0
        if now - self._last_switch_at < cooldown:
            return

        self._last_switch_at = now
        ctx.logger.info(
            "%s is disadvantaged against this enemy; equipping %r (%s).",
            STYLE_LABEL.get(style.word or "", style.word or "?"),
            weapon,
            STYLE_LABEL.get(target, target),
        )
        if not self._act(ctx, f"equip {weapon!r} through the bank"):
            return
        try:
            equipment.switch_weapon(ctx.window, ctx.settings.automation, weapon)
        except Exception:
            ctx.logger.exception(
                "Could not equip %r; backing off for %.0f minutes.",
                weapon,
                SWITCH_BACKOFF_SECONDS / 60.0,
            )
            self._switch_blocked_until = time.monotonic() + SWITCH_BACKOFF_SECONDS
            return
        self._pending_style = target
        self._pending_from = style.word
        self._pending_since = time.monotonic()

    def _check_switch_grace(
        self, ctx: TaskContext, image, now: float, ammo_ok: bool
    ) -> None:
        """Undo a switch that produced no task progress.

        The combat triangle can recommend a style the character cannot use
        (for example a weapon above its level). If kills do not resume within
        the grace window, put the previous weapon back and stop trying that
        style for the rest of the task.
        """
        if self._switch_to is None:
            return
        grace = ctx.settings.slayer.switch_grace_minutes * 60.0
        if now - self._switch_at < grace:
            return

        current = ui.region_hash(image, ui.TASK_PROGRESS_BOX)
        if current != self._switch_progress_sig:
            ctx.logger.info(
                "Progress resumed on %s; keeping the new weapon.",
                STYLE_LABEL.get(self._switch_to, self._switch_to),
            )
            self._switch_to = None
            return

        target = self._switch_to
        previous = self._switch_from
        self._switch_to = None
        self._blocked_targets.add(target)

        weapon = ctx.settings.slayer.weapons.get(previous or "", "").strip()
        if previous == "ranged" and not ammo_ok:
            self._warn(
                ctx,
                f"revert_{target}",
                "No progress since switching to %s, and Ranged has no ammo to "
                "revert to.",
                STYLE_LABEL.get(target, target),
                every=600.0,
            )
            return
        if not weapon:
            self._warn(
                ctx,
                f"revert_{target}",
                "No progress since switching to %s, and no %s weapon is "
                "configured to revert to.",
                STYLE_LABEL.get(target, target),
                STYLE_LABEL.get(previous or "", previous or "?"),
                every=600.0,
            )
            return

        ctx.logger.warning(
            "No slayer progress since switching to %s; reverting to %r (%s) "
            "and leaving that style alone for this task.",
            STYLE_LABEL.get(target, target),
            weapon,
            STYLE_LABEL.get(previous or "", previous or "?"),
        )
        if not self._act(ctx, f"equip {weapon!r} to revert the switch"):
            return
        try:
            equipment.switch_weapon(ctx.window, ctx.settings.automation, weapon)
        except Exception:
            ctx.logger.exception("Could not revert to %r.", weapon)
            self._switch_blocked_until = time.monotonic() + SWITCH_BACKOFF_SECONDS
            return
        self._last_switch_at = time.monotonic()
        self._switch_blocked_until = time.monotonic() + SWITCH_BACKOFF_SECONDS

    def _recover_from_empty_ammo(
        self, ctx: TaskContext, style: ui.CombatStyle, now: float
    ) -> None:
        """A bow with an empty ammo slot cannot fire: fall back to melee."""
        if self._pending_style is not None:
            return
        if now < self._switch_blocked_until:
            return
        cooldown = ctx.settings.slayer.switch_cooldown_minutes * 60.0
        if now - self._last_switch_at < cooldown:
            return

        target = "melee"
        weapon = ctx.settings.slayer.weapons.get(target, "").strip()
        if not weapon:
            self._warn(
                ctx,
                "ammo_fallback",
                "Ranged weapon has no ammo and no melee weapon is configured; "
                "cannot recover.",
                every=300.0,
            )
            return

        self._last_switch_at = now
        ctx.logger.warning(
            "Ranged weapon has no ammo in the ammo slot; equipping %r (%s).",
            weapon,
            STYLE_LABEL[target],
        )
        if not self._act(ctx, f"equip {weapon!r} because the ammo slot is empty"):
            return
        try:
            equipment.switch_weapon(ctx.window, ctx.settings.automation, weapon)
        except Exception:
            ctx.logger.exception(
                "Could not equip %r; backing off for %.0f minutes.",
                weapon,
                SWITCH_BACKOFF_SECONDS / 60.0,
            )
            self._switch_blocked_until = time.monotonic() + SWITCH_BACKOFF_SECONDS
            return
        self._pending_style = target
        self._pending_from = style.word
        self._pending_since = time.monotonic()

    # -- task panel ------------------------------------------------------
    def _track_task(self, ctx: TaskContext, image, now: float) -> None:
        slayer = ctx.settings.slayer

        if not ui.jump_button_ready(image):
            self._warn(
                ctx,
                "no_task",
                "No slayer task is shown (Jump To Enemy is not enabled).",
                every=600.0,
            )
            self._task_sig = None
            self._progress_sig = None
            self._last_progress_at = now
            return

        name_sig = ui.region_hash(image, ui.TASK_NAME_BOX)
        progress_sig = ui.region_hash(image, ui.TASK_PROGRESS_BOX)

        if self._task_sig is None:
            self._task_sig = name_sig
            self._progress_sig = progress_sig
            self._last_progress_at = now
            return

        if name_sig != self._task_sig:
            ctx.logger.info("New slayer task detected; jumping to the task enemy.")
            self._task_sig = name_sig
            self._progress_sig = progress_sig
            self._last_progress_at = now
            self._stalls = 0
            # A different enemy can favour the style we gave up on.
            self._blocked_targets.clear()
            self._switch_to = None
            self._switch_from = None
            if self._style_switcher is not None:
                self._style_switcher.reset()
            self._jump(ctx, now)
            return

        if progress_sig != self._progress_sig:
            self._progress_sig = progress_sig
            self._last_progress_at = now
            self._stalls = 0
            return

        if now - self._last_progress_at < slayer.stall_minutes * 60.0:
            return

        self._stalls += 1
        if self._stalls > slayer.max_stalls:
            ctx.logger.error(
                "Slayer progress has not moved for %.0f minutes after %d jump(s); stopping.",
                slayer.stall_minutes,
                self._stalls - 1,
            )
            ctx.stop.set()
            return

        ctx.logger.warning(
            "No slayer progress for %.0f minutes; jumping to the task enemy (%d/%d).",
            slayer.stall_minutes,
            self._stalls,
            slayer.max_stalls,
        )
        self._last_progress_at = now
        self._jump(ctx, now)

    def _jump(self, ctx: TaskContext, now: float) -> bool:
        if now - self._last_jump_at < ctx.settings.slayer.jump_cooldown_seconds:
            return False
        if not self._act(ctx, "click Jump To Enemy"):
            return False
        self._last_jump_at = now
        self._click(ctx, ui.JUMP_BUTTON)
        time.sleep(1.0)
        return True

    def _flee(self, ctx: TaskContext, image) -> None:
        """Leave combat so a character with no food does not die idle."""
        if not ctx.settings.slayer.flee_when_out_of_food:
            return
        if not ui.run_from_combat_ready(image):
            return
        ctx.logger.warning(
            "Leaving combat so the character is not left fighting without food."
        )
        if not self._act(ctx, "click Run from Combat"):
            return
        self._click(ctx, ui.RUN_FROM_COMBAT)
        time.sleep(1.5)

    # -- startup ---------------------------------------------------------
    def _initialize(
        self, ctx: TaskContext, image, style: ui.CombatStyle, now: float
    ) -> float:
        if not style.readable:
            if now - self._init_started_at > INIT_TIMEOUT_SECONDS:
                raise RuntimeError(
                    "The Combat page never appeared. Open the Combat tab and "
                    "keep the game unminimized."
                )
            self._warn(
                ctx,
                "init_page",
                "Waiting for the Combat page; opening the Combat tab.",
                every=15.0,
            )
            self._fix_combat_page(ctx)
            return 2.0

        self._initialized = True
        ratio = ui.hp_ratio(image)
        ctx.logger.info(
            "Combat page ready: style %s (%s), HP %s, food %s, ammo %s, "
            "task panel %s.",
            STYLE_LABEL.get(style.word or "", style.word or "unknown"),
            style.advantage,
            f"{ratio:.0%}" if ratio is not None else "unknown",
            ui.eat_button_state(image),
            "yes" if ui.ammo_available(image) else "none",
            "visible" if ui.jump_button_ready(image) else "missing",
        )

        if ctx.settings.slayer.jump_on_start and ui.jump_button_ready(image):
            ctx.logger.info("Jumping to the task enemy once at startup.")
            self._jump(ctx, now)

        self._track_task(ctx, image, time.monotonic())
        return 1.0
