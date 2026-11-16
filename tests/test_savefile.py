from __future__ import annotations

import struct
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from mi2_aio.savefile import SaveFileError, format_header, parse_header

EPOCH = datetime(1, 1, 1, tzinfo=UTC)


def _string(value: str) -> bytes:
    payload = value.encode("utf-8")
    length = len(payload)
    prefix = bytearray()
    while True:
        byte = length & 0x7F
        length >>= 7
        if length:
            prefix.append(byte | 0x80)
        else:
            prefix.append(byte)
            break
    return bytes(prefix) + payload


def _timestamp(value: datetime, kind: int = 1) -> bytes:
    ticks = ((value - EPOCH) // timedelta(microseconds=1)) * 10
    return struct.pack("<Q", (kind << 62) | ticks)


def build_header(
    *,
    version: int = 28,
    name: str = "DrinkWater",
    gamemode: str = "Test",
    timestamp: datetime = datetime(2026, 11, 1, 11, 31, tzinfo=UTC),
    timestamp_kind: int = 1,
    entity: str = "Fishing",
    action: str = "Quiet Bend",
    total_level: int = 174,
    gp: int = 365,
    slayer_coins: int = 0,
    demo: bool = True,
) -> bytes:
    data = bytearray()
    data += struct.pack("<i", version)
    data += uuid.UUID("f48db479-6723-3343-80bb-73bcc91ba57d").bytes_le
    data += _string(name)
    data += _string(gamemode)
    data += _timestamp(timestamp, timestamp_kind)

    if version < 9:
        data += _string("legacy-field")
    else:
        data += _string(entity)
        data += _string(f"res://Assets/Icons/{entity}.png")
        data += _string(action)
        data += _string("res://Assets/Icons/missing_artwork.png")

    data += struct.pack("<i", total_level)
    data += struct.pack("<q", gp)
    data += struct.pack("<q", slayer_coins)
    if version >= 24:
        data += b"\x01" if demo else b"\x00"
    return bytes(data)


def test_parse_current_header() -> None:
    header = parse_header(build_header())

    assert header.save_version == 28
    assert header.character_name == "DrinkWater"
    assert header.gamemode == "Test"
    assert header.uuid == "F48DB479-6723-3343-80BB-73BCC91BA57D"
    assert header.active_entity == "Fishing"
    assert header.active_action == "Quiet Bend"
    assert header.total_level == 174
    assert header.gp == 365
    assert header.slayer_coins == 0
    assert header.is_demo is True
    assert header.timestamp == datetime(2026, 11, 1, 11, 31, tzinfo=UTC)


def test_local_kind_timestamp_is_utc_ticks_displayed_locally() -> None:
    moment = datetime(2026, 11, 11, 3, 29, 34, tzinfo=UTC)
    header = parse_header(build_header(timestamp=moment, timestamp_kind=2))
    assert header.timestamp is not None
    assert header.timestamp.timestamp() == moment.timestamp()


def test_long_string_uses_multi_byte_length_prefix() -> None:
    name = "A" * 300
    header = parse_header(build_header(name=name))
    assert header.character_name == name


def test_legacy_layout_before_localization() -> None:
    header = parse_header(build_header(version=8, demo=False))
    assert header.save_version == 8
    assert header.active_entity == ""
    assert header.active_action == ""
    assert header.is_demo is False


def test_version_before_demo_flag_has_no_bool() -> None:
    header = parse_header(build_header(version=23, demo=False))
    assert header.is_demo is False


def test_truncated_header_raises() -> None:
    with pytest.raises(SaveFileError):
        parse_header(build_header()[:20])


def test_format_header_mentions_character_and_action() -> None:
    text = format_header(parse_header(build_header()))
    assert "DrinkWater" in text
    assert "Quiet Bend" in text

def _hp_save_blob(hp: int, hitpoints_level: int | None = None) -> bytes:
    hp_region = struct.pack("<i", 4) + struct.pack("<i", hp)
    player = _string("Player") + struct.pack("<i", len(hp_region)) + hp_region
    combat = struct.pack("<i", 1) + player
    blob = (
        struct.pack("<i", 1)
        + _string("MelvorBase:Combat")
        + struct.pack("<i", len(combat))
        + combat
    )
    if hitpoints_level is not None:
        payload = struct.pack("<d", 0.0) + struct.pack("<i", hitpoints_level)
        blob += (
            b"MelvorBase:Hitpoints"
            + struct.pack("<i", 200)
            + b"\x00" * 8
            + b"Experience"
            + struct.pack("<i", len(payload))
            + payload
        )
    return blob


def test_current_hp_is_read_from_the_save() -> None:
    header = parse_header(build_header() + _hp_save_blob(400))
    assert header.current_hp == 400


def test_hp_ratio_uses_hitpoints_level_for_the_maximum() -> None:
    header = parse_header(build_header() + _hp_save_blob(400, 51))
    assert header.current_hp == 400
    assert header.max_hp == 510
    assert header.hp_ratio == pytest.approx(400 / 510)
