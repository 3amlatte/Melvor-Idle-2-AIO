"""Weapon-type stance tables extracted from the Melvor 2 client.

The combat page renders one stance button per entry in the weapon type's
``Stances`` list, in that order. The style switcher needs the order to click
the right button (for example a 2H sword is Slash, Block, Crush).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

DEFAULT_WEAPON_TYPE_DB_PATH = DATA_DIR / "weapon_types.json"


@dataclass(frozen=True)
class WeaponType:
    id: str
    name: str
    stances: tuple[str, ...]


@dataclass(frozen=True)
class WeaponTypeDatabase:
    game: str
    build: str
    source: str
    generated: str
    weapon_types: tuple[WeaponType, ...]

    def by_id(self, weapon_type_id: str) -> WeaponType | None:
        wanted = weapon_type_id.strip().lower()
        for item in self.weapon_types:
            if item.id.lower() == wanted:
                return item
        return None

    def by_name(self, display_name: str) -> WeaponType | None:
        wanted = display_name.strip().lower()
        for item in self.weapon_types:
            if item.name.lower() == wanted:
                return item
        return None

    def stances(self, display_name: str) -> tuple[str, ...]:
        item = self.by_name(display_name)
        return item.stances if item else ()

    def stance_index(self, display_name: str, style: str) -> int | None:
        """1-based order of ``style`` in the weapon type's stance list."""
        wanted = style.strip().lower()
        try:
            return self.stances(display_name).index(wanted)
        except ValueError:
            return None


@lru_cache(maxsize=4)
def _load(path: str) -> WeaponTypeDatabase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return WeaponTypeDatabase(
        game=str(raw.get("game", "")),
        build=str(raw.get("build", "")),
        source=str(raw.get("source", "")),
        generated=str(raw.get("generated", "")),
        weapon_types=tuple(
            WeaponType(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                stances=tuple(str(stance) for stance in item.get("stances", [])),
            )
            for item in raw.get("weapon_types", [])
        ),
    )


def load_weapon_types(path: str | Path | None = None) -> WeaponTypeDatabase:
    """Load the weapon-type stance table (cached per path)."""
    return _load(str(path or DEFAULT_WEAPON_TYPE_DB_PATH))
