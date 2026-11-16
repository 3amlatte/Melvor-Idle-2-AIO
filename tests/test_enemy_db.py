from __future__ import annotations

from mi2_aio.enemy_db import load_enemies


def database():
    return load_enemies()


def test_enemy_database_loaded() -> None:
    db = database()
    assert db.game == "Melvor Idle 2"
    assert db.build.startswith("Demo")
    assert len(db.enemies) >= 100
    assert db.find("Blue Slime") is not None
    assert db.find("blue slime") is not None
    assert db.find("Toxic Razorfish") is not None


def test_blue_slime_defence_values() -> None:
    slime = database().find("Blue Slime")
    assert slime is not None
    assert slime.defence_level == 16
    assert slime.defence_bonus("slash") == 109
    assert slime.defence_bonus("block") == 109
    assert slime.defence_bonus("crush") == 45


def test_toxic_razorfish_defence_values() -> None:
    fish = database().find("Toxic Razorfish")
    assert fish is not None
    assert fish.defence_level == 41
    assert fish.defence_bonus("slash") == 216
    assert fish.defence_bonus("block") == 227
    assert fish.defence_bonus("crush") == 245


def test_enemy_names_are_unique_and_populated() -> None:
    db = database()
    assert len(set(db.names())) == len(db.names())
    assert all(name.strip() for name in db.names())


def test_find_by_game_id() -> None:
    db = database()
    assert db.find_by_id("BlueSlime") is not None
    assert db.find_by_id("BlueSlime").name == "Blue Slime"
    assert db.find_by_id("ToxicRazorfish") is not None
    assert db.find_by_id("NotAnEnemy") is None
