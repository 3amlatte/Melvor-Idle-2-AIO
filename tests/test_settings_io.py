from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mi2_aio import settings_io, settings_schema
from mi2_aio.paths import PROJECT_ROOT


def _copy_config(tmp_path: Path) -> Path:
    target = tmp_path / "settings.toml"
    shutil.copy(PROJECT_ROOT / "config" / "settings.default.toml", target)
    return target


def test_schema_covers_operational_sections() -> None:
    assert len(settings_schema.SECTIONS) >= 10
    assert len(settings_schema.FIELDS) > 50
    assert settings_schema.get_field("combat.prayer.bone_threshold").default == 50
    assert settings_schema.get_field("combat.slayer.max_tasks").kind == "int"


def test_feature_sections_are_not_general_settings() -> None:
    farming = settings_schema.feature_sections("farming")
    assert [section.path for section in farming] == ["farming"]
    assert len(farming[0].fields) == 13
    general = settings_schema.general_sections()
    paths = {section.path for section in general}
    assert "farming" not in paths
    assert "automation" in paths
    assert all(not section.feature for section in general)
    assert settings_schema.feature_sections("fishing") == ()
    with pytest.raises(KeyError):
        settings_schema.get_field("nope.nope")


def test_read_values_uses_the_document(tmp_path: Path) -> None:
    path = _copy_config(tmp_path)
    values = settings_io.read_values(path)
    assert values["combat.slayer.max_tasks"] == 0
    assert values["combat.prayer.enabled"] is True
    assert values["automation.action_delay_ms"] == [120, 420]
    assert values["failsafe.page"] == [39, 303]
    assert values["farming.categories"][0] == "allotments"


def test_save_values_preserves_comments_and_updates_only_requested(
    tmp_path: Path,
) -> None:
    path = _copy_config(tmp_path)
    before = path.read_text(encoding="utf-8")
    settings = settings_io.save_values(
        {
            "combat.slayer.max_tasks": 5,
            "automation.background_input": False,
            "failsafe.page": [40, 304],
        },
        path,
    )
    after = path.read_text(encoding="utf-8")
    assert settings.slayer.max_tasks == 5
    assert settings.automation.background_input is False
    assert tuple(settings.failsafe.page) == (40, 304)
    # The curated comments must survive a UI settings save.
    assert "# Stop after this many completed Slayer tasks" in after
    assert "# Post mouse messages to the game window" in after
    assert "max_tasks = 5" in after
    assert "background_input = false" in after
    assert before != after


def test_invalid_value_does_not_touch_the_file(tmp_path: Path) -> None:
    path = _copy_config(tmp_path)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(settings_io.SettingsError):
        settings_io.save_values({"combat.slayer.max_tasks": "not a number"}, path)
    assert path.read_text(encoding="utf-8") == before

    with pytest.raises(settings_io.SettingsError):
        settings_io.save_values({"farming.compost_slot": 99}, path)
    assert path.read_text(encoding="utf-8") == before


def test_validation_shapes() -> None:
    spec = settings_schema.get_field("failsafe.page")
    assert settings_io.validate_value(spec, "10, 20") == [10, 20]
    with pytest.raises(settings_io.SettingsError):
        settings_io.validate_value(spec, "10")

    categories = settings_schema.get_field("farming.categories")
    assert settings_io.validate_value(categories, "allotments, herbs") == [
        "allotments",
        "herbs",
    ]
    with pytest.raises(settings_io.SettingsError):
        settings_io.validate_value(categories, "")
