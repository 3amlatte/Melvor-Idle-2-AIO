from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import pytest

import mi2_aio.tasks.bone_farming as bone_module
from mi2_aio import ui
from mi2_aio.config import Settings
from mi2_aio.savefile import SaveHeader
from mi2_aio.tasks.base import TaskContext
from mi2_aio.tasks.bone_farming import BoneFarmingTask

WINDOW = SimpleNamespace(hwnd=1, client_area=ui.REFERENCE_SIZE)


def header(enemy: str = "GiantChicken") -> SaveHeader:
    return SaveHeader(
        save_version=28,
        uuid="X",
        character_name="DrinkWater",
        gamemode="Test",
        timestamp=None,
        active_entity="Combat",
        active_entity_icon="",
        active_action="GiantChicken" if enemy else "Idle",
        active_action_icon="",
        total_level=735,
        gp=0,
        slayer_coins=0,
        is_demo=True,
        active_enemy_id=enemy,
    )


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.ctx = TaskContext(
            settings=Settings(),
            window=WINDOW,
            logger=logging.getLogger("test.bone_farming"),
            stop=threading.Event(),
        )
        self.task = BoneFarmingTask()
        self.clicks: list[tuple[int, int]] = []
        self.menu = False
        self.food = "enabled"
        self.fighting = False
        self.hp = 0.8

        self.task._capture = lambda ctx: object()  # type: ignore[method-assign]
        self.task._click = lambda ctx, point: self.clicks.append(point)  # type: ignore[method-assign]
        monkeypatch.setattr(bone_module, "is_minimized", lambda _hwnd: False)
        monkeypatch.setattr(ui, "area_menu_open", lambda image: self.menu)
        monkeypatch.setattr(ui, "hp_ratio", lambda image: self.hp)
        monkeypatch.setattr(ui, "eat_button_state", lambda image: self.food)
        monkeypatch.setattr(
            ui, "run_from_combat_ready", lambda image: self.fighting
        )
        monkeypatch.setattr(bone_module.time, "sleep", lambda *_: None)

    def step(self) -> None:
        self.task.step(self.ctx)


def test_idle_opens_the_area_menu(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header("")
    h.step()
    assert ui.AREA_BUTTON in h.clicks


def test_menu_selects_giant_chicken_and_fights(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header("")
    h.menu = True
    h.step()
    assert ui.BONE_FARM_AREA_TAB in h.clicks
    assert ui.BONE_FARM_AREA_ROW in h.clicks
    assert ui.BONE_FARM_FIGHT in h.clicks


def test_target_combat_does_not_navigate(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header("GiantChicken")
    h.fighting = True
    h.step()
    assert h.clicks == []
    assert not h.ctx.stop.is_set()


def test_out_of_food_stops_the_farm(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header("GiantChicken")
    h.fighting = True
    h.food = "disabled"
    h.step()
    assert h.ctx.stop.is_set()


def test_target_still_monitored_when_combat_page_is_unreadable(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header("GiantChicken")
    h.fighting = True
    h.hp = None
    h.food = "disabled"
    h.step()
    assert h.ctx.stop.is_set()
    assert ui.AREA_BUTTON not in h.clicks


def test_non_combat_page_opens_the_combat_tab(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header("")
    h.hp = None
    h.step()
    assert ui.NAV_COMBAT in h.clicks
    assert ui.AREA_BUTTON not in h.clicks


def test_wrong_enemy_reopens_the_area_menu(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header("MangroveMantis")
    h.fighting = True
    h.step()
    assert ui.AREA_BUTTON in h.clicks


def test_fight_click_waits_for_the_save_to_catch_up(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header("MangroveMantis")
    h.fighting = True
    h.task._fight_clicked_at = 1e12  # far future: inside the confirm window
    h.step()
    assert ui.AREA_BUTTON not in h.clicks


def test_dry_run_sends_no_clicks(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header("")
    h.ctx.dry_run = True
    h.step()
    assert h.clicks == []


def test_bone_farm_forces_prayer_upkeep() -> None:
    assert BoneFarmingTask.force_prayer is True
    assert BoneFarmingTask.skip_failsafe is True
