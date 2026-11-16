from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from mi2_aio.config import Settings
from mi2_aio.overlay import (
    OVERLAY_WIDTH,
    OverlayWindow,
    is_supported_foreground,
    logical_client_point,
    overlay_physical_width,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_foreground_targets() -> None:
    # The game window is focused.
    assert is_supported_foreground(100, 100)
    # The bot UI (or any other application) is focused: hidden.
    assert not is_supported_foreground(200, 100)


def test_overlay_physical_width_tracks_the_client() -> None:
    assert overlay_physical_width(2560) == OVERLAY_WIDTH
    assert overlay_physical_width(1920) == round(OVERLAY_WIDTH * 1920 / 2560)


def test_logical_client_point_scales_with_the_client() -> None:
    assert logical_client_point(2560, 1369, 136, 0) == (136, 0)
    # 150% display scale: the same client is 1706x912 logical pixels.
    assert logical_client_point(1706, 912, 136, 0) == (91, 0)
    # 100% on a smaller physical client.
    assert logical_client_point(1920, 1080, 136, 0) == (102, 0)


def test_overlay_loads_and_is_click_through(app) -> None:
    overlay = OverlayWindow(Settings())
    try:
        assert overlay.width() == OVERLAY_WIDTH
        assert overlay.height() > 0
        assert overlay.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert overlay.label.pixmap() is not None
        assert not overlay.label.pixmap().isNull()
    finally:
        overlay.close()
