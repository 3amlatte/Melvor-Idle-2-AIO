"""Bone item database and prayer-point helpers.

Bones are ordinary bank items with a ``MelvorBase:Bury`` capability. Their
``CurrencyGain`` is the number of Prayer points restored by burying one item.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

DEFAULT_BONE_DB_PATH = DATA_DIR / "bones.json"


def item_name(item_id: str) -> str:
    """Turn a CamelCase game id into its display-style name.

    ``BoneScythe`` -> ``Bone Scythe``, ``SmallDragonBone`` -> ``Small Dragon
    Bone``. Bank search matches item names, so this is enough to reproduce the
    result order without shipping a full item catalogue.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", item_id)
    return re.sub(r"\s+", " ", spaced).strip()


def search_index(
    bank_order: tuple[str, ...] | list[str],
    search: str,
    target_id: str,
) -> int | None:
    """Return the bank result-grid index of ``target_id`` for a search term.

    Melvor 2's bank search matches the words in an item's name ("Bone" returns
    Bone Scythe before Bone). The save stores the bank in display order, so
    filtering that order by the same term reproduces the grid exactly. This is
    what lets the bot select the real bone instead of the first result.
    """
    wanted = search.replace(" ", "").lower()
    if not wanted:
        return None
    seen: set[str] = set()
    index = 0
    for item_id in bank_order:
        if item_id in seen:
            continue
        seen.add(item_id)
        if wanted not in item_name(item_id).replace(" ", "").lower():
            continue
        if item_id == target_id:
            return index
        index += 1
    return None


@dataclass(frozen=True)
class Bone:
    id: str
    name: str
    icon: str
    prayer_points: int
    sells_for: int | None
    available_in_demo: bool


@dataclass(frozen=True)
class BoneDatabase:
    game: str
    build: str
    source: str
    generated: str
    bones: tuple[Bone, ...]

    def find(self, query: str) -> Bone | None:
        wanted = query.strip().lower()
        for bone in self.bones:
            if bone.id.lower() == wanted or bone.name.lower() == wanted:
                return bone
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(bone.name for bone in self.bones)

    def bone_stacks(
        self, stacks: Mapping[str, int]
    ) -> tuple[tuple[Bone, int], ...]:
        """Return ``(bone, quantity)`` for owned bone items."""
        found: list[tuple[Bone, int]] = []
        for bone in self.bones:
            quantity = int(stacks.get(bone.id, 0))
            if quantity > 0:
                found.append((bone, quantity))
        return tuple(found)

    def count(self, stacks: Mapping[str, int]) -> int:
        return sum(quantity for _bone, quantity in self.bone_stacks(stacks))

    def prayer_points(self, stacks: Mapping[str, int]) -> int:
        return sum(
            bone.prayer_points * quantity
            for bone, quantity in self.bone_stacks(stacks)
        )


@lru_cache(maxsize=4)
def _load(path: str) -> BoneDatabase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return BoneDatabase(
        game=str(raw.get("game", "")),
        build=str(raw.get("build", "")),
        source=str(raw.get("source", "")),
        generated=str(raw.get("generated", "")),
        bones=tuple(
            Bone(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                icon=str(item.get("icon", "")),
                prayer_points=int(item.get("prayer_points", 0)),
                sells_for=(
                    int(item["sells_for"])
                    if item.get("sells_for") is not None
                    else None
                ),
                available_in_demo=bool(item.get("available_in_demo", True)),
            )
            for item in raw.get("bones", [])
        ),
    )


def load_bones(path: str | Path | None = None) -> BoneDatabase:
    """Load the bone database (cached per path)."""
    return _load(str(path or DEFAULT_BONE_DB_PATH))
