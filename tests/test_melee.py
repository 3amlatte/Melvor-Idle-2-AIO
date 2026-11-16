from __future__ import annotations

import pytest

from mi2_aio.enemy_db import load_enemies
from mi2_aio.equipment_db import load_database
from mi2_aio.melee import choose_melee_style, hit_chance


def test_hit_chance_matches_the_game_formula() -> None:
    # Bone Scythe slash 95 vs Blue Slime slash defence 109, Attack 48, Def 16.
    assert hit_chance(95, 48, 109, 16) == pytest.approx(0.7614, abs=1e-3)
    # Accuracy below evasion: accuracy / (2 * evasion).
    assert hit_chance(0, 1, 1000, 50) == pytest.approx(0.0048, abs=1e-3)


def test_blue_slime_recommends_crush() -> None:
    decision = choose_melee_style(
        load_database(),
        load_enemies().find("Blue Slime"),
        attack_level=48,
        defence_level=40,
        smithing_level=59,
    )
    assert decision.best is not None
    assert decision.best.style == "crush"
    assert decision.best.weapon.name == "Mithril Mallet"
    assert decision.best.defender is None
    assert decision.best.hit_chance == pytest.approx(0.8610, abs=1e-3)
    assert decision.candidates
    assert decision.candidates[0].key == decision.best.key
    hits = [choice.hit_chance for choice in decision.candidates]
    assert hits == sorted(hits, reverse=True)


def test_blue_slime_craftable_only_choice() -> None:
    decision = choose_melee_style(
        load_database(),
        load_enemies().find("Blue Slime"),
        attack_level=48,
        defence_level=40,
        smithing_level=59,
        craftable_only=True,
    )
    assert decision.best is not None
    assert decision.best.style == "crush"
    assert decision.best.weapon.name == "Mithril Mallet"


def test_toxic_razorfish_prefers_lower_evasion_slash() -> None:
    decision = choose_melee_style(
        load_database(),
        load_enemies().find("Toxic Razorfish"),
        attack_level=48,
        defence_level=40,
        smithing_level=59,
    )
    assert decision.best is not None
    assert decision.best.style == "slash"
    assert decision.best.weapon.name == "Bone Scythe"
    assert decision.best.hit_chance == pytest.approx(0.3237, abs=1e-3)


def test_mangrove_mantis_avoids_marginal_block() -> None:
    decision = choose_melee_style(
        load_database(),
        load_enemies().find("Mangrove Mantis"),
        attack_level=48,
        defence_level=40,
        smithing_level=59,
    )
    assert decision.best is not None
    assert decision.best.style == "slash"
    assert decision.best.weapon.name == "Bone Scythe"
    # Block has the highest raw hit chance but the higher enemy evasion.
    highest = max(decision.choices, key=lambda choice: choice.hit_chance)
    assert highest.style == "block"
    assert highest.enemy_evasion > decision.best.enemy_evasion


def test_block_still_wins_when_it_is_the_clear_choice() -> None:
    decision = choose_melee_style(
        load_database(),
        load_enemies().find("Angry Wasp"),
        attack_level=48,
        defence_level=40,
        smithing_level=59,
    )
    assert decision.best is not None
    assert decision.best.style == "block"
    assert decision.best.weapon.name == "Mithril 2H Sword"


def test_wyvern_recommends_slash() -> None:
    decision = choose_melee_style(
        load_database(),
        load_enemies().find("Wyvern"),
        attack_level=48,
        defence_level=40,
        smithing_level=59,
    )
    assert decision.best is not None
    assert decision.best.style == "slash"
    assert decision.best.weapon.name == "Bone Scythe"


def test_standard_only_still_uses_the_best_style() -> None:
    decision = choose_melee_style(
        load_database(),
        load_enemies().find("Blue Slime"),
        attack_level=48,
        defence_level=40,
        smithing_level=59,
        include_special=False,
    )
    assert decision.best is not None
    assert decision.best.style == "crush"
    assert decision.best.weapon.name == "Mithril Mallet"
