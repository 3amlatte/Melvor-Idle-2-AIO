"""Screen-size independence tests.

The bot must work on any monitor, resolution and display scale. These tests
pin the two invariants every reader/click relies on:

* captures are normalized to REFERENCE_SIZE before analysis
* reference-space points are scaled into the live client area before clicking
"""

from __future__ import annotations

import pytest
from PIL import Image

from mi2_aio import ui
from mi2_aio import window as window_module
from mi2_aio.window import WindowInfo

CLIENT_SIZES = [
    (2560, 1369),  # reference
    (1920, 1033),
    (1366, 729),
    (1280, 720),
    (1001, 567),  # odd numbers / rounding
    (3840, 2054),
]


def _image(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGB", size, (10, 20, 30))


def test_normalize_always_returns_the_reference_size() -> None:
    for size in CLIENT_SIZES:
        normalized = ui.normalize(_image(size))
        assert normalized.size == ui.REFERENCE_SIZE, size


def test_to_client_maps_the_reference_corners_into_the_client() -> None:
    for width, height in CLIENT_SIZES:
        top_left = ui.to_client(0, 0, (width, height))
        bottom_right = ui.to_client(
            ui.REFERENCE_SIZE[0] - 1, ui.REFERENCE_SIZE[1] - 1, (width, height)
        )
        assert top_left == (0, 0)
        assert 0 <= bottom_right[0] <= width - 1
        assert 0 <= bottom_right[1] <= height - 1
        assert bottom_right[0] >= width - 3
        assert bottom_right[1] >= height - 3


def test_reference_points_survive_a_scale_round_trip() -> None:
    points = [(0, 0), (35, 223), (748, 35), (1935, 1265), (2559, 1368)]
    for width, height in CLIENT_SIZES:
        scale_x = ui.REFERENCE_SIZE[0] / width
        scale_y = ui.REFERENCE_SIZE[1] / height
        for x, y in points:
            client_x, client_y = ui.to_client(x, y, (width, height))
            back_x = round(client_x * scale_x)
            back_y = round(client_y * scale_y)
            assert abs(back_x - x) <= 2, (width, height, x, y)
            assert abs(back_y - y) <= 2, (width, height, x, y)


def _window(client_width: int, client_height: int) -> WindowInfo:
    border_w, border_h = 16, 39
    return WindowInfo(
        hwnd=0x1,
        title="Melvor2",
        left=0,
        top=0,
        right=client_width + border_w,
        bottom=client_height + border_h,
        client_x=0,
        client_y=0,
        client_width=client_width,
        client_height=client_height,
    )


@pytest.mark.parametrize(
    "delta, expected",
    [(0, True), (2, True), (-2, True), (3, False), (-3, False)],
)
def test_layout_ready_tolerates_only_rounding(
    monkeypatch: pytest.MonkeyPatch, delta: int, expected: bool
) -> None:
    monkeypatch.setattr(window_module, "is_minimized", lambda hwnd: False)
    win = _window(
        ui.REFERENCE_SIZE[0] + delta, ui.REFERENCE_SIZE[1] + delta
    )
    ok, _reason = window_module.layout_ready(win)
    assert ok is expected


def test_layout_ready_rejects_a_minimized_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(window_module, "is_minimized", lambda hwnd: True)
    ok, reason = window_module.layout_ready(_window(*ui.REFERENCE_SIZE))
    assert ok is False
    assert "minimized" in reason


class FakeUser32:
    def __init__(self, *, maximized: bool) -> None:
        self.maximized = maximized
        self.restored = 0
        self.placed: tuple[int, int, int, int, int] | None = None

    def IsIconic(self, hwnd: int) -> bool:
        return False

    def IsZoomed(self, hwnd: int) -> bool:
        return self.maximized

    def ShowWindow(self, hwnd: int, command: int) -> bool:
        assert command == window_module.SW_RESTORE
        self.maximized = False
        self.restored += 1
        return True

    def SetWindowPos(
        self,
        hwnd: int,
        insert_after: int,
        x: int,
        y: int,
        width: int,
        height: int,
        flags: int,
    ) -> bool:
        self.placed = (x, y, width, height, flags)
        return True


def _fake_display(
    monkeypatch: pytest.MonkeyPatch, fake: FakeUser32, restored: WindowInfo
) -> None:
    monkeypatch.setattr(window_module, "user32", fake)
    monkeypatch.setattr(window_module.time, "sleep", lambda *_: None)

    def fake_info(hwnd: int, title: str | None = None) -> WindowInfo:
        if fake.placed is None:
            return restored
        _x, _y, width, height, _flags = fake.placed
        return WindowInfo(
            hwnd=hwnd,
            title="Melvor2",
            left=0,
            top=0,
            right=width,
            bottom=height,
            client_x=0,
            client_y=0,
            client_width=width - 16,
            client_height=height - 39,
        )

    monkeypatch.setattr(window_module, "window_info", fake_info)


def test_ensure_reference_size_restores_a_maximized_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeUser32(maximized=True)
    _fake_display(monkeypatch, fake, _window(1350, 729))

    result = window_module.ensure_reference_size(_window(1350, 729))

    assert fake.restored == 1
    assert fake.placed is not None
    _x, _y, width, height, flags = fake.placed
    assert (width - 16, height - 39) == ui.REFERENCE_SIZE
    assert flags & window_module.SWP_NOACTIVATE
    assert flags & window_module.SWP_NOZORDER
    assert result.client_area == ui.REFERENCE_SIZE


def test_ensure_reference_size_leaves_a_correct_window_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeUser32(maximized=False)
    _fake_display(monkeypatch, fake, _window(*ui.REFERENCE_SIZE))
    win = _window(*ui.REFERENCE_SIZE)

    result = window_module.ensure_reference_size(win)

    assert result is win
    assert fake.restored == 0
    assert fake.placed is None


def test_ensure_reference_size_never_touches_a_minimized_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeUser32(maximized=False)
    _fake_display(monkeypatch, fake, _window(1350, 729))
    monkeypatch.setattr(window_module, "is_minimized", lambda hwnd: True)
    win = _window(1350, 729)

    result = window_module.ensure_reference_size(win)

    assert result is win
    assert fake.placed is None
