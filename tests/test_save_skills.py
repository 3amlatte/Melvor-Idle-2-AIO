from __future__ import annotations

import struct

from mi2_aio.savefile import (
    MAX_SKILL_LEVEL,
    MAX_TOTAL_LEVEL,
    SKILL_NAMES,
    UNAVAILABLE_SKILLS,
    parse_skill_levels,
)


def skill_block(
    name: str,
    xp: float,
    level: int,
    *,
    version: int = 28,
    component_length: int = 200,
    payload_length: int | None = None,
) -> bytes:
    payload = struct.pack("<d", xp)
    if version < 25:
        payload += struct.pack("<i", 0)  # legacy extra int32 before the level
    payload += struct.pack("<i", level)
    length = payload_length if payload_length is not None else len(payload)
    return (
        f"MelvorBase:{name}".encode()
        + struct.pack("<i", component_length)
        + b"\x00" * 8
        + b"Experience"
        + struct.pack("<i", length)
        + payload
    )


def test_parse_skill_level_uses_stored_level_not_level_cap() -> None:
    # The Skills tab shows "56/60"; the save stores 56, and 60 is the cap.
    levels = parse_skill_levels(skill_block("Strength", 186400.0, 56), 28)
    assert levels["Strength"].level == 56
    assert levels["Strength"].xp == 186400.0


def test_parse_all_four_gear_skills() -> None:
    data = b"".join(
        [
            skill_block("Attack", 89897.0, 48),
            skill_block("Strength", 186400.0, 56),
            skill_block("Defence", 39098.0, 40),
            skill_block("Smithing", 255089.0, 59),
        ]
    )
    levels = parse_skill_levels(data, 28)
    assert {name: skill.level for name, skill in levels.items()} == {
        "Attack": 48,
        "Strength": 56,
        "Defence": 40,
        "Smithing": 59,
    }


def test_longer_entity_ids_and_skill_list_are_skipped() -> None:
    data = (
        # Skill list occurrence: next bytes decode to an implausible length.
        b"MelvorBase:Strength" + b"\x14MelvorBase:Attack"
        # Longer entity id (StrengthTask3): "Task" is not a length.
        + b"MelvorBase:StrengthTask3"
        + b"Task"
        + b"Experience"
        + struct.pack("<i", 12)
        + struct.pack("<d", 1.0)
        + struct.pack("<i", 1)
        # The real skill entity.
        + skill_block("Strength", 186400.0, 56)
    )
    levels = parse_skill_levels(data, 28)
    assert levels["Strength"].level == 56


def test_legacy_save_layout_has_an_extra_int32() -> None:
    levels = parse_skill_levels(
        skill_block("Strength", 186400.0, 56, version=24), 24
    )
    assert levels["Strength"].level == 56


def test_wrong_experience_payload_length_is_ignored() -> None:
    levels = parse_skill_levels(
        skill_block("Strength", 186400.0, 56, payload_length=20), 28
    )
    assert "Strength" not in levels

def test_demo_total_level_max_excludes_unplayable_skills() -> None:
    playable = len(SKILL_NAMES) - len(UNAVAILABLE_SKILLS)
    assert playable == 22
    assert UNAVAILABLE_SKILLS == {"Astrology", "Summoning", "Herblore", "Agility"}
    assert MAX_TOTAL_LEVEL == playable * MAX_SKILL_LEVEL == 1320
