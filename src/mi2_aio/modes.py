"""Game-mode (character type) profiles.

The save header carries a ``Gamemode`` string. In this demo build it is always
"Test" (hardcoded in Game.cs), but the full release will expose Regular,
Hardcore, and possibly others. Nothing in a task should branch on a mode name;
instead tasks read the resolved profile's policy (permanent death, risky actions,
minimum HP, blocked tasks) and declare which modes they support.

Profiles are built-in and overridable from ``[gamemodes.<key>]`` in
config/settings.toml, so a new mode in a future build needs no code changes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

UNKNOWN_MODE_KEY = "unknown"


@dataclass(frozen=True)
class GameModeProfile:
    key: str
    display_name: str
    aliases: tuple[str, ...] = ()
    permanent_death: bool = True
    allow_risky_tasks: bool = False
    min_hp_ratio: float = 0.75
    blocked_tasks: frozenset[str] = frozenset()
    builtin: bool = True
    description: str = ""

    @property
    def is_hardcore(self) -> bool:
        return self.permanent_death


@dataclass(frozen=True)
class ResolvedMode:
    profile: GameModeProfile
    raw: str
    matched: bool


def _default_profiles() -> dict[str, GameModeProfile]:
    return {
        "regular": GameModeProfile(
            key="regular",
            display_name="Regular",
            aliases=("regular", "standard", "normal", "softcore"),
            permanent_death=False,
            allow_risky_tasks=True,
            min_hp_ratio=0.35,
            description="Standard character; death is not permanent.",
        ),
        "hardcore": GameModeProfile(
            key="hardcore",
            display_name="Hardcore",
            aliases=("hardcore", "hc"),
            permanent_death=True,
            allow_risky_tasks=False,
            min_hp_ratio=0.65,
            description="Permanent death; risky tasks are disabled by default.",
        ),
        "test": GameModeProfile(
            key="test",
            display_name="Test / Demo",
            aliases=("test", "demo", "testing"),
            permanent_death=False,
            allow_risky_tasks=True,
            min_hp_ratio=0.35,
            description="Alpha/demo build mode; current header reports 'Test'.",
        ),
        UNKNOWN_MODE_KEY: GameModeProfile(
            key=UNKNOWN_MODE_KEY,
            display_name="Unknown",
            aliases=(),
            permanent_death=True,
            allow_risky_tasks=False,
            min_hp_ratio=0.75,
            description=(
                "Conservative fallback for a mode this build has not seen. "
                "Assumes permanent death and blocks risky tasks."
            ),
        ),
    }


DEFAULT_PROFILES: Mapping[str, GameModeProfile] = _default_profiles()


def normalize_mode_name(value: str) -> str:
    """Case/punctuation-insensitive key used for profile matching."""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def default_profiles() -> dict[str, GameModeProfile]:
    """A mutable copy of the built-in profiles."""
    return dict(DEFAULT_PROFILES)


def _as_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return ()


def _as_bool(value: object, fallback: bool) -> bool:
    return bool(value) if isinstance(value, bool) else fallback


def _as_float(value: object, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return min(1.0, max(0.0, float(value)))
    return fallback


def build_profiles(
    raw: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, GameModeProfile]:
    """Merge ``[gamemodes.*]`` config over the built-in profiles."""
    profiles = default_profiles()
    if not raw:
        return profiles

    for raw_key, values in raw.items():
        key = normalize_mode_name(raw_key) or raw_key
        base = profiles.get(key)
        if base is None:
            base = GameModeProfile(
                key=key,
                display_name=raw_key,
                permanent_death=True,
                allow_risky_tasks=False,
                min_hp_ratio=0.75,
                builtin=False,
            )
        profiles[key] = GameModeProfile(
            key=key,
            display_name=str(values.get("display_name", base.display_name)),
            aliases=_as_tuple(values.get("aliases", base.aliases)),
            permanent_death=_as_bool(
                values.get("permanent_death"), base.permanent_death
            ),
            allow_risky_tasks=_as_bool(
                values.get("allow_risky_tasks"), base.allow_risky_tasks
            ),
            min_hp_ratio=_as_float(values.get("min_hp_ratio"), base.min_hp_ratio),
            blocked_tasks=frozenset(
                _as_tuple(values.get("blocked_tasks", sorted(base.blocked_tasks)))
            ),
            builtin=base.builtin,
            description=str(values.get("description", base.description)),
        )
    return profiles


def resolve_mode(
    raw: str | None, profiles: Mapping[str, GameModeProfile] | None = None
) -> ResolvedMode:
    """Map a save-header gamemode string onto a profile.

    Unknown values resolve to the conservative ``unknown`` profile so a new
    full-release mode can never accidentally enable risky behavior.
    """
    profiles = profiles or DEFAULT_PROFILES
    fallback = profiles.get(UNKNOWN_MODE_KEY) or default_profiles()[UNKNOWN_MODE_KEY]
    raw_value = (raw or "").strip()
    if not raw_value:
        return ResolvedMode(profile=fallback, raw=raw_value, matched=False)

    needle = normalize_mode_name(raw_value)
    for profile in profiles.values():
        names = {
            normalize_mode_name(profile.key),
            normalize_mode_name(profile.display_name),
            *(normalize_mode_name(alias) for alias in profile.aliases),
        }
        if needle in names:
            return ResolvedMode(profile=profile, raw=raw_value, matched=True)
    return ResolvedMode(profile=fallback, raw=raw_value, matched=False)


def task_allowed(
    task_name: str,
    *,
    supported_modes: frozenset[str] | None,
    risky: bool,
    mode: GameModeProfile,
) -> tuple[bool, str | None]:
    """Check a task's declared compatibility against a mode profile."""
    if task_name in mode.blocked_tasks:
        return False, f"task {task_name!r} is blocked in mode {mode.key!r}"
    if supported_modes is not None and mode.key not in supported_modes:
        allowed = ", ".join(sorted(supported_modes)) or "none"
        return (
            False,
            f"task {task_name!r} supports modes [{allowed}], not {mode.key!r}",
        )
    if risky and not mode.allow_risky_tasks:
        return (
            False,
            f"task {task_name!r} is marked risky; mode {mode.key!r} does not "
            "allow risky tasks (set allow_risky_tasks = true to override)",
        )
    return True, None
