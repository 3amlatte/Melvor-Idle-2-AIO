"""Read-only enemy database extracted from the Melvor 2 client.

Each enemy carries its combat levels and Slash/Block/Crush defence bonuses.
Those are the values the game uses for evasion, so the melee style scorer can
choose the best style for any enemy without reading the enemy panel on screen.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

DEFAULT_ENEMY_DB_PATH = DATA_DIR / "enemies.json"


@dataclass(frozen=True)
class Enemy:
    id: str
    name: str
    levels: Mapping[str, int]
    stances: tuple[str, ...]
    attack_bonuses: Mapping[str, float]
    defence_bonuses: Mapping[str, float]
    misc_stats: Mapping[str, float]
    power_ratings: Mapping[str, float]
    protection_ratings: Mapping[str, float]

    @property
    def defence_level(self) -> int:
        return int(self.levels.get("Defence", 1))

    def defence_bonus(self, style: str) -> float:
        """Enemy defence/evasion bonus for slash, block or crush."""
        return float(self.defence_bonuses.get(style, 0))

    def attack_bonus(self, style: str) -> float:
        return float(self.attack_bonuses.get(style, 0))

    @property
    def normal_power(self) -> float:
        return float(self.power_ratings.get("normal", 0))

    @property
    def normal_protection(self) -> float:
        return float(self.protection_ratings.get("normal", 0))


@dataclass(frozen=True)
class EnemyDatabase:
    game: str
    build: str
    source: str
    generated: str
    enemies: tuple[Enemy, ...]

    def find(self, query: str) -> Enemy | None:
        wanted = query.strip().lower()
        for enemy in self.enemies:
            if enemy.id.lower() == wanted or enemy.name.lower() == wanted:
                return enemy
        return None

    def find_by_id(self, enemy_id: str) -> Enemy | None:
        wanted = enemy_id.strip().lower()
        for enemy in self.enemies:
            if enemy.id.lower() == wanted:
                return enemy
        return None

    def names(self) -> tuple[str, ...]:
        return tuple(enemy.name for enemy in self.enemies)


def _enemy(raw: Mapping[str, object]) -> Enemy:
    def numbers(value: object) -> dict[str, float]:
        return {
            str(key): float(item)
            for key, item in dict(value or {}).items()
            if isinstance(item, (int, float))
        }

    def integers(value: object) -> dict[str, int]:
        return {
            str(key): int(item)
            for key, item in dict(value or {}).items()
            if isinstance(item, (int, float))
        }

    return Enemy(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        levels=integers(raw.get("levels")),
        stances=tuple(str(item) for item in raw.get("stances", [])),
        attack_bonuses=numbers(raw.get("attack_bonuses")),
        defence_bonuses=numbers(raw.get("defence_bonuses")),
        misc_stats=numbers(raw.get("misc_stats")),
        power_ratings=numbers(raw.get("power_ratings")),
        protection_ratings=numbers(raw.get("protection_ratings")),
    )


@lru_cache(maxsize=4)
def _load(path: str) -> EnemyDatabase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return EnemyDatabase(
        game=str(raw.get("game", "")),
        build=str(raw.get("build", "")),
        source=str(raw.get("source", "")),
        generated=str(raw.get("generated", "")),
        enemies=tuple(_enemy(item) for item in raw.get("enemies", [])),
    )


def load_enemies(path: str | Path | None = None) -> EnemyDatabase:
    """Load the enemy database (cached per path)."""
    return _load(str(path or DEFAULT_ENEMY_DB_PATH))
