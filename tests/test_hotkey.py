from __future__ import annotations

import pytest

from mi2_aio.hotkey import KeyboardToggleHook


def test_hotkey_installs_and_uninstalls() -> None:
    hook = KeyboardToggleHook(lambda: None, lambda: False)
    if not hook.install():
        pytest.skip("Windows rejected the low-level keyboard hook.")
    try:
        assert hook._handle
    finally:
        hook.uninstall()
    assert hook._handle is None
