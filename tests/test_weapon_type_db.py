from __future__ import annotations

from mi2_aio.weapon_type_db import load_weapon_types


def test_weapon_type_database_loaded() -> None:
    db = load_weapon_types()
    assert db.game == "Melvor Idle 2"
    assert len(db.weapon_types) >= 20


def test_stance_orders_match_the_game() -> None:
    db = load_weapon_types()
    assert db.by_id("Sword2H") is not None
    assert db.stances("2H Sword") == ("slash", "block", "crush")
    assert db.stances("Sword") == ("stab", "slash", "block")
    assert db.stances("Scimitar") == ("slash",)
    assert db.stances("Mallet") == ("crush",)


def test_stance_index() -> None:
    db = load_weapon_types()
    assert db.stance_index("2H Sword", "slash") == 0
    assert db.stance_index("2H Sword", "block") == 1
    assert db.stance_index("2H Sword", "crush") == 2
    assert db.stance_index("Sword", "slash") == 1
    assert db.stance_index("Sword", "block") == 2
    assert db.stance_index("Scimitar", "slash") == 0
    assert db.stance_index("Mallet", "crush") == 0
    assert db.stance_index("Scimitar", "crush") is None
