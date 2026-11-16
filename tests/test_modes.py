from __future__ import annotations

from pathlib import Path

from mi2_aio.config import load_settings
from mi2_aio.modes import (
    DEFAULT_PROFILES,
    build_profiles,
    normalize_mode_name,
    resolve_mode,
    task_allowed,
)


def test_builtin_profiles_cover_demo_and_expected_types() -> None:
    assert DEFAULT_PROFILES["regular"].permanent_death is False
    assert DEFAULT_PROFILES["regular"].allow_risky_tasks is True
    assert DEFAULT_PROFILES["hardcore"].permanent_death is True
    assert DEFAULT_PROFILES["hardcore"].allow_risky_tasks is False
    assert DEFAULT_PROFILES["test"].permanent_death is False


def test_normalize_mode_name() -> None:
    assert normalize_mode_name("Test / Demo") == "testdemo"
    assert normalize_mode_name("Hardcore") == "hardcore"


def test_resolve_known_modes_by_key_display_and_alias() -> None:
    assert resolve_mode("Regular").profile.key == "regular"
    assert resolve_mode("HARDCORE").profile.key == "hardcore"
    assert resolve_mode("hc").profile.key == "hardcore"
    assert resolve_mode("Test").profile.key == "test"
    assert resolve_mode(" demo ").profile.key == "test"
    assert resolve_mode("Softcore").profile.key == "regular"


def test_unknown_mode_is_conservative() -> None:
    resolved = resolve_mode("Adventure")
    assert resolved.matched is False
    assert resolved.raw == "Adventure"
    assert resolved.profile.key == "unknown"
    assert resolved.profile.permanent_death is True
    assert resolved.profile.allow_risky_tasks is False


def test_empty_mode_is_unknown() -> None:
    resolved = resolve_mode("")
    assert resolved.matched is False
    assert resolved.profile.key == "unknown"


def test_build_profiles_merges_overrides_and_new_modes() -> None:
    profiles = build_profiles(
        {
            "hardcore": {
                "display_name": "Hardcore+",
                "min_hp_ratio": 0.9,
                "blocked_tasks": ["combat"],
            },
            "ironman": {
                "display_name": "Ironman",
                "aliases": ["iron"],
                "permanent_death": True,
                "allow_risky_tasks": False,
                "min_hp_ratio": 0.5,
            },
        }
    )

    hardcore = profiles["hardcore"]
    assert hardcore.display_name == "Hardcore+"
    assert hardcore.min_hp_ratio == 0.9
    assert hardcore.blocked_tasks == frozenset({"combat"})
    assert hardcore.permanent_death is True  # inherited from the built-in

    assert resolve_mode("iron", profiles).profile.key == "ironman"
    assert profiles["ironman"].builtin is False
    assert profiles["regular"].key == "regular"


def test_task_gating_respects_risky_and_supported_modes() -> None:
    regular = DEFAULT_PROFILES["regular"]
    hardcore = DEFAULT_PROFILES["hardcore"]

    allowed, reason = task_allowed(
        "combat", supported_modes=None, risky=True, mode=regular
    )
    assert allowed is True
    assert reason is None

    allowed, reason = task_allowed(
        "combat", supported_modes=None, risky=True, mode=hardcore
    )
    assert allowed is False
    assert reason and "risky" in reason

    allowed, reason = task_allowed(
        "observe", supported_modes=frozenset({"regular"}), risky=False, mode=hardcore
    )
    assert allowed is False
    assert reason and "supports modes" in reason

    blocked = build_profiles({"hardcore": {"blocked_tasks": ["observe"]}})[
        "hardcore"
    ]
    allowed, reason = task_allowed(
        "observe", supported_modes=None, risky=False, mode=blocked
    )
    assert allowed is False
    assert reason and "blocked" in reason


def test_config_loads_gamemode_overrides(tmp_path: Path) -> None:
    config = tmp_path / "settings.toml"
    config.write_text(
        """
[gamemodes.regular]
min_hp_ratio = 0.5

[gamemodes.ironman]
display_name = "Ironman"
aliases = ["iron"]
permanent_death = true
allow_risky_tasks = false
min_hp_ratio = 0.6
""",
        encoding="utf-8",
    )

    settings = load_settings(config)
    assert settings.gamemodes["regular"].min_hp_ratio == 0.5
    assert settings.gamemodes["ironman"].display_name == "Ironman"
    assert resolve_mode("iron", settings.gamemodes).profile.key == "ironman"
