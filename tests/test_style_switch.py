from __future__ import annotations

import logging
import threading

from PIL import Image

from mi2_aio import style_switch, ui
from mi2_aio.config import Settings
from mi2_aio.modes import resolve_mode
from mi2_aio.savefile import SaveHeader, SkillLevel, SkillLevels
from mi2_aio.style_switch import StyleSwitcher
from mi2_aio.tasks.base import TaskContext
from mi2_aio.window import WindowInfo

WINDOW = WindowInfo(
    hwnd=0x1,
    title="Melvor2",
    left=0,
    top=0,
    right=2560,
    bottom=1369,
    client_x=0,
    client_y=0,
    client_width=2560,
    client_height=1369,
)


def make_levels() -> SkillLevels:
    return SkillLevels(
        character_name="DrinkWater",
        gamemode="Test",
        save_version=28,
        total_level=727,
        skills={
            "Attack": SkillLevel("Attack", 48, 0.0),
            "Defence": SkillLevel("Defence", 40, 0.0),
            "Smithing": SkillLevel("Smithing", 59, 0.0),
        },
    )


def make_header() -> SaveHeader:
    return SaveHeader(
        save_version=28,
        uuid="X",
        character_name="DrinkWater",
        gamemode="Test",
        timestamp=None,
        active_entity="Combat",
        active_entity_icon="res://Assets/Icons/Combat.png",
        active_action="Blue Slime",
        active_action_icon="res://Assets/Monsters/BlueSlime.png",
        total_level=727,
        gp=0,
        slayer_coins=0,
        is_demo=True,
        active_enemy_id="BlueSlime",
        equipment={"Weapon": "BoneScythe", "Offhand": "BoneScythe"},
        bank_order=(
            "MithrilMallet",
            "SteelMallet",
            "IronMallet",
            "CopperMallet",
            "StoneMallet",
            "Mithril2HSword",
            "Steel2HSword",
            "BoneScythe",
            "MithrilHelmet",
            "SteelHelmet",
            "MithrilDefender",
            "MithrilScimitar",
        ),
    )


def make_context(header: SaveHeader | None = None) -> TaskContext:
    settings = Settings()
    return TaskContext(
        settings=settings,
        window=WINDOW,
        logger=logging.getLogger("test.style"),
        stop=threading.Event(),
        header=header or make_header(),
        mode=resolve_mode("Test", settings.gamemodes).profile,
    )


def test_blue_slime_equips_crush_and_sets_stance(monkeypatch) -> None:
    ctx = make_context()
    switcher = StyleSwitcher(auto_style=True)
    calls: list[tuple[str, ...]] = []
    clicks: list[tuple[int, int]] = []

    def fake_equip(window, settings, targets):
        names = tuple(target.name for target in targets)
        calls.append(names)
        return set(names)

    monkeypatch.setattr(switcher, "_capture", lambda ctx: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(
        switcher, "_click", lambda ctx, point: clicks.append(point)
    )
    monkeypatch.setattr(style_switch, "read_skills", lambda settings: make_levels())
    monkeypatch.setattr(style_switch.equipment, "equip_targets", fake_equip)
    stances = iter(["slash", "crush"])
    monkeypatch.setattr(ui, "read_attack_stance", lambda image: next(stances))

    handled = switcher.maybe_apply(
        ctx, Image.new("RGB", (8, 8)), ui.CombatStyle("melee", ui.NEUTRAL)
    )
    assert handled is True
    assert calls == [("Mithril Mallet",)]
    # Mallet has a single Crush stance in the first button position.
    assert clicks == [ui.STANCE_BUTTONS[0]]


def test_two_handed_weapon_does_not_need_a_defender(monkeypatch) -> None:
    ctx = make_context()
    switcher = StyleSwitcher(auto_style=True)
    calls: list[tuple[str, ...]] = []

    def fake_equip(window, settings, targets):
        names = tuple(target.name for target in targets)
        calls.append(names)
        return set(names)

    monkeypatch.setattr(switcher, "_capture", lambda ctx: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(switcher, "_click", lambda ctx, point: None)
    monkeypatch.setattr(style_switch, "read_skills", lambda settings: make_levels())
    monkeypatch.setattr(style_switch.equipment, "equip_targets", fake_equip)
    monkeypatch.setattr(ui, "read_attack_stance", lambda image: "crush")

    assert switcher.maybe_apply(ctx, Image.new("RGB", (8, 8))) is True
    assert calls == [("Mithril Mallet",)]
    # The next poll must not re-open the bank for the same setup.
    assert switcher.maybe_apply(ctx, Image.new("RGB", (8, 8))) is True
    assert len(calls) == 1


def test_missing_defender_is_treated_as_the_current_setup() -> None:
    from mi2_aio.enemy_db import load_enemies
    from mi2_aio.equipment_db import load_database
    from mi2_aio.melee import choose_melee_style

    decision = choose_melee_style(
        load_database(),
        load_enemies().find("Blue Slime"),
        attack_level=48,
        defence_level=40,
        smithing_level=59,
    )
    choice = next(
        item for item in decision.candidates if item.defender is not None
    )
    switcher = StyleSwitcher(auto_style=True)
    switcher._missing_defenders.add(choice.defender.id)
    assert switcher._matches_current(choice, (choice.weapon.id, None))


def test_equipped_key_survives_an_enemy_change(monkeypatch) -> None:
    ctx = make_context()
    ctx.header = _replace_header(
        ctx.header,
        active_enemy_id="UndeadFarmer",
        active_action="Undead Farmer",
        equipment={"Weapon": "Mithril2HSword", "Offhand": "Mithril2HSword"},
    )
    switcher = StyleSwitcher(auto_style=True)
    switcher._equipped_key = ("mithril-2h-sword", None)
    switcher._equipped_until = 10**9
    calls: list[tuple[str, ...]] = []

    def fake_equip(window, settings, targets):
        names = tuple(target.name for target in targets)
        calls.append(names)
        return set(names)

    monkeypatch.setattr(switcher, "_capture", lambda ctx: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(switcher, "_click", lambda ctx, point: None)
    monkeypatch.setattr(style_switch, "read_skills", lambda settings: make_levels())
    monkeypatch.setattr(style_switch.equipment, "equip_targets", fake_equip)
    monkeypatch.setattr(ui, "read_attack_stance", lambda image: "block")

    # First enemy: the current Mithril 2H Sword is the best block setup.
    assert switcher.maybe_apply(ctx, Image.new("RGB", (8, 8))) is True
    assert calls == []

    # Second enemy: Morgis favours Slash/Bone Scythe. The manager must still
    # remember that it equipped the 2H sword, even if the save is stale.
    ctx.header = _replace_header(
        ctx.header,
        active_enemy_id="MorgistheGraveCorruptor",
        active_action="Morgis, the Grave Corruptor",
        equipment={"Weapon": "Mithril2HSword", "Offhand": "Mithril2HSword"},
    )
    assert switcher.maybe_apply(ctx, Image.new("RGB", (8, 8))) is True
    assert any("Bone Scythe" in call for call in calls)


def _replace_header(header, **changes):
    from dataclasses import replace

    return replace(header, **changes)


def test_unowned_weapons_are_skipped(monkeypatch) -> None:
    ctx = make_context()
    switcher = StyleSwitcher(auto_style=True)
    calls: list[tuple[str, ...]] = []

    def fake_equip(window, settings, targets):
        names = tuple(target.name for target in targets)
        calls.append(names)
        if any("Mallet" in name for name in names):
            return set()
        return set(names)

    monkeypatch.setattr(switcher, "_capture", lambda ctx: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(switcher, "_click", lambda ctx, point: None)
    monkeypatch.setattr(style_switch, "read_skills", lambda settings: make_levels())
    monkeypatch.setattr(style_switch.equipment, "equip_targets", fake_equip)
    monkeypatch.setattr(ui, "read_attack_stance", lambda image: "block")

    assert switcher.maybe_apply(ctx, Image.new("RGB", (8, 8))) is True
    assert calls[0] == ("Mithril Mallet",)
    assert any("Mithril 2H Sword" in call for call in calls)


def test_auto_armour_equips_an_owned_upgrade(monkeypatch) -> None:
    ctx = make_context()
    ctx.header = _replace_header(
        ctx.header,
        equipment={"Helmet": "SteelHelmet"},
        bank_items=frozenset({"MithrilHelmet"}),
    )
    switcher = StyleSwitcher(auto_style=False, auto_armour=True)
    calls: list[tuple[str, ...]] = []

    def fake_verified(window, settings, **kwargs):
        calls.append((kwargs["slot_key"], kwargs["desired_game_id"]))
        return True

    monkeypatch.setattr(switcher, "_capture", lambda ctx: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(switcher, "_click", lambda ctx, point: None)
    monkeypatch.setattr(style_switch, "read_skills", lambda settings: make_levels())
    monkeypatch.setattr(style_switch, "read_header", lambda settings: ctx.header)
    monkeypatch.setattr(style_switch.equipment, "equip_verified_slot", fake_verified)

    # auto_style is off, so the call only performs the armour check.
    assert switcher.maybe_apply(ctx, Image.new("RGB", (8, 8))) is False
    assert calls == [("Helmet", "MithrilHelmet")]


def test_auto_armour_never_uses_magic_or_ranged_armour(monkeypatch) -> None:
    ctx = make_context()
    ctx.header = _replace_header(
        ctx.header,
        equipment={"Torso": "SteelPlatebody"},
        bank_items=frozenset({"DustWizardRobe", "ChainmailBody"}),
    )
    switcher = StyleSwitcher(auto_style=False, auto_armour=True)
    calls: list[tuple[str, ...]] = []

    def fake_verified(window, settings, **kwargs):
        calls.append((kwargs["slot_key"], kwargs["desired_game_id"]))
        return True

    monkeypatch.setattr(switcher, "_capture", lambda ctx: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(switcher, "_click", lambda ctx, point: None)
    monkeypatch.setattr(style_switch, "read_skills", lambda settings: make_levels())
    monkeypatch.setattr(style_switch, "read_header", lambda settings: ctx.header)
    monkeypatch.setattr(style_switch.equipment, "equip_verified_slot", fake_verified)

    assert switcher.maybe_apply(ctx, Image.new("RGB", (8, 8))) is False
    assert calls == []


def test_auto_armour_upgrades_defender_for_one_handed_weapon(monkeypatch) -> None:
    ctx = make_context()
    ctx.header = _replace_header(
        ctx.header,
        equipment={"Weapon": "MithrilScimitar"},
        bank_items=frozenset({"MithrilDefender"}),
    )
    switcher = StyleSwitcher(auto_style=False, auto_armour=True)
    calls: list[tuple[str, ...]] = []

    def fake_verified(window, settings, **kwargs):
        calls.append((kwargs["slot_key"], kwargs["desired_game_id"]))
        return True

    monkeypatch.setattr(switcher, "_capture", lambda ctx: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(switcher, "_click", lambda ctx, point: None)
    monkeypatch.setattr(style_switch, "read_skills", lambda settings: make_levels())
    monkeypatch.setattr(style_switch, "read_header", lambda settings: ctx.header)
    monkeypatch.setattr(style_switch.equipment, "equip_verified_slot", fake_verified)

    assert switcher.maybe_apply(ctx, Image.new("RGB", (8, 8))) is False
    assert calls == [("Offhand", "MithrilDefender")]


def test_auto_armour_skips_defender_for_two_handed_weapon(monkeypatch) -> None:
    ctx = make_context()
    ctx.header = _replace_header(
        ctx.header,
        equipment={"Weapon": "BoneScythe", "Offhand": "BoneScythe"},
        bank_items=frozenset({"MithrilDefender"}),
    )
    switcher = StyleSwitcher(auto_style=False, auto_armour=True)
    calls: list[tuple[str, ...]] = []

    def fake_verified(window, settings, **kwargs):
        calls.append((kwargs["slot_key"], kwargs["desired_game_id"]))
        return True

    monkeypatch.setattr(switcher, "_capture", lambda ctx: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(switcher, "_click", lambda ctx, point: None)
    monkeypatch.setattr(style_switch, "read_skills", lambda settings: make_levels())
    monkeypatch.setattr(style_switch, "read_header", lambda settings: ctx.header)
    monkeypatch.setattr(style_switch.equipment, "equip_verified_slot", fake_verified)

    assert switcher.maybe_apply(ctx, Image.new("RGB", (8, 8))) is False
    assert calls == []
