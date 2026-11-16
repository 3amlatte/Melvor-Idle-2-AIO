from __future__ import annotations

from mi2_aio.bones import item_name, load_bones, search_index


def test_bone_database_loaded() -> None:
    db = load_bones()
    assert db.game == "Melvor Idle 2"
    assert len(db.bones) == 4
    assert db.find("Bone") is not None
    assert db.find("Big Bone").prayer_points == 6


def test_bone_counts_and_prayer_points() -> None:
    db = load_bones()
    stacks = {"Bone": 40, "BigBone": 10, "BoneScythe": 12}
    assert db.count(stacks) == 50
    assert db.prayer_points(stacks) == 40 * 1 + 10 * 6
    found = db.bone_stacks(stacks)
    assert [bone.name for bone, _quantity in found] == ["Bone", "Big Bone"]
    assert db.bone_stacks({"BoneScythe": 12}) == ()


def test_unknown_bones_are_ignored() -> None:
    db = load_bones()
    assert db.count({"NotABone": 999}) == 0
    assert db.prayer_points({"NotABone": 999}) == 0


def test_item_name_splits_camel_case() -> None:
    assert item_name("BoneScythe") == "Bone Scythe"
    assert item_name("SmallDragonBone") == "Small Dragon Bone"


def test_search_index_matches_the_bank_grid() -> None:
    # Live bank search "Bone" showed Bone Scythe first, then Bone: the search
    # matches words in the item name, not exact names. Burying therefore uses
    # the bone's last word as the search term ("Bone", "Dust").
    order = ("OnionSeed", "BoneScythe", "Bone", "BigBone", "GeodeDust", "MagicDust")
    assert search_index(order, "Bone", "Bone") == 1
    assert search_index(order, "Bone", "BoneScythe") == 0
    assert search_index(order, "Bone", "BigBone") == 2
    assert search_index(order, "Dust", "MagicDust") == 1
    assert search_index(order, "Bone", "MagicDust") is None


def test_search_index_ignores_duplicate_bank_entries() -> None:
    order = ("BoneScythe", "Bone", "Bone")
    assert search_index(order, "Bone", "Bone") == 1

