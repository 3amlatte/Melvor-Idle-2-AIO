"""Typed access to config/settings.toml."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .modes import GameModeProfile, build_profiles, default_profiles
from .paths import CONFIG_FILE


@dataclass(frozen=True)
class GameSettings:
    window_title: str = "Melvor2"


@dataclass(frozen=True)
class SaveSettings:
    root: str = ""
    poll_seconds: float = 5.0
    character: str = ""


@dataclass(frozen=True)
class AutomationSettings:
    max_runtime_minutes: float = 480.0
    emergency_stop_file: str = "STOP"
    humanize: bool = True
    click_jitter_px: int = 3
    action_delay_ms: tuple[int, int] = field(default=(120, 420))
    screenshot_on_error: bool = True
    # Post input messages directly to the game window instead of moving the
    # real cursor. Lets the bot act while another app is focused.
    background_input: bool = True


@dataclass(frozen=True)
class LoggingSettings:
    level: str = "INFO"


DEFAULT_SLAYER_WEAPONS: Mapping[str, str] = {
    "melee": "Bone Scythe",
    "ranged": "Normal Bow",
    "magic": "Water Staff",
}


@dataclass(frozen=True)
class SlayerSettings:    # Jump to the task enemy once when the task starts.
    jump_on_start: bool = True
    poll_seconds: float = 2.0
    # Stop the run when the Eat button shows no food left.
    stop_when_out_of_food: bool = True
    # Click Run from Combat before stopping when food is gone or HP is critical.
    flee_when_out_of_food: bool = True
    # Jump again when task progress has not moved for this long.
    stall_minutes: float = 12.0
    # Stop after this many consecutive stalls (each triggers one jump).
    max_stalls: int = 2
    jump_cooldown_seconds: float = 60.0
    # Wait this long between weapon switches.
    switch_cooldown_minutes: float = 3.0
    # Undo a switch if no task progress appears within this window.
    switch_grace_minutes: float = 4.0
    # Choose slash/block/crush from the active enemy's defence data.
    auto_style: bool = True
    # Minimum seconds between melee weapon bank switches. Stance-only changes
    # are immediate.
    style_switch_cooldown_seconds: float = 20.0
    # Equip better owned armour pieces (Defence requirements) between fights.
    auto_armour: bool = True
    armour_check_minutes: float = 10.0
    # Stop after this many completed tasks. 0 = run until the duration/stop file.
    max_tasks: int = 0
    # Bank item names per combat style. Empty string disables a style.
    weapons: Mapping[str, str] = field(
        default_factory=lambda: dict(DEFAULT_SLAYER_WEAPONS)
    )


DEFAULT_FARM_CATEGORIES: tuple[str, ...] = (
    "allotments",
    "herbs",
    "compost",
    "trees",
    "mill",
)


@dataclass(frozen=True)
class PrayerSettings:
    """Keep Prayer points topped up by burying bones from the bank.

    Bones are only buried in batches: either when enough have accumulated
    (``bone_threshold``) or when Prayer points are low and at least one bone is
    available. This avoids opening the bank after every single kill.
    """

    enabled: bool = False
    # Bury once this many bones have accumulated.
    bone_threshold: int = 50
    # Bury when Prayer points are below this value (if any bones are owned).
    low_prayer_threshold: int = 100
    # Minimum seconds between checks. Protects against bank spam when the
    # save has not refreshed yet or a bury action failed.
    check_seconds: float = 60.0
    # How long to wait for the save to confirm a bury before giving up.
    verify_seconds: float = 12.0


@dataclass(frozen=True)
class FarmingSettings:
    """Run farming maintenance between main-task steps."""

    enabled: bool = False
    # Run a needed farm pass before the main task step. When false, the task
    # gets its step first and farming is serviced afterwards.
    prioritise: bool = True
    # How often the cheap attention-badge check runs.
    badge_poll_seconds: float = 5.0
    # Optional safety full pass interval. 0 = only when the red badge appears.
    check_minutes: float = 0.0
    # Plot categories to service, in order.
    categories: tuple[str, ...] = DEFAULT_FARM_CATEGORIES
    harvest: bool = True
    compost: bool = True
    # Select the compost type in the plot header before applying it.
    select_compost: bool = True
    # 1-based picker slot: 1 = Fertiliser, 2 = Compost, 3 = third compost.
    compost_slot: int = 1
    plant: bool = True
    water: bool = True
    # Service The Mill building: deposit storage items and keep it running.
    mill: bool = True
    # Return to the main task's page (Task.page) after a pass.
    restore_page: bool = True


@dataclass(frozen=True)
class DungeonSettings:
    """Raid a standard dungeon (combat screen -> select area -> dungeons)."""

    # Display name of the dungeon (used in logs and to pick the row template).
    dungeon: str = "Harvest Farm"
    # Binarized name template in the Standard Dungeons list, relative to the
    # project root. Captured from the game at the reference client size.
    template: str = "assets/templates/dungeon_harvest_farm.png"
    poll_seconds: float = 2.0
    stop_when_out_of_food: bool = True
    flee_when_out_of_food: bool = True
    # Same combat-triangle weapon switching as slayer.
    switch_cooldown_minutes: float = 3.0
    # Choose slash/block/crush per dungeon wave from the save's active enemy.
    auto_style: bool = True
    style_switch_cooldown_seconds: float = 20.0
    # Equip better owned armour pieces (Defence requirements) between waves.
    auto_armour: bool = True
    armour_check_minutes: float = 10.0
    weapons: Mapping[str, str] = field(
        default_factory=lambda: dict(DEFAULT_SLAYER_WEAPONS)
    )


@dataclass(frozen=True)
class FailsafeSettings:
    """Start a fallback action whenever the character has nothing to do."""

    enabled: bool = False
    # Human-readable name, used in logs.
    action: str = "Spikemoss Shrub"
    # Sidebar icon of the skill page (reference client coordinates).
    page: tuple[int, int] = (39, 303)
    # The action's Start/Cut button (reference client coordinates).
    button: tuple[int, int] = (1082, 1096)
    # Minimum seconds between attempts.
    cooldown_seconds: float = 60.0


@dataclass(frozen=True)
class RestoreSettings:
    """Resume the pre-run action when a run ends (for example Woodcutting)."""

    enabled: bool = True
    # How long to wait for the save header to confirm the restored action.
    verify_seconds: float = 25.0
    poll_seconds: float = 1.5


@dataclass(frozen=True)
class Settings:
    game: GameSettings = field(default_factory=GameSettings)
    save: SaveSettings = field(default_factory=SaveSettings)
    automation: AutomationSettings = field(default_factory=AutomationSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    slayer: SlayerSettings = field(default_factory=SlayerSettings)
    dungeons: DungeonSettings = field(default_factory=DungeonSettings)
    prayer: PrayerSettings = field(default_factory=PrayerSettings)
    farming: FarmingSettings = field(default_factory=FarmingSettings)
    failsafe: FailsafeSettings = field(default_factory=FailsafeSettings)
    restore: RestoreSettings = field(default_factory=RestoreSettings)
    gamemodes: Mapping[str, GameModeProfile] = field(
        default_factory=default_profiles
    )
    source: Path | None = None


def _point(raw: object, fallback: tuple[int, int]) -> tuple[int, int]:
    if (
        isinstance(raw, (list, tuple))
        and len(raw) == 2
        and all(isinstance(value, (int, float)) for value in raw)
    ):
        return (int(raw[0]), int(raw[1]))
    return fallback


def _delay_range(raw: object, fallback: tuple[int, int]) -> tuple[int, int]:
    if (
        isinstance(raw, (list, tuple))
        and len(raw) == 2
        and all(isinstance(v, (int, float)) for v in raw)
    ):
        low, high = sorted((int(raw[0]), int(raw[1])))
        return low, high
    return fallback


def load_settings(path: Path | None = None) -> Settings:
    """Load settings, falling back to defaults when the file is absent."""
    path = path or CONFIG_FILE
    if not path.exists():
        return Settings()

    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    game = raw.get("game", {})
    save = raw.get("save", {})
    automation = raw.get("automation", {})
    logging = raw.get("logging", {})
    combat = raw.get("combat", {})
    slayer = combat.get("slayer", raw.get("slayer", {}))
    dungeons = combat.get("dungeons", {})
    prayer = combat.get("prayer", {})
    farming = raw.get("farming", {})
    failsafe = raw.get("failsafe", {})
    restore = raw.get("restore", {})
    gamemodes = raw.get("gamemodes", {})

    def weapons_from(section: Mapping[str, object]) -> dict[str, str]:
        result = dict(DEFAULT_SLAYER_WEAPONS)
        for style, name in dict(section.get("weapons", {})).items():
            key = str(style).strip().lower()
            if key in result and isinstance(name, str):
                result[key] = name.strip()
        return result

    weapons = weapons_from(slayer)

    return Settings(
        game=GameSettings(
            window_title=str(game.get("window_title", "Melvor2")),
        ),
        save=SaveSettings(
            root=str(save.get("root", "")),
            poll_seconds=float(save.get("poll_seconds", 5.0)),
            character=str(save.get("character", "")),
        ),
        automation=AutomationSettings(
            max_runtime_minutes=float(automation.get("max_runtime_minutes", 480)),
            emergency_stop_file=str(automation.get("emergency_stop_file", "STOP")),
            humanize=bool(automation.get("humanize", True)),
            click_jitter_px=int(automation.get("click_jitter_px", 3)),
            action_delay_ms=_delay_range(
                automation.get("action_delay_ms"), (120, 420)
            ),
            screenshot_on_error=bool(automation.get("screenshot_on_error", True)),
            background_input=bool(automation.get("background_input", True)),
        ),
        logging=LoggingSettings(level=str(logging.get("level", "INFO"))),
        slayer=SlayerSettings(
            jump_on_start=bool(slayer.get("jump_on_start", True)),
            poll_seconds=max(0.5, float(slayer.get("poll_seconds", 2.0))),
            stop_when_out_of_food=bool(slayer.get("stop_when_out_of_food", True)),
            flee_when_out_of_food=bool(slayer.get("flee_when_out_of_food", True)),
            stall_minutes=max(1.0, float(slayer.get("stall_minutes", 12.0))),
            max_stalls=max(0, int(slayer.get("max_stalls", 2))),
            jump_cooldown_seconds=max(
                5.0, float(slayer.get("jump_cooldown_seconds", 60.0))
            ),
            switch_cooldown_minutes=max(
                0.5, float(slayer.get("switch_cooldown_minutes", 3.0))
            ),
            switch_grace_minutes=max(
                1.0, float(slayer.get("switch_grace_minutes", 4.0))
            ),
            auto_style=bool(slayer.get("auto_style", True)),
            style_switch_cooldown_seconds=max(
                5.0, float(slayer.get("style_switch_cooldown_seconds", 20.0))
            ),
            auto_armour=bool(slayer.get("auto_armour", True)),
            armour_check_minutes=max(
                1.0, float(slayer.get("armour_check_minutes", 10.0))
            ),
            max_tasks=max(0, int(slayer.get("max_tasks", 0))),
            weapons=weapons,
        ),
        dungeons=DungeonSettings(
            dungeon=str(dungeons.get("dungeon", "Harvest Farm")),
            template=str(
                dungeons.get(
                    "template", "assets/templates/dungeon_harvest_farm.png"
                )
            ),
            poll_seconds=max(0.5, float(dungeons.get("poll_seconds", 2.0))),
            stop_when_out_of_food=bool(
                dungeons.get("stop_when_out_of_food", True)
            ),
            flee_when_out_of_food=bool(
                dungeons.get("flee_when_out_of_food", True)
            ),
            switch_cooldown_minutes=max(
                0.5, float(dungeons.get("switch_cooldown_minutes", 3.0))
            ),
            auto_style=bool(dungeons.get("auto_style", True)),
            style_switch_cooldown_seconds=max(
                5.0,
                float(dungeons.get("style_switch_cooldown_seconds", 20.0)),
            ),
            auto_armour=bool(dungeons.get("auto_armour", True)),
            armour_check_minutes=max(
                1.0, float(dungeons.get("armour_check_minutes", 10.0))
            ),
            weapons=weapons_from(dungeons),
        ),
        prayer=PrayerSettings(
            enabled=bool(prayer.get("enabled", False)),
            bone_threshold=max(1, int(prayer.get("bone_threshold", 50))),
            low_prayer_threshold=max(
                0, int(prayer.get("low_prayer_threshold", 100))
            ),
            check_seconds=max(5.0, float(prayer.get("check_seconds", 60.0))),
            verify_seconds=max(2.0, float(prayer.get("verify_seconds", 12.0))),
        ),
        farming=FarmingSettings(
            enabled=bool(farming.get("enabled", False)),
            prioritise=bool(farming.get("prioritise", True)),
            badge_poll_seconds=max(
                1.0, float(farming.get("badge_poll_seconds", 5.0))
            ),
            check_minutes=max(
                0.0, float(farming.get("check_minutes", 0.0))
            ),
            categories=tuple(
                str(item).strip().lower()
                for item in farming.get("categories", DEFAULT_FARM_CATEGORIES)
                if str(item).strip()
            )
            or DEFAULT_FARM_CATEGORIES,
            harvest=bool(farming.get("harvest", True)),
            compost=bool(farming.get("compost", True)),
            select_compost=bool(farming.get("select_compost", True)),
            compost_slot=max(
                1, min(3, int(farming.get("compost_slot", 1)))
            ),
            plant=bool(farming.get("plant", True)),
            water=bool(farming.get("water", True)),
            mill=bool(farming.get("mill", True)),
            restore_page=bool(farming.get("restore_page", True)),
        ),
        failsafe=FailsafeSettings(
            enabled=bool(failsafe.get("enabled", False)),
            action=str(failsafe.get("action", "Spikemoss Shrub")),
            page=_point(failsafe.get("page"), (39, 303)),
            button=_point(failsafe.get("button"), (1082, 1096)),
            cooldown_seconds=max(
                5.0, float(failsafe.get("cooldown_seconds", 60.0))
            ),
        ),
        restore=RestoreSettings(
            enabled=bool(restore.get("enabled", True)),
            verify_seconds=max(1.0, float(restore.get("verify_seconds", 25.0))),
            poll_seconds=max(0.5, float(restore.get("poll_seconds", 1.5))),
        ),
        gamemodes=build_profiles(gamemodes),
        source=path,
    )
