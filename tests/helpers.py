"""Synthetic combat-page frames for tests.

The frames are built at the reference size so the real readers in
:mod:`mi2_aio.ui` can be exercised without a running game.
"""

from __future__ import annotations

import hashlib

import numpy as np
from PIL import Image, ImageDraw

from mi2_aio import ui

BACKGROUND = (32, 32, 34)

STYLE_COLOURS = {
    "disadvantaged": (255, 69, 0),
    "advantaged": (0, 128, 0),
    "neutral": (255, 255, 255),
}

ENABLED_GREEN = (1, 97, 1)
DISABLED_FILL = (25, 9, 9)
COVERED_LIGHT = (210, 210, 210)
HP_RED = (139, 17, 17)
HP_EMPTY = (24, 32, 40)


def _stamp(array: np.ndarray, box: tuple[int, int, int, int], text: str) -> None:
    """Draw a deterministic pattern so different strings hash differently."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    x0, y0, x1, y1 = box
    array[y0:y1, x0:x1] = (24, 24, 26)
    width = x1 - x0 - 4
    height = y1 - y0 - 4
    for index, value in enumerate(digest):
        x = x0 + 2 + (index * 7) % width
        y = y0 + 2 + (index * 5) % height
        array[y, x] = (value, 255 - value, 128)


def _paste_style(array: np.ndarray, word: str, colour: tuple[int, int, int]) -> None:
    template = np.array(
        Image.open(ui.TEMPLATE_DIR / f"style_{word}.png").convert("L")
    ) > 0
    height, width = template.shape
    _x0, y0, x1, _ = ui.STYLE_VALUE_BOX
    x = x1 - 12 - width
    y = y0 + 8
    region = array[y : y + height, x : x + width]
    region[template] = colour


def make_combat_frame(
    *,
    word: str = "melee",
    advantage: str = "disadvantaged",
    task: str = "Rainbow Slime",
    progress: str = "5 / 37",
    food: str = "enabled",
    hp: float = 0.8,
    jump: bool = True,
    ammo: bool = True,
) -> Image.Image:
    image = Image.new("RGB", ui.REFERENCE_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)

    if ammo:
        x0, y0, x1, _ = ui.AMMO_SLOT_BOX
        draw.rectangle((x0 + 20, y0 + 4, x1 - 6, y0 + 22), fill=(250, 250, 250))

    if food == "enabled":
        draw.rectangle(ui.EAT_BUTTON_BOX, fill=ENABLED_GREEN)
    elif food == "disabled":
        draw.rectangle(ui.EAT_BUTTON_BOX, fill=DISABLED_FILL)
    else:
        draw.rectangle(ui.EAT_BUTTON_BOX, fill=COVERED_LIGHT)

    if jump:
        draw.rectangle(ui.JUMP_BUTTON_BOX, fill=ENABLED_GREEN)

    draw.rectangle(ui.RUN_FROM_COMBAT_BOX, fill=(121, 41, 41))

    x0, y0, x1, y1 = ui.HP_BAR_BOX
    draw.rectangle((x0, y0, x1, y1), fill=HP_EMPTY)
    filled = int((x1 - x0) * max(0.0, min(1.0, hp)))
    draw.rectangle((x0, y0, x0 + filled, y1), fill=HP_RED)

    array = np.array(image)
    if word:
        _paste_style(array, word, STYLE_COLOURS[advantage])
    _stamp(array, ui.TASK_NAME_BOX, task)
    _stamp(array, ui.TASK_PROGRESS_BOX, progress)
    return Image.fromarray(array)


def make_bank_frame(*, tab1: bool = True, item: bool = True) -> Image.Image:
    image = Image.new("RGB", ui.REFERENCE_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    if tab1:
        draw.rectangle(ui.BANK_TAB1_BOX, fill=ENABLED_GREEN)
    if item:
        x0, y0, x1, y1 = ui.BANK_FIRST_CELL_BOX
        draw.rectangle((x0 + 10, y0 + 10, x1 - 10, y1 - 10), fill=(220, 120, 40))
    return image


def make_farm_badge_frame(*, badge: bool = True) -> Image.Image:
    image = Image.new("RGB", ui.REFERENCE_SIZE, BACKGROUND)
    if badge:
        draw = ImageDraw.Draw(image)
        x0, y0, x1, y1 = ui.FARM_BADGE_BOX
        draw.ellipse((x0, y0, x1, y1), fill=(230, 60, 60))
    return image


def make_farm_card_frame(
    state: str,
    *,
    card: tuple[int, int] = (140, 239),
    width: int = 446,
    watered: bool = True,
    composted: bool = False,
    plantable: bool = True,
    red_art: bool = False,
) -> Image.Image:
    """Synthetic farming plot card in one of the states the reader recognises.

    The card mimics the real layout: a black header bar (split by the Select
    buttons) and a middle panel holding the action buttons.
    """
    image = Image.new("RGB", ui.REFERENCE_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    x, y = card
    right = x + width

    # Header bar with a thin gap, so the card detector sees the two dark runs
    # that the real page shows around the Select buttons.
    draw.rectangle((x, y, right, y + 45), fill=(8, 8, 8))
    draw.rectangle((x + 200, y + 40, x + 204, y + 45), fill=(70, 70, 70))

    if state == "locked":
        return image

    draw.rectangle((x + 10, y + 10, x + 150, y + 30), fill=(235, 235, 235))

    if state == "purchase":
        # "Purchase to Unlock" card: white label, gold price, brown buy button.
        draw.rectangle(
            (x + 60, y + 165, x + width - 60, y + 185), fill=(240, 240, 240)
        )
        draw.rectangle((x + 60, y + 195, x + 200, y + 215), fill=(230, 190, 60))
        draw.rectangle((x + 120, y + 225, x + 320, y + 260), fill=(120, 90, 60))
        return image

    if state == "locked_title":
        # Level/demo lock: orange "Locked" title, no white control text.
        draw.rectangle((x + 120, y + 195, x + 330, y + 225), fill=(235, 90, 40))
        return image

    if state == "growing":
        draw.rectangle((x + 160, y + 75, x + 290, y + 120), fill=(150, 20, 20))
        draw.rectangle((x + 5, y + 310, x + 90, y + 370), fill=(220, 220, 220))
        if watered:
            draw.rectangle(
                (x + 160, y + 305, x + 280, y + 360),
                outline=(98, 192, 137),
                width=3,
            )
        else:
            # "Hold to Water" button label
            draw.rectangle((x + 220, y + 325, x + 360, y + 345), fill=(245, 245, 245))

    if state == "ready":
        # Teal "Ready to Harvest" title, then the green Harvest button.
        draw.rectangle((x + 140, y + 268, x + 350, y + 296), fill=(93, 183, 131))
        draw.rectangle((x + 120, y + 250, x + 320, y + 330), fill=(1, 97, 1))
        if red_art:
            # Strawberry-like red fruit in the Clear-button region.
            draw.rectangle((x + 160, y + 80, x + 300, y + 120), fill=(200, 30, 30))

    if state == "empty":
        # Empty plots show "Waiting..." near the top of the body.
        draw.rectangle((x + 110, y + 130, x + 250, y + 158), fill=(242, 242, 242))
        # The body's Compost/Plant buttons.
        draw.rectangle(
            (x + 120, y + 275, x + 320, y + 330),
            fill=(1, 97, 1) if plantable else (45, 45, 45),
        )
        if not composted:
            # "Apply Compost" button: dark background, tan bag, white label.
            draw.rectangle((x + 110, y + 165, x + 330, y + 235), fill=(60, 60, 60))
            draw.rectangle((x + 120, y + 180, x + 150, y + 225), fill=(170, 135, 85))
            draw.rectangle((x + 160, y + 195, x + 300, y + 216), fill=(245, 245, 245))
        else:
            # Compost already applied: green "Applied" label, no white button.
            draw.rectangle((x + 150, y + 195, x + 260, y + 216), fill=(0, 170, 60))
    return image

def make_fishing_frame(
    *,
    running: bool = False,
    cards: bool = False,
    menu: bool = False,
) -> Image.Image:
    """Minimal Fishing page: teal Select Spot bar, beige value, buttons."""
    image = Image.new("RGB", ui.REFERENCE_SIZE, (60, 110, 140))
    draw = ImageDraw.Draw(image)
    draw.rectangle(ui.FISH_SPOT_HEADER_BOX, fill=(0, 95, 108))
    draw.rectangle(ui.FISH_SPOT_VALUE_BOX, fill=(206, 189, 158))
    if cards:
        draw.rectangle(ui.FISH_CARDS_BOX, fill=(10, 10, 10))
    if menu:
        draw.rectangle((1860, 455, 2290, 530), fill=(50, 130, 55))
    if not running:
        draw.rectangle(ui.FISH_START_BUTTON_BOX, fill=(30, 140, 40))
    return image


def make_cooking_frame(
    *,
    active: bool = False,
    expanded: bool = False,
) -> Image.Image:
    """Minimal Cooking page: beige headers, footer labels, optional stop."""
    image = Image.new("RGB", ui.REFERENCE_SIZE, (40, 38, 34))
    draw = ImageDraw.Draw(image)
    draw.rectangle(ui.COOK_PAGE_CHOOSE_BOX, fill=(206, 189, 158))
    draw.rectangle(ui.COOK_PAGE_SELECTED_BOX, fill=(206, 189, 158))
    draw.rectangle((1529, 1198, 1698, 1208), fill=(240, 240, 240))
    draw.rectangle((1566, 1254, 1643, 1267), fill=(240, 240, 240))
    if expanded:
        draw.rectangle((1425, 1030, 1660, 1060), fill=(206, 189, 158))
        draw.rectangle((1425, 1059, 1660, 1089), fill=(206, 189, 158))
    if active:
        draw.rectangle((2024, 1039, 2234, 1073), fill=(99, 1, 1))
    return image


def make_mill_frame(
    *, running: bool = True, stock: bool = True, open: bool = True
) -> Image.Image:
    """Synthetic The Mill panel for the mill readers."""
    image = Image.new("RGB", ui.REFERENCE_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)

    if open:
        draw.rectangle(ui.MILL_TOGGLE_BOX, fill=(20, 20, 20))
        draw.rectangle(
            (
                ui.MILL_TOGGLE_BOX[0] + 60,
                ui.MILL_TOGGLE_BOX[1] + 20,
                ui.MILL_TOGGLE_BOX[2] - 60,
                ui.MILL_TOGGLE_BOX[3] - 20,
            ),
            fill=(240, 240, 240),
        )

    colour = (0, 200, 0) if running else (230, 60, 0)
    draw.rectangle(ui.MILL_STATUS_BOX, fill=colour)

    for index, box in enumerate(ui.MILL_ITEM_BARS):
        draw.rectangle(box, fill=(50, 50, 55))
        if stock and index == 0:
            draw.rectangle(
                (box[0], box[1], box[0] + (box[2] - box[0]) // 2, box[3]),
                fill=(143, 144, 147),
            )
    return image
