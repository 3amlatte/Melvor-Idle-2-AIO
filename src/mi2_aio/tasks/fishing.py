"""Fish a chosen spot: open Fishing, pick the location and spot, then start.

The page is driven by the **Select Location** bar, its location cards, the
**Select Spot** dropdown and the green **Start Fishing** button. The save header
reports the active spot's display name, which is the authoritative success
check; the panel's green/gold button is the immediate visual signal.

Per-run choices arrive in ``ctx.options``:

``location``
    Location id or display name (for example ``ShallowShores``).
``spot``
    Spot id or display name inside that location (for example ``CalmShallows``).

Unknown, demo-locked or missing choices fall back to the first available
location and spot, so a bare ``--task fishing`` run still works.
"""

from __future__ import annotations

import time

from .. import ui
from ..fishing_db import (
    FishingDatabase,
    FishingLocation,
    FishingSpot,
    load_fishing,
)
from ..window import capture_client, is_minimized
from .base import Task, TaskContext

POLL_SECONDS = 2.0
# The save autosaves every few seconds; give it time to report the new spot
# before deciding the Start click failed and selecting again.
CONFIRM_SECONDS = 22.0
# Attempts before stopping. Each attempt re-selects the location and spot, so a
# level-locked or demo-locked choice produces a clear error instead of an
# endless click loop.
MAX_ATTEMPTS = 3


class FishingTask(Task):
    name = "fishing"
    description = (
        "Open the Fishing page, select a location and fishing spot, and start "
        "fishing the fish that spot provides."
    )
    page = "fishing"
    changes_action = True

    def __init__(self) -> None:
        self._db: FishingDatabase | None = None
        self._location: FishingLocation | None = None
        self._spot: FishingSpot | None = None
        self._location_index = 0
        self._spot_index = 0
        self._attempts = 0
        self._last_attempt = float("-inf")
        self._active_logged = False
        self._dry_run_logged = False
        self._start_logged = False

    # -- lifecycle -------------------------------------------------------
    def start(self, ctx: TaskContext) -> None:
        db = load_fishing()
        location = self._pick_location(db, str(ctx.options.get("location", "")))
        spot = self._pick_spot(location, str(ctx.options.get("spot", "")))
        self._db = db
        self._location = location
        self._spot = spot
        self._location_index = db.locations.index(location)
        self._spot_index = location.available_spots.index(spot)
        fish = ", ".join(
            f"{item.name} {item.chance:.0%}" for item in spot.fish
        ) or "no fish"
        ctx.logger.info(
            "Fishing: %s -> %s (level %d, %.0f%% fish chance, %s, XP %d) | %s",
            location.name,
            spot.name,
            spot.level,
            spot.fish_chance * 100,
            spot.interval_label,
            spot.experience,
            fish,
        )
        if spot.level > self._fishing_level(ctx):
            ctx.logger.warning(
                "Fishing level is below %d, so %s may stay locked. The task "
                "will stop after %d attempts.",
                spot.level,
                spot.name,
                MAX_ATTEMPTS,
            )

    def stop(self, ctx: TaskContext) -> None:
        ctx.logger.info("Fishing task stopped.")

    # -- options ---------------------------------------------------------
    def _pick_location(
        self, db: FishingDatabase, wanted: str
    ) -> FishingLocation:
        available = db.available_locations()
        if wanted:
            found = db.location(wanted)
            if found is not None and not found.demo_locked:
                return found
        return available[0]

    def _pick_spot(
        self, location: FishingLocation, wanted: str
    ) -> FishingSpot:
        spots = location.available_spots
        if wanted:
            lowered = wanted.strip().lower()
            for spot in spots:
                if spot.id.lower() == lowered or spot.name.lower() == lowered:
                    return spot
        return spots[0]

    @staticmethod
    def _fishing_level(ctx: TaskContext) -> int:
        try:
            from ..savefile import read_skills

            levels = read_skills(settings=ctx.settings)
        except Exception:
            return 0
        skill = levels.skills.get("Fishing")
        return skill.level if skill is not None else 0

    # -- main loop -------------------------------------------------------
    def step(self, ctx: TaskContext) -> float | None:
        if self._location is None or self._spot is None:
            return None
        if is_minimized(ctx.window.hwnd):
            ctx.logger.error(
                "Game window is minimized; the fishing page cannot be read or "
                "clicked. Stopping."
            )
            ctx.stop.set()
            return 5.0

        image = self._capture(ctx)
        if not ui.fishing_page_open(image):
            if self._act(ctx, "open the Fishing page"):
                self._click(ctx, ui.FISH_ICON)
            return 1.4

        action = (ctx.header.active_action if ctx.header else "").strip()
        if action.lower() == self._spot.name.lower():
            if not self._active_logged:
                self._active_logged = True
                ctx.logger.info(
                    "Fishing active: %s at %s.",
                    self._spot.name,
                    self._location.name,
                )
            return 5.0

        now = time.monotonic()
        if self._last_attempt and now - self._last_attempt < CONFIRM_SECONDS:
            if (
                not ui.fishing_start_visible(image)
                and not self._start_logged
            ):
                self._start_logged = True
                ctx.logger.info(
                    "Start Fishing clicked; waiting for the save to confirm "
                    "%s.",
                    self._spot.name,
                )
            return POLL_SECONDS

        known = self._known_spots()
        if action.lower() not in known and action:
            ctx.logger.info(
                "Switching from %r to %s.", action, self._spot.name
            )

        if not self._act(ctx, "select the location and spot"):
            return 5.0

        if self._attempts >= MAX_ATTEMPTS:
            ctx.logger.error(
                "Could not start %s at %s after %d attempts. Check that the "
                "location and spot are unlocked (the spot needs Fishing level "
                "%d) and that the game window accepts clicks. Stopping the "
                "fishing task.",
                self._spot.name,
                self._location.name,
                MAX_ATTEMPTS,
                self._spot.level,
            )
            ctx.stop.set()
            return 5.0

        self._apply_selection(ctx, image)
        self._attempts += 1
        self._last_attempt = time.monotonic()
        self._start_logged = False
        return 1.5

    def _known_spots(self) -> set[str]:
        if self._db is None:
            return set()
        return {name.lower() for name in self._db.spot_names()}

    # -- navigation ------------------------------------------------------
    def _apply_selection(self, ctx: TaskContext, image) -> None:
        assert self._location is not None
        assert self._spot is not None
        if not ui.fishing_cards_visible(image):
            ctx.logger.debug("Opening the fishing location cards.")
            self._click(ctx, ui.FISH_LOCATION_BAR)
            time.sleep(1.0)
            image = self._capture(ctx)
            if not ui.fishing_cards_visible(image):
                # A second click restores the bar if the first one toggled it
                # closed while the capture was still settling.
                self._click(ctx, ui.FISH_LOCATION_BAR)
                time.sleep(1.0)

        ctx.logger.info(
            "Selecting %s (card %d) and %s (spot %d).",
            self._location.name,
            self._location_index + 1,
            self._spot.name,
            self._spot_index + 1,
        )
        # Click the card twice. An open Select Spot menu swallows the first
        # click (it only closes the menu), so a second click is required to
        # actually select the location. When the menu is already closed the
        # second click just keeps the same card selected.
        self._click(ctx, ui.fishing_location_point(self._location_index))
        time.sleep(0.8)
        self._click(ctx, ui.fishing_location_point(self._location_index))
        time.sleep(1.0)

        # Opening the menu can be swallowed while the game finishes switching
        # the location, so verify it actually expanded before clicking a row.
        for _attempt in range(3):
            if not ui.fishing_spot_menu_open(self._capture(ctx)):
                self._click(ctx, ui.FISH_SPOT_DROPDOWN)
                time.sleep(0.8)
            else:
                break

        self._click(ctx, ui.fishing_spot_point(self._spot_index))
        time.sleep(1.0)
        if ui.fishing_spot_menu_open(self._capture(ctx)):
            # The row click did not register; click it once more.
            self._click(ctx, ui.fishing_spot_point(self._spot_index))
            time.sleep(0.9)

        for _attempt in range(2):
            if not ui.fishing_start_visible(self._capture(ctx)):
                break
            # The big green Start Fishing button ignores posted window
            # messages; only a real cursor click starts the action.
            self._click_foreground(ctx, ui.FISH_START_BUTTON)
            time.sleep(1.6)

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

    def _click_foreground(
        self, ctx: TaskContext, point: tuple[int, int]
    ) -> None:
        x, y = ui.to_client(*point, ctx.window.client_area)
        from ..input import click_client
        from ..window import focus

        try:
            if not focus(ctx.window.hwnd):
                raise OSError("could not focus the game window")
            time.sleep(0.3)
            # Windows/Godot can swallow the first real click after another
            # window owned the foreground. Spend it on a harmless point (open
            # water) so the Start click always lands on the button.
            park_x, park_y = ui.to_client(
                *ui.CURSOR_PARK, ctx.window.client_area
            )
            click_client(
                ctx.window,
                park_x,
                park_y,
                ctx.settings.automation,
                focus_first=False,
            )
            time.sleep(0.35)
            click_client(
                ctx.window, x, y, ctx.settings.automation, focus_first=False
            )
        except Exception as exc:
            ctx.logger.warning(
                "Foreground click failed (%s); falling back to background "
                "input.",
                exc,
            )
            self._click(ctx, point)

    def _act(self, ctx: TaskContext, description: str) -> bool:
        if ctx.dry_run:
            if not self._dry_run_logged:
                self._dry_run_logged = True
                assert self._location is not None
                assert self._spot is not None
                ctx.logger.info(
                    "DRY RUN: would open Fishing, select %s -> %s and click "
                    "Start Fishing.",
                    self._location.name,
                    self._spot.name,
                )
            return False
        return True
