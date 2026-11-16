from __future__ import annotations

import pytest
from helpers import (
    HP_RED,
    make_bank_frame,
    make_combat_frame,
    make_cooking_frame,
    make_fishing_frame,
)
from PIL import Image, ImageDraw

from mi2_aio import ui


def test_normalize_and_to_client_scale() -> None:
    image = ui.normalize(make_combat_frame())
    assert image.size == ui.REFERENCE_SIZE

    assert ui.to_client(0, 0, ui.REFERENCE_SIZE) == (0, 0)
    assert ui.to_client(*ui.STYLE_VALUE_BOX[:2], (1280, 684)) == (
        ui.STYLE_VALUE_BOX[0] // 2,
        ui.STYLE_VALUE_BOX[1] // 2,
    )
    assert ui.from_client(0, 0, ui.REFERENCE_SIZE) == (0, 0)
    assert ui.from_client(640, 342, (1280, 684)) == (
        ui.REFERENCE_SIZE[0] // 2,
        ui.REFERENCE_SIZE[1] // 2,
    )
    assert ui.to_client(*ui.from_client(123, 456, (1920, 1080)), (1920, 1080)) == (
        123,
        456,
    )


@pytest.mark.parametrize("word", ["melee", "ranged", "magic"])
@pytest.mark.parametrize(
    "advantage", ["advantaged", "disadvantaged", "neutral"]
)
def test_read_combat_style(word: str, advantage: str) -> None:
    style = ui.read_combat_style(
        make_combat_frame(word=word, advantage=advantage)
    )
    assert style.word == word
    assert style.advantage == advantage


def test_read_combat_style_without_text() -> None:
    style = ui.read_combat_style(make_combat_frame(word=""))
    assert style.word is None
    assert style.readable is False


@pytest.mark.parametrize(
    "food,expected",
    [("enabled", "enabled"), ("disabled", "disabled"), ("covered", "unknown")],
)
def test_eat_button_state(food: str, expected: str) -> None:
    assert ui.eat_button_state(make_combat_frame(food=food)) == expected


def test_jump_button_ready() -> None:
    assert ui.jump_button_ready(make_combat_frame(jump=True)) is True
    assert ui.jump_button_ready(make_combat_frame(jump=False)) is False


def test_hp_ratio() -> None:
    for ratio in (0.0, 0.25, 0.8, 1.0):
        value = ui.hp_ratio(make_combat_frame(hp=ratio))
        assert value is not None
        assert abs(value - ratio) < 0.03


def test_hp_ratio_without_bar() -> None:
    blank = Image.new("RGB", ui.REFERENCE_SIZE, (30, 30, 30))
    assert ui.hp_ratio(blank) is None


def test_hp_ratio_ignores_red_elements_on_other_pages() -> None:
    image = Image.new("RGB", ui.REFERENCE_SIZE, (32, 32, 34))
    draw = ImageDraw.Draw(image)
    x0, y0, _x1, y1 = ui.HP_BAR_BOX
    for offset in range(0, 700, 140):
        draw.rectangle((x0 + offset, y0 + 4, x0 + offset + 90, y1 - 8), fill=HP_RED)
    assert ui.hp_ratio(image) is None


def test_character_selection_readers() -> None:
    image = Image.new("RGB", ui.REFERENCE_SIZE, (20, 20, 20))
    draw = ImageDraw.Draw(image)
    draw.rectangle(ui.CHARACTER_SELECT_BOX, fill=(50, 140, 50))
    for top in (330, 520):
        draw.rectangle((1640, top, 1750, top + 60), fill=(50, 140, 50))
    assert ui.character_select_open(image) is True
    buttons = ui.character_load_buttons(image)
    assert len(buttons) == 2
    assert buttons[0][1] < buttons[1][1]


def test_game_menu_reader() -> None:
    image = Image.new("RGB", ui.REFERENCE_SIZE, (20, 20, 20))
    draw = ImageDraw.Draw(image)
    draw.rectangle(ui.GAME_MENU_TAB_BOX, fill=(235, 225, 195))
    assert ui.game_menu_open(image) is True
    assert ui.game_menu_open(Image.new("RGB", ui.REFERENCE_SIZE, (20, 20, 20))) is False


def test_modal_confirm_reader() -> None:
    image = Image.new("RGB", ui.REFERENCE_SIZE, (20, 20, 20))
    draw = ImageDraw.Draw(image)
    draw.rectangle((1180, 690, 1390, 750), fill=(1, 97, 1))
    point = ui.modal_confirm_button(image)
    assert point is not None
    assert ui.modal_confirm_visible(image) is True
    assert ui.modal_confirm_visible(
        Image.new("RGB", ui.REFERENCE_SIZE, (20, 20, 20))
    ) is False


def test_region_hash_tracks_changes() -> None:
    first = make_combat_frame(task="Rainbow Slime")
    second = make_combat_frame(task="Goblin")
    same = make_combat_frame(task="Rainbow Slime")
    assert ui.region_hash(first, ui.TASK_NAME_BOX) == ui.region_hash(
        same, ui.TASK_NAME_BOX
    )
    assert ui.region_hash(first, ui.TASK_NAME_BOX) != ui.region_hash(
        second, ui.TASK_NAME_BOX
    )


def test_bank_open_and_first_cell() -> None:
    assert ui.bank_open(make_bank_frame(tab1=True)) is True
    assert ui.bank_open(make_bank_frame(tab1=False)) is False
    assert ui.first_bank_cell_has_item(make_bank_frame(item=True)) is True
    assert ui.first_bank_cell_has_item(make_bank_frame(item=False)) is False


def test_counter_style_cycle() -> None:
    assert ui.COUNTER_STYLE == {
        "melee": "ranged",
        "ranged": "magic",
        "magic": "melee",
    }


def test_fishing_page_readers() -> None:
    idle = make_fishing_frame(running=False, cards=True)
    assert ui.fishing_page_open(idle) is True
    assert ui.fishing_cards_visible(idle) is True
    assert ui.fishing_start_visible(idle) is True
    assert ui.fishing_spot_menu_open(idle) is False

    menu = make_fishing_frame(running=False, cards=True, menu=True)
    assert ui.fishing_spot_menu_open(menu) is True

    fishing = make_fishing_frame(running=True, cards=False)
    assert ui.fishing_page_open(fishing) is True
    assert ui.fishing_cards_visible(fishing) is False
    assert ui.fishing_start_visible(fishing) is False

    # Another page with dark panels must not look like Fishing.
    assert ui.fishing_page_open(make_combat_frame()) is False


def test_cooking_page_and_footer_readers() -> None:
    idle = make_cooking_frame()
    assert ui.cooking_page_open(idle) is True
    footer = ui.cooking_footer(idle)
    assert footer is not None
    assert footer.manage == (1613, 1203)
    assert footer.create == (1604, 1260)
    assert footer.condition == (1530, 1046)
    assert footer.condition_menu == (1530, 1136)
    assert footer.quantity == (1545, 1112)
    assert ui.cooking_stop_panel_open(idle, footer) is False
    assert ui.cooking_stop_item_open(idle, footer) is False
    assert ui.cooking_stop_point(idle) is None

    expanded = make_cooking_frame(expanded=True)
    assert ui.cooking_stop_panel_open(expanded, footer) is True
    assert ui.cooking_stop_item_open(expanded, footer) is True

    active = make_cooking_frame(active=True)
    assert ui.cooking_stop_point(active) == (2129, 1056)

    assert ui.cooking_page_open(make_combat_frame()) is False


def test_cooking_recipe_points() -> None:
    assert ui.cooking_recipe_point(0) == (800, 280)
    assert ui.cooking_recipe_point(9) == (1200, 708)
    assert ui.cooking_recipe_point(13) == (1200, 922)
    with pytest.raises(ui.UiError):
        ui.cooking_recipe_point(26)
    assert ui.PAGE_TARGETS["cooking"] == ui.NAV_COOKING


def test_fishing_click_points() -> None:
    assert ui.fishing_location_point(0) == (438, 240)
    assert ui.fishing_location_point(6) == (2214, 240)
    assert ui.fishing_spot_point(0) == (2070, 486)
    assert ui.fishing_spot_point(2) == (2070, 638)
    with pytest.raises(ui.UiError):
        ui.fishing_location_point(7)
    with pytest.raises(ui.UiError):
        ui.fishing_spot_point(4)
    assert ui.PAGE_TARGETS["fishing"] == ui.NAV_FISHING
