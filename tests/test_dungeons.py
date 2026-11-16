from __future__ import annotations

import logging
import threading

import numpy as np
import pytest
from PIL import Image, ImageDraw

from mi2_aio import ui
from mi2_aio.config import DungeonSettings, Settings
from mi2_aio.savefile import SaveHeader
from mi2_aio.tasks import dungeons as dungeons_module
from mi2_aio.tasks.base import TaskContext
from mi2_aio.tasks.dungeons import DungeonTask
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


def _frame() -> Image.Image:
    return Image.new("RGB", ui.REFERENCE_SIZE, (30, 30, 32))


def test_area_menu_reader() -> None:
    closed = _frame()
    assert ui.area_menu_open(closed) is False
    opened = _frame()
    draw = ImageDraw.Draw(opened)
    # the menu's close button has a white X in this region
    draw.rectangle((2415, 165, 2455, 205), fill=(240, 240, 240))
    assert ui.area_menu_open(opened) is True


def test_dungeon_active_reader() -> None:
    assert ui.dungeon_active(_frame()) is False
    active = _frame()
    draw = ImageDraw.Draw(active)
    draw.rectangle(ui.DUNGEON_PROGRESS_BOX, fill=(240, 240, 240))
    assert ui.dungeon_active(active) is True


def test_find_dungeon_row() -> None:
    image = _frame()
    # A name-like glyph mask with structure (a constant mask makes normalized
    # cross-correlation degenerate), painted white inside the list region.
    template = np.zeros((20, 120), dtype=np.uint8)
    template[2:6, 8:112] = 255
    template[11:15, 28:92] = 255
    origin = (300, 545)
    array = np.asarray(image).copy()
    mask = template > 0
    region = array[origin[1]:origin[1] + mask.shape[0], origin[0]:origin[0] + mask.shape[1]]
    region[mask] = (245, 245, 245)
    image = Image.fromarray(array)
    point = ui.find_dungeon_row(image, (template > 0).astype(np.float32))
    assert point is not None
    assert origin[0] <= point[0] <= origin[0] + template.shape[1]
    assert origin[1] <= point[1] <= origin[1] + template.shape[0]


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
    def __init__(self, monkeypatch: pytest.MonkeyPatch, **dungeons: object) -> None:
        settings = Settings(dungeons=DungeonSettings(**dungeons))
        self.ctx = TaskContext(
            settings=settings,
            window=WINDOW,
            logger=logging.getLogger("test.dungeons"),
            stop=threading.Event(),
        )
        self.task = DungeonTask()
        self.clicks: list[tuple[int, int]] = []
        self.menu = False
        self.active = False
        self.food = "enabled"
        self.hp = 0.9
        self.style = ui.CombatStyle(word="melee", advantage="disadvantaged")
        self.switched: list[str] = []

        self.task._capture = lambda ctx: _frame()  # type: ignore[method-assign]
        self.task._click = lambda ctx, point: self.clicks.append(point)  # type: ignore[method-assign]
        self.task._template = np.ones((10, 10), dtype=np.float32)
        monkeypatch.setattr(ui, "area_menu_open", lambda image: self.menu)
        monkeypatch.setattr(ui, "dungeon_active", lambda image: self.active)
        monkeypatch.setattr(ui, "read_combat_style", lambda image: self.style)
        monkeypatch.setattr(ui, "find_dungeon_row", lambda image, tpl: (300, 550))
        monkeypatch.setattr(ui, "eat_button_state", lambda image: self.food)
        monkeypatch.setattr(ui, "hp_ratio", lambda image: self.hp)
        monkeypatch.setattr(ui, "ammo_available", lambda image: True)
        monkeypatch.setattr(ui, "run_from_combat_ready", lambda image: True)
        monkeypatch.setattr(
            dungeons_module.equipment,
            "switch_weapon",
            lambda window, settings, name: self.switched.append(name),
        )
        monkeypatch.setattr(dungeons_module.time, "sleep", lambda *_: None)

    def step(self) -> None:
        self.task.step(self.ctx)


def test_idle_opens_the_area_menu(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header()
    h.step()
    assert ui.AREA_BUTTON in h.clicks


def test_menu_navigates_and_starts_the_dungeon(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header()
    h.menu = True
    h.step()
    assert ui.DUNGEON_TAB in h.clicks
    assert (300, 550) in h.clicks
    assert ui.START_DUNGEON in h.clicks


def test_in_dungeon_does_not_navigate(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header(entity="Combat", action="Harvest Farm")
    h.active = True
    h.step()
    assert ui.AREA_BUTTON not in h.clicks
    assert ui.START_DUNGEON not in h.clicks


def test_header_confirms_dungeon_during_transition(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header(entity="Combat", action="Harvest Farm")
    h.active = False
    h.step()
    assert ui.AREA_BUTTON not in h.clicks


def test_out_of_food_flees_and_stops(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header(entity="Combat", action="Harvest Farm")
    h.active = True
    h.food = "disabled"
    h.step()
    assert h.ctx.stop.is_set() is False
    h.step()
    assert h.ctx.stop.is_set() is True
    assert ui.RUN_FROM_COMBAT in h.clicks


def test_disadvantage_switches_weapon(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header(entity="Combat", action="Harvest Farm")
    h.active = True
    h.step()
    assert h.switched == ["Normal Bow"]
