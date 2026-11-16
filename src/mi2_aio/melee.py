"""Choose the best melee style (slash, block or crush) for an enemy.

The game computes melee accuracy from the player's Attack level and the
stance's attack bonus, and enemy evasion from the enemy's Defence level and the
matching defence bonus. The hit chance is exactly the formula in
``TargetCharacterStats.ComputeHitChance``:

    accuracy = floor((attack_level + 9) * (attack_bonus + 64))
    evasion  = floor((enemy_defence_level + 9) * (enemy_defence_bonus + 64))
    hit      = 1 - evasion / (2 * accuracy)      if accuracy >= evasion
             = accuracy / (2 * evasion)           otherwise

This module ranks the best weapon for each style (using a defender for
one-handed weapons), then the best of the three styles for the selected enemy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .enemy_db import Enemy
from .equipment_db import EquipmentDatabase, EquipmentItem

STYLES: tuple[str, ...] = ("slash", "block", "crush")
STYLE_LABELS = {"slash": "Slash", "block": "Block", "crush": "Crush"}

# If a style's hit chance is within this margin of the best, prefer the style
# with the lower enemy evasion. This avoids switching to the enemy's more
# resistant style for a negligible accuracy gain (for example Mangrove Mantis:
# Block 37.3% at +188 evasion vs Slash 36.0% at +178).
EVASION_PREFERENCE_MARGIN = 0.02


def hit_chance(
    attack_bonus: float,
    attack_level: int,
    enemy_defence_bonus: float,
    enemy_defence_level: int,
) -> float:
    """Exact Melvor 2 melee hit chance for one style (0.0 - 1.0)."""
    accuracy = math.floor((attack_level + 9) * (attack_bonus + 64.0))
    evasion = math.floor((enemy_defence_level + 9) * (enemy_defence_bonus + 64.0))
    if accuracy <= 0 or evasion <= 0:
        return 0.0
    if accuracy >= evasion:
        value = 1.0 - evasion / (2.0 * accuracy)
    else:
        value = accuracy / (2.0 * evasion)
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class StyleChoice:
    style: str
    weapon: EquipmentItem
    defender: EquipmentItem | None
    attack_bonus: float
    melee_strength: float
    hit_chance: float
    enemy_evasion: float
    interval_s: float
    slash_defence: float

    @property
    def label(self) -> str:
        if self.defender is not None:
            return f"{self.weapon.name} + {self.defender.name}"
        return self.weapon.name

    @property
    def two_handed(self) -> bool:
        return self.weapon.two_handed

    @property
    def style_label(self) -> str:
        return STYLE_LABELS.get(self.style, self.style.title())

    @property
    def key(self) -> tuple[str, str | None]:
        """Stable key for cooldowns/blocklists."""
        return (self.weapon.id, self.defender.id if self.defender else None)

    def to_dict(self) -> dict[str, object]:
        return {
            "style": self.style,
            "weapon": self.weapon.name,
            "weapon_id": self.weapon.id,
            "defender": self.defender.name if self.defender else None,
            "defender_id": self.defender.id if self.defender else None,
            "two_handed": self.two_handed,
            "attack_bonus": self.attack_bonus,
            "melee_strength": self.melee_strength,
            "hit_chance": self.hit_chance,
            "enemy_evasion": self.enemy_evasion,
            "interval_s": self.interval_s,
            "slash_defence": self.slash_defence,
        }


@dataclass(frozen=True)
class MeleeDecision:
    enemy: Enemy
    attack_level: int
    defence_level: int
    smithing_level: int
    choices: tuple[StyleChoice, ...]
    best: StyleChoice | None
    # Every weapon/style candidate, best hit chance first. The live style
    # switcher walks this list so an item the character does not own is simply
    # skipped in favour of the next best owned setup.
    candidates: tuple[StyleChoice, ...] = ()

    @property
    def best_style(self) -> str | None:
        return self.best.style if self.best else None

    def to_dict(self) -> dict[str, object]:
        return {
            "enemy": {
                "id": self.enemy.id,
                "name": self.enemy.name,
                "defence_level": self.enemy.defence_level,
                "evasions": {
                    style: self.enemy.defence_bonus(style) for style in STYLES
                },
            },
            "attack_level": self.attack_level,
            "defence_level": self.defence_level,
            "smithing_level": self.smithing_level,
            "best_style": self.best_style,
            "best": self.best.to_dict() if self.best else None,
            "styles": [choice.to_dict() for choice in self.choices],
            "candidates": [choice.to_dict() for choice in self.candidates],
        }


def _best_defender(
    db: EquipmentDatabase,
    style: str,
    defence_level: int,
    *,
    craftable_only: bool,
    smithing_level: int,
    include_special: bool,
    owned: set[str] | frozenset[str] | None = None,
) -> EquipmentItem | None:
    candidates = [
        defender
        for defender in db.defenders_for(defence_level)
        if (include_special or not defender.special)
        and (not craftable_only or defender.can_smith(smithing_level))
        and (owned is None or defender.id in owned)
    ]
    if not candidates:
        return None
    if style in ("slash", "block"):
        return max(
            candidates,
            key=lambda item: (
                item.style_bonus(style),
                item.slash_defence,
                item.melee_strength,
                item.required_level,
            ),
        )
    # Defenders have no crush attack bonus; use the most defensive one.
    return max(
        candidates,
        key=lambda item: (
            item.slash_defence,
            item.style_bonus(style),
            item.melee_strength,
            item.required_level,
        ),
    )


def choose_melee_style(
    db: EquipmentDatabase,
    enemy: Enemy,
    *,
    attack_level: int,
    defence_level: int,
    smithing_level: int,
    craftable_only: bool = False,
    include_special: bool = True,
    owned: set[str] | frozenset[str] | None = None,
) -> MeleeDecision:
    """Select the best slash/block/crush setup for ``enemy``.

    Each style is evaluated with the best weapon that has that style bonus and
    the best defender for that style (one-handed weapons only). The style with
    the highest hit chance wins; ties use melee strength, attack speed and
    defender defence. If another style has lower enemy evasion and its hit
    chance is within ``EVASION_PREFERENCE_MARGIN``, that lower-evasion style
    wins instead.
    """
    choices: list[StyleChoice] = []
    all_candidates: list[StyleChoice] = []
    for style in STYLES:
        defender = _best_defender(
            db,
            style,
            defence_level,
            craftable_only=craftable_only,
            smithing_level=smithing_level,
            include_special=include_special,
            owned=owned,
        )
        style_candidates: list[StyleChoice] = []
        for weapon in db.weapons_for_style(
            style,
            attack_level,
            craftable_only=craftable_only,
            smithing_level=smithing_level,
            include_special=include_special,
        ):
            pair_defender = None if weapon.two_handed else defender
            bonus = weapon.style_bonus(style)
            strength = weapon.melee_strength
            slash_defence = 0.0
            if pair_defender is not None:
                bonus += pair_defender.style_bonus(style)
                strength += pair_defender.melee_strength
                slash_defence = pair_defender.slash_defence
            chance = hit_chance(
                bonus,
                attack_level,
                enemy.defence_bonus(style),
                enemy.defence_level,
            )
            style_candidates.append(
                StyleChoice(
                    style=style,
                    weapon=weapon,
                    defender=pair_defender,
                    attack_bonus=bonus,
                    melee_strength=strength,
                    hit_chance=chance,
                    enemy_evasion=enemy.defence_bonus(style),
                    interval_s=weapon.turn_interval_s,
                    slash_defence=slash_defence,
                )
            )
        all_candidates.extend(style_candidates)
        if style_candidates:
            # Best weapon for this style: hit chance, then damage/defence.
            choices.append(
                max(
                    style_candidates,
                    key=lambda choice: (
                        choice.hit_chance,
                        choice.melee_strength,
                        -choice.interval_s,
                        choice.slash_defence,
                        choice.weapon.power_rating,
                    ),
                )
            )

    best = (
        max(
            choices,
            key=lambda choice: (
                choice.hit_chance,
                choice.melee_strength,
                -choice.interval_s,
            ),
        )
        if choices
        else None
    )
    if best is not None:
        lower_evasion = [
            choice
            for choice in choices
            if choice.enemy_evasion < best.enemy_evasion
            and choice.hit_chance
            >= best.hit_chance - EVASION_PREFERENCE_MARGIN
        ]
        if lower_evasion:
            best = max(
                lower_evasion,
                key=lambda choice: (
                    -choice.enemy_evasion,
                    choice.hit_chance,
                    choice.melee_strength,
                    -choice.interval_s,
                ),
            )
    ranked = sorted(
        all_candidates,
        key=lambda choice: (
            -choice.hit_chance,
            -choice.melee_strength,
            choice.interval_s,
            -choice.slash_defence,
        ),
    )
    return MeleeDecision(
        enemy=enemy,
        attack_level=attack_level,
        defence_level=defence_level,
        smithing_level=smithing_level,
        choices=tuple(choices),
        best=best,
        candidates=tuple(ranked),
    )


def format_decision(decision: MeleeDecision) -> str:
    enemy = decision.enemy
    lines = [
        f"Enemy: {enemy.name} (Defence level {enemy.defence_level})",
        "Evasions: "
        + ", ".join(
            f"{STYLE_LABELS[style]} {enemy.defence_bonus(style):+.0f}"
            for style in STYLES
        ),
        f"Player: Attack {decision.attack_level}, "
        f"Defence {decision.defence_level}, Smithing {decision.smithing_level}",
        "",
        f"{'Style':<8} {'Weapon + defender':<46} {'Atk':>5} {'Hit':>7}",
    ]
    for choice in sorted(decision.choices, key=lambda item: -item.hit_chance):
        marker = "  <-- best" if choice is decision.best else ""
        lines.append(
            f"{choice.style_label:<8} {choice.label:<46} "
            f"{choice.attack_bonus:>5.0f} {choice.hit_chance * 100:>6.1f}%{marker}"
        )
    if decision.best is not None and decision.choices:
        highest = max(
            decision.choices,
            key=lambda choice: (
                choice.hit_chance,
                choice.melee_strength,
                -choice.interval_s,
            ),
        )
        if decision.best.key != highest.key:
            lines.append("")
            lines.append(
                "Preference: lower enemy evasion within "
                f"{EVASION_PREFERENCE_MARGIN * 100:.0f}% hit chance."
            )
    if decision.best is None:
        lines.append("No equippable melee weapon for these levels.")
    return "\n".join(lines)
