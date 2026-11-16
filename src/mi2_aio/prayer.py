"""Prayer maintenance: bury banked bones in batches.

Bones are ordinary bank items with the game's ``Bury`` capability. The bot
keeps Prayer points topped up without interrupting every kill:

* bury when enough bones have accumulated
  (``[combat.prayer].bone_threshold``), or
* bury when Prayer points are low and at least one bone is owned
  (``low_prayer_threshold``).

The bury uses the bank's item panel: select the exact bone result, press the
``All`` quantity button, then the ``Bury N Bones`` action. Everything is posted
to the game window, so it works while the game is unfocused.
"""

from __future__ import annotations

import time

from PIL import Image

from . import bones as bone_db
from . import equipment, ui
from .config import PrayerSettings
from .input import background_move, background_type, click_game
from .savefile import SaveHeader, read_header
from .tasks.base import TaskContext
from .window import capture_client, is_minimized

CLEAR_KEYSTROKES = 40
SEARCH_SETTLE_SECONDS = 0.9
SELECT_SETTLE_SECONDS = 0.9
BURY_SETTLE_SECONDS = 1.2
# Duplicate bank stacks of the same bone are possible; each bury removes one
# stack, so allow a generous number of attempts per bone type.
MAX_STACKS_PER_TYPE = 12


def should_bury(
    count: int, prayer_points: int, settings: PrayerSettings
) -> bool:
    """Decide whether a bone batch is due.

    Bury when either threshold is reached. Having no bones never triggers a
    bank visit, which is what keeps the check cheap.
    """
    if count <= 0:
        return False
    if count >= settings.bone_threshold:
        return True
    return (
        settings.low_prayer_threshold > 0
        and prayer_points < settings.low_prayer_threshold
    )


class PrayerMaintenance:
    def __init__(self, settings) -> None:
        self.settings = settings.prayer
        self.bones = bone_db.load_bones()
        self._last_check = float("-inf")

    # -- polling ---------------------------------------------------------
    def poll(self, ctx: TaskContext) -> None:
        if not self.settings.enabled:
            return
        if ctx.header is None or is_minimized(ctx.window.hwnd):
            return
        if ctx.stop.is_set():
            return

        now = time.monotonic()
        if now - self._last_check < self.settings.check_seconds:
            return

        count = self.bones.count(ctx.header.bank_stacks)
        prayer = ctx.header.prayer_points
        if not should_bury(count, prayer, self.settings):
            return

        self._last_check = now
        if ctx.dry_run:
            ctx.logger.info(
                "DRY RUN: would bury %d bone(s) at %d Prayer points.",
                count,
                prayer,
            )
            return

        ctx.logger.info(
            "Prayer upkeep: %d bone(s) banked at %d Prayer points; burying.",
            count,
            prayer,
        )
        try:
            buried, gained, after = self.bury(ctx)
        except Exception:
            ctx.logger.exception("Prayer bury failed; will retry later.")
            self._last_check = time.monotonic()
            return

        self._last_check = time.monotonic()
        if after is not None:
            ctx.logger.info(
                "Prayer upkeep done: buried %d bone(s), +%d Prayer points "
                "(now %d).",
                buried,
                gained,
                after.prayer_points,
            )
        else:
            ctx.logger.warning(
                "Prayer upkeep: could not confirm the bury from the save "
                "(buried about %d bone(s)).",
                buried,
            )

    # -- one bury pass ---------------------------------------------------
    def bury(
        self, ctx: TaskContext
    ) -> tuple[int, int, SaveHeader | None]:
        """Open the bank and bury every owned bone type.

        Returns ``(buried, prayer_gained, final_header)``.
        """
        header = self._read_header(ctx)
        if header is None:
            return 0, 0, None
        if ctx.stop.is_set():
            return 0, 0, header

        equipment.open_bank(ctx.window, ctx.settings.automation)
        buried = 0
        gained = 0
        try:
            for bone, _quantity in self.bones.bone_stacks(header.bank_stacks):
                type_buried, type_gained = self._bury_bone(ctx, bone)
                buried += type_buried
                gained += type_gained
        finally:
            self._restore_page(ctx)
        return buried, gained, self._read_header(ctx)

    def _bury_bone(self, ctx: TaskContext, bone) -> tuple[int, int]:
        buried = 0
        gained = 0
        for _attempt in range(MAX_STACKS_PER_TYPE):
            if ctx.stop.is_set():
                break
            self._wait_if_paused(ctx)
            if ctx.stop.is_set():
                break
            header = self._read_header(ctx)
            if header is None:
                break
            count_before = int(header.bank_stacks.get(bone.id, 0))
            if count_before <= 0:
                break

            index = bone_db.search_index(
                header.bank_order, bone.name.split()[-1], bone.id
            )
            points = ui.bank_grid_points()
            if index is None or index >= len(points):
                ctx.logger.warning(
                    "Could not locate %s in the bank search results.", bone.name
                )
                break

            self._search(ctx, bone.name.split()[-1])
            self._click(ctx, points[index])
            time.sleep(SELECT_SETTLE_SECONDS)
            if not ui.bank_bury_row_visible(self._capture(ctx)):
                # Duplicate stacks can make the computed index point at a
                # neighbouring item after a previous stack was buried. Scan
                # the results for the bury panel rather than giving up.
                if not self._select_bury_result(ctx):
                    ctx.logger.warning(
                        "The bank panel for %s did not show a Bury action.",
                        bone.name,
                    )
                    break

            prayer_before = header.prayer_points
            self._click(ctx, ui.BANK_BURY_ALL)
            time.sleep(0.5)
            self._click(ctx, ui.BANK_BURY_ROW)
            time.sleep(BURY_SETTLE_SECONDS)

            after = self._wait_for_bury(
                ctx, bone.id, count_before, prayer_before
            )
            if after is None:
                ctx.logger.warning(
                    "Burying %s was not confirmed by the save; stopping this "
                    "bone type to avoid bank spam.",
                    bone.name,
                )
                break

            count_after = int(after.bank_stacks.get(bone.id, 0))
            buried += max(0, count_before - count_after)
            gained += max(0, after.prayer_points - prayer_before)
            if count_after <= 0:
                break
        return buried, gained

    # -- helpers ---------------------------------------------------------
    def _wait_if_paused(self, ctx: TaskContext) -> None:
        pause = ctx.pause
        if pause is None:
            return
        while pause.is_set() and not ctx.stop.is_set():
            time.sleep(0.2)

    def _read_header(self, ctx: TaskContext) -> SaveHeader | None:
        try:
            return read_header(settings=ctx.settings)
        except Exception:
            ctx.logger.debug("Could not read the save during prayer upkeep",
                             exc_info=True)
            return None

    def _wait_for_bury(
        self,
        ctx: TaskContext,
        bone_id: str,
        count_before: int,
        prayer_before: int,
    ) -> SaveHeader | None:
        deadline = time.monotonic() + self.settings.verify_seconds
        while time.monotonic() < deadline:
            if ctx.stop.is_set():
                return None
            time.sleep(1.0)
            header = self._read_header(ctx)
            if header is None:
                continue
            if (
                header.prayer_points > prayer_before
                or int(header.bank_stacks.get(bone_id, 0)) < count_before
            ):
                return header
        return None

    def _select_bury_result(self, ctx: TaskContext) -> bool:
        """Select the first search result whose panel shows Bury Item."""
        for point in ui.bank_grid_points():
            if ctx.stop.is_set():
                return False
            image = self._capture(ctx)
            if not ui.bank_cell_has_item(image, point):
                continue
            self._click(ctx, point)
            time.sleep(SELECT_SETTLE_SECONDS)
            if ui.bank_bury_row_visible(self._capture(ctx)):
                return True
        return False

    def _search(self, ctx: TaskContext, term: str) -> None:
        self._click(ctx, ui.BANK_SEARCH_BOX)
        time.sleep(0.3)
        background_type(
            ctx.window, term, ctx.settings.automation, clear=CLEAR_KEYSTROKES
        )
        time.sleep(SEARCH_SETTLE_SECONDS)

    def _restore_page(self, ctx: TaskContext) -> None:
        """Return to the current action's page after the bank visit."""
        self._click(ctx, ui.ACTIVE_ACTION_BUTTON)
        time.sleep(1.5)
        if not ui.bank_open(self._capture(ctx)):
            return
        target = ui.PAGE_TARGETS.get(ctx.page or "")
        if target is None:
            return
        self._click(ctx, target)
        time.sleep(0.9)

    def _capture(self, ctx: TaskContext) -> Image.Image:
        x, y = ui.to_client(*ui.CURSOR_PARK, ctx.window.client_area)
        try:
            background_move(
                ctx.window, x, y, ctx.settings.automation, settle=False
            )
        except Exception:
            pass
        time.sleep(0.2)
        return ui.normalize(capture_client(ctx.window))

    def _click(self, ctx: TaskContext, point: tuple[int, int]) -> None:
        x, y = ui.to_client(*point, ctx.window.client_area)
        click_game(ctx.window, x, y, ctx.settings.automation)
