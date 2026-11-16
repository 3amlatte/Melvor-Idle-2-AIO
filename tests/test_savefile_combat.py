from __future__ import annotations

import struct

from test_savefile import build_header

from mi2_aio.savefile import (
    format_header,
    parse_active_enemy,
    parse_equipment,
    parse_header,
)


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


def _slot(name: str, item: str | None = None) -> bytes:
    if item is None:
        payload = b"\xff\xff\xff\xff\x00\x00"
    else:
        payload = b"\x01\x00\x00\x00\x00\x01" + _string("MelvorBase:" + item)
    return (
        _string("MelvorBase:" + name)
        + struct.pack("<i", len(payload))
        + payload
    )


def build_equipment() -> bytes:
    slots = [
        _slot("Helmet", "MithrilHelmet"),
        _slot("Cape"),
        _slot("Amulet"),
        _slot("Ammo"),
        _slot("Weapon", "BoneScythe"),
        _slot("Torso", "MithrilPlatebody"),
        _slot("Offhand", "BoneScythe"),
        _slot("Legs"),
        _slot("Gloves", "MithrilGloves"),
        _slot("Boots"),
        _slot("RingSlot1"),
    ]
    return (
        b"\x09Equipment"
        + struct.pack("<i", 0)
        + struct.pack("<i", len(slots))
        + b"".join(slots)
    )


def _stance(name: str) -> bytes:
    return bytes([len("MelvorBase:") + len(name)]) + (
        "MelvorBase:" + name
    ).encode("ascii")


def build_enemy_block() -> bytes:
    # The second Enemy field is the active enemy. The Slash token before it is
    # not a stance (it is not preceded by the bool), so it must be ignored.
    return (
        b"\x05Enemy"
        + b"\x05Enemy"
        + b"\x00"
        + _stance("Slash")
        + b"\x01"
        + _string("MelvorBase:BlueSlime")
        + b"\x01"
        + _stance("Defensive")
    )


def test_parse_equipment_reads_slots_and_handles_two_handed() -> None:
    data = build_equipment() + b"\x00\x00\x00\x00\rItemEquipping"
    equipment = parse_equipment(data)
    assert equipment == {
        "Helmet": "MithrilHelmet",
        "Weapon": "BoneScythe",
        "Torso": "MithrilPlatebody",
        "Offhand": "BoneScythe",
        "Gloves": "MithrilGloves",
    }
    assert "Cape" not in equipment


def test_parse_equipment_returns_empty_when_block_is_missing() -> None:
    assert parse_equipment(b"no equipment here") == {}


def test_parse_active_enemy_uses_the_second_enemy_field() -> None:
    data = build_equipment() + build_enemy_block()
    assert parse_active_enemy(data) == "BlueSlime"


def test_parse_active_enemy_returns_empty_without_a_stance() -> None:
    data = build_equipment() + b"\x05Enemy" + b"\x05Enemy" + b"\x00\x00"
    assert parse_active_enemy(data) == ""


def test_parse_header_includes_enemy_and_equipment() -> None:
    header = parse_header(
        build_header(entity="Combat", action="Blue Slime")
        + build_equipment()
        + build_enemy_block()
    )
    assert header.active_enemy_id == "BlueSlime"
    assert header.equipment["Weapon"] == "BoneScythe"
    assert header.to_dict()["active_enemy_id"] == "BlueSlime"

    text = format_header(header)
    assert "active enemy   BlueSlime" in text
    assert "equipped       BoneScythe" in text


def test_parse_bank_items_reads_exact_ids() -> None:
    from mi2_aio.savefile import parse_bank_items

    data = (
        b"\x0fMelvorBase:Bank"
        + b"\x15MelvorBase:BoneScythe"
        + b"\t\x00\x00\x00\x00\x00"
        + b"\x18MelvorBase:MithrilHelmet"
        + b"\x01\x00\x00\x00\x00\x00"
        + b"Tab 1"
        + b"\x1aMelvorBase:MithrilScimitar"
    )
    items = parse_bank_items(data)
    assert "BoneScythe" in items
    assert "MithrilHelmet" in items
    # Items after the tab-name boundary are not part of the bank list.
    assert "MithrilScimitar" not in items


def test_parse_bank_stacks_sums_duplicate_stacks() -> None:
    import struct

    from mi2_aio.savefile import parse_bank_stacks

    def stack(item: str, quantity: int) -> bytes:
        token = ("MelvorBase:" + item).encode("ascii")
        # The real format is quantity, placeholder, locked, then the item id.
        return (
            struct.pack("<i", quantity)
            + b"\x00\x00"
            + bytes([len(token)])
            + token
        )

    data = (
        b"\tInventory"
        + b"\x00" * 12  # stackable-inventory header before the stack list
        + stack("Bone", 2)
        + stack("BigBone", 7)
        + stack("Bone", 53)
        + b"\x05Tab 1"
        + stack("Bone", 999)
    )
    stacks = parse_bank_stacks(data)
    # The bank can hold several stacks of the same item; the UI shows each one
    # and burying needs the total.
    assert stacks["Bone"] == 55
    assert stacks["BigBone"] == 7
    assert 999 not in stacks.values()


def test_parse_slayer_task_reads_active_master() -> None:
    from mi2_aio.savefile import parse_slayer_task

    def entry(master: str, enemy: str, length: int, progress: int) -> bytes:
        payload = (
            b"\x01"
            + _string("MelvorBase:" + enemy)
            + struct.pack("<i", length)
            + struct.pack("<i", progress)
            + b"\x00"
        )
        return (
            _string("MelvorBase:" + master)
            + struct.pack("<i", len(payload))
            + payload
        )

    fragment = (
        entry("Kuren", "Golbin", 15, 3)
        + entry("Satsgar", "CreeperVines", 42, 7)
        + b"\x01"
        + _string("MelvorBase:Satsgar")
        + _string("Statistics")
        + b"\x00"
        + b"MelvorBase:SlayerMasterTasksCompleted"
    )
    task = parse_slayer_task(fragment)
    assert task is not None
    assert task.master == "Satsgar"
    assert task.enemy_id == "CreeperVines"
    assert task.length == 42
    assert task.progress == 7
    assert task.key == ("Satsgar", "CreeperVines", 42)
