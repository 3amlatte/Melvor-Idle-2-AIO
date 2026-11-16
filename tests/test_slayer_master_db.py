from __future__ import annotations

from mi2_aio.slayer_master_db import load_slayer_masters


def test_slayer_master_database_loaded() -> None:
    db = load_slayer_masters()
    assert db.game == "Melvor Idle 2"
    assert db.build.startswith("Demo")
    assert len(db.masters) == 10
    assert db.find("Satsgar") is not None
    assert db.find("satsgar") is not None


def test_satsgar_fields() -> None:
    master = load_slayer_masters().find("Satsgar")
    assert master is not None
    assert master.base_task_length == 35
    assert master.area_ids == ("GreenMangroves",)
    assert master.areas[0].name == "Green Mangroves"
    assert master.unlock_level == 20
    assert master.reroll_cost is not None
    assert master.reroll_cost.quantity == 1500
    assert master.block_cost is not None
    assert master.block_cost.quantity == 10000
    assert len(master.block_slots) == 2
    assert master.block_slots[0].tasks_completed == 5
    assert master.block_slots[1].tasks_completed == 20


def test_kuren_is_unlocked_and_high_masters_are_demo_locked() -> None:
    db = load_slayer_masters()
    kuren = db.find("Kuren")
    assert kuren is not None
    assert kuren.unlock_requirements == ()
    assert kuren.unlocked_for({"Slayer": 1}) is True
    assert kuren.base_task_length == 15

    feriken = db.find("Feriken")
    assert feriken is not None
    assert feriken.unlocked_for({"Slayer": 99}) is False
    assert any(
        requirement.type == "DemoLocked"
        for requirement in feriken.unlock_requirements
    )


def test_unlocked_filter_uses_slayer_level() -> None:
    db = load_slayer_masters()
    unlocked = db.unlocked({"Slayer": 35})
    names = {master.name for master in unlocked}
    assert "Kuren" in names
    assert "Allevia" in names
    assert "Satsgar" in names
    assert "Fells" in names
    assert "Galan" not in names
