from __future__ import annotations

import logging
import threading

import pytest
from helpers import make_farm_badge_frame, make_farm_card_frame, make_mill_frame

from mi2_aio import farming as farming_module
from mi2_aio import ui
from mi2_aio.config import FarmingSettings, Settings
from mi2_aio.farming import FarmingMaintenance
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

CARD = ui.FarmCard(140, 239, 446)
counts = {"harvested": 0, "composted": 0, "planted": 0, "watered": 0, "bins": 0, "blocked": 0, "locked": 0}


def test_attention_badge_reader() -> None:
    assert ui.farming_badge(make_farm_badge_frame(badge=True)) is True
    assert ui.farming_badge(make_farm_badge_frame(badge=False)) is False


@pytest.mark.parametrize(
    "state", ["growing", "ready", "empty", "locked", "purchase", "locked_title"]
)
def test_card_state_reader(state: str) -> None:
    frame = make_farm_card_frame(state)
    expected = "locked" if state in {"purchase", "locked_title"} else state
    assert ui.card_state(frame, CARD) == expected


def test_white_flower_art_is_not_empty() -> None:
    frame = make_farm_card_frame("growing")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    # White strawberry-like flowers in the title region + green leaves above.
    draw.rectangle(
        (CARD.x + 110, CARD.y + 125, CARD.x + 250, CARD.y + 160),
        fill=(250, 250, 250),
    )
    draw.rectangle(
        (CARD.x + 60, CARD.y + 80, CARD.x + 380, CARD.y + 220),
        fill=(20, 160, 20),
    )
    assert ui.card_empty(frame, CARD) is False
    assert ui.card_state(frame, CARD) == "growing"


def test_ready_card_with_red_crop_art_is_ready() -> None:
    frame = make_farm_card_frame("ready", red_art=True)
    assert ui.card_clear_button(frame, CARD) is True  # red fruit looks like Clear
    assert ui.card_ready(frame, CARD) is True
    assert ui.card_state(frame, CARD) == "ready"


def test_growing_card_water_badges() -> None:
    watered = make_farm_card_frame("growing", watered=True)
    dry = make_farm_card_frame("growing", watered=False)
    assert ui.card_watered(watered, CARD) is True
    assert ui.card_not_watered(watered, CARD) is False
    assert ui.card_watered(dry, CARD) is False
    assert ui.card_not_watered(dry, CARD) is True


def test_empty_card_after_compost_stays_empty() -> None:
    frame = make_farm_card_frame("empty", composted=True)
    assert ui.card_compost_button(frame, CARD) is False
    assert ui.card_state(frame, CARD) == "empty"


def test_compost_picker_readers() -> None:
    closed = make_farm_card_frame("empty")
    assert ui.card_compost_picker_open(closed, CARD) is False

    opened = make_farm_card_frame("empty")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(opened)
    draw.rectangle(CARD.box(ui.FARM_COMPOST_PICKER_BOX), fill=(240, 240, 240))
    assert ui.card_compost_picker_open(opened, CARD) is True

    select = ui.card_compost_select_point(CARD)
    first = ui.card_compost_picker_point(CARD, 1)
    second = ui.card_compost_picker_point(CARD, 2)
    assert select[1] < first[1]
    assert first[0] < second[0]


class FarmHarness:
    def __init__(self, frames, **farming: object) -> None:
        # Keep the classic sequences deterministic; the compost-picker path has
        # its own test.
        farming.setdefault("select_compost", False)
        settings = Settings(farming=FarmingSettings(**farming))
        self.ctx = TaskContext(
            settings=settings,
            window=WINDOW,
            logger=logging.getLogger("test.farming"),
            stop=threading.Event(),
            page="combat",
        )
        self.maintenance = FarmingMaintenance(settings)
        self.frames = list(frames)
        self.clicks: list[tuple[int, int]] = []
        self.holds: list[tuple[int, int]] = []

        def capture(ctx):
            if len(self.frames) > 1:
                return self.frames.pop(0)
            return self.frames[0]

        self.maintenance._capture = capture  # type: ignore[method-assign]
        self.maintenance._click = lambda ctx, point: self.clicks.append(point)  # type: ignore[method-assign]
        self.maintenance._hold = lambda ctx, point: self.holds.append(point)  # type: ignore[method-assign]

    def handle(self) -> dict[str, int]:
        counts = {"harvested": 0, "composted": 0, "planted": 0, "watered": 0, "bins": 0, "blocked": 0, "locked": 0}
        self.maintenance._handle_card(self.ctx, CARD, counts)
        return counts


def test_harvest_compost_plant_sequence() -> None:
    h = FarmHarness(
        [
            make_farm_card_frame("ready"),
            make_farm_card_frame("empty"),
            make_farm_card_frame("empty", composted=True),
            make_farm_card_frame("growing"),
        ]
    )
    counts = h.handle()

    assert counts == {"harvested": 1, "composted": 1, "planted": 1, "watered": 0, "bins": 0, "blocked": 0, "locked": 0}
    assert len(h.clicks) == 3
    # Harvest and Plant use the green button in the same column (the ready
    # title sits just above and can shift the detected centroid slightly).
    assert abs(h.clicks[0][0] - h.clicks[2][0]) <= 10
    assert h.clicks[1] != h.clicks[0]
    assert h.holds == []


def test_empty_plot_skips_harvest_count() -> None:
    h = FarmHarness(
        [
            make_farm_card_frame("empty"),
            make_farm_card_frame("empty", composted=True),
            make_farm_card_frame("growing"),
        ]
    )
    counts = h.handle()
    assert counts["harvested"] == 0
    assert counts["composted"] == 1
    assert counts["planted"] == 1


def test_compost_disabled_plants_directly() -> None:
    h = FarmHarness(
        [
            make_farm_card_frame("empty"),
            make_farm_card_frame("growing"),
        ],
        compost=False,
    )
    counts = h.handle()
    assert counts["composted"] == 0
    assert counts["planted"] == 1


def test_empty_plot_without_seeds_is_blocked() -> None:
    h = FarmHarness(
        [make_farm_card_frame("empty", plantable=False)],
        compost=False,
    )
    counts = h.handle()
    assert counts["planted"] == 0
    assert counts["blocked"] == 1
    assert h.clicks == [] and h.holds == []


def test_empty_plot_selects_compost_before_applying_it() -> None:
    h = FarmHarness(
        [
            make_farm_card_frame("empty"),  # initial empty plot
            make_farm_card_frame("empty"),  # picker-closed check
            make_farm_card_frame("empty"),  # after selecting the compost
            make_farm_card_frame("empty", composted=True),
            make_farm_card_frame("growing"),
        ],
        select_compost=True,
        compost_slot=1,
    )
    counts = h.handle()

    assert ui.card_compost_select_point(CARD) in h.clicks
    assert ui.card_compost_picker_point(CARD, 1) in h.clicks
    assert counts["composted"] == 1
    assert counts["planted"] == 1


def test_growing_unwatered_holds_water() -> None:
    h = FarmHarness(
        [
            make_farm_card_frame("growing", watered=False),
            make_farm_card_frame("growing"),
        ]
    )
    counts = h.handle()
    assert counts["watered"] == 1
    assert h.clicks == []
    assert len(h.holds) == 1


def test_water_disabled_does_nothing() -> None:
    h = FarmHarness(
        [make_farm_card_frame("growing", watered=False)], water=False
    )
    counts = h.handle()
    assert counts["watered"] == 0
    assert h.holds == []


def test_locked_card_is_ignored() -> None:
    h = FarmHarness([make_farm_card_frame("locked")])
    counts = h.handle()
    assert h.clicks == [] and h.holds == []
    assert counts == {"harvested": 0, "composted": 0, "planted": 0, "watered": 0, "bins": 0, "blocked": 0, "locked": 1}


def test_poll_is_disabled_by_default() -> None:
    settings = Settings()
    maintenance = FarmingMaintenance(settings)
    calls: list[str] = []
    maintenance._capture = lambda ctx: calls.append("capture")  # type: ignore[method-assign]
    ctx = TaskContext(
        settings=settings,
        window=WINDOW,
        logger=logging.getLogger("test.farming"),
        stop=threading.Event(),
    )
    maintenance.poll(ctx)
    assert calls == []


def test_farming_prioritise_defaults_true_and_badge_only() -> None:
    settings = FarmingSettings()
    assert settings.prioritise is True
    assert settings.check_minutes == 0.0


def test_poll_only_runs_when_the_attention_badge_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        farming=FarmingSettings(
            enabled=True, check_minutes=0.0, badge_poll_seconds=1.0
        )
    )
    maintenance = FarmingMaintenance(settings)
    maintenance._capture = lambda ctx: object()  # type: ignore[method-assign]
    ctx = TaskContext(
        settings=settings,
        window=WINDOW,
        logger=logging.getLogger("test.farming"),
        stop=threading.Event(),
    )
    passes: list[str] = []
    maintenance.run_pass = (  # type: ignore[method-assign]
        lambda ctx, **kwargs: passes.append(kwargs.get("reason", ""))
    )

    monkeypatch.setattr(ui, "farming_badge", lambda image: False)
    maintenance.poll(ctx)
    assert passes == []

    monkeypatch.setattr(ui, "farming_badge", lambda image: True)
    maintenance._last_badge_poll = 0.0
    maintenance.poll(ctx)
    assert passes == ["badge"]


# --- the mill --------------------------------------------------------------
def test_mill_status_reader() -> None:
    assert ui.mill_status(make_mill_frame(running=True)) == "running"
    assert ui.mill_status(make_mill_frame(running=False)) == "stopped"


def test_mill_open_reader() -> None:
    assert ui.mill_open(make_mill_frame(open=True)) is True
    assert ui.mill_open(make_mill_frame(open=False)) is False


def test_mill_item_fill_reader() -> None:
    assert ui.mill_item_fill(make_mill_frame(stock=True)) > 0.4
    assert ui.mill_item_fill(make_mill_frame(stock=False)) < 0.05


class MillHarness:
    def __init__(self, frames, monkeypatch, **farming: object) -> None:
        settings = Settings(farming=FarmingSettings(**farming))
        self.ctx = TaskContext(
            settings=settings,
            window=WINDOW,
            logger=logging.getLogger("test.farming"),
            stop=threading.Event(),
            page="combat",
        )
        self.maintenance = FarmingMaintenance(settings)
        self.frames = list(frames)
        self.clicks: list[tuple[int, int]] = []
        self.counts = {
            "harvested": 0,
            "composted": 0,
            "planted": 0,
            "watered": 0,
            "bins": 0,
            "mill": 0,
        }

        def capture(ctx):
            if len(self.frames) > 1:
                return self.frames.pop(0)
            return self.frames[0]

        self.maintenance._capture = capture  # type: ignore[method-assign]
        self.maintenance._click = lambda ctx, point: self.clicks.append(point)  # type: ignore[method-assign]
        monkeypatch.setattr(farming_module.time, "sleep", lambda *_: None)

    def handle(self) -> dict[str, int]:
        self.maintenance._handle_mill(self.ctx, self.counts)
        return self.counts


def test_mill_starts_when_stopped(monkeypatch) -> None:
    h = MillHarness(
        [make_mill_frame(running=False, stock=True, open=True)], monkeypatch
    )
    counts = h.handle()
    assert counts["mill"] == 1
    assert ui.MILL_TOGGLE in h.clicks
    deposits = [c for c in h.clicks if c in ui.MILL_DEPOSIT_BUTTONS]
    assert len(deposits) == 4


def test_mill_running_does_not_toggle(monkeypatch) -> None:
    h = MillHarness(
        [make_mill_frame(running=True, stock=True, open=True)], monkeypatch
    )
    h.handle()
    assert ui.MILL_TOGGLE not in h.clicks


def test_mill_stopped_without_stock_does_not_start(monkeypatch) -> None:
    h = MillHarness(
        [make_mill_frame(running=False, stock=False, open=True)], monkeypatch
    )
    h.handle()
    assert ui.MILL_TOGGLE not in h.clicks


def test_mill_opens_and_closes_panel(monkeypatch) -> None:
    h = MillHarness(
        [
            make_mill_frame(open=False),
            make_mill_frame(running=True, stock=True, open=True),
        ],
        monkeypatch,
    )
    h.handle()
    assert h.clicks[0] == ui.MILL_PANEL_BUTTON
    assert h.clicks[-1] == ui.MILL_PANEL_BUTTON


def test_farming_tabs_visible_reader() -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", ui.REFERENCE_SIZE, (30, 30, 32))
    assert ui.farming_tabs_visible(image) is False
    draw = ImageDraw.Draw(image)
    draw.rectangle(ui.FARM_TABS_BOX, fill=(30, 110, 40))
    draw.rectangle(ui.FARM_BUILDINGS_BOX, fill=(245, 245, 245))
    assert ui.farming_tabs_visible(image) is True
