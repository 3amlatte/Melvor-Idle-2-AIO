"""Capture a real mouse click in the game window as reference coordinates.

Used by the fallback-action wizard: the user switches to Melvor, clicks the
skill's sidebar icon, then clicks the action's Start button. The app records
both points and stores them in ``[failsafe]``.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from . import ui
from .config import Settings
from .window import WindowInfo, ensure_reference_size, find_game_window

VK_LBUTTON = 0x01


class CaptureError(RuntimeError):
    """Raised when no valid game-window click was captured."""


def capture_next_click(
    settings: Settings,
    stop_event,
    *,
    timeout: float = 30.0,
    poll_seconds: float = 0.02,
) -> tuple[int, int]:
    """Wait for the next left click inside the game client and return it.

    The returned point is in the UI reference space, ready for
    ``[failsafe].page`` / ``[failsafe].button``.
    """
    window = ensure_reference_size(find_game_window(settings.game.window_title))
    return capture_next_click_in_window(window, stop_event, timeout=timeout, poll_seconds=poll_seconds)


def capture_next_click_in_window(
    window: WindowInfo,
    stop_event,
    *,
    timeout: float = 30.0,
    poll_seconds: float = 0.02,
) -> tuple[int, int]:
    user32 = ctypes.windll.user32
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.ScreenToClient.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.POINT),
    ]
    user32.ScreenToClient.restype = wintypes.BOOL
    deadline = time.monotonic() + max(1.0, timeout)
    # Ignore a button that is already down when capture starts (the user may
    # still be releasing the app's own button).
    while time.monotonic() < deadline:
        if stop_event.is_set():
            raise CaptureError("Capture cancelled.")
        if not (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
            break
        time.sleep(poll_seconds)

    while time.monotonic() < deadline:
        if stop_event.is_set():
            raise CaptureError("Capture cancelled.")
        # GetAsyncKeyState's low bit means "pressed since the previous call";
        # the high bit is the current state. Checking both catches a very fast
        # click that goes down and up between two polls.
        state = user32.GetAsyncKeyState(VK_LBUTTON)
        if state & 0x8001:
            point = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                raise CaptureError("Could not read the cursor position.")
            client = wintypes.POINT(point.x, point.y)
            if not user32.ScreenToClient(window.hwnd, ctypes.byref(client)):
                raise CaptureError("Could not convert the click position.")
            if (
                0 <= client.x < window.client_width
                and 0 <= client.y < window.client_height
            ):
                return ui.from_client(
                    client.x, client.y, window.client_area
                )
        time.sleep(poll_seconds)
    raise CaptureError("No click was captured before the timeout.")
