from __future__ import annotations

import logging
import threading

import numpy as np
import pytest
from PIL import Image

from mi2_aio import failsafe as failsafe_module
from mi2_aio.config import FailsafeSettings, Settings
from mi2_aio.failsafe import IdleFailsafe
from mi2_aio.savefile import SaveHeader
from mi2_aio.tasks.base import TaskContext
from mi2_aio.window import WindowInfo

WINDOW = WindowInfo(
    hwnd=0x1,
    title="Melvor2",
    left=0,
    top=0,
    right=2560,
    bottom=1369,
    client_x=0,
    client_y=0,
    client_width=2560,
    client_height=1369,
)


def header(*, entity: str = "", action: str = "") -> SaveHeader:
    return SaveHeader(
        save_version=28,
        uuid="X",
        character_name="DrinkWater",
        gamemode="Test",
        timestamp=None,
        active_entity=entity,
        active_entity_icon="",
        active_action=action,
        active_action_icon="",
        total_level=1,
        gp=0,
        slayer_coins=0,
        is_demo=True,
    )


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, **failsafe: object) -> None:
        settings = Settings(failsafe=FailsafeSettings(**failsafe))
        self.ctx = TaskContext(
            settings=settings,
            window=WINDOW,
            logger=logging.getLogger("test.failsafe"),
            stop=threading.Event(),
        )
        self.failsafe = IdleFailsafe(settings)
        self.clicks: list[tuple[int, int]] = []
        self.failsafe._click = lambda ctx, point: self.clicks.append(point)  # type: ignore[method-assign]
        monkeypatch.setattr(failsafe_module, "is_minimized", lambda hwnd: False)
        monkeypatch.setattr(failsafe_module.time, "sleep", lambda *_: None)


def test_idle_starts_the_fallback_action(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.ctx.header = header()
    h.failsafe.poll(h.ctx)
    assert h.clicks == [h.failsafe.settings.page, h.failsafe.settings.button]


def test_active_character_does_nothing(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.ctx.header = header(entity="Woodcutting", action="Maple Tree")
    h.failsafe.poll(h.ctx)
    assert h.clicks == []


def test_combat_entity_without_action_is_treated_as_idle(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.ctx.header = header(entity="Combat", action="")
    h.failsafe.poll(h.ctx)
    assert h.clicks == [h.failsafe.settings.page, h.failsafe.settings.button]


def test_ensure_active_runs_after_a_run(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.ctx.header = header(entity="Combat", action="Creeper Vines")
    monkeypatch.setattr(
        failsafe_module,
        "capture_client",
        lambda win: Image.new("RGB", (8, 8)),
    )
    monkeypatch.setattr(
        failsafe_module.ui, "action_panel_title", lambda image: None
    )
    h.failsafe.ensure_active(h.ctx)
    assert h.clicks == [h.failsafe.settings.page, h.failsafe.settings.button]


def test_ensure_active_does_not_override_a_visible_action(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.ctx.header = header()
    monkeypatch.setattr(
        failsafe_module,
        "capture_client",
        lambda win: Image.new("RGB", (8, 8)),
    )
    monkeypatch.setattr(
        failsafe_module.ui,
        "action_panel_title",
        lambda image: np.zeros((8, 8)),
    )
    h.failsafe.ensure_active(h.ctx)
    assert h.clicks == []


def test_disabled_does_nothing(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=False)
    h.ctx.header = header()
    h.failsafe.poll(h.ctx)
    assert h.clicks == []


def test_dry_run_sends_no_input(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.ctx.header = header()
    h.ctx.dry_run = True
    h.failsafe.poll(h.ctx)
    assert h.clicks == []


def test_cooldown_prevents_spam(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True, cooldown_seconds=60.0)
    h.ctx.header = header()
    h.failsafe.poll(h.ctx)
    h.failsafe.poll(h.ctx)
    assert len(h.clicks) == 2  # one attempt: page + button
