"""Humanized mouse/keyboard actions targeted at the game's client area.

Two input paths exist:

``background_*``
    Posts window messages (``WM_MOUSEMOVE`` / ``WM_LBUTTONDOWN`` ...) straight to
    the game window. The bot can act while another application is focused, the
    game is covered, or the window is parked off-screen. Verified against the
    Melvor Idle 2 demo (Godot).

``click_client`` / ``move_client`` / ``press``
    Use the real cursor and keyboard via pyautogui, so the game window has to be
    focused. Useful as a fallback and for controls that need true OS input.

``click_game`` picks the background path when ``[automation].background_input``
is enabled.
"""

from __future__ import annotations

import random
import time
from ctypes import wintypes as wt

import pyautogui

from .config import AutomationSettings
from .window import WindowInfo, focus, is_minimized, user32

pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort
pyautogui.PAUSE = 0.02

user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MBUTTONDBLCLK = 0x0209
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102

VK_BACK = 0x08
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010

# button -> (down, up, double-click, button-state mask)
_BUTTONS = {
    "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK, MK_LBUTTON),
    "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK, MK_RBUTTON),
    "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK, MK_MBUTTON),
}


class InputBlocked(RuntimeError):
    """Raised when the game window cannot receive input."""


def _pause(settings: AutomationSettings) -> None:
    low, high = settings.action_delay_ms
    time.sleep(random.uniform(low, high) / 1000.0)


def _jitter(settings: AutomationSettings) -> tuple[int, int]:
    if not settings.humanize:
        return 0, 0
    amount = max(0, settings.click_jitter_px)
    return random.randint(-amount, amount), random.randint(-amount, amount)


def _pack_xy(x: int, y: int) -> int:
    """Pack client coordinates into a Win32 LPARAM."""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def _check_client_point(win: WindowInfo, x: int, y: int) -> None:
    if not (0 <= x < win.client_width and 0 <= y < win.client_height):
        raise ValueError(f"({x}, {y}) is outside the game client area.")


def _require_background_capable(win: WindowInfo) -> None:
    if win.client_width <= 0 or win.client_height <= 0 or is_minimized(win.hwnd):
        raise InputBlocked(
            "Game window is minimized. Restore it, or leave it behind other "
            "windows / off-screen; minimized windows cannot be captured or "
            "receive client-relative input."
        )


def _post(hwnd: int, message: int, wparam: int, lparam: int) -> None:
    if not user32.PostMessageW(hwnd, message, wparam, lparam):
        raise OSError(f"PostMessage(0x{message:04X}) failed for hwnd 0x{hwnd:X}")


def background_move(
    win: WindowInfo,
    x: int,
    y: int,
    settings: AutomationSettings,
    *,
    settle: bool = True,
) -> None:
    """Move the game's notion of the cursor without touching the real cursor."""
    _require_background_capable(win)
    _check_client_point(win, x, y)
    dx, dy = _jitter(settings)
    px = min(max(0, x + dx), win.client_width - 1)
    py = min(max(0, y + dy), win.client_height - 1)
    _post(win.hwnd, WM_MOUSEMOVE, 0, _pack_xy(px, py))
    if settle:
        time.sleep(random.uniform(0.03, 0.08))


def background_click(
    win: WindowInfo,
    x: int,
    y: int,
    settings: AutomationSettings,
    *,
    button: str = "left",
    clicks: int = 1,
) -> None:
    """Click at a client-relative point using window messages.

    The real cursor and the foreground window are left untouched, so the bot can
    work while another game or browser has focus.
    """
    _require_background_capable(win)
    _check_client_point(win, x, y)
    try:
        down, up, double, state = _BUTTONS[button]
    except KeyError:
        raise ValueError(f"Unsupported mouse button: {button!r}") from None

    dx, dy = _jitter(settings)
    px = min(max(0, x + dx), win.client_width - 1)
    py = min(max(0, y + dy), win.client_height - 1)
    lparam = _pack_xy(px, py)

    # Godot updates hover state from WM_MOUSEMOVE before the button event.
    _post(win.hwnd, WM_MOUSEMOVE, 0, lparam)
    time.sleep(random.uniform(0.03, 0.08))

    for index in range(max(1, clicks)):
        # Windows only synthesises WM_*BUTTONDBLCLK for physical input, so a
        # posted double click has to send it explicitly.
        _post(win.hwnd, down if index == 0 else double, state, lparam)
        time.sleep(random.uniform(0.03, 0.07))
        _post(win.hwnd, up, 0, lparam)
        if index + 1 < max(1, clicks):
            time.sleep(random.uniform(0.04, 0.09))

    _post(win.hwnd, WM_MOUSEMOVE, 0, lparam)
    _pause(settings)


def background_key(
    win: WindowInfo,
    virtual_key: int,
    settings: AutomationSettings,
    *,
    presses: int = 1,
    interval: float = 0.04,
) -> None:
    """Send a key press to the game window without focusing it.

    Godot maps posted ``WM_KEYDOWN``/``WM_KEYUP`` pairs onto its own key
    events, so this works for widgets that already hold keyboard focus (for
    example a LineEdit opened with :func:`background_click`).
    """
    _require_background_capable(win)
    for index in range(max(1, presses)):
        _post(win.hwnd, WM_KEYDOWN, virtual_key, 0x0001)
        time.sleep(interval / 2)
        _post(win.hwnd, WM_KEYUP, virtual_key, 0xC001_0001)
        if index + 1 < max(1, presses):
            time.sleep(interval)
    _pause(settings)


def background_type(
    win: WindowInfo,
    text: str,
    settings: AutomationSettings,
    *,
    clear: int = 0,
    interval: float = 0.05,
) -> None:
    """Type text into the game's focused control via ``WM_CHAR``.

    ``clear`` sends that many backspaces first, which is how a bank search box
    is reset before a new query. Verified against the bank search box in the
    demo build.
    """
    _require_background_capable(win)
    if clear:
        background_key(win, VK_BACK, settings, presses=clear, interval=0.02)
    for character in text:
        _post(win.hwnd, WM_CHAR, ord(character), 0x0001)
        time.sleep(interval)
    _pause(settings)


def background_hold(
    win: WindowInfo,
    x: int,
    y: int,
    settings: AutomationSettings,
    *,
    seconds: float = 1.2,
) -> None:
    """Press and hold the left button at a client point.

    Melvor 2's ``HoldForActionButton`` fires its action after a one-second hold
    (unless the accessibility "disable press and hold" setting is on), so
    watering and clearing need a real hold rather than a click.
    """
    _require_background_capable(win)
    _check_client_point(win, x, y)
    lparam = _pack_xy(x, y)
    _post(win.hwnd, WM_MOUSEMOVE, 0, lparam)
    time.sleep(random.uniform(0.03, 0.08))
    _post(win.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(max(0.1, seconds))
    _post(win.hwnd, WM_LBUTTONUP, 0, lparam)
    _post(win.hwnd, WM_MOUSEMOVE, 0, lparam)
    _pause(settings)


def hold_game(
    win: WindowInfo,
    x: int,
    y: int,
    settings: AutomationSettings,
    *,
    seconds: float = 1.2,
) -> str:
    """Hold using the configured input path; returns ``"background"`` or ``"foreground"``."""
    if settings.background_input:
        background_hold(win, x, y, settings, seconds=seconds)
        return "background"
    _check_client_point(win, x, y)
    if not focus(win.hwnd):
        raise InputBlocked("Could not focus the game window before holding.")
    screen_x, screen_y = win.client_to_screen(x, y)
    pyautogui.moveTo(screen_x, screen_y, duration=random.uniform(0.04, 0.16))
    pyautogui.mouseDown()
    time.sleep(max(0.1, seconds))
    pyautogui.mouseUp()
    _pause(settings)
    return "foreground"


def click_client(
    win: WindowInfo,
    x: int,
    y: int,
    settings: AutomationSettings,
    *,
    button: str = "left",
    clicks: int = 1,
    focus_first: bool = True,
) -> None:
    """Click at a client-relative coordinate with the real cursor."""
    _check_client_point(win, x, y)
    if focus_first and not focus(win.hwnd):
        raise InputBlocked("Could not focus the game window before clicking.")

    dx, dy = _jitter(settings)
    screen_x, screen_y = win.client_to_screen(x + dx, y + dy)
    pyautogui.moveTo(screen_x, screen_y, duration=random.uniform(0.04, 0.16))
    pyautogui.click(button=button, clicks=clicks)
    _pause(settings)


def click_game(
    win: WindowInfo,
    x: int,
    y: int,
    settings: AutomationSettings,
    *,
    button: str = "left",
    clicks: int = 1,
) -> str:
    """Click using the configured input path; returns ``"background"`` or ``"foreground"``."""
    if settings.background_input:
        background_click(win, x, y, settings, button=button, clicks=clicks)
        return "background"
    click_client(win, x, y, settings, button=button, clicks=clicks)
    return "foreground"


def move_client(
    win: WindowInfo, x: int, y: int, settings: AutomationSettings
) -> None:
    if not focus(win.hwnd):
        raise InputBlocked("Could not focus the game window before moving.")
    dx, dy = _jitter(settings)
    screen_x, screen_y = win.client_to_screen(x + dx, y + dy)
    pyautogui.moveTo(screen_x, screen_y, duration=random.uniform(0.04, 0.16))
    _pause(settings)


def press(
    key: str,
    settings: AutomationSettings,
    *,
    presses: int = 1,
    interval: float = 0.05,
) -> None:
    pyautogui.press(key, presses=presses, interval=interval)
    _pause(settings)


def hotkey(*keys: str, settings: AutomationSettings) -> None:
    pyautogui.hotkey(*keys)
    _pause(settings)


def type_text(text: str, settings: AutomationSettings, *, interval: float = 0.03) -> None:
    pyautogui.write(text, interval=interval)
    _pause(settings)


def cursor_position() -> tuple[int, int]:
    point = pyautogui.position()
    return point.x, point.y
