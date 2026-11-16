"""Read-only database of melee weapons and off-hand defenders.

The data lives in ``data/scimitars_defenders.json`` and is loaded once. It
covers demo scimitars (slash), swords (slash/block; 2H adds crush), mallets
(crush) and defenders. Each item carries its equip requirement, combat stats,
Smithing recipe (if any) and drop sources, so the future auto-upgrade feature
can answer:

* what is the best weapon for a style at my Attack level?
* what is the best defender I can equip at my Defence level?
* what is the best one I can make at my Smithing level?
* what materials and levels does the next upgrade need?

The database is reference data only; it does not equip or smith anything.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "scimitars_defenders.json"


def _normalize_game_id(value: str) -> str:
    """Match a human id/name against the save's compact item id."""
    return "".join(character for character in value.lower() if character.isalnum())


@dataclass(frozen=True)
class Requirement:
    skill: str
    level: int


@dataclass(frozen=True)
class SmithingRecipe:
    level: int
    # (item name, quantity) pairs.
    ingredients: tuple[tuple[str, int], ...]
    base_xp: float | None
    steps: int | None
    step_interval_s: float | None
    category: str
    subcategory: str


@dataclass(frozen=True)
class EquipmentItem:
    id: str
    name: str
    slot: str
    type: str
    tier: str
    tier_rank: int | None
    special: bool
    requirement: Requirement | None
    stats: Mapping[str, float]
    smithing: SmithingRecipe | None
    drops: tuple[str, ...]
    special_text: str | None
    sells_for: int | None
    available_in_demo: bool
    wiki_url: str
    requirements: tuple[Requirement, ...] = ()
    game_id: str = ""
    weapon_type: str = ""
    two_handed: bool = False
    occupied_slots: tuple[str, ...] = ()
    obtained_from: str | None = None
    objective: str | None = None
    drop_chance: float | None = None
    drop_area: str | None = None
    icon: str | None = None
    evidence: tuple[str, ...] = ()
    note: str | None = None

    @property
    def required_level(self) -> int:
        return self.requirement.level if self.requirement else 0

    @property
    def required_skill(self) -> str:
        return self.requirement.skill if self.requirement else ""

    @property
    def slash_attack(self) -> float:
        return float(self.stats.get("slash_attack", 0))

    @property
    def melee_strength(self) -> float:
        return float(self.stats.get("melee_strength", 0))

    @property
    def slash_defence(self) -> float:
        return float(self.stats.get("slash_defence", 0))

    @property
    def protection(self) -> float:
        return float(self.stats.get("protection_normal", 0))

    @property
    def total_defence(self) -> float:
        return sum(
            value
            for key, value in self.stats.items()
            if key.endswith("_defence")
        )

    @property
    def armour_score(self) -> tuple[float, float, float, int]:
        """Ranking for an armour slot: protection, total defence, strength."""
        return (
            self.protection,
            self.total_defence,
            self.melee_strength,
            self.required_level,
        )

    @property
    def is_defender(self) -> bool:
        return self.slot == "offhand" and self.type == "defender"

    @property
    def styles(self) -> tuple[str, ...]:
        """Styles this item has an attack bonus for (slash/block/crush/stab)."""
        return tuple(
            style
            for style in ("slash", "block", "crush", "stab")
            if self.style_bonus(style) > 0
        )

    def style_bonus(self, style: str) -> float:
        return float(self.stats.get(f"{style}_attack", 0))

    def stance_index(self, style: str) -> int | None:
        """Zero-based stance button index for this weapon type, if present."""
        from .weapon_type_db import load_weapon_types

        return load_weapon_types().stance_index(self.weapon_type, style)

    @property
    def turn_interval_s(self) -> float:
        return float(self.stats.get("turn_interval_s", 0))

    @property
    def power_rating(self) -> float:
        return float(self.stats.get("power_rating", 0))

    def can_equip(self, skill_level: int) -> bool:
        return self.requirement is not None and skill_level >= self.requirement.level

    def can_equip_all(self, levels: Mapping[str, int]) -> bool:
        """Check every level requirement (armour can need two skills)."""
        requirements = self.requirements or (
            (self.requirement,) if self.requirement is not None else ()
        )
        return all(
            levels.get(requirement.skill, 0) >= requirement.level
            for requirement in requirements
        )

    def can_smith(self, smithing_level: int) -> bool:
        return self.smithing is not None and smithing_level >= self.smithing.level


@dataclass(frozen=True)
class Loadout:
    """A one-handed scimitar + defender pair."""

    weapon: EquipmentItem
    defender: EquipmentItem

    @property
    def name(self) -> str:
        return f"{self.weapon.name} + {self.defender.name}"

    @property
    def slash_attack(self) -> float:
        return self.weapon.slash_attack + self.defender.slash_attack

    @property
    def melee_strength(self) -> float:
        return self.weapon.melee_strength + self.defender.melee_strength

    @property
    def slash_defence(self) -> float:
        return self.defender.slash_defence

    @property
    def turn_interval_s(self) -> float:
        return self.weapon.turn_interval_s

    @property
    def power_rating(self) -> float:
        # Defenders do not carry a power rating; the weapon's rating is the
        # comparable single-item score.
        return self.weapon.power_rating

    def summary(self) -> dict[str, float]:
        interval = self.turn_interval_s
        return {
            "slash_attack": self.slash_attack,
            "melee_strength": self.melee_strength,
            "slash_defence": self.slash_defence,
            "turn_interval_s": interval,
            "power_rating": self.power_rating,
            "slash_attack_per_s": self.slash_attack / interval if interval else 0.0,
            "melee_strength_per_s": (
                self.melee_strength / interval if interval else 0.0
            ),
        }


@dataclass(frozen=True)
class EquipmentDatabase:
    game: str
    build: str
    data_version: str
    source: str
    generated: str
    scimitars: tuple[EquipmentItem, ...]
    swords: tuple[EquipmentItem, ...]
    mallets: tuple[EquipmentItem, ...]
    future_tiers: Mapping[str, tuple[str, ...]]
    armour: tuple[EquipmentItem, ...] = ()
    other_weapons: tuple[EquipmentItem, ...] = ()

    @property
    def items(self) -> tuple[EquipmentItem, ...]:
        return (
            self.scimitars
            + self.swords
            + self.mallets
            + self.other_weapons
            + self.armour
        )

    @property
    def defenders(self) -> tuple[EquipmentItem, ...]:
        """Offhand defenders (kept as a view for existing callers)."""
        return tuple(item for item in self.armour if item.is_defender)

    def find_by_game_id(self, game_id: str) -> EquipmentItem | None:
        """Find an item by the save's id (for example ``MithrilMallet``)."""
        wanted = _normalize_game_id(game_id)
        if not wanted:
            return None
        for item in self.items:
            if item.game_id and _normalize_game_id(item.game_id) == wanted:
                return item
            if _normalize_game_id(item.id) == wanted:
                return item
            if item.name and _normalize_game_id(item.name) == wanted:
                return item
        return None

    @property
    def weapons(self) -> tuple[EquipmentItem, ...]:
        return self.scimitars + self.swords + self.mallets + self.other_weapons

    def armour_for_slot(
        self, slot: str, *, subtype: str | None = None
    ) -> tuple[EquipmentItem, ...]:
        wanted = slot.strip().lower()
        return tuple(
            item
            for item in self.armour
            if item.slot == wanted
            and (subtype is None or item.type == subtype.lower())
        )

    def best_armour(
        self,
        slot: str,
        levels: Mapping[str, int],
        *,
        owned: set[str] | frozenset[str] | None = None,
        subtype: str | None = None,
    ) -> EquipmentItem | None:
        """Best equippable armour for ``slot`` at the character's levels.

        ``owned`` limits the result to items in the save's bank/equipment set.
        """
        candidates = [
            item
            for item in self.armour_for_slot(slot, subtype=subtype)
            if item.can_equip_all(levels)
            and (owned is None or item.id in owned)
            and not any(
                requirement.skill.lower() in ("magic", "ranged")
                for requirement in item.requirements
            )
            and (
                item.protection > 0
                or item.total_defence > 0
                or item.melee_strength > 0
            )
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.armour_score)

    def owned_items(self, header) -> frozenset[str]:
        """Item ids the character owns (equipped + bank), from a save header."""
        raw_ids = set(header.equipment.values()) | set(header.bank_items)
        wanted = {_normalize_game_id(value) for value in raw_ids if value}
        return frozenset(
            item.id
            for item in self.items
            if _normalize_game_id(item.game_id or item.id) in wanted
            or _normalize_game_id(item.name) in wanted
        )

    def bank_search(self, item: EquipmentItem) -> tuple[str, object]:
        """Search term and filter for locating ``item`` in the bank grid.

        The bank search understands equipment slot words ("Helmet", "Torso",
        "Legs", ...) and returns all items of that slot in bank order. That is
        exactly what the grid index calculation needs.
        """
        slot = item.slot
        if slot in ("helmet", "torso", "legs", "boots", "gloves", "ring"):
            term = slot.title()
            return term, lambda candidate, slot=slot: candidate.slot == slot
        if slot == "amulet":
            if "necklace" in item.name.lower():
                return (
                    "Necklace",
                    lambda candidate: candidate.slot == "amulet"
                    and "necklace" in candidate.name.lower(),
                )
            return "Amulet", lambda candidate: candidate.slot == "amulet"
        if slot == "cape":
            if "cloak" in item.name.lower():
                return (
                    "Cloak",
                    lambda candidate: candidate.slot == "cape"
                    and "cloak" in candidate.name.lower(),
                )
            return "Cape", lambda candidate: candidate.slot == "cape"
        if slot == "offhand":
            if item.is_defender:
                return "Defender", lambda candidate: candidate.is_defender
            if item.type == "shield":
                return "Shield", lambda candidate: candidate.type == "shield"
            if item.type == "lantern":
                return "Lantern", lambda candidate: candidate.type == "lantern"
            if item.type == "grimoire":
                return "Grimoire", lambda candidate: candidate.type == "grimoire"
            return "Offhand", lambda candidate: candidate.slot == "offhand"
        # Weapons: the last word is the distinguishing type ("Sword",
        # "Scimitar", "Mallet", "Scythe", "Greatsword", ...).
        word = item.name.split()[-1]
        wanted = word.lower()
        return word, lambda candidate: wanted in candidate.name.lower()

    def bank_target(
        self, header, item: EquipmentItem
    ) -> tuple[str, int] | None:
        """Return ``(search_term, zero-based grid index)`` for ``item``.

        The index is computed from the save's bank order filtered by the same
        set the bank search displays, so it selects the exact item rather than
        the first search result (which can be a material such as "Leather").
        """
        search, predicate = self.bank_search(item)
        ordered: list[EquipmentItem] = []
        seen: set[str] = set()
        for game_id in header.bank_order:
            candidate = self.find_by_game_id(game_id)
            if candidate is None or candidate.id in seen:
                continue
            if predicate(candidate):  # type: ignore[operator]
                ordered.append(candidate)
                seen.add(candidate.id)
        for index, candidate in enumerate(ordered):
            if candidate.id == item.id:
                return search, index
        return None

    def scimitars_for(self, attack_level: int) -> tuple[EquipmentItem, ...]:
        return tuple(
            item
            for item in self.scimitars
            if item.can_equip(attack_level)
        )

    def defenders_for(self, defence_level: int) -> tuple[EquipmentItem, ...]:
        return tuple(
            item
            for item in self.defenders
            if item.can_equip(defence_level)
        )

    def best_scimitar(
        self,
        attack_level: int,
        *,
        craftable_only: bool = False,
        smithing_level: int = 0,
        include_special: bool = True,
    ) -> EquipmentItem | None:
        """Best equippable scimitar, ranked by slash attack then strength.

        ``craftable_only`` additionally requires a Smithing recipe whose level
        the player meets (special drop-only items are then excluded).
        """
        candidates = [
            item
            for item in self.scimitars_for(attack_level)
            if include_special or not item.special
        ]
        if craftable_only:
            candidates = [
                item for item in candidates if item.can_smith(smithing_level)
            ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item.slash_attack,
                item.melee_strength,
                item.required_level,
            ),
        )

    def best_defender(
        self,
        defence_level: int,
        *,
        craftable_only: bool = False,
        smithing_level: int = 0,
        include_special: bool = True,
    ) -> EquipmentItem | None:
        """Best equippable defender, ranked by slash defence then attack."""
        candidates = [
            item
            for item in self.defenders_for(defence_level)
            if include_special or not item.special
        ]
        if craftable_only:
            candidates = [
                item for item in candidates if item.can_smith(smithing_level)
            ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item.slash_defence,
                item.slash_attack,
                item.melee_strength,
                item.required_level,
            ),
        )

    def weapons_for_style(
        self,
        style: str,
        attack_level: int,
        *,
        craftable_only: bool = False,
        smithing_level: int = 0,
        include_special: bool = True,
    ) -> tuple[EquipmentItem, ...]:
        """Weapons with an attack bonus for ``style``, best first."""
        candidates = [
            item
            for item in self.weapons
            if item.style_bonus(style) > 0
            and item.can_equip(attack_level)
            and (include_special or not item.special)
        ]
        if craftable_only:
            candidates = [
                item for item in candidates if item.can_smith(smithing_level)
            ]
        return tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.style_bonus(style),
                    item.melee_strength,
                    -item.turn_interval_s,
                    item.power_rating,
                    item.required_level,
                ),
                reverse=True,
            )
        )

    def best_weapon_for_style(
        self,
        style: str,
        attack_level: int,
        *,
        craftable_only: bool = False,
        smithing_level: int = 0,
        include_special: bool = True,
    ) -> EquipmentItem | None:
        candidates = self.weapons_for_style(
            style,
            attack_level,
            craftable_only=craftable_only,
            smithing_level=smithing_level,
            include_special=include_special,
        )
        return candidates[0] if candidates else None

    def best_loadout(
        self,
        attack_level: int,
        defence_level: int,
        *,
        craftable_only: bool = False,
        smithing_level: int = 0,
        include_special: bool = True,
    ) -> Loadout | None:
        """Best equippable scimitar + defender pair for the given levels."""
        weapon = self.best_scimitar(
            attack_level,
            craftable_only=craftable_only,
            smithing_level=smithing_level,
            include_special=include_special,
        )
        defender = self.best_defender(
            defence_level,
            craftable_only=craftable_only,
            smithing_level=smithing_level,
            include_special=include_special,
        )
        if weapon is None or defender is None:
            return None
        return Loadout(weapon=weapon, defender=defender)

    def weapon_by_name(self, name: str) -> EquipmentItem | None:
        wanted = name.strip().lower()
        for item in self.other_weapons + self.scimitars + self.defenders:
            if item.name.lower() == wanted or item.id == wanted:
                return item
        return None

    @staticmethod
    def compare_to_two_handed(
        baseline: EquipmentItem, loadout: Loadout
    ) -> dict[str, object]:
        """Raw and per-second comparison of a 2H weapon vs a 1H pair.

        The game's Normal Damage Power rating is a useful single-item score;
        the pair's rating uses the weapon's rating (defenders do not have one).
        Per-second values are only a sanity check, not the game's damage
        formula.
        """
        interval = baseline.turn_interval_s
        return {
            "baseline": baseline.name,
            "loadout": loadout.name,
            "baseline_power_rating": baseline.power_rating,
            "loadout_power_rating": loadout.power_rating,
            "power_rating_delta": loadout.power_rating - baseline.power_rating,
            "baseline_slash_attack": baseline.slash_attack,
            "loadout_slash_attack": loadout.slash_attack,
            "slash_attack_delta": loadout.slash_attack - baseline.slash_attack,
            "baseline_melee_strength": baseline.melee_strength,
            "loadout_melee_strength": loadout.melee_strength,
            "melee_strength_delta": loadout.melee_strength - baseline.melee_strength,
            "baseline_interval_s": interval,
            "loadout_interval_s": loadout.turn_interval_s,
            "interval_delta_s": interval - loadout.turn_interval_s,
            "baseline_slash_per_s": (
                baseline.slash_attack / interval if interval else 0.0
            ),
            "loadout_slash_per_s": (
                loadout.slash_attack / loadout.turn_interval_s
                if loadout.turn_interval_s
                else 0.0
            ),
            "baseline_strength_per_s": (
                baseline.melee_strength / interval if interval else 0.0
            ),
            "loadout_strength_per_s": (
                loadout.melee_strength / loadout.turn_interval_s
                if loadout.turn_interval_s
                else 0.0
            ),
            "loadout_slash_defence": loadout.slash_defence,
            "baseline_slots": list(baseline.occupied_slots),
            "loadout_slots": ["weapon", "offhand"],
        }


def _requirement(raw: Mapping[str, object] | None) -> Requirement | None:
    if not isinstance(raw, Mapping):
        return None
    skill = str(raw.get("skill", "")).strip()
    level = int(raw.get("level", 0))
    if not skill or level <= 0:
        return None
    return Requirement(skill=skill, level=level)


def _smithing(raw: Mapping[str, object] | None) -> SmithingRecipe | None:
    if not isinstance(raw, Mapping):
        return None
    ingredients = tuple(
        (
            str(entry.get("item", "")).strip(),
            int(entry.get("quantity", 0)),
        )
        if isinstance(entry, Mapping)
        else (str(entry[0]).strip(), int(entry[1]))
        for entry in raw.get("ingredients", [])
        if isinstance(entry, Mapping)
        or (isinstance(entry, (list, tuple)) and len(entry) == 2)
    )
    return SmithingRecipe(
        level=int(raw.get("level", 0)),
        ingredients=ingredients,
        base_xp=(
            float(raw["base_xp"])
            if raw.get("base_xp") is not None
            else None
        ),
        steps=(
            int(raw["steps"]) if raw.get("steps") is not None else None
        ),
        step_interval_s=(
            float(raw["step_interval_s"])
            if raw.get("step_interval_s") is not None
            else None
        ),
        category=str(raw.get("category", "")),
        subcategory=str(raw.get("subcategory", "")),
    )


def _item(raw: Mapping[str, object]) -> EquipmentItem:
    stats = {
        str(key): float(value)
        for key, value in dict(raw.get("stats", {})).items()
        if isinstance(value, (int, float))
    }
    requirement = _requirement(raw.get("requirement"))
    requirements = tuple(
        parsed
        for parsed in (
            _requirement(value) for value in raw.get("requirements", [])
        )
        if parsed is not None
    )
    if not requirements and requirement is not None:
        requirements = (requirement,)
    return EquipmentItem(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        slot=str(raw.get("slot", "")),
        type=str(raw.get("type", "")),
        tier=str(raw.get("tier", "")),
        tier_rank=(
            int(raw["tier_rank"]) if raw.get("tier_rank") is not None else None
        ),
        special=bool(raw.get("special", False)),
        requirement=requirement,
        requirements=requirements,
        game_id=str(raw.get("game_id", "")),
        stats=stats,
        smithing=_smithing(raw.get("smithing")),
        drops=tuple(str(name) for name in raw.get("drops", [])),
        special_text=(
            str(raw["special_text"])
            if raw.get("special_text") is not None
            else None
        ),
        sells_for=(
            int(raw["sells_for"]) if raw.get("sells_for") is not None else None
        ),
        available_in_demo=bool(raw.get("available_in_demo", True)),
        wiki_url=str(raw.get("wiki_url", "")),
        weapon_type=str(
            raw.get("weapon_type")
            or (
                "Scimitar"
                if str(raw.get("type", "")) == "scimitar"
                else "Defender"
                if str(raw.get("type", "")) == "defender"
                else ""
            )
        ),
        two_handed=bool(raw.get("two_handed", False)),
        occupied_slots=tuple(
            str(value)
            for value in raw.get(
                "occupied_slots",
                ["weapon"]
                if str(raw.get("slot", "")) == "weapon"
                else ["offhand"]
                if str(raw.get("slot", "")) == "offhand"
                else [],
            )
        ),
        obtained_from=(
            str(raw["obtained_from"])
            if raw.get("obtained_from") is not None
            else None
        ),
        objective=(
            str(raw["objective"]) if raw.get("objective") is not None else None
        ),
        drop_chance=(
            float(raw["drop_chance"])
            if raw.get("drop_chance") is not None
            else None
        ),
        drop_area=(
            str(raw["drop_area"]) if raw.get("drop_area") is not None else None
        ),
        icon=str(raw["icon"]) if raw.get("icon") is not None else None,
        evidence=tuple(str(value) for value in raw.get("evidence", [])),
        note=str(raw["note"]) if raw.get("note") is not None else None,
    )


@lru_cache(maxsize=4)
def _load(path: str) -> EquipmentDatabase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return EquipmentDatabase(
        game=str(raw.get("game", "")),
        build=str(raw.get("build", "")),
        data_version=str(raw.get("data_version", "")),
        source=str(raw.get("source", "")),
        generated=str(raw.get("generated", "")),
        scimitars=tuple(_item(item) for item in raw.get("scimitars", [])),
        swords=tuple(_item(item) for item in raw.get("swords", [])),
        mallets=tuple(_item(item) for item in raw.get("mallets", [])),
        armour=tuple(_item(item) for item in raw.get("armour", [])),
        other_weapons=tuple(
            _item(item) for item in raw.get("other_weapons", [])
        ),
        future_tiers={
            str(key): tuple(str(name) for name in names)
            for key, names in dict(raw.get("future_tiers", {})).items()
        },
    )


def load_database(path: str | Path | None = None) -> EquipmentDatabase:
    """Load the scimitar/defender database (cached per path)."""
    return _load(str(path or DEFAULT_DB_PATH))
