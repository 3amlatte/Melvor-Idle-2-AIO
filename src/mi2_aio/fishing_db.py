"""Read-only fishing database extracted from the client.

Locations hold the fishing spots shown by the **Select Spot** dropdown. Each
spot lists the fish it can produce, with the relative weight the client uses
(the right-hand output panel shows those weights as percentages), plus the
special-item rolls and the level requirement.

The demo locks whole locations and individual spots; those entries are kept so
the UI can explain what is missing instead of silently hiding content.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

DEFAULT_FISHING_DB_PATH = DATA_DIR / "fishing.json"


@dataclass(frozen=True)
class FishingFish:
    id: str
    name: str
    weight: float
    chance: float
    min_quantity: int
    max_quantity: int

    @property
    def quantity_label(self) -> str:
        if self.min_quantity == self.max_quantity:
            return str(self.min_quantity)
        return f"{self.min_quantity}-{self.max_quantity}"


@dataclass(frozen=True)
class FishingSpecial:
    id: str
    name: str
    chance: float
    quantity: int


@dataclass(frozen=True)
class FishingSpot:
    id: str
    name: str
    level: int
    demo_locked: bool
    experience: int
    fish_chance: float
    min_interval_ms: int
    max_interval_ms: int
    fish: tuple[FishingFish, ...]
    special: tuple[FishingSpecial, ...]

    @property
    def interval_label(self) -> str:
        return (
            f"{self.min_interval_ms / 1000:.2f}s - "
            f"{self.max_interval_ms / 1000:.2f}s"
        )

    @property
    def fish_names(self) -> tuple[str, ...]:
        return tuple(fish.name for fish in self.fish)

    @property
    def junk_chance(self) -> float:
        return max(0.0, 1.0 - self.fish_chance)


@dataclass(frozen=True)
class FishingLocation:
    id: str
    name: str
    level: int
    demo_locked: bool
    spots: tuple[FishingSpot, ...]

    @property
    def available_spots(self) -> tuple[FishingSpot, ...]:
        return tuple(spot for spot in self.spots if not spot.demo_locked)

    @property
    def spot_count(self) -> int:
        return len(self.available_spots)


@dataclass(frozen=True)
class FishingDatabase:
    game: str
    build: str
    source: str
    generated: str
    locations: tuple[FishingLocation, ...]

    def location(self, query: str) -> FishingLocation | None:
        wanted = query.strip().lower()
        for location in self.locations:
            if location.id.lower() == wanted or location.name.lower() == wanted:
                return location
        return None

    def available_locations(self) -> tuple[FishingLocation, ...]:
        return tuple(
            location for location in self.locations if not location.demo_locked
        )

    def spot(self, location: str, query: str) -> FishingSpot | None:
        found = self.location(location)
        if found is None:
            return None
        wanted = query.strip().lower()
        for spot in found.spots:
            if spot.id.lower() == wanted or spot.name.lower() == wanted:
                return spot
        return None

    def spot_names(self) -> tuple[str, ...]:
        return tuple(
            spot.name for location in self.locations for spot in location.spots
        )


def _fish(raw: Mapping[str, object]) -> FishingFish:
    return FishingFish(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        weight=float(raw.get("weight", 1)),
        chance=float(raw.get("chance", 0)),
        min_quantity=int(raw.get("min_quantity", 1)),
        max_quantity=int(raw.get("max_quantity", 1)),
    )


def _special(raw: Mapping[str, object]) -> FishingSpecial:
    return FishingSpecial(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        chance=float(raw.get("chance", 0)),
        quantity=int(raw.get("quantity", 1)),
    )


def _spot(raw: Mapping[str, object]) -> FishingSpot:
    return FishingSpot(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        level=int(raw.get("level", 1)),
        demo_locked=bool(raw.get("demo_locked", False)),
        experience=int(raw.get("experience", 0)),
        fish_chance=float(raw.get("fish_chance", 0)),
        min_interval_ms=int(raw.get("min_interval_ms", 0)),
        max_interval_ms=int(raw.get("max_interval_ms", 0)),
        fish=tuple(_fish(item) for item in raw.get("fish", [])),  # type: ignore[arg-type]
        special=tuple(
            _special(item) for item in raw.get("special", [])  # type: ignore[arg-type]
        ),
    )


def _location(raw: Mapping[str, object]) -> FishingLocation:
    return FishingLocation(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        level=int(raw.get("level", 1)),
        demo_locked=bool(raw.get("demo_locked", False)),
        spots=tuple(
            _spot(item) for item in raw.get("spots", [])  # type: ignore[arg-type]
        ),
    )


@lru_cache(maxsize=4)
def _load(path: str) -> FishingDatabase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return FishingDatabase(
        game=str(raw.get("game", "")),
        build=str(raw.get("build", "")),
        source=str(raw.get("source", "")),
        generated=str(raw.get("generated", "")),
        locations=tuple(
            _location(item) for item in raw.get("locations", [])
        ),
    )


def load_fishing(path: str | Path | None = None) -> FishingDatabase:
    """Load the fishing database (cached per path)."""
    return _load(str(path or DEFAULT_FISHING_DB_PATH))
