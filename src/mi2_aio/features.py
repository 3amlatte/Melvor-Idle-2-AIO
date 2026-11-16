"""Feature registry: what the bot can do, grouped for the settings UI.

The future UI will show categories (Combat, Farming, Global) and the features
inside them. Keeping this list in one place means the UI can be built from the
registry instead of hardcoding each feature.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Feature:
    key: str
    category: str
    name: str
    description: str
    config_section: str
    task: str | None = None


CATEGORIES: dict[str, str] = {
    "combat": "Combat",
    "farming": "Farming",
    "fishing": "Fishing",
    "cooking": "Cooking",
    "global": "Global",
}


FEATURES: tuple[Feature, ...] = (
    Feature(
        key="slayer",
        category="combat",
        name="Slayer",
        description=(
            "Jump to the task enemy, counter its combat style with a bank "
            "weapon, and stop when food runs out."
        ),
        config_section="[combat.slayer]",
        task="slayer",
    ),
    Feature(
        key="prayer",
        category="combat",
        name="Prayer",
        description=(
            "Bury banked bones in batches to restore Prayer points without "
            "opening the bank after every kill."
        ),
        config_section="[combat.prayer]",
    ),
    Feature(
        key="dungeons",
        category="combat",
        name="Dungeons",
        description=(
            "Enter a standard dungeon, keep fighting through its waves and "
            "collect the completion loot."
        ),
        config_section="[combat.dungeons]",
        task="dungeons",
    ),
    Feature(
        key="bone_farming",
        category="combat",
        name="Farm Prayer Points",
        description=(
            "Switch to Corrupted Farmlands and farm Giant Chicken (50 HP, "
            "guaranteed Big Bone for 6 Prayer points) with the current combat "
            "setup. Prayer maintenance buries the bones for Prayer points."
        ),
        config_section="[combat.prayer]",
        task="farm_bones",
    ),
    Feature(
        key="farming",
        category="farming",
        name="Farming",
        description=(
            "Harvest and replant plots, compost bins and the Mill Farm, and "
            "keep The Mill fed and running."
        ),
        config_section="[farming]",
    ),
    Feature(
        key="fishing",
        category="fishing",
        name="Fishing",
        description=(
            "Open the Fishing page, choose a location and spot, and start "
            "fishing the fish available at that spot."
        ),
        config_section="[fishing]",
        task="fishing",
    ),
    Feature(
        key="cooking",
        category="cooking",
        name="Cooking",
        description=(
            "Cook a Basic Food recipe and optionally stop after a set number "
            "of products using the in-game Products Gained stop condition."
        ),
        config_section="[cooking]",
        task="cooking",
    ),
    Feature(
        key="failsafe",
        category="global",
        name="Idle failsafe",
        description="Start a fallback action whenever the character is idle.",
        config_section="[failsafe]",
    ),
    Feature(
        key="restore",
        category="global",
        name="Restore previous action",
        description=(
            "When a run ends, resume the action the game was doing before it "
            "started (for example Woodcutting)."
        ),
        config_section="[restore]",
    ),
)


def by_category() -> dict[str, list[Feature]]:
    grouped: dict[str, list[Feature]] = {key: [] for key in CATEGORIES}
    for feature in FEATURES:
        grouped.setdefault(feature.category, []).append(feature)
    return grouped


def get_feature(key: str) -> Feature:
    for feature in FEATURES:
        if feature.key == key:
            return feature
    raise KeyError(key)
