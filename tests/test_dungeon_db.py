from __future__ import annotations

from mi2_aio.dungeon_db import load_dungeons


def test_dungeon_database_loaded() -> None:
    db = load_dungeons()
    assert db.game == "Melvor Idle 2"
    assert len(db.dungeons) == 12
    assert db.find("Harvest Farm") is not None
    assert db.find("harvestfarm") is not None


def test_harvest_farm_waves_and_enemies() -> None:
    dungeon = load_dungeons().find("Harvest Farm")
    assert dungeon is not None
    assert [wave.enemy_ids for wave in dungeon.waves] == [
        ("MagicCow",),
        ("JackOLantern",),
        ("UndeadFarmer",),
        ("MorgistheGraveCorruptor",),
    ]
    assert dungeon.difficulty == "Intermediate"
    assert dungeon.category == "StandardDungeons"


def test_dungeon_enemy_list_is_deduplicated_in_wave_order() -> None:
    dungeon = load_dungeons().find("Hobgolbin Camp")
    assert dungeon is not None
    assert dungeon.enemy_ids[0] == "Golbin"
    assert len(set(dungeon.enemy_ids)) == len(dungeon.enemy_ids)
