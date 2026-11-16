from __future__ import annotations

import pytest

from mi2_aio.equipment_db import EquipmentDatabase, load_database


def database() -> EquipmentDatabase:
    return load_database()


def by_name(items, name):
    return next(item for item in items if item.name == name)


def test_lookup_by_game_id_and_stance_index() -> None:
    db = database()
    assert db.find_by_game_id("MithrilMallet").name == "Mithril Mallet"
    assert db.find_by_game_id("BoneScythe").name == "Bone Scythe"
    assert db.find_by_game_id("mithril-2h-sword").name == "Mithril 2H Sword"
    assert db.find_by_game_id("not-an-item") is None

    mithril_2h = db.find_by_game_id("Mithril2HSword")
    assert mithril_2h is not None
    assert mithril_2h.stance_index("slash") == 0
    assert mithril_2h.stance_index("block") == 1
    assert mithril_2h.stance_index("crush") == 2

    mallet = db.find_by_game_id("MithrilMallet")
    assert mallet is not None
    assert mallet.stance_index("crush") == 0
    assert mallet.stance_index("slash") is None


def test_database_metadata_and_counts() -> None:
    db = database()
    assert db.game == "Melvor Idle 2"
    assert db.build.startswith("Demo")
    assert len(db.scimitars) == 6
    assert len(db.defenders) == 6
    assert len(db.swords) == 12
    assert len(db.mallets) == 6
    assert len(db.other_weapons) == 1
    assert len(db.armour) == 188
    assert len(db.items) == 213


def test_armour_slots_and_defence_requirements() -> None:
    db = database()
    assert len(db.armour_for_slot("helmet")) == 34
    assert len(db.armour_for_slot("torso")) == 28
    assert len(db.armour_for_slot("legs")) == 29
    assert len(db.armour_for_slot("boots")) == 30
    assert len(db.armour_for_slot("gloves")) == 14
    assert len(db.armour_for_slot("offhand")) == 23

    mithril = db.find_by_game_id("MithrilPlatebody")
    assert mithril is not None
    assert mithril.slot == "torso"
    assert mithril.required_skill == "Defence"
    assert mithril.required_level == 40
    assert mithril.can_equip_all({"Defence": 40}) is True
    assert mithril.can_equip_all({"Defence": 39}) is False
    assert mithril.protection == 246
    assert mithril.total_defence > 200
    assert mithril.smithing is not None and mithril.smithing.level == 45

    defender = db.find_by_game_id("MithrilDefender")
    assert defender is not None
    assert defender.slot == "offhand"
    assert defender.is_defender is True
    assert defender in db.defenders


def test_armour_multi_skill_requirements() -> None:
    db = database()
    chainmail = db.find_by_game_id("ChainmailBody")
    assert chainmail is not None
    assert {(req.skill, req.level) for req in chainmail.requirements} == {
        ("Ranged", 40),
        ("Defence", 30),
    }
    assert chainmail.can_equip_all({"Ranged": 1, "Defence": 40}) is False
    assert chainmail.can_equip_all({"Ranged": 40, "Defence": 30}) is True


def test_best_armour_respects_ownership_and_levels() -> None:
    db = database()
    levels = {
        "Attack": 48,
        "Strength": 56,
        "Defence": 40,
        "Ranged": 1,
        "Magic": 1,
        "Smithing": 59,
    }
    owned = {"mithril-platebody", "steel-platebody"}
    best = db.best_armour("torso", levels, owned=owned)
    assert best is not None
    assert best.name == "Mithril Platebody"

    best_no_owned = db.best_armour("torso", levels, owned={"steel-platebody"})
    assert best_no_owned is not None
    assert best_no_owned.name == "Steel Platebody"

    # Wizard/chainmail pieces need Magic/Ranged and are never chosen for melee.
    assert db.best_armour("torso", {"Defence": 40, "Magic": 99, "Ranged": 99}) is not None
    assert db.best_armour("torso", {"Defence": 40, "Magic": 99, "Ranged": 99}).name not in {
        "Dust Wizard Robe",
        "Chainmail Body",
    }


def test_owned_items_combines_bank_and_equipment() -> None:
    from mi2_aio.savefile import SaveHeader

    db = database()
    header = SaveHeader(
        save_version=28,
        uuid="X",
        character_name="DrinkWater",
        gamemode="Test",
        timestamp=None,
        active_entity="Combat",
        active_entity_icon="",
        active_action="Blue Slime",
        active_action_icon="",
        total_level=727,
        gp=0,
        slayer_coins=0,
        is_demo=True,
        equipment={"Weapon": "BoneScythe"},
        bank_items=frozenset({"MithrilPlatebody", "MithrilHelmet"}),
    )
    owned = db.owned_items(header)
    assert "bone-scythe" in owned
    assert "mithril-platebody" in owned
    assert "mithril-helmet" in owned
    assert "mithril-platelegs" not in owned


def test_sword_tiers_and_styles() -> None:
    db = database()
    stone = by_name(db.swords, "Stone Sword")
    assert stone.required_level == 1
    assert stone.slash_attack == 20
    assert stone.melee_strength == 12
    assert set(stone.styles) == {"stab", "slash", "block"}
    assert stone.two_handed is False
    assert stone.smithing is not None and stone.smithing.level == 1

    mithril = by_name(db.swords, "Mithril Sword")
    assert mithril.required_level == 40
    assert mithril.slash_attack == 54
    assert mithril.style_bonus("block") == 70
    assert mithril.smithing is not None and mithril.smithing.level == 36

    mithril_2h = by_name(db.swords, "Mithril 2H Sword")
    assert mithril_2h.required_level == 40
    assert mithril_2h.two_handed is True
    assert mithril_2h.occupied_slots == ("weapon", "offhand")
    assert mithril_2h.slash_attack == 83
    assert mithril_2h.style_bonus("crush") == 87
    assert mithril_2h.style_bonus("block") == 108
    assert mithril_2h.melee_strength == 50

    greatsword = by_name(db.swords, "Staggering Lash Greatsword")
    assert greatsword.special is True
    assert greatsword.required_level == 55
    assert greatsword.style_bonus("slash") == 100
    assert greatsword.style_bonus("crush") == 109
    assert greatsword.style_bonus("block") == 136
    assert greatsword.smithing is None
    assert greatsword.drops == ("Wyvern",)


def test_mallet_tiers_and_crush_style() -> None:
    db = database()
    assert len(db.mallets) == 6
    stone = by_name(db.mallets, "Stone Mallet")
    assert stone.required_level == 1
    assert stone.style_bonus("crush") == 38
    assert stone.style_bonus("slash") == 0
    assert stone.style_bonus("block") == 0
    assert stone.melee_strength == 45
    assert stone.smithing is not None and stone.smithing.level == 3

    adamant = by_name(db.mallets, "Adamant Mallet")
    assert adamant.required_level == 50
    assert adamant.style_bonus("crush") == 121
    assert adamant.melee_strength == 66
    assert adamant.smithing is not None and adamant.smithing.level == 51
    assert adamant.two_handed is True
    assert adamant.occupied_slots == ("weapon", "offhand")


def test_best_weapon_for_each_melee_style() -> None:
    db = database()
    # The Bone Scythe's high raw slash/block makes it the best special slash
    # choice at Attack 48; standard weapons are evaluated without it.
    assert (
        db.best_weapon_for_style("slash", 48, include_special=False).name
        == "Mithril 2H Sword"
    )
    assert (
        db.best_weapon_for_style("crush", 48, craftable_only=True, smithing_level=59).name
        == "Mithril Mallet"
    )
    assert (
        db.best_weapon_for_style("block", 48, include_special=False).name
        == "Mithril 2H Sword"
    )
    assert db.best_weapon_for_style("slash", 1).name == "Stone Sword"


def test_bone_scythe_baseline() -> None:
    db = database()
    bone = db.weapon_by_name("Bone Scythe")
    assert bone is not None
    assert bone.two_handed is True
    assert bone.weapon_type == "2H Sword"
    assert bone.occupied_slots == ("weapon", "offhand")
    assert bone.required_level == 23
    assert bone.slash_attack == 95
    assert bone.melee_strength == 47
    assert bone.turn_interval_s == 3.3
    assert bone.power_rating == 672
    assert bone.smithing is None
    assert bone.obtained_from == "Harvest Farm Chest"


def test_best_loadout_at_current_levels() -> None:
    db = database()
    # Attack 48 / Defence 40 (double-checked on the live character).
    available = db.best_loadout(48, 40)
    assert available is not None
    assert available.name == "Toxic Razors Scimitar + Mithril Defender"
    assert available.slash_attack == 88
    assert available.melee_strength == 31
    assert available.turn_interval_s == 2.6
    assert available.slash_defence == 22

    craftable = db.best_loadout(
        48, 40, craftable_only=True, smithing_level=59
    )
    assert craftable is not None
    assert craftable.name == "Mithril Scimitar + Mithril Defender"
    assert craftable.slash_attack == 83
    assert craftable.melee_strength == 30
    assert craftable.slash_defence == 22


def test_compare_bone_scythe_to_mithril_pair() -> None:
    db = database()
    bone = db.weapon_by_name("Bone Scythe")
    loadout = db.best_loadout(48, 40, craftable_only=True, smithing_level=59)
    assert bone is not None and loadout is not None

    diff = db.compare_to_two_handed(bone, loadout)
    assert diff["baseline_power_rating"] == 672
    assert diff["loadout_power_rating"] == 1148
    assert diff["power_rating_delta"] == 476
    assert diff["slash_attack_delta"] == -12
    assert diff["melee_strength_delta"] == -17
    assert diff["interval_delta_s"] == pytest.approx(0.7)
    assert diff["loadout_slash_per_s"] > diff["baseline_slash_per_s"]
    assert diff["loadout_strength_per_s"] < diff["baseline_strength_per_s"]


def test_toxic_razors_power_rating_is_complete() -> None:
    db = database()
    toxic = by_name(db.scimitars, "Toxic Razors Scimitar")
    assert toxic.power_rating == 1204


def test_scimitar_tiers_and_stats() -> None:
    db = database()
    copper = by_name(db.scimitars, "Copper Scimitar")
    assert copper.required_skill == "Attack"
    assert copper.required_level == 10
    assert copper.slash_attack == 34
    assert copper.melee_strength == 16
    assert copper.smithing is not None
    assert copper.smithing.level == 6
    assert copper.smithing.ingredients == (("Copper Bar", 2),)

    mithril = by_name(db.scimitars, "Mithril Scimitar")
    assert mithril.required_level == 40
    assert mithril.slash_attack == 69
    assert mithril.smithing is not None
    assert mithril.smithing.level == 37

    adamant = by_name(db.scimitars, "Adamant Scimitar")
    assert adamant.required_level == 50
    assert adamant.slash_attack == 82
    assert adamant.melee_strength == 32
    assert adamant.smithing is not None
    assert adamant.smithing.level == 47
    assert adamant.smithing.ingredients == (("Adamantite Bar", 2),)
    assert adamant.sells_for == 307
    assert "Wolf" in adamant.drops


def test_special_drop_weapons() -> None:
    db = database()
    toxic = by_name(db.scimitars, "Toxic Razors Scimitar")
    assert toxic.special is True
    assert toxic.required_level == 42
    assert toxic.slash_attack == 74
    assert toxic.smithing is None
    assert toxic.drops == ("Toxic Razorfish",)
    assert toxic.drop_area == "Toxic Bog"
    assert toxic.drop_chance == pytest.approx(0.00678)
    assert toxic.sells_for == 1332
    assert "Toxic Razors" in (toxic.special_text or "")
    assert toxic.icon == "res://Assets/Items/ToxicRazorsDagger.png"
    assert "ToxicRazorfish" in " ".join(toxic.evidence)
    assert "legacy art filename" in (toxic.note or "")

    mantis = by_name(db.defenders, "Mantis Defender")
    assert mantis.special is True
    assert mantis.required_level == 45
    assert mantis.smithing is None
    assert mantis.drops == ("Mangrove Mantis",)
    assert mantis.sells_for == 1168
    assert mantis.slash_defence == 26


def test_defender_stats_and_recipes() -> None:
    db = database()
    copper = by_name(db.defenders, "Copper Defender")
    assert copper.required_skill == "Defence"
    assert copper.required_level == 10
    assert copper.slash_defence == 6
    assert copper.smithing is not None
    assert copper.smithing.level == 5
    assert copper.smithing.ingredients == (("Copper Bar", 1),)

    adamant = by_name(db.defenders, "Adamant Defender")
    assert adamant.required_level == 50
    assert adamant.slash_defence == 27
    assert adamant.smithing is not None
    assert adamant.smithing.level == 45
    assert adamant.smithing.ingredients == (("Adamantite Bar", 1),)


def test_best_scimitar_by_attack_level() -> None:
    db = database()
    assert db.best_scimitar(43).name == "Toxic Razors Scimitar"
    assert db.best_scimitar(43, include_special=False).name == "Mithril Scimitar"
    assert db.best_scimitar(50).name == "Adamant Scimitar"
    assert db.best_scimitar(1) is None


def test_best_craftable_scimitar() -> None:
    db = database()
    assert (
        db.best_scimitar(43, craftable_only=True, smithing_level=37).name
        == "Mithril Scimitar"
    )
    assert (
        db.best_scimitar(43, craftable_only=True, smithing_level=36).name
        == "Steel Scimitar"
    )
    assert (
        db.best_scimitar(50, craftable_only=True, smithing_level=47).name
        == "Adamant Scimitar"
    )
    assert db.best_scimitar(43, craftable_only=True, smithing_level=0) is None


def test_best_defender_by_defence_level() -> None:
    db = database()
    assert db.best_defender(45).name == "Mantis Defender"
    assert db.best_defender(45, include_special=False).name == "Mithril Defender"
    assert db.best_defender(50).name == "Adamant Defender"
    assert (
        db.best_defender(50, craftable_only=True, smithing_level=45).name
        == "Adamant Defender"
    )


def test_future_tiers_are_documented() -> None:
    db = database()
    assert "Rune" in db.future_tiers["scimitars"]
    assert "Dragon" in db.future_tiers["scimitars"]
    assert "Rune" in db.future_tiers["defenders"]


def test_bank_target_uses_bank_order_and_slot_search() -> None:
    from mi2_aio.savefile import SaveHeader

    db = database()
    header = SaveHeader(
        save_version=28,
        uuid="X",
        character_name="DrinkWater",
        gamemode="Test",
        timestamp=None,
        active_entity="Combat",
        active_entity_icon="",
        active_action="Blue Slime",
        active_action_icon="",
        total_level=727,
        gp=0,
        slayer_coins=0,
        is_demo=True,
        equipment={},
        bank_order=(
            "BasicWizardHat",
            "PumpkinHead",
            "HardLeatherCowl",
            "MithrilHelmet",
            "MithrilMallet",
            "Mithril2HSword",
            "MithrilDefender",
        ),
    )
    helmet = db.find_by_game_id("MithrilHelmet")
    assert helmet is not None
    assert db.bank_target(header, helmet) == ("Helmet", 3)

    mallet = db.find_by_game_id("MithrilMallet")
    assert mallet is not None
    assert db.bank_target(header, mallet) == ("Mallet", 0)

    sword = db.find_by_game_id("Mithril2HSword")
    assert sword is not None
    assert db.bank_target(header, sword) == ("Sword", 0)

    defender = db.find_by_game_id("MithrilDefender")
    assert defender is not None
    assert db.bank_target(header, defender) == ("Defender", 0)

    missing = db.find_by_game_id("AdamantPlatebody")
    assert missing is not None
    assert db.bank_target(header, missing) is None
