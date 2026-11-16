"""Read-only Slayer master database extracted from the Melvor 2 client.

Each master lists its combat areas, task length, reroll/block costs and unlock
requirements. The current task itself is read from the save (see
``savefile.parse_slayer_task``); this database is the reference for future
automatic master switching.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

DEFAULT_MASTER_DB_PATH = DATA_DIR / "slayer_masters.json"


@dataclass(frozen=True)
class SlayerArea:
    id: str
    name: str


@dataclass(frozen=True)
class SlayerRequirement:
    type: str
    skill: str = ""
    level: int | None = None
    statistic: str = ""
    value: float | None = None


@dataclass(frozen=True)
class BlockSlot:
    id: str
    tasks_completed: float | None
    requirements: tuple[SlayerRequirement, ...]


@dataclass(frozen=True)
class CurrencyCost:
    currency: str
    quantity: int


@dataclass(frozen=True)
class SlayerMaster:
    id: str
    name: str
    icon: str
    areas: tuple[SlayerArea, ...]
    unlock_requirements: tuple[SlayerRequirement, ...]
    base_task_length: int
    reroll_cost: CurrencyCost | None
    block_slots: tuple[BlockSlot, ...]
    block_cost: CurrencyCost | None
    reward_currency: str

    @property
    def area_ids(self) -> tuple[str, ...]:
        return tuple(area.id for area in self.areas)

    @property
    def unlock_level(self) -> int | None:
        for requirement in self.unlock_requirements:
            if requirement.type == "Level" and requirement.skill == "Slayer":
                return requirement.level
        return None

    def unlocked_for(self, levels: Mapping[str, int]) -> bool:
        for requirement in self.unlock_requirements:
            if requirement.type != "Level":
                return False
            if levels.get(requirement.skill, 0) < (requirement.level or 0):
                return False
        return True


@dataclass(frozen=True)
class SlayerMasterDatabase:
    game: str
    build: str
    source: str
    generated: str
    masters: tuple[SlayerMaster, ...]

    def find(self, query: str) -> SlayerMaster | None:
        wanted = query.strip().lower()
        for master in self.masters:
            if master.id.lower() == wanted or master.name.lower() == wanted:
                return master
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(master.name for master in self.masters)

    def unlocked(self, levels: Mapping[str, int]) -> tuple[SlayerMaster, ...]:
        return tuple(
            master for master in self.masters if master.unlocked_for(levels)
        )


def _area(raw: Mapping[str, object]) -> SlayerArea:
    return SlayerArea(
        id=str(raw.get("id", "")), name=str(raw.get("name", ""))
    )


def _requirement(raw: Mapping[str, object]) -> SlayerRequirement:
    return SlayerRequirement(
        type=str(raw.get("type", "")),
        skill=str(raw.get("skill", "")),
        level=(
            int(raw["level"]) if raw.get("level") is not None else None
        ),
        statistic=str(raw.get("statistic", "")),
        value=(
            float(raw["value"]) if raw.get("value") is not None else None
        ),
    )


def _cost(raw: Mapping[str, object] | None) -> CurrencyCost | None:
    if not isinstance(raw, Mapping):
        return None
    return CurrencyCost(
        currency=str(raw.get("currency", "")),
        quantity=int(raw.get("quantity", 0)),
    )


def _master(raw: Mapping[str, object]) -> SlayerMaster:
    return SlayerMaster(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        icon=str(raw.get("icon", "")),
        areas=tuple(
            _area(area) for area in raw.get("areas", [])
        ),
        unlock_requirements=tuple(
            _requirement(requirement)
            for requirement in raw.get("unlock_requirements", [])
        ),
        base_task_length=int(raw.get("base_task_length", 0)),
        reroll_cost=_cost(raw.get("reroll_cost")),  # type: ignore[arg-type]
        block_slots=tuple(
            BlockSlot(
                id=str(slot.get("id", "")),
                tasks_completed=(
                    float(slot["tasks_completed"])
                    if slot.get("tasks_completed") is not None
                    else None
                ),
                requirements=tuple(
                    _requirement(requirement)
                    for requirement in slot.get("requirements", [])
                ),
            )
            for slot in raw.get("block_slots", [])
        ),
        block_cost=_cost(raw.get("block_cost")),  # type: ignore[arg-type]
        reward_currency=str(raw.get("reward_currency", "")),
    )


@lru_cache(maxsize=4)
def _load(path: str) -> SlayerMasterDatabase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return SlayerMasterDatabase(
        game=str(raw.get("game", "")),
        build=str(raw.get("build", "")),
        source=str(raw.get("source", "")),
        generated=str(raw.get("generated", "")),
        masters=tuple(
            _master(master) for master in raw.get("masters", [])
        ),
    )


def load_slayer_masters(
    path: str | Path | None = None,
) -> SlayerMasterDatabase:
    """Load the Slayer master database (cached per path)."""
    return _load(str(path or DEFAULT_MASTER_DB_PATH))
