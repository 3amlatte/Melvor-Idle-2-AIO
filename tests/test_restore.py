from __future__ import annotations

import logging
import threading

import numpy as np
import pytest
from PIL import Image, ImageDraw

from mi2_aio import ui
from mi2_aio.config import RestoreSettings, Settings
from mi2_aio.restore import PreviousActionRestore, RestoreState
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


def frame() -> Image.Image:
    return Image.new("RGB", ui.REFERENCE_SIZE, (25, 25, 28))


def test_action_panel_title_extracts_the_name_mask() -> None:
    image = frame()
    draw = ImageDraw.Draw(image)
    draw.rectangle((1981, 850, 2442, 901), fill=(0, 128, 128))
    # A large name block plus a separate category label on the right, matching
    # the game's banner layout (the label must be ignored).
    draw.rectangle((2005, 858, 2150, 892), fill=(255, 255, 255))
    draw.rectangle((2390, 858, 2430, 892), fill=(255, 255, 255))

    title = ui.action_panel_title(image)

    assert title is not None
    assert title.shape[0] > 8
    assert title.shape[1] > 30
    assert int(title.sum()) > 50


def test_action_panel_title_is_none_without_a_banner() -> None:
    assert ui.action_panel_title(frame()) is None


def test_find_action_title_matches_a_scaled_name() -> None:
    template = np.zeros((20, 120), dtype=np.float32)
    template[2:6, 8:112] = 1
    template[11:15, 28:92] = 1

    image = frame()
    draw = ImageDraw.Draw(image)
    scaled = np.asarray(
        Image.fromarray((template * 255).astype(np.uint8)).resize(
            (96, 16), Image.Resampling.LANCZOS
        )
    )
    left, top = 520, 700
    for y in range(scaled.shape[0]):
        for x in range(scaled.shape[1]):
            if scaled[y, x] > 128:
                draw.point((left + x, top + y), fill=(255, 255, 255))

    match = ui.find_action_title(image, template)

    assert match is not None
    point, score = match
    assert score > 0.65
    assert abs(point[0] - (left + 48)) <= 8
    assert abs(point[1] - (top + 8)) <= 8


def test_action_buttons_and_choice() -> None:
    image = frame()
    draw = ImageDraw.Draw(image)
    draw.rectangle((310, 838, 460, 885), fill=(1, 97, 1))
    draw.rectangle((310, 1074, 460, 1121), fill=(1, 97, 1))

    buttons = ui.find_action_buttons(image)

    assert len(buttons) == 2
    chosen = ui.choose_action_button(buttons, (574, 717))
    assert chosen is not None
    assert abs(chosen[0] - 385) <= 5
    assert abs(chosen[1] - 861) <= 5


def test_choose_action_button_ignores_buttons_above_the_name() -> None:
    assert ui.choose_action_button([(383, 500)], (574, 717)) is None


def test_same_title_compares_masks() -> None:
    mask = np.ones((20, 100), dtype=np.float32)
    assert ui.same_title(mask, mask.copy())
    assert not ui.same_title(mask, np.zeros((20, 100), dtype=np.float32))
    assert not ui.same_title(mask, np.ones((10, 100), dtype=np.float32))


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, **restore: object) -> None:
        settings = Settings(restore=RestoreSettings(**restore))
        self.ctx = TaskContext(
            settings=settings,
            window=WINDOW,
            logger=logging.getLogger("test.restore"),
            stop=threading.Event(),
        )
        self.restorer = PreviousActionRestore(settings.restore)
        self.clicks: list[tuple[int, int]] = []
        self.restorer._click = lambda ctx, point: self.clicks.append(point)  # type: ignore[method-assign]
        self.restorer._capture = lambda ctx: frame()  # type: ignore[method-assign]
        self.restorer._verify = lambda ctx, state: True  # type: ignore[method-assign]
        monkeypatch.setattr("mi2_aio.restore.time.sleep", lambda *_: None)

    def capture(self) -> None:
        self.restorer.capture(self.ctx)

    def restore(self) -> None:
        self.restorer.restore(self.ctx)


def test_capture_skips_an_idle_character(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header()
    h.capture()
    assert h.clicks == []
    assert h.restorer._state is None


def test_capture_skips_dry_run(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header(entity="Woodcutting", action="Willow Tree")
    h.ctx.dry_run = True
    h.capture()
    assert h.clicks == []
    assert h.restorer._state is None


def test_find_page_icon_skips_the_active_action_button() -> None:
    image = frame()
    draw = ImageDraw.Draw(image)

    def icon(box: tuple[int, int, int, int]) -> None:
        draw.rectangle(box, fill=(200, 50, 50))
        x0, y0, x1, y1 = box
        draw.rectangle((x0 + 10, y0 + 10, x1 - 10, y1 - 10), fill=(255, 255, 255))
        draw.rectangle((x0 + 18, y0 + 4, x1 - 18, y0 + 14), fill=(0, 150, 0))

    icon((1000, 15, 1060, 75))  # page header icon
    icon((18, 205, 62, 245))  # active-action button (same artwork, must be skipped)
    icon((18, 285, 62, 325))  # the actual page icon

    point = ui.find_page_icon(image)

    assert point is not None
    assert 270 <= point[1] <= 340
    assert 10 <= point[0] <= 70


def test_capture_remembers_a_skill_page(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header(entity="Woodcutting", action="Willow Tree")
    monkeypatch.setattr(ui, "find_page_icon", lambda image: (30, 304))
    monkeypatch.setattr(
        ui, "action_panel_title", lambda image: np.ones((20, 100), dtype=np.float32)
    )

    h.capture()

    assert h.clicks == [ui.ACTIVE_ACTION_BUTTON]
    state = h.restorer._state
    assert state is not None
    assert state.entity == "Woodcutting"
    assert state.action == "Willow Tree"
    assert state.page_icon == (30, 304)
    assert state.title_template is not None


def test_capture_combat_only_remembers_the_page(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.ctx.header = header(entity="Combat", action="Harvest Farm")
    h.capture()
    assert h.clicks == []
    assert h.restorer._state is not None
    assert h.restorer._state.is_combat


def test_restore_clicks_the_page_and_the_card_button(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.restorer._state = RestoreState(
        entity="Woodcutting",
        action="Willow Tree",
        page_icon=(30, 304),
        title_template=np.ones((20, 100), dtype=np.float32),
    )
    monkeypatch.setattr(h.restorer, "_read_header", lambda ctx: header())
    monkeypatch.setattr(
        ui, "find_action_title", lambda image, template: ((574, 717), 0.9)
    )
    monkeypatch.setattr(ui, "find_action_buttons", lambda image: [(383, 860)])
    monkeypatch.setattr(
        ui, "choose_action_button", lambda buttons, name: (383, 860)
    )

    h.restore()

    assert h.clicks == [(30, 304), (383, 860)]


def test_restore_does_nothing_when_the_action_is_running(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.restorer._state = RestoreState(
        entity="Woodcutting",
        action="Willow Tree",
        page_icon=(30, 304),
        title_template=np.ones((20, 100), dtype=np.float32),
    )
    monkeypatch.setattr(
        h.restorer,
        "_read_header",
        lambda ctx: header(entity="Woodcutting", action="Willow Tree"),
    )

    h.restore()

    assert h.clicks == []


def test_restore_leaves_combat_before_restoring(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.restorer._state = RestoreState(
        entity="Woodcutting",
        action="Willow Tree",
        page_icon=(30, 304),
        title_template=np.ones((20, 100), dtype=np.float32),
    )
    monkeypatch.setattr(
        h.restorer,
        "_read_header",
        lambda ctx: header(entity="Combat", action="Harvest Farm"),
    )
    monkeypatch.setattr(ui, "run_from_combat_ready", lambda image: True)
    monkeypatch.setattr(
        ui, "find_action_title", lambda image, template: ((574, 717), 0.9)
    )
    monkeypatch.setattr(ui, "find_action_buttons", lambda image: [(383, 860)])
    monkeypatch.setattr(
        ui, "choose_action_button", lambda buttons, name: (383, 860)
    )

    h.restore()

    assert h.clicks[:2] == [ui.NAV_COMBAT, ui.RUN_FROM_COMBAT]
    assert h.clicks[2:] == [(30, 304), (383, 860)]


def test_restore_combat_only_opens_the_combat_page(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.restorer._state = RestoreState(
        entity="Combat", action="Harvest Farm", page_icon=None, title_template=None
    )
    h.restore()
    assert h.clicks == [ui.NAV_COMBAT]
