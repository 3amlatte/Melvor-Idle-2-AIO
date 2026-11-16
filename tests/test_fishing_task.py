from __future__ import annotations

import logging
import threading

import pytest

from mi2_aio.config import Settings
from mi2_aio.fishing_db import load_fishing
from mi2_aio.tasks.base import TaskContext
from mi2_aio.tasks.fishing import FishingTask
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


def make_context(**options: str) -> TaskContext:
    return TaskContext(
        settings=Settings(),
        window=WINDOW,
        logger=logging.getLogger("test.fishing"),
        stop=threading.Event(),
        options=options,
    )


def test_defaults_to_the_first_available_location() -> None:
    task = FishingTask()
    db = load_fishing()
    location = task._pick_location(db, "")
    assert location.name == "Shallow Shores"
    assert task._pick_spot(location, "").name == "Shallow Pools"


def test_demo_locked_and_unknown_choices_fall_back() -> None:
    task = FishingTask()
    db = load_fishing()
    assert task._pick_location(db, "Coral Reef").name == "Shallow Shores"
    assert task._pick_location(db, "Nope").name == "Shallow Shores"
    assert task._pick_location(db, "Lemvor Pier").name == "Lemvor Pier"

    lemvor = db.location("Lemvor Pier")
    assert task._pick_spot(lemvor, "Pier Walk").name == "Pier Walk"
    assert task._pick_spot(lemvor, "pierwalk").name == "Pier Walk"
    assert task._pick_spot(lemvor, "Not A Spot").name == "Dock Waters"


def test_start_logs_the_chosen_spot(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "mi2_aio.savefile.read_skills",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no save")),
    )
    task = FishingTask()
    ctx = make_context(location="ShrapnelRiver", spot="PebbleBank")
    with caplog.at_level(logging.INFO):
        task.start(ctx)
    assert task._location.name == "Shrapnel River"
    assert task._spot.name == "Pebble Bank"
    assert task._location_index == 1
    assert task._spot_index == 1
    assert "Raw Trout 56%" in caplog.text
    assert "Pebble Bank" in caplog.text


def test_dry_run_logs_the_plan_once(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "mi2_aio.savefile.read_skills",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no save")),
    )
    task = FishingTask()
    ctx = make_context(location="GlowingDepths", spot="ShimmeringDepths")
    ctx.dry_run = True
    task.start(ctx)
    with caplog.at_level(logging.INFO):
        assert task._act(ctx, "select the location and spot") is False
        assert task._act(ctx, "select the location and spot") is False
    assert caplog.text.count("DRY RUN") == 1
    assert "Shimmering Depths" in caplog.text


def test_spot_point_for_each_available_row() -> None:
    from mi2_aio import ui

    assert [ui.fishing_spot_point(index)[1] for index in range(3)] == [
        486,
        562,
        638,
    ]
    with pytest.raises(ui.UiError):
        ui.fishing_spot_point(-1)
