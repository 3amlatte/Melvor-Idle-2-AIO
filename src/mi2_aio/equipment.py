"""Change equipment through the bank.

Loadouts beyond the first are shop unlocks, so the portable way to change a
weapon is: open the bank, filter with the search box, pick the first result and
press the item's "Equip To" row. Every step is a posted window message, so it
works while the game is unfocused. Verified against the demo build.

The bank search box is a Godot ``LineEdit``: a posted click focuses it and
posted ``WM_CHAR`` characters reach it without the window being active.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PIL import Image

from . import ui
from .config import AutomationSettings
from .input import background_type, click_game
from .window import WindowInfo, capture_client

BANK_OPEN_TIMEOUT = 8.0
CLEAR_KEYSTROKES = 40


@dataclass(frozen=True)
class BankTarget:
    """An exact bank search result: term plus zero-based grid index."""

    name: str
    search: str
    index: int


class EquipmentError(RuntimeError):
    """Raised when a weapon cannot be equipped through the bank."""


def _click(
    win: WindowInfo, point: tuple[int, int], settings: AutomationSettings
) -> None:
    x, y = ui.to_client(*point, win.client_area)
    click_game(win, x, y, settings)


def _capture(win: WindowInfo) -> Image.Image:
    return ui.normalize(capture_client(win))


def open_bank(
    win: WindowInfo, settings: AutomationSettings, *, timeout: float = BANK_OPEN_TIMEOUT
) -> None:
    """Open the bank page, tolerating the nav button's toggle behaviour."""
    deadline = time.monotonic() + timeout
    attempts = 0
    while time.monotonic() < deadline:
        if ui.bank_open(_capture(win)):
            return
        if attempts >= 3:
            break
        attempts += 1
        _click(win, ui.NAV_BANK, settings)
        # The bank page animates in; poll instead of clicking again too soon,
        # which would toggle the already-opening page closed.
        settle = min(deadline, time.monotonic() + 2.5)
        while time.monotonic() < settle:
            time.sleep(0.25)
            if ui.bank_open(_capture(win)):
                return
    raise EquipmentError("Could not open the bank page.")


def close_bank(win: WindowInfo, settings: AutomationSettings) -> None:
    _click(win, ui.NAV_COMBAT, settings)
    time.sleep(0.8)


def _equip_open_bank_item(
    win: WindowInfo, settings: AutomationSettings, item_name: str
) -> bool:
    """Search the already-open bank and equip the first result.

    Returns False when the bank has no result (the item is not owned). The bank
    page is left open so a caller can equip several items with one visit.
    """
    item_name = item_name.strip()
    if not item_name:
        return False
    _click(win, ui.BANK_SEARCH_BOX, settings)
    time.sleep(0.3)
    background_type(win, item_name, settings, clear=CLEAR_KEYSTROKES)
    time.sleep(0.8)

    # The bank search is token-based: "Leather Cowl" lists the "Leather"
    # material first. Scan the result grid for the first cell that shows the
    # "Equip To" row, rather than assuming the first result is the item.
    image = _capture(win)
    for point in ui.bank_grid_points(limit=12):
        if not ui.bank_cell_has_item(image, point):
            continue
        _click(win, point, settings)
        time.sleep(0.9)
        image = _capture(win)
        if ui.bank_equip_row_visible(image):
            _click(win, ui.BANK_EQUIP_ROW, settings)
            time.sleep(1.5)
            return True
    return False


def equip_loadout(
    win: WindowInfo,
    settings: AutomationSettings,
    item_names: list[str] | tuple[str, ...],
) -> set[str]:
    """Equip several items (weapon then defender) with a single bank visit.

    Returns the names the bank contained and that were equipped. A missing
    defender does not prevent the weapon from being equipped, so the caller can
    fall back to the best loadout the character actually owns.
    """
    names = [name.strip() for name in item_names if name and name.strip()]
    if not names:
        return set()

    equipped: set[str] = set()
    open_bank(win, settings)
    try:
        for name in names:
            if _equip_open_bank_item(win, settings, name):
                equipped.add(name)
    finally:
        close_bank(win, settings)
    return equipped


def equip_targets(
    win: WindowInfo,
    settings: AutomationSettings,
    targets: list[BankTarget] | tuple[BankTarget, ...],
) -> set[str]:
    """Equip exact bank search targets with a single bank visit.

    Each target carries the search term and the grid index computed from the
    save's bank order, so materials or other items sharing a word are never
    picked by mistake.
    """
    if not targets:
        return set()
    equipped: set[str] = set()
    open_bank(win, settings)
    try:
        for target in targets:
            if _equip_target(win, settings, target):
                equipped.add(target.name)
    finally:
        close_bank(win, settings)
    return equipped


def _equip_target(
    win: WindowInfo, settings: AutomationSettings, target: BankTarget
) -> bool:
    _click(win, ui.BANK_SEARCH_BOX, settings)
    time.sleep(0.3)
    background_type(win, target.search, settings, clear=CLEAR_KEYSTROKES)
    time.sleep(0.9)

    points = ui.bank_grid_points()
    if target.index < 0 or target.index >= len(points):
        return False
    point = points[target.index]
    image = _capture(win)
    if not ui.bank_cell_has_item(image, point):
        return False

    _click(win, point, settings)
    time.sleep(0.9)
    image = _capture(win)
    if not ui.bank_equip_row_visible(image):
        return False
    _click(win, ui.BANK_EQUIP_ROW, settings)
    time.sleep(1.5)
    return True


def equip_verified_slot(
    win: WindowInfo,
    settings: AutomationSettings,
    *,
    search: str,
    slot_key: str,
    desired_game_id: str,
    read_equipment,
    max_attempts: int = 10,
    save_timeout: float = 15.0,
) -> bool:
    """Equip the exact item for ``slot_key`` and verify it from the save.

    The bank search can return several items for a slot word ("Helmet" lists
    every helmet), so this walks the result grid, equips candidates one at a
    time and waits for the save to name the desired game id. A candidate is
    never trusted just because the bank click succeeded.
    """
    if not desired_game_id:
        return False
    tried: set[bytes] = set()
    open_bank(win, settings)
    try:
        for _attempt in range(max_attempts):
            _click(win, ui.BANK_SEARCH_BOX, settings)
            time.sleep(0.3)
            background_type(win, search, settings, clear=CLEAR_KEYSTROKES)
            time.sleep(0.9)
            progressed = False
            for point in ui.bank_grid_points(limit=16):
                image = _capture(win)
                if not ui.bank_cell_has_item(image, point):
                    continue
                _click(win, point, settings)
                time.sleep(0.8)
                image = _capture(win)
                marker = ui.bank_selected_item_hash(image)
                if marker in tried:
                    continue
                tried.add(marker)
                if not ui.bank_equip_row_visible(image):
                    continue

                before = read_equipment()
                _click(win, ui.BANK_EQUIP_ROW, settings)
                deadline = time.monotonic() + save_timeout
                while time.monotonic() < deadline:
                    time.sleep(1.2)
                    current = read_equipment()
                    if current == desired_game_id:
                        return True
                    if current is not None and current != before:
                        progressed = True
                        break
                if progressed:
                    break
            if not progressed:
                continue
    finally:
        close_bank(win, settings)
    return False


def switch_weapon(
    win: WindowInfo, settings: AutomationSettings, item_name: str
) -> None:
    """Equip ``item_name`` from the bank, leaving the combat page open."""
    item_name = item_name.strip()
    if not item_name:
        raise EquipmentError("Empty weapon name.")

    equipped = equip_loadout(win, settings, [item_name])
    if item_name not in equipped:
        raise EquipmentError(f"No bank result for weapon {item_name!r}.")
