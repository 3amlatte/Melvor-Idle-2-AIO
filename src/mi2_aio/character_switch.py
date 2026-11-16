"""Switch the running Melvor client between character saves.

The game exposes a hamburger menu with **Save and Exit to Main Menu**, then the
standard character-selection screen with a green **Load** button per save. The
switch is intentionally conservative: it verifies the target save row, loads it,
and waits for the save header to confirm the new character before returning.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import ui
from .config import Settings
from .input import click_game
from .savefile import SaveHeader, discover_saves, read_header
from .window import (
    WindowInfo,
    capture_client,
    ensure_reference_size,
    find_game_window,
    is_minimized,
)


class CharacterSwitchError(RuntimeError):
    """Raised when the client could not be switched to the requested save."""


def _capture(window: WindowInfo):
    return ui.normalize(capture_client(window))


def _find_target(
    settings: Settings, target: str
) -> tuple[Path, SaveHeader]:
    wanted = target.strip().lower()
    if not wanted:
        raise CharacterSwitchError("No character was selected.")
    for path in discover_saves(settings):
        try:
            header = read_header(path, settings=settings)
        except Exception:
            continue
        if (
            header.uuid.lower() == wanted
            or header.character_name.lower() == wanted
            or wanted in path.name.lower()
        ):
            return path, header
    raise CharacterSwitchError(
        f"Character save {target!r} was not found. Refresh the character list."
    )


def _wait_for_character_select(
    window: WindowInfo, logger, timeout: float
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ui.character_select_open(_capture(window)):
            return True
        time.sleep(1.0)
    return False


def _dismiss_modals(
    window: WindowInfo, settings: Settings, logger, timeout: float = 12.0
) -> bool:
    """Click the green Confirm button on Welcome Back / results screens."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        image = _capture(window)
        point = ui.modal_confirm_button(image)
        if point is None:
            return True
        logger.info("Dismissing the Welcome Back / results screen.")
        click_game(window, *point, settings.automation)
        time.sleep(1.5)
    return ui.modal_confirm_button(_capture(window)) is None


def _exit_to_menu(window: WindowInfo, settings: Settings, logger) -> None:
    _dismiss_modals(window, settings, logger)
    for _attempt in range(4):
        image = _capture(window)
        if not ui.game_menu_open(image):
            logger.debug("Opening the in-game menu.")
            click_game(window, *ui.GAME_MENU_BUTTON, settings.automation)
            time.sleep(1.2)
            image = _capture(window)
        if ui.game_menu_open(image):
            logger.debug("Leaving to the character-selection screen.")
            click_game(window, *ui.GAME_MENU_EXIT, settings.automation)
            time.sleep(1.5)
            if _wait_for_character_select(window, logger, 15.0):
                return
        else:
            time.sleep(0.8)
    raise CharacterSwitchError(
        "Could not reach the character-selection screen. Check that the game "
        "is not showing a modal dialog or a level-up popup."
    )


def _load_character(
    window: WindowInfo,
    settings: Settings,
    target_path: Path,
    target_header: SaveHeader,
    logger,
) -> SaveHeader:
    image = _capture(window)
    if not ui.character_select_open(image):
        if not _wait_for_character_select(window, logger, 5.0):
            _exit_to_menu(window, settings, logger)
            image = _capture(window)

    saves = sorted(
        discover_saves(settings), key=lambda path: path.stat().st_ctime
    )
    try:
        index = saves.index(target_path)
    except ValueError as exc:
        raise CharacterSwitchError(
            "The selected character disappeared while switching."
        ) from exc

    buttons = ui.character_load_buttons(image)
    if index >= len(buttons):
        raise CharacterSwitchError(
            "The target character is not visible in the selection list. "
            "Scroll the list in Melvor and try again."
        )

    logger.info(
        "Loading character %s (row %d).",
        target_header.character_name,
        index + 1,
    )
    click_game(window, *buttons[index], settings.automation)
    time.sleep(2.0)

    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        image = _capture(window)
        if not ui.character_select_open(image):
            break
        time.sleep(1.0)
    else:
        raise CharacterSwitchError(
            "The game did not leave the character-selection screen."
        )

    time.sleep(1.5)
    if not _dismiss_modals(window, settings, logger, timeout=15.0):
        raise CharacterSwitchError(
            "The Welcome Back / results screen could not be dismissed."
        )

    # The active character writes a fresh save after loading. Wait until the
    # newest save is the target, then confirm its header.
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        saves = discover_saves(settings)
        if saves:
            try:
                newest = read_header(saves[0], settings=settings)
            except Exception:
                newest = None
            if newest is not None and newest.uuid.lower() == target_header.uuid.lower():
                return newest
        time.sleep(1.0)

    raise CharacterSwitchError(
        "Melvor loaded, but the target save was not confirmed. The bot did not "
        "start the next task; switch back to the Queue tab and retry."
    )


def ensure_character(
    settings: Settings,
    target: str,
    logger,
) -> SaveHeader:
    """Make the running client load ``target`` and return its fresh header."""
    window = ensure_reference_size(
        find_game_window(settings.game.window_title)
    )
    if is_minimized(window.hwnd):
        raise CharacterSwitchError(
            "The Melvor window is minimized. Restore it before switching "
            "characters."
        )

    target_path, target_header = _find_target(settings, target)
    image = _capture(window)
    if ui.modal_confirm_visible(image):
        if not _dismiss_modals(window, settings, logger):
            raise CharacterSwitchError(
                "The Welcome Back / results screen could not be dismissed."
            )
        image = _capture(window)

    if not ui.character_select_open(image):
        saves = discover_saves(settings)
        if saves:
            try:
                newest = read_header(saves[0], settings=settings)
            except Exception:
                newest = None
            if (
                newest is not None
                and newest.uuid.lower() == target_header.uuid.lower()
            ):
                logger.info(
                    "Character %s is already loaded.",
                    target_header.character_name,
                )
                return newest
        _exit_to_menu(window, settings, logger)
        image = _capture(window)

    return _load_character(
        window,
        settings,
        target_path,
        target_header,
        logger,
    )
