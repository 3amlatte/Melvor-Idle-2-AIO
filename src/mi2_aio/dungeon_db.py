"""Read-only standard-dungeon database extracted from the client.

Each dungeon lists its waves and the enemies in each wave. The style switcher
does not need the wave number: the save stores the active enemy id directly.
The database is kept for validation, logging and future wave planning.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

DEFAULT_DUNGEON_DB_PATH = DATA_DIR / "dungeons.json"


@dataclass(frozen=True)
class DungeonWave:
    count: int
    enemies: tuple[tuple[str, int], ...]  # (enemy id, weight)

    @property
    def enemy_ids(self) -> tuple[str, ...]:
        return tuple(enemy for enemy, _weight in self.enemies)


@dataclass(frozen=True)
class Dungeon:
    id: str
    name: str
    category: str
    difficulty: str
    darkness: int
    waves: tuple[DungeonWave, ...]
    rewards: Mapping[str, object]

    @property
    def enemy_ids(self) -> tuple[str, ...]:
        """Every enemy id that can appear in this dungeon, in wave order."""
        seen: list[str] = []
        for wave in self.waves:
            for enemy in wave.enemy_ids:
                if enemy not in seen:
                    seen.append(enemy)
        return tuple(seen)


@dataclass(frozen=True)
class DungeonDatabase:
    game: str
    build: str
    source: str
    generated: str
    dungeons: tuple[Dungeon, ...]

    def find(self, query: str) -> Dungeon | None:
        wanted = query.strip().lower()
        for dungeon in self.dungeons:
            if dungeon.id.lower() == wanted or dungeon.name.lower() == wanted:
                return dungeon
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(dungeon.name for dungeon in self.dungeons)


def _wave(raw: Mapping[str, object]) -> DungeonWave:
    enemies: list[tuple[str, int]] = []
    for item in raw.get("enemies", []):  # type: ignore[union-attr]
        if not isinstance(item, Mapping):
            continue
        enemy = str(item.get("enemy", "")).strip()
        if not enemy:
            continue
        enemies.append((enemy, int(item.get("weight", 1))))
    return DungeonWave(count=int(raw.get("count", 1)), enemies=tuple(enemies))


def _dungeon(raw: Mapping[str, object]) -> Dungeon:
    return Dungeon(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        category=str(raw.get("category", "")),
        difficulty=str(raw.get("difficulty", "")),
        darkness=int(raw.get("darkness", 0)),
        waves=tuple(_wave(wave) for wave in raw.get("waves", [])),  # type: ignore[union-attr]
        rewards=dict(raw.get("rewards", {})),  # type: ignore[arg-type]
    )


@lru_cache(maxsize=4)
def _load(path: str) -> DungeonDatabase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return DungeonDatabase(
        game=str(raw.get("game", "")),
        build=str(raw.get("build", "")),
        source=str(raw.get("source", "")),
        generated=str(raw.get("generated", "")),
        dungeons=tuple(
            _dungeon(item) for item in raw.get("dungeons", [])
        ),
    )


def load_dungeons(path: str | Path | None = None) -> DungeonDatabase:
    """Load the dungeon database (cached per path)."""
    return _load(str(path or DEFAULT_DUNGEON_DB_PATH))
