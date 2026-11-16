"""Always-on-top, click-through indicator for the Ctrl+A hide/show shortcut.

The hint follows the Melvor client and is shown only while the Melvor window is
the foreground window, so it never floats over the bot UI or another application
(for example a movie) that happens to overlap the game's screen area. Geometry is
expressed as a fraction of the game client in reference space and rendered at the
game window's DPI, so it keeps the same physical appearance at any resolution or
display scale.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QWindow
from PySide6.QtWidgets import QLabel, QWidget

from . import ui
from .config import Settings
from .paths import ASSETS_DIR
from .window import find_game_window, is_minimized

# Physical/reference width at the 2560px game client. Two 15% reductions from
# the original 420px presentation.
OVERLAY_WIDTH = 303
# Reference-space point inside the game client: the dark header between the
# Melvor logo and the Bank icon.
OVERLAY_REFERENCE_POINT = (136, 0)
# Physical-pixel nudges at 100%: slightly above the client top and 10px right.
OVERLAY_Y_OFFSET = 13
OVERLAY_X_NUDGE = 10
# Shift 5% of the overlay width to the left (before the right nudge).
OVERLAY_X_SHIFT_PCT = 0.05
ASSET_NAME = "overlay_ctrl_a.png"
SYNC_MS = 500


def is_supported_foreground(foreground_hwnd: int, game_hwnd: int) -> bool:
    """Show the hint only while the game window itself is foreground."""
    return foreground_hwnd == game_hwnd


def overlay_physical_width(client_width: int) -> int:
    """Physical width of the hint for a given game client width."""
    reference = max(1, ui.REFERENCE_SIZE[0])
    return max(1, round(OVERLAY_WIDTH * client_width / reference))


def logical_client_point(
    client_width: int,
    client_height: int,
    reference_x: int,
    reference_y: int,
) -> tuple[int, int]:
    """Map a reference-space point onto an arbitrary logical client size."""
    if client_width <= 0 or client_height <= 0:
        return 0, 0
    return (
        int(round(reference_x * client_width / ui.REFERENCE_SIZE[0])),
        int(round(reference_y * client_height / ui.REFERENCE_SIZE[1])),
    )


class OverlayWindow(QWidget):
    """A frameless, non-focusable image pinned to the game client.

    The window is click-through and never appears in the taskbar. It is shown
    only while Melvor itself is the foreground window; focusing the bot UI or
    another application hides it.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            None,
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.settings = settings
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setWindowTitle("MI2 AIO shortcut hint")

        self.label = QLabel(self)
        self.label.setStyleSheet("background: transparent; border: none;")
        self._source = QPixmap(str(ASSETS_DIR / ASSET_NAME))
        self._available = not self._source.isNull()
        self._physical_width = 0
        self._dpr = 1.0
        self._game_cache = (None, 0.0)
        if self._available:
            self._load_pixmap(OVERLAY_WIDTH, 1.0)
        else:
            self.resize(OVERLAY_WIDTH, 115)

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32 = user32
        self._sync()
        self._timer = QTimer(self)
        self._timer.setInterval(SYNC_MS)
        self._timer.timeout.connect(self._sync)
        self._timer.start()

    # -- geometry --------------------------------------------------------
    def _game_window(self):
        now = time.monotonic()
        if now - self._game_cache[1] < 2.0:
            return self._game_cache[0]
        try:
            window = find_game_window(self.settings.game.window_title)
        except (LookupError, OSError):
            window = None
        self._game_cache = (window, now)
        return window

    def _window_context(self, window):
        """Return the game's logical client geometry and DPI via Qt."""
        try:
            foreign = QWindow.fromWinId(int(window.hwnd))
        except Exception:
            return None
        if foreign is None:
            return None
        geometry = foreign.geometry()
        dpr = float(foreign.devicePixelRatio() or 1.0)
        if geometry.width() <= 0 or geometry.height() <= 0:
            return None
        return geometry, dpr

    def _load_pixmap(self, physical_width: int, dpr: float) -> None:
        if not self._available:
            return
        if (physical_width, dpr) == (self._physical_width, self._dpr):
            return
        scaled = self._source.scaledToWidth(
            physical_width, Qt.TransformationMode.SmoothTransformation
        )
        scaled.setDevicePixelRatio(dpr)
        self._pixmap = scaled
        self.label.setPixmap(scaled)
        logical_width = max(1, round(physical_width / dpr))
        logical_height = max(1, round(scaled.height() / dpr))
        self.label.resize(logical_width, logical_height)
        self.resize(logical_width, logical_height)
        self._physical_width = physical_width
        self._dpr = dpr

    def _position(self, geometry, dpr: float) -> None:
        # The foreign QWindow geometry is the game client in logical
        # coordinates, including its position on a multi-monitor desktop.
        offset_x, offset_y = logical_client_point(
            geometry.width(),
            geometry.height(),
            *OVERLAY_REFERENCE_POINT,
        )
        x_shift = round(self.width() * OVERLAY_X_SHIFT_PCT)
        x_nudge = round(OVERLAY_X_NUDGE / dpr)
        y_offset = round(OVERLAY_Y_OFFSET / dpr)
        self.move(
            geometry.left() + offset_x - x_shift + x_nudge,
            geometry.top() + offset_y - y_offset,
        )

    # -- visibility ------------------------------------------------------
    def _sync(self) -> None:
        if not self._available:
            self.hide()
            return
        window = self._game_window()
        if window is None or is_minimized(window.hwnd):
            self.hide()
            return
        foreground = self._user32.GetForegroundWindow()
        if not is_supported_foreground(int(foreground), int(window.hwnd)):
            self.hide()
            return
        context = self._window_context(window)
        if context is None:
            self.hide()
            return
        geometry, dpr = context
        self._load_pixmap(
            overlay_physical_width(window.client_width), dpr
        )
        self._position(geometry, dpr)
        if not self.isVisible():
            self.show()
        self._ensure_topmost()

    def reposition(self) -> None:
        window = self._game_window()
        if window is None:
            return
        context = self._window_context(window)
        if context is None:
            return
        geometry, dpr = context
        self._load_pixmap(
            overlay_physical_width(window.client_width), dpr
        )
        self._position(geometry, dpr)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_topmost()

    def _ensure_topmost(self) -> None:
        if not self.isVisible():
            return
        try:
            hwnd = int(self.winId())
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:
            pass
