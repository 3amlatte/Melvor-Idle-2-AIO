"""Windows helpers: locate the game window, focus it, and capture it.

PrintWindow with PW_RENDERFULLCONTENT works for this Godot window while it is
covered by another application or parked off-screen, so state checks never need
focus. It does not work while the window is minimized: Windows gives a minimized
window no composition surface and PrintWindow returns an empty (black) frame.
Leave the game unminimized instead of minimizing it.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as wt
from dataclasses import dataclass

from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
SW_RESTORE = 9
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x2

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.restype = wt.BOOL
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.ClientToScreen.restype = wt.BOOL
user32.GetForegroundWindow.restype = wt.HWND
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindow.restype = wt.BOOL
user32.IsIconic.argtypes = [wt.HWND]
user32.IsIconic.restype = wt.BOOL
user32.IsZoomed.argtypes = [wt.HWND]
user32.IsZoomed.restype = wt.BOOL
user32.SetWindowPos.argtypes = [
    wt.HWND,
    wt.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wt.UINT,
]
user32.SetWindowPos.restype = wt.BOOL

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.PrintWindow.restype = wt.BOOL
user32.GetWindowDC.argtypes = [wt.HWND]
user32.GetWindowDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]

gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.GetDIBits.argtypes = [
    wt.HDC,
    wt.HBITMAP,
    wt.UINT,
    wt.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wt.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int


def _set_dpi_awareness() -> None:
    """Match Win32 coordinates to physical pixels (per-monitor v2).

    Without this, Windows virtualizes coordinates on displays scaled above
    100%, so ``GetClientRect``/``ClientToScreen`` disagree with the pixels
    ``PrintWindow`` returns and every click lands in the wrong place. The
    fallbacks cover older Windows builds.
    """
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wt.BOOL
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
        return
    except Exception:
        pass
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


_set_dpi_awareness()


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    left: int
    top: int
    right: int
    bottom: int
    client_x: int
    client_y: int
    client_width: int
    client_height: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def client_area(self) -> tuple[int, int]:
        return self.client_width, self.client_height

    def client_to_screen(self, x: int, y: int) -> tuple[int, int]:
        return self.client_x + x, self.client_y + y

    def describe(self) -> str:
        return (
            f"hwnd=0x{self.hwnd:X} '{self.title}' "
            f"window={self.width}x{self.height} at ({self.left},{self.top}) "
            f"client={self.client_width}x{self.client_height} "
            f"at ({self.client_x},{self.client_y})"
        )


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def list_windows() -> list[tuple[int, str]]:
    windows: list[tuple[int, str]] = []

    @WNDENUMPROC
    def _callback(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            title = _window_title(hwnd)
            if title:
                windows.append((hwnd, title))
        return True

    user32.EnumWindows(_callback, 0)
    return windows


def find_game_window(title_substring: str = "Melvor2") -> WindowInfo:
    """Find the largest visible window whose title contains the substring."""
    matches: list[WindowInfo] = []
    for hwnd, title in list_windows():
        if title_substring.lower() in title.lower():
            try:
                matches.append(window_info(hwnd, title))
            except OSError:
                continue

    if not matches:
        raise LookupError(
            f"No visible window matching '{title_substring}'. Is the game running?"
        )
    return max(matches, key=lambda info: info.width * info.height)


def window_info(hwnd: int, title: str | None = None) -> WindowInfo:
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OSError(f"GetWindowRect failed for hwnd 0x{hwnd:X}")

    client = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        raise OSError(f"GetClientRect failed for hwnd 0x{hwnd:X}")

    origin = wt.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise OSError(f"ClientToScreen failed for hwnd 0x{hwnd:X}")

    return WindowInfo(
        hwnd=hwnd,
        title=title if title is not None else _window_title(hwnd),
        left=rect.left,
        top=rect.top,
        right=rect.right,
        bottom=rect.bottom,
        client_x=origin.x,
        client_y=origin.y,
        client_width=client.right - client.left,
        client_height=client.bottom - client.top,
    )


def is_minimized(hwnd: int) -> bool:
    """True when the window is iconic (minimized).

    A minimized window has no composition surface: PrintWindow returns black and
    client coordinates are meaningless. Leave the game behind other windows or
    off-screen instead of minimizing it.
    """
    return bool(user32.IsIconic(hwnd))


def is_maximized(hwnd: int) -> bool:
    """True when the window is maximized.

    Maximizing is not required: :func:`ensure_reference_size` restores a
    maximized window and resizes it to the reference client area, because a
    maximized window is limited to the monitor's work area (which breaks the
    readers on a small display).
    """
    return bool(user32.IsZoomed(hwnd))


def monitor_size() -> tuple[int, int]:
    """Primary monitor size in physical pixels (DPI-aware)."""
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def dpi_scale() -> float:
    """Primary monitor scale factor (1.0 = 96 DPI)."""
    try:
        return float(user32.GetDpiForSystem()) / 96.0
    except Exception:
        return 1.0


def layout_ready(win: WindowInfo) -> tuple[bool, str]:
    """Check the window is in the state the UI readers were calibrated for.

    Returns ``(ok, reason)``. The reference is a 2560x1369 client area; a small
    tolerance covers border rounding. The bot resizes the window to that size
    at startup (:func:`ensure_reference_size`), so the window does not need to
    be maximized — on a smaller display it simply extends off-screen.
    """
    from .ui import REFERENCE_SIZE

    if is_minimized(win.hwnd):
        return False, "the window is minimized"
    width, height = win.client_area
    if abs(width - REFERENCE_SIZE[0]) > 2 or abs(height - REFERENCE_SIZE[1]) > 2:
        return (
            False,
            f"client area is {width}x{height}, expected "
            f"{REFERENCE_SIZE[0]}x{REFERENCE_SIZE[1]}",
        )
    return True, ""


def ensure_reference_size(win: WindowInfo, *, tolerance: int = 2) -> WindowInfo:
    """Resize the game window so its client area matches the UI reference.

    The UI readers are calibrated for a 2560x1369 client. Resizing works on any
    display: Windows allows a window larger than the screen, and the game
    renders/captures its full client area even when part of the window is
    off-screen. A maximized window is restored first, because Windows keeps a
    maximized window clamped to the monitor work area; this is what makes the
    bot work on a small laptop display.
    """
    from .ui import REFERENCE_SIZE

    def matches(info: WindowInfo) -> bool:
        return (
            abs(info.client_width - REFERENCE_SIZE[0]) <= tolerance
            and abs(info.client_height - REFERENCE_SIZE[1]) <= tolerance
        )

    if matches(win):
        return win
    if is_minimized(win.hwnd):
        return win

    if is_maximized(win.hwnd):
        user32.ShowWindow(win.hwnd, SW_RESTORE)
        time.sleep(0.5)
        win = window_info(win.hwnd)
        if matches(win):
            return win

    border_w = win.width - win.client_width
    border_h = win.height - win.client_height
    target_w = REFERENCE_SIZE[0] + border_w
    target_h = REFERENCE_SIZE[1] + border_h
    if not user32.SetWindowPos(
        win.hwnd,
        0,
        win.left,
        win.top,
        target_w,
        target_h,
        SWP_NOZORDER | SWP_NOACTIVATE,
    ):
        return win
    time.sleep(1.5)
    return window_info(win.hwnd)


def focus(hwnd: int, timeout: float = 1.5) -> bool:
    """Bring a window to the foreground; returns True when it succeeded."""
    if user32.GetForegroundWindow() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.2)

    # Windows blocks focus stealing; a synthetic ALT press lifts the restriction.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return user32.GetForegroundWindow() == hwnd


def capture(win: WindowInfo) -> Image.Image:
    """Capture the full window via PrintWindow (works while occluded)."""
    width, height = win.width, win.height
    if width <= 0 or height <= 0:
        raise OSError("Window has no drawable area.")

    window_dc = user32.GetWindowDC(win.hwnd)
    if not window_dc:
        raise OSError("GetWindowDC failed.")
    mem_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    if not mem_dc or not bitmap:
        user32.ReleaseDC(win.hwnd, window_dc)
        raise OSError("Could not create GDI capture surfaces.")

    previous = gdi32.SelectObject(mem_dc, bitmap)
    try:
        if not user32.PrintWindow(win.hwnd, mem_dc, PW_RENDERFULLCONTENT):
            raise OSError("PrintWindow failed.")

        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # top-down
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB

        info = BITMAPINFO()
        info.bmiHeader = header
        buffer = ctypes.create_string_buffer(width * height * 4)
        lines = gdi32.GetDIBits(
            mem_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0
        )
        if lines == 0:
            raise OSError("GetDIBits failed.")

        image = Image.frombuffer(
            "RGB", (width, height), buffer, "raw", "BGRX", 0, 1
        )
        return image.copy()
    finally:
        gdi32.SelectObject(mem_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(win.hwnd, window_dc)


def capture_client(win: WindowInfo) -> Image.Image:
    """Capture and crop to the client area using client coordinates."""
    image = capture(win)
    offset_x = win.client_x - win.left
    offset_y = win.client_y - win.top
    box = (
        offset_x,
        offset_y,
        offset_x + win.client_width,
        offset_y + win.client_height,
    )
    if box[0] == 0 and box[1] == 0 and box[2] == image.width and box[3] == image.height:
        return image
    return image.crop(box)
