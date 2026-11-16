"""Declarative settings schema for the desktop app.

The TOML file remains the source of truth. This module only describes which
fields exist, how to render them and how to validate them, so the UI never has
to hardcode the settings tree or duplicate defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BOOL = "bool"
INT = "int"
FLOAT = "float"
STR = "str"
POINT = "point"
PAIR_INT = "pair_int"
LIST_STR = "list_str"
CHOICE = "choice"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str = STR
    default: Any = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()
    help: str = ""
    suffix: str = ""
    # Hidden fields remain valid in the config and writable by the app, but are
    # not shown in the Settings tab (low-level or redundant controls).
    hidden: bool = False
    # Assigned by SectionSpec when the registry is built.
    section: str = field(default="", compare=False)

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(self.section.split(".")) + (self.key,)

    @property
    def dotted(self) -> str:
        return ".".join(self.path)

    def with_section(self, section: str) -> FieldSpec:
        return FieldSpec(
            key=self.key,
            label=self.label,
            kind=self.kind,
            default=self.default,
            minimum=self.minimum,
            maximum=self.maximum,
            step=self.step,
            choices=self.choices,
            help=self.help,
            suffix=self.suffix,
            hidden=self.hidden,
            section=section,
        )


@dataclass(frozen=True)
class SectionSpec:
    path: str
    title: str
    description: str = ""
    fields: tuple[FieldSpec, ...] = ()
    # Feature-specific sections are rendered on their Features page instead of
    # the general Settings tab (for example "farming").
    feature: str = ""


def _section(
    path: str,
    title: str,
    fields: list[FieldSpec],
    description: str = "",
    *,
    feature: str = "",
) -> SectionSpec:
    return SectionSpec(
        path=path,
        title=title,
        description=description,
        fields=tuple(f.with_section(path) for f in fields),
        feature=feature,
    )


# Build sections with a compact helper. FieldSpec.section is filled by _section.
def _models() -> tuple[SectionSpec, ...]:
    sections: list[SectionSpec] = []

    sections.append(
        _section(
            "game",
            "Game",
            [
                FieldSpec("window_title", "Window title", STR, "Melvor2", hidden=True),
            ],
            "How the bot finds the Melvor Idle 2 window.",
        )
    )
    sections.append(
        _section(
            "save",
            "Save file",
            [
                FieldSpec("root", "Save root", STR, "", help="Empty = auto-discover under %APPDATA%.", hidden=True),
                FieldSpec("poll_seconds", "Save poll interval", FLOAT, 5.0, 0.5, 60.0, 0.5, suffix="s", hidden=True),
                FieldSpec("character", "Character selector", STR, "", help="Empty = newest save. Name, UUID or filename fragment.", hidden=True),
            ],
        )
    )
    sections.append(
        _section(
            "automation",
            "Automation",
            [
                FieldSpec("max_runtime_minutes", "Maximum runtime", FLOAT, 480.0, 1.0, 100000.0, 1.0, suffix="min"),
                FieldSpec("emergency_stop_file", "Emergency stop file", STR, "STOP"),
                FieldSpec("humanize", "Humanized clicks", BOOL, True),
                FieldSpec("click_jitter_px", "Click jitter", INT, 3, 0, 30, 1, suffix="px"),
                FieldSpec("action_delay_ms", "Action delay range", PAIR_INT, [120, 420], 0, 10000, 10, suffix="ms"),
                FieldSpec("screenshot_on_error", "Screenshot on error", BOOL, True),
                FieldSpec("background_input", "Background input", BOOL, True, help="Post clicks to the game window without moving the real cursor."),
            ],
        )
    )
    sections.append(
        _section(
            "combat.slayer",
            "Slayer",
            [
                FieldSpec("jump_on_start", "Jump on start", BOOL, True),
                FieldSpec("poll_seconds", "Screen poll interval", FLOAT, 2.0, 0.5, 60.0, 0.5, suffix="s"),
                FieldSpec("stop_when_out_of_food", "Stop when out of food", BOOL, True),
                FieldSpec("flee_when_out_of_food", "Flee when out of food", BOOL, True),
                FieldSpec("stall_minutes", "Stall timeout", FLOAT, 12.0, 1.0, 600.0, 1.0, suffix="min"),
                FieldSpec("max_stalls", "Maximum stalls", INT, 2, 0, 20, 1),
                FieldSpec("jump_cooldown_seconds", "Jump cooldown", FLOAT, 60.0, 5.0, 3600.0, 5.0, suffix="s"),
                FieldSpec("switch_cooldown_minutes", "Weapon switch cooldown", FLOAT, 3.0, 0.5, 120.0, 0.5, suffix="min"),
                FieldSpec("switch_grace_minutes", "Switch grace period", FLOAT, 4.0, 1.0, 120.0, 1.0, suffix="min"),
                FieldSpec("auto_style", "Automatic melee style", BOOL, True),
                FieldSpec("style_switch_cooldown_seconds", "Style switch cooldown", FLOAT, 20.0, 5.0, 3600.0, 5.0, suffix="s"),
                FieldSpec("auto_armour", "Automatic armour upgrades", BOOL, True),
                FieldSpec("armour_check_minutes", "Armour check interval", FLOAT, 10.0, 1.0, 240.0, 1.0, suffix="min"),
                FieldSpec("max_tasks", "Stop after tasks", INT, 0, 0, 100000, 1, help="0 = no task limit."),
            ],
        )
    )
    sections.append(
        _section(
            "combat.slayer.weapons",
            "Slayer weapons",
            [
                FieldSpec("melee", "Melee weapon", STR, "Bone Scythe", hidden=True),
                FieldSpec("ranged", "Ranged weapon", STR, "Normal Bow", hidden=True),
                FieldSpec("magic", "Magic weapon", STR, "", help="Empty disables the magic fallback.", hidden=True),
            ],
        )
    )
    sections.append(
        _section(
            "combat.dungeons",
            "Dungeons",
            [
                FieldSpec("dungeon", "Dungeon name", STR, "Harvest Farm"),
                FieldSpec("template", "Name template", STR, "assets/templates/dungeon_harvest_farm.png", help="Relative to the app resource folder."),
                FieldSpec("poll_seconds", "Screen poll interval", FLOAT, 2.0, 0.5, 60.0, 0.5, suffix="s"),
                FieldSpec("stop_when_out_of_food", "Stop when out of food", BOOL, True),
                FieldSpec("flee_when_out_of_food", "Flee when out of food", BOOL, True),
                FieldSpec("switch_cooldown_minutes", "Weapon switch cooldown", FLOAT, 3.0, 0.5, 120.0, 0.5, suffix="min"),
                FieldSpec("auto_style", "Automatic melee style", BOOL, True),
                FieldSpec("style_switch_cooldown_seconds", "Style switch cooldown", FLOAT, 20.0, 5.0, 3600.0, 5.0, suffix="s"),
                FieldSpec("auto_armour", "Automatic armour upgrades", BOOL, True),
                FieldSpec("armour_check_minutes", "Armour check interval", FLOAT, 10.0, 1.0, 240.0, 1.0, suffix="min"),
            ],
        )
    )
    sections.append(
        _section(
            "combat.dungeons.weapons",
            "Dungeon weapons",
            [
                FieldSpec("melee", "Melee weapon", STR, "Bone Scythe", hidden=True),
                FieldSpec("ranged", "Ranged weapon", STR, "Normal Bow", hidden=True),
                FieldSpec("magic", "Magic weapon", STR, "", hidden=True),
            ],
        )
    )
    sections.append(
        _section(
            "combat.prayer",
            "Prayer upkeep",
            [
                FieldSpec("enabled", "Enabled", BOOL, True),
                FieldSpec("bone_threshold", "Bone batch size", INT, 50, 1, 100000, 1),
                FieldSpec("low_prayer_threshold", "Low Prayer threshold", INT, 100, 0, 100000, 1, help="0 disables the early top-up."),
                FieldSpec("check_seconds", "Check interval", FLOAT, 60.0, 5.0, 3600.0, 5.0, suffix="s"),
                FieldSpec("verify_seconds", "Save verify timeout", FLOAT, 12.0, 2.0, 120.0, 1.0, suffix="s"),
            ],
        )
    )
    sections.append(
        _section(
            "farming",
            "Farming",
            [
                FieldSpec("enabled", "Enabled", BOOL, True),
                FieldSpec(
                    "prioritise",
                    "Prioritise farming",
                    BOOL,
                    True,
                    help=(
                        "Service a needed farm pass before the main task step. "
                        "When off, the task runs first and farming is serviced "
                        "afterwards."
                    ),
                ),
                FieldSpec("badge_poll_seconds", "Badge poll interval", FLOAT, 5.0, 1.0, 120.0, 0.5, suffix="s"),
                FieldSpec(
                    "check_minutes",
                    "Safety full-check interval",
                    FLOAT,
                    0.0,
                    0.0,
                    240.0,
                    1.0,
                    suffix="min",
                    help="0 = only run when the red farming badge appears.",
                ),
                FieldSpec("categories", "Categories", LIST_STR, ["allotments", "herbs", "compost", "trees", "flowers", "orchard", "mill"]),
                FieldSpec("harvest", "Harvest", BOOL, True),
                FieldSpec("compost", "Compost", BOOL, True),
                FieldSpec("select_compost", "Select compost type", BOOL, True),
                FieldSpec("compost_slot", "Compost slot", INT, 1, 1, 3, 1),
                FieldSpec("plant", "Plant", BOOL, True),
                FieldSpec("water", "Water", BOOL, True),
                FieldSpec("mill", "Service The Mill", BOOL, True),
                FieldSpec("restore_page", "Restore page after pass", BOOL, True),
            ],
            feature="farming",
        )
    )
    sections.append(
        _section(
            "failsafe",
            "Idle failsafe",
            [
                FieldSpec("enabled", "Enabled", BOOL, True),
                FieldSpec("action", "Fallback action", STR, "Spikemoss Shrub"),
                FieldSpec("page", "Skill page point", POINT, [39, 303], 0, 10000, 1, suffix="px"),
                FieldSpec("button", "Action button point", POINT, [1082, 1096], 0, 10000, 1, suffix="px"),
                FieldSpec("cooldown_seconds", "Retry cooldown", FLOAT, 60.0, 5.0, 3600.0, 5.0, suffix="s"),
            ],
            "Reference-space coordinates for the fallback skill page and its action button.",
        )
    )
    sections.append(
        _section(
            "restore",
            "Restore previous action",
            [
                FieldSpec("enabled", "Enabled", BOOL, True),
                FieldSpec("verify_seconds", "Verify timeout", FLOAT, 25.0, 1.0, 300.0, 1.0, suffix="s"),
                FieldSpec("poll_seconds", "Poll interval", FLOAT, 1.5, 0.5, 60.0, 0.5, suffix="s"),
            ],
        )
    )
    sections.append(
        _section(
            "logging",
            "Logging",
            [
                FieldSpec("level", "Level", CHOICE, "INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR")),
            ],
        )
    )
    return tuple(sections)


SECTIONS: tuple[SectionSpec, ...] = _models()
FIELDS: dict[str, FieldSpec] = {
    field.dotted: field for section in SECTIONS for field in section.fields
}


def feature_sections(feature: str) -> tuple[SectionSpec, ...]:
    """Sections rendered on a Features page instead of the Settings tab."""
    return tuple(section for section in SECTIONS if section.feature == feature)


def general_sections() -> tuple[SectionSpec, ...]:
    """Sections that stay on the general Settings tab."""
    return tuple(section for section in SECTIONS if not section.feature)


def get_field(path: str) -> FieldSpec:
    try:
        return FIELDS[path]
    except KeyError as exc:
        raise KeyError(f"Unknown setting {path!r}") from exc


def default_values() -> dict[str, Any]:
    return {path: field.default for path, field in FIELDS.items()}
