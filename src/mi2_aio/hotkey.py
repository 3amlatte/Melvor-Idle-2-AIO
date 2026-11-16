"""Global Ctrl+A toggle.

A ``WH_KEYBOARD_LL`` hook is used instead of ``RegisterHotKey`` so Ctrl+A keeps
working normally in text fields and other applications. The hook only consumes
the key when the foreground window is the game, or the MI2 AIO window while no
text input is focused.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable
from ctypes import wintypes

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_CONTROL = 0x11
VK_A = 0x41


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class KeyboardToggleHook:
    """Install a low-level keyboard hook for Ctrl+A.

    ``should_toggle`` is called on the GUI thread and decides whether the key
    belongs to the app. Return False to let the key continue to the focused
    application normally.
    """

    def __init__(
        self,
        callback: Callable[[], None],
        should_toggle: Callable[[], bool],
    ) -> None:
        self.callback = callback
        self.should_toggle = should_toggle
        self._handle = None
        self._proc = None
        self._last_toggle = 0.0
        self._armed = True
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            HOOKPROC,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        self.user32.UnhookWindowsHookEx.restype = wintypes.BOOL

    def install(self) -> bool:
        if self._handle:
            return True
        self._proc = HOOKPROC(self._hook)
        self._handle = self.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, None, 0
        )
        return bool(self._handle)

    def uninstall(self) -> None:
        if self._handle:
            try:
                self.user32.UnhookWindowsHookEx(self._handle)
            except Exception:
                pass
            self._handle = None
            self._proc = None

    def _hook(self, n_code, w_param, l_param):
        try:
            if n_code == HC_ACTION:
                event = ctypes.cast(
                    l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)
                ).contents
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    ctrl = bool(
                        self.user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                    )
                    if event.vkCode == VK_A and ctrl and self._armed:
                        if self.should_toggle():
                            now = time.monotonic()
                            if now - self._last_toggle >= 0.2:
                                self._last_toggle = now
                                self._armed = False
                                self.callback()
                            return 1
                elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                    if event.vkCode in (VK_A, VK_CONTROL):
                        self._armed = True
        except Exception:
            pass
        return self.user32.CallNextHookEx(
            self._handle, n_code, w_param, l_param
        )
