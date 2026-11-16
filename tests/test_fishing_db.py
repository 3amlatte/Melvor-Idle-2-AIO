from __future__ import annotations

import pytest

from mi2_aio.fishing_db import load_fishing


def test_locations_match_the_demo_layout() -> None:
    db = load_fishing()
    assert [location.name for location in db.locations] == [
        "Shallow Shores",
        "Shrapnel River",
        "Lemvor Pier",
        "Windy Coastline",
        "Glowing Depths",
        "Coral Reef",
        "Open Ocean",
    ]
    available = [location.name for location in db.available_locations()]
    assert available == [
        "Shallow Shores",
        "Shrapnel River",
        "Lemvor Pier",
        "Windy Coastline",
        "Glowing Depths",
    ]
    assert db.location("Coral Reef").demo_locked is True
    assert db.location("Open Ocean").demo_locked is True


def test_spots_and_demo_locks() -> None:
    db = load_fishing()
    counts = {
        location.name: len(location.available_spots)
        for location in db.locations
    }
    assert counts == {
        "Shallow Shores": 3,
        "Shrapnel River": 3,
        "Lemvor Pier": 3,
        "Windy Coastline": 1,
        "Glowing Depths": 1,
        "Coral Reef": 0,
        "Open Ocean": 0,
    }
    assert sum(len(location.spots) for location in db.locations) == 23
    assert db.spot("Shrapnel River", "Moonlit Stream").demo_locked is True
    assert db.spot("Glowing Depths", "Glowing Rift").demo_locked is True


def test_spot_fish_weights_match_the_client() -> None:
    db = load_fishing()
    pebble = db.spot("Shrapnel River", "Pebble Bank")
    assert pebble is not None
    assert [fish.name for fish in pebble.fish] == ["Raw Herring", "Raw Trout"]
    assert [fish.chance for fish in pebble.fish] == pytest.approx(
        [4 / 9, 5 / 9], abs=1e-4
    )
    assert pebble.experience == 35
    assert pebble.interval_label == "8.00s - 16.00s"
    assert [item.name for item in pebble.special] == ["Rusty Ancient Dagger"]

    rocky = db.spot("Shallow Shores", "Rocky Shores")
    assert [fish.name for fish in rocky.fish] == ["Raw Sardine", "Raw Lobster"]
    assert [fish.chance for fish in rocky.fish] == pytest.approx(
        [4 / 9, 5 / 9], abs=1e-4
    )
    assert rocky.level == 44


def test_spot_lookup_accepts_ids_and_names() -> None:
    db = load_fishing()
    assert db.location("shallowshores").name == "Shallow Shores"
    assert db.location("Lemvor Pier").id == "LemvorPier"
    assert db.spot("Shallow Shores", "CalmShallows").name == "Calm Shallows"
    assert db.spot("Lemvor Pier", "sea edge").name == "Sea Edge"
    assert db.spot("Shallow Shores", "Open Ocean") is None
    assert db.location("Nowhere") is None
    assert "Pebble Bank" in db.spot_names()
