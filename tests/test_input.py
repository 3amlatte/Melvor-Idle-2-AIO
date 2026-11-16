from __future__ import annotations

from pathlib import Path

import pytest

from mi2_aio import input as input_module
from mi2_aio.config import AutomationSettings, load_settings
from mi2_aio.input import (
    MK_LBUTTON,
    MK_RBUTTON,
    WM_LBUTTONDBLCLK,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEMOVE,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    InputBlocked,
    background_click,
    click_game,
)
from mi2_aio.window import WindowInfo

WIN = WindowInfo(
    hwnd=0x1234,
    title="Melvor2",
    left=0,
    top=0,
    right=800,
    bottom=600,
    client_x=0,
    client_y=0,
    client_width=800,
    client_height=600,
)


@pytest.fixture()
def recorder(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int, int]]:
    sent: list[tuple[int, int, int]] = []
    monkeypatch.setattr(
        input_module,
        "_post",
        lambda hwnd, message, wparam, lparam: sent.append(
            (message, wparam, lparam)
        ),
    )
    monkeypatch.setattr(input_module, "_pause", lambda settings: None)
    monkeypatch.setattr(input_module, "_jitter", lambda settings: (0, 0))
    monkeypatch.setattr(input_module, "is_minimized", lambda hwnd: False)
    return sent


def test_pack_xy() -> None:
    assert input_module._pack_xy(10, 20) == (20 << 16) | 10
    assert input_module._pack_xy(0x1234, 0x5678) == (0x5678 << 16) | 0x1234


def test_background_click_message_sequence(
    recorder: list[tuple[int, int, int]]
) -> None:
    background_click(WIN, 100, 200, AutomationSettings(humanize=False))

    assert [message for message, _, _ in recorder] == [
        WM_MOUSEMOVE,
        WM_LBUTTONDOWN,
        WM_LBUTTONUP,
        WM_MOUSEMOVE,
    ]
    expected = input_module._pack_xy(100, 200)
    assert all(lparam == expected for _, _, lparam in recorder)
    assert recorder[1][1] == MK_LBUTTON
    assert recorder[2][1] == 0


def test_background_double_click_sends_dblclk(
    recorder: list[tuple[int, int, int]]
) -> None:
    background_click(WIN, 5, 6, AutomationSettings(humanize=False), clicks=2)
    assert [message for message, _, _ in recorder] == [
        WM_MOUSEMOVE,
        WM_LBUTTONDOWN,
        WM_LBUTTONUP,
        WM_LBUTTONDBLCLK,
        WM_LBUTTONUP,
        WM_MOUSEMOVE,
    ]


def test_background_right_click_uses_right_button_state(
    recorder: list[tuple[int, int, int]]
) -> None:
    background_click(
        WIN, 5, 6, AutomationSettings(humanize=False), button="right"
    )
    messages = [message for message, _, _ in recorder]
    assert messages[1] == WM_RBUTTONDOWN
    assert messages[2] == WM_RBUTTONUP
    assert recorder[1][1] == MK_RBUTTON


def test_background_click_refuses_minimized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(input_module, "is_minimized", lambda hwnd: True)
    with pytest.raises(InputBlocked, match="minimized"):
        background_click(WIN, 10, 10, AutomationSettings())


def test_background_click_rejects_out_of_bounds() -> None:
    with pytest.raises(ValueError, match="outside"):
        background_click(WIN, 900, 10, AutomationSettings())


def test_background_click_rejects_unknown_button(
    recorder: list[tuple[int, int, int]]
) -> None:
    with pytest.raises(ValueError, match="Unsupported mouse button"):
        background_click(WIN, 10, 10, AutomationSettings(), button="side")


def test_click_game_selects_input_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        input_module, "background_click", lambda *a, **k: calls.append("background")
    )
    monkeypatch.setattr(
        input_module, "click_client", lambda *a, **k: calls.append("foreground")
    )

    assert (
        click_game(WIN, 1, 1, AutomationSettings(background_input=True))
        == "background"
    )
    assert (
        click_game(WIN, 1, 1, AutomationSettings(background_input=False))
        == "foreground"
    )
    assert calls == ["background", "foreground"]


def test_background_input_config(tmp_path: Path) -> None:
    config = tmp_path / "settings.toml"
    config.write_text("[automation]\nbackground_input = false\n", encoding="utf-8")
    assert load_settings(config).automation.background_input is False
    assert AutomationSettings().background_input is True
