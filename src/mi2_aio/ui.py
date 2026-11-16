"""Readers for the combat page (combat style, food button, HP bar, task panel).

Melvor Idle 2 renders its UI into the Godot canvas, so everything here works on
captured pixels. Coordinates are for a **2560x1369 client area**; captures are
resized to that reference size first (:func:`normalize`) and click targets are
scaled back with :func:`to_client`. Recalibrate the boxes below if the game's UI
scale or layout changes.

Colour semantics verified against the demo build:

* ``OffensiveStatsContainer`` tints the player's Combat Style green when the
  triangle favours the player, orange-red when it does not, white when neutral
  (``SetLabelStyle`` in the game's source).
* ``CombatFoodView`` disables the Eat button when the selected food is gone.
  A disabled button is dark; a covered button (food picker open) is not, which
  is why :func:`eat_button_state` distinguishes the two.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from .paths import ASSETS_DIR

REFERENCE_SIZE = (2560, 1369)

# --- regions (client pixels at the reference size) -------------------------
STYLE_VALUE_BOX = (690, 396, 843, 424)
# "Attack Stance" value row directly below the combat style.
STANCE_VALUE_BOX = (690, 424, 843, 456)
TASK_NAME_BOX = (645, 1032, 885, 1090)
TASK_PROGRESS_BOX = (645, 1088, 885, 1122)
JUMP_BUTTON_BOX = (660, 1114, 900, 1160)
EAT_BUTTON_BOX = (900, 1215, 1060, 1300)
# Player HP bar on the Combat page. It starts right after the Hitpoints
# level badge and ends at the bar's right border.
HP_BAR_BOX = (146, 141, 952, 181)
# Ammo slot in the equipment panel. A filled slot shows a white quantity;
# an empty one shows only a translucent placeholder.
AMMO_SLOT_BOX = (360, 442, 444, 510)
# "Run from Combat" button on the combat page.
RUN_FROM_COMBAT = (1935, 1265)
RUN_FROM_COMBAT_BOX = (1800, 1238, 2070, 1292)

# --- click targets (client pixels at the reference size) -------------------
# --- page navigation -------------------------------------------------------
NAV_COMBAT = (748, 35)
NAV_BANK = (530, 35)
# Fishing and Cooking live on the skill sidebar (no top navigation tab).
NAV_FISHING = (35, 425)
NAV_COOKING = (35, 487)
PAGE_TARGETS = {
    "combat": NAV_COMBAT,
    "bank": NAV_BANK,
    "fishing": NAV_FISHING,
    "cooking": NAV_COOKING,
}
# Sidebar button that shows the current action's icon and returns to its page
# (tooltip: "Click to return to this page."). It sits under the action timer.
ACTIVE_ACTION_BUTTON = (35, 223)
# Offensive Stats tab in the combat page's middle panel (needed for the style).
COMBAT_STATS_TAB = (546, 280)
JUMP_BUTTON = (780, 1137)
BANK_SEARCH_BOX = (1750, 125)
BANK_FIRST_CELL = (155, 320)
BANK_FIRST_CELL_BOX = (115, 280, 195, 360)
BANK_EQUIP_ROW = (2200, 600)
CURSOR_PARK = (1550, 950)

TEMPLATE_DIR = ASSETS_DIR / "templates"
STYLE_TEMPLATES = ("melee", "ranged", "magic")
STANCE_TEMPLATES = ("slash", "block", "crush")
MATCH_THRESHOLD = 0.72

# Stance buttons in the equipment panel, in the order the game fills its
# stance grid (top-left, top-right, bottom-left, bottom-right).
STANCE_BUTTONS = ((211, 951), (385, 951), (211, 1001), (385, 1001))

STYLES = ("melee", "ranged", "magic")
# The combat triangle: the style that beats each style.
COUNTER_STYLE = {"melee": "ranged", "ranged": "magic", "magic": "melee"}

ADVANTAGED = "advantaged"
DISADVANTAGED = "disadvantaged"
NEUTRAL = "neutral"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class CombatStyle:
    word: str | None
    advantage: str

    @property
    def readable(self) -> bool:
        return self.word is not None


class UiError(RuntimeError):
    """Raised when a UI element cannot be located."""


def normalize(image: Image.Image) -> Image.Image:
    """Resize a client capture to the reference size used by this module."""
    if image.size == REFERENCE_SIZE:
        return image
    return image.resize(REFERENCE_SIZE, Image.Resampling.LANCZOS)


def to_client(x: int, y: int, client_size: tuple[int, int]) -> tuple[int, int]:
    """Scale a reference-space point back to the live client area.

    The result is clamped into the client rectangle. Rounding can otherwise
    return ``width``/``height`` for a point on the last reference pixel, which
    the input layer correctly rejects as outside the window.
    """
    width, height = client_size
    scale_x = width / REFERENCE_SIZE[0]
    scale_y = height / REFERENCE_SIZE[1]
    client_x = int(round(x * scale_x))
    client_y = int(round(y * scale_y))
    if width > 0:
        client_x = min(max(0, client_x), width - 1)
    else:
        client_x = 0
    if height > 0:
        client_y = min(max(0, client_y), height - 1)
    else:
        client_y = 0
    return client_x, client_y


def from_client(x: int, y: int, client_size: tuple[int, int]) -> tuple[int, int]:
    """Convert a live client point to the reference coordinate space."""
    width, height = client_size
    if width <= 0 or height <= 0:
        return (0, 0)
    ref_x = int(round(x * REFERENCE_SIZE[0] / width))
    ref_y = int(round(y * REFERENCE_SIZE[1] / height))
    ref_x = min(max(0, ref_x), REFERENCE_SIZE[0] - 1)
    ref_y = min(max(0, ref_y), REFERENCE_SIZE[1] - 1)
    return ref_x, ref_y



def _text_mask(image: Image.Image, box: tuple[int, int, int, int]) -> np.ndarray:
    """Binary mask of glyph pixels: bright, and not the blue hint icons."""
    array = np.asarray(image.crop(box), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    bright = np.maximum(np.maximum(red, green), blue) > 105
    hint = (blue > 110) & (blue > red + 40)
    return (bright & ~hint).astype(np.float32)


@lru_cache(maxsize=8)
def _template(name: str) -> np.ndarray:
    path = TEMPLATE_DIR / f"style_{name}.png"
    if not path.exists():
        raise UiError(
            f"Missing style template {path}. Re-capture it with "
            "`python -m mi2_aio capture` and crop the combat style value."
        )
    image = Image.open(path).convert("L")
    return (np.asarray(image) > 0).astype(np.float32)


@lru_cache(maxsize=8)
def _stance_template(name: str) -> np.ndarray:
    path = TEMPLATE_DIR / f"stance_{name}.png"
    if not path.exists():
        raise UiError(
            f"Missing stance template {path}. Re-capture it with "
            "`python -m mi2_aio capture` and crop the Attack Stance value."
        )
    image = Image.open(path).convert("L")
    return (np.asarray(image) > 0).astype(np.float32)


def _match(mask: np.ndarray, template: np.ndarray) -> float:
    if mask.shape[0] < template.shape[0] or mask.shape[1] < template.shape[1]:
        return 0.0
    result = cv2.matchTemplate(mask, template, cv2.TM_CCOEFF_NORMED)
    value = float(np.nanmax(result))
    return value if np.isfinite(value) else 0.0


def read_combat_style(image: Image.Image) -> CombatStyle:
    """Read the player's combat style word and whether the triangle favours us."""
    mask = _text_mask(image, STYLE_VALUE_BOX)
    word: str | None = None
    if float(mask.sum()) >= 40:
        scores = {name: _match(mask, _template(name)) for name in STYLE_TEMPLATES}
        best = max(scores, key=scores.get)
        if scores[best] >= MATCH_THRESHOLD:
            word = best

    array = np.asarray(image.crop(STYLE_VALUE_BOX), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    orange = (red > 150) & (green < 110) & (blue < 90) & ((red - green) > 60)
    favoured = (green > 80) & ((green - red) > 40) & ((green - blue) > 40)
    white = (red > 200) & (green > 200) & (blue > 200)
    counts = {
        DISADVANTAGED: int(orange.sum()),
        ADVANTAGED: int(favoured.sum()),
        NEUTRAL: int(white.sum()),
    }
    best_advantage = max(counts, key=counts.get)
    advantage = best_advantage if counts[best_advantage] >= 20 else UNKNOWN
    return CombatStyle(word=word, advantage=advantage)


def read_attack_stance(image: Image.Image) -> str | None:
    """Read the current melee stance (slash/block/crush), if visible."""
    mask = _text_mask(image, STANCE_VALUE_BOX)
    if float(mask.sum()) < 20:
        return None
    scores = {
        name: _match(mask, _stance_template(name)) for name in STANCE_TEMPLATES
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= MATCH_THRESHOLD else None


def stance_button(index: int) -> tuple[int, int]:
    """Click point for a zero-based stance button index."""
    return STANCE_BUTTONS[max(0, min(len(STANCE_BUTTONS) - 1, index))]


def _green_pixels(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    array = np.asarray(image.crop(box), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    green_fill = (green > 60) & ((green - red) > 35) & ((green - blue) > 35)
    return int(green_fill.sum())


def eat_button_state(image: Image.Image) -> str:
    """``enabled`` (green), ``disabled`` (out of food) or ``unknown`` (covered)."""
    if _green_pixels(image, EAT_BUTTON_BOX) > 300:
        return "enabled"
    array = np.asarray(image.crop(EAT_BUTTON_BOX), dtype=np.int16)
    brightness = array.max(axis=2)
    # A disabled button is uniformly dark (max ~90 in the demo). A picker or
    # tooltip covering the button contains bright content instead.
    if int(brightness.max()) <= 110:
        return "disabled"
    return "unknown"


def run_from_combat_ready(image: Image.Image) -> bool:
    """True when the red Run from Combat button is enabled."""
    array = np.asarray(image.crop(RUN_FROM_COMBAT_BOX), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    red_fill = (red > 90) & ((red - green) > 40) & ((red - blue) > 40)
    return int(red_fill.sum()) > 2000


def jump_button_ready(image: Image.Image) -> bool:
    """True when the slayer panel shows an enabled Jump To Enemy button."""
    return _green_pixels(image, JUMP_BUTTON_BOX) > 300


def hp_ratio(image: Image.Image) -> float | None:
    """Fraction of the player's HP bar that is filled, or None if not found.

    The Combat page is the only page with the player HP bar. Requiring a tall
    horizontal band of bar pixels stops red UI elements on other pages (farming
    buttons, labels, ...) from being mistaken for hitpoints.
    """
    array = np.asarray(image.crop(HP_BAR_BOX), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    filled = (red > 100) & (green < 70) & (blue < 70)
    # The empty part of the bar is a dark navy strip; neutral dark UI
    # backgrounds are not blue enough to match.
    empty = (
        (red < 50)
        & (green < 45)
        & (blue < 65)
        & ((blue - red) >= 10)
        & (blue > green)
    )
    bar = filled | empty
    row_fraction = bar.mean(axis=1)

    best_start = 0
    best_length = 0
    current_start = 0
    current_length = 0
    for index, is_bar in enumerate(row_fraction >= 0.8):
        if is_bar:
            if current_length == 0:
                current_start = index
            current_length += 1
            if current_length > best_length:
                best_start = current_start
                best_length = current_length
        else:
            current_length = 0
    # A real bar spans ~twice the minimum; a stray red line does not.
    if best_length < 8:
        return None
    band = slice(best_start, best_start + best_length)
    columns = filled[band].any(axis=0)
    if not columns.any():
        return 0.0
    return float(columns.sum()) / float(columns.size)


def ammo_available(image: Image.Image) -> bool:
    """True when the ammo slot holds a stack (bows cannot fire without it).

    A filled slot shows the item icon plus a white quantity; an empty slot only
    shows a translucent quiver placeholder, so the quantity's near-white pixels
    are the discriminator.
    """
    array = np.asarray(image.crop(AMMO_SLOT_BOX), dtype=np.int16)
    near_white = (array.min(axis=2) > 200)
    return int(near_white.sum()) > 20


def region_hash(image: Image.Image, box: tuple[int, int, int, int]) -> bytes:
    """Stable fingerprint of a static UI region (task name / progress)."""
    crop = image.crop(box).convert("RGB")
    return hashlib.blake2b(crop.tobytes(), digest_size=8).digest()


def first_bank_cell_has_item(image: Image.Image) -> bool:
    """True when the first bank grid cell contains an item icon."""
    return bank_cell_has_item(image, BANK_FIRST_CELL)


# Bank search results are laid out on a fixed reference grid. Scanning more
# than the first cell matters: searching "Leather Cowl" returns the "Leather"
# material first, then the actual cowls.
BANK_GRID_START = (155, 320)
BANK_CELL_STEP = (89, 89)
BANK_GRID_COLUMNS = 10
BANK_GRID_ROWS = 2
BANK_EQUIP_ROW_BOX = (1900, 520, 2500, 640)


def bank_grid_points(limit: int | None = None) -> list[tuple[int, int]]:
    points = [
        (
            BANK_GRID_START[0] + column * BANK_CELL_STEP[0],
            BANK_GRID_START[1] + row * BANK_CELL_STEP[1],
        )
        for row in range(BANK_GRID_ROWS)
        for column in range(BANK_GRID_COLUMNS)
    ]
    return points[:limit] if limit is not None else points


def bank_cell_has_item(image: Image.Image, point: tuple[int, int]) -> bool:
    """True when the grid cell centred on ``point`` contains an item icon."""
    x, y = point
    box = (x - 40, y - 40, x + 40, y + 40)
    array = np.asarray(image.crop(box), dtype=np.int16)
    high = array.max(axis=2)
    low = array.min(axis=2)
    colourful = (high > 90) & ((high - low) > 45)
    # Dark armour icons (leather cowls) are not colourful; their texture still
    # gives the cell a much higher variance than the flat empty background.
    return int(colourful.sum()) > 150 or float(array.var()) > 60.0


def bank_equip_row_visible(image: Image.Image) -> bool:
    """True when the selected bank item shows its "Equip To" row."""
    return _bright_pixels(image, BANK_EQUIP_ROW_BOX, 150) > 300


def bank_selected_item_hash(image: Image.Image) -> bytes:
    """Fingerprint of the selected bank item's icon (panel top-left)."""
    return region_hash(image, (1880, 150, 1975, 240))


# Selected bank item panel: the "Bury Item" section (bank items with the Bury
# capability). The quantity row's "All" button and the "Bury N Bones" action
# row sit at these reference points. Calibrated from the demo's bank panel.
BANK_BURY_ALL = (2505, 403)
BANK_BURY_ROW = (2200, 463)
BANK_BURY_ROW_BOX = (1900, 440, 2500, 490)
# "+N Prayer Points" total under the bury row; green text unique to this panel.
BANK_BURY_GAIN_BOX = (2000, 490, 2300, 520)


def bank_bury_panel_visible(image: Image.Image) -> bool:
    """True when the selected item shows the Bury Item section."""
    return _green_pixels(image, BANK_BURY_GAIN_BOX) > 100


def bank_bury_row_visible(image: Image.Image) -> bool:
    """True when the selected item's bury action row is readable."""
    return (
        bank_bury_panel_visible(image)
        and _bright_pixels(image, BANK_BURY_ROW_BOX, 150) > 200
    )


BANK_TAB1_BOX = (110, 145, 230, 200)


def bank_open(image: Image.Image) -> bool:
    """True when the bank page is showing (its green Tab 1 is visible)."""
    return _green_pixels(image, BANK_TAB1_BOX) > 400


# --- farming page ----------------------------------------------------------
# The farming page is reached from the skill sidebar. The badge on its icon is
# the game's ``Entity.RequiresAttention`` flag, which farming sets when a plot
# is harvestable (``ActiveFarmingCategory.RequiresAttention``).
FARM_ICON = (35, 970)
FARM_BADGE_BOX = (42, 928, 64, 954)
FARM_CATEGORY_TABS = {
    "allotments": (280, 136),
    "herbs": (570, 136),
    "compost": (800, 136),
    "trees": (1050, 136),
    "flowers": (1385, 136),
    "orchard": (1656, 136),
    "mill": (1975, 136),
}

# --- fishing page ----------------------------------------------------------
# The right-hand panel is an unmistakable dark brown card; the scenery behind
# the other skill pages is blue/green, so a brown-pixel ratio is a stable page
# detector that does not depend on text.
FISH_ICON = NAV_FISHING
# The panel's teal "Select Spot" bar plus its solid beige dropdown. The pair is
# unique to the Fishing page, unlike the panel body which shares its brown tone
# with the bank and other dark cards.
FISH_SPOT_HEADER_BOX = (1830, 400, 2320, 416)
FISH_SPOT_VALUE_BOX = (2000, 418, 2240, 446)
FISH_CARDS_BOX = (200, 150, 2500, 340)
FISH_CARDS_MIN_RATIO = 0.5
FISH_LOCATION_BAR = (1300, 119)
FISH_LOCATION_COUNT = 7
FISH_CARD_FIRST_X = 438
FISH_CARD_STEP = 296
FISH_CARD_Y = 240
FISH_SPOT_DROPDOWN = (2220, 431)
FISH_SPOT_ROW_X = 2070
FISH_SPOT_ROW_FIRST_Y = 486
FISH_SPOT_ROW_STEP = 76
FISH_SPOT_ROW_LIMIT = 4
FISH_SPOT_ROWS_BOX = (1850, 455, 2300, 700)
FISH_START_BUTTON = (2070, 878)
FISH_START_BUTTON_BOX = (1830, 845, 2310, 910)


def fishing_page_open(image: Image.Image) -> bool:
    """True when the Fishing page's Select Spot panel is showing.

    Two independent markers are required: the teal bar behind "Select Spot"
    and the solid beige value box below it. Either one alone can appear on
    another page (dark cards, beige item slots), but not both here.
    """
    header = np.asarray(image.crop(FISH_SPOT_HEADER_BOX), dtype=np.int16)
    value = np.asarray(image.crop(FISH_SPOT_VALUE_BOX), dtype=np.int16)
    if header.size == 0 or value.size == 0:
        return False

    red, green, blue = header[..., 0], header[..., 1], header[..., 2]
    teal = (
        (red < 40)
        & (green > 70)
        & (green < 125)
        & (blue > 85)
        & (blue < 145)
    )
    red, green, blue = value[..., 0], value[..., 1], value[..., 2]
    beige = (
        (red > 180)
        & (green > 160)
        & (blue > 130)
        & ((red - blue) > 25)
    )
    return float(teal.mean()) > 0.30 and float(beige.mean()) > 0.30


def fishing_cards_visible(image: Image.Image) -> bool:
    """True when the location card row under the Select Location bar is open."""
    region = np.asarray(image.crop(FISH_CARDS_BOX), dtype=np.uint8)
    if region.size == 0:
        return False
    dark = (region.max(axis=2) < 95)
    return float(dark.mean()) > FISH_CARDS_MIN_RATIO


def fishing_start_visible(image: Image.Image) -> bool:
    """True when the panel shows the green Start Fishing button."""
    return _green_pixels(image, FISH_START_BUTTON_BOX) > 4000


def fishing_spot_menu_open(image: Image.Image) -> bool:
    """True when the Select Spot list is expanded.

    An expanded list highlights the current spot with a wide green row; the
    closed panel only has text and small item icons, so the green area is a
    stable open/closed signal.
    """
    region = np.asarray(image.crop(FISH_SPOT_ROWS_BOX), dtype=np.int16)
    if region.size == 0:
        return False
    red, green, blue = region[..., 0], region[..., 1], region[..., 2]
    highlighted = (green > 60) & (green > red + 18) & (green > blue + 18)
    return int(highlighted.sum()) > 5000


def fishing_location_point(index: int) -> tuple[int, int]:
    """Reference-space click point for a location card (data order)."""
    if not 0 <= index < FISH_LOCATION_COUNT:
        raise UiError(
            f"Fishing location index {index} is outside 0-"
            f"{FISH_LOCATION_COUNT - 1}."
        )
    return (FISH_CARD_FIRST_X + FISH_CARD_STEP * index, FISH_CARD_Y)


def fishing_spot_point(index: int) -> tuple[int, int]:
    """Reference-space click point for a row of the open Select Spot menu."""
    if not 0 <= index < FISH_SPOT_ROW_LIMIT:
        raise UiError(
            f"Fishing spot row {index} is outside 0-{FISH_SPOT_ROW_LIMIT - 1}."
        )
    return (
        FISH_SPOT_ROW_X,
        FISH_SPOT_ROW_FIRST_Y + FISH_SPOT_ROW_STEP * index,
    )


# --- cooking page ----------------------------------------------------------
# Cooking uses the same skilling layout as Fletching: a recipe grid on the left,
# a Selected panel in the middle and a Creating panel on the right. Two beige
# ribbons ("Choose Recipe" and "Selected") make a stable page detector.
COOK_ICON = NAV_COOKING
COOK_PAGE_CHOOSE_BOX = (880, 85, 1070, 120)
COOK_PAGE_SELECTED_BOX = (1510, 85, 1700, 120)
COOK_BASIC_FOOD = (419, 251)
COOK_GRID_X = (800, 1200)
COOK_GRID_FIRST_Y = 280
COOK_GRID_STEP_Y = 107
COOK_GRID_SLOTS = 26
COOK_FOOTER_BOX = (1450, 950, 1760, 1345)
COOK_STOP_BUTTON_BOX = (1900, 950, 2260, 1150)
COOK_STOP_VALUE_DY = 157
COOK_STOP_ITEM_DY = 128
COOK_STOP_QUANTITY_DY = 91
COOK_STOP_MENU_DY = 67
COOK_STOP_CONDITION_X = 1530
COOK_STOP_QUANTITY_X = 1545


def _beige_pixels(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    array = np.asarray(image.crop(box), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    beige = (
        (red > 180)
        & (green > 170)
        & (blue > 140)
        & ((red - blue) > 25)
    )
    return int(beige.sum())


def cooking_page_open(image: Image.Image) -> bool:
    """True when the Cooking page's Choose Recipe/Selected panels are showing."""
    return (
        _beige_pixels(image, COOK_PAGE_CHOOSE_BOX) > 1000
        and _beige_pixels(image, COOK_PAGE_SELECTED_BOX) > 1000
    )


@dataclass(frozen=True)
class CookingFooter:
    """The Selected panel's fixed footer (Manage Stop Conditions + Create)."""

    manage: tuple[int, int]
    create: tuple[int, int]

    @property
    def condition(self) -> tuple[int, int]:
        return (COOK_STOP_CONDITION_X, self.manage[1] - COOK_STOP_VALUE_DY)

    @property
    def condition_menu(self) -> tuple[int, int]:
        """The "Products Gained" row of the open condition menu."""
        return (COOK_STOP_CONDITION_X, self.manage[1] - COOK_STOP_MENU_DY)

    @property
    def item(self) -> tuple[int, int]:
        return (COOK_STOP_CONDITION_X, self.manage[1] - COOK_STOP_ITEM_DY)

    @property
    def quantity(self) -> tuple[int, int]:
        return (COOK_STOP_QUANTITY_X, self.manage[1] - COOK_STOP_QUANTITY_DY)


def cooking_footer(image: Image.Image) -> CookingFooter | None:
    """Locate the Manage Stop Conditions and Create rows.

    The footer sits at the bottom of the scrollable Selected panel, so its
    absolute position changes with the scroll. Both labels are bright text; the
    last two text bands are Manage Stop Conditions and Create.
    """
    box = COOK_FOOTER_BOX
    array = np.asarray(image.crop(box), dtype=np.int16)
    bright = array.min(axis=2) > 140
    rows = [
        (y, int(bright[y].sum()))
        for y in range(bright.shape[0])
        if bright[y].sum() > 20
    ]
    bands: list[list[int]] = []
    for y, _count in rows:
        if bands and y - bands[-1][-1] <= 3:
            bands[-1].append(y)
        else:
            bands.append([y])
    if len(bands) < 2:
        return None
    points: list[tuple[int, int]] = []
    for band in bands[-2:]:
        top, bottom = band[0], band[-1]
        columns = bright[top : bottom + 1].any(axis=0)
        xs = np.where(columns)[0]
        if xs.size == 0:
            return None
        points.append(
            (box[0] + int(xs.min() + xs.max()) // 2, box[1] + (top + bottom) // 2)
        )
    return CookingFooter(manage=points[0], create=points[1])


def cooking_stop_panel_open(image: Image.Image, footer: CookingFooter) -> bool:
    """True when the stop-condition foldable is expanded."""
    y = footer.manage[1]
    box = (1425, y - COOK_STOP_VALUE_DY - 16, 1660, y - COOK_STOP_VALUE_DY + 14)
    return _beige_pixels(image, box) > 300


def cooking_stop_item_open(image: Image.Image, footer: CookingFooter) -> bool:
    """True when the condition's Item row is visible (a condition is set)."""
    y = footer.manage[1]
    box = (1425, y - COOK_STOP_ITEM_DY - 16, 1660, y - COOK_STOP_ITEM_DY + 14)
    return _beige_pixels(image, box) > 300


def cooking_recipe_point(slot: int) -> tuple[int, int]:
    """Reference-space click point for a recipe grid slot (row-major)."""
    if not 0 <= slot < COOK_GRID_SLOTS:
        raise UiError(f"Cooking grid slot {slot} is outside 0-{COOK_GRID_SLOTS - 1}.")
    row, column = divmod(slot, 2)
    return (COOK_GRID_X[column], COOK_GRID_FIRST_Y + row * COOK_GRID_STEP_Y)


def cooking_stop_point(image: Image.Image) -> tuple[int, int] | None:
    """Centre of the red Stop button in the Creating panel, if showing."""
    box = COOK_STOP_BUTTON_BOX
    array = np.asarray(image.crop(box), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    mask = (
        (red > 80)
        & (green < 55)
        & (blue < 55)
        & (red > 2 * green + 20)
    ).astype(np.uint8)
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        fill = area / (width * height) if width * height else 0.0
        if area < 3000 or width < 120 or height < 20 or fill < 0.6:
            continue
        if best is None or area > best[0]:
            best = (area, index)
    if best is None:
        return None
    return (
        box[0] + int(centroids[best[1]][0]),
        box[1] + int(centroids[best[1]][1]),
    )


# --- the mill building -----------------------------------------------------
MILL_PANEL_BUTTON = (2400, 140)
MILL_STATUS_BOX = (2340, 110, 2530, 155)
MILL_TOGGLE = (1468, 1083)
MILL_TOGGLE_BOX = (1339, 1050, 1614, 1121)
MILL_DEPOSIT_BUTTONS = ((1420, 460), (1919, 460), (1420, 614), (1919, 614))
# Inventory bars for Wheat, Sugarcane, Corn and Flax.
MILL_ITEM_BARS = (
    (1090, 405, 1290, 435),
    (1540, 405, 1740, 435),
    (1090, 562, 1290, 588),
    (1540, 562, 1740, 588),
)
# Cards are laid out by the game as a 5x2 grid, but the exact origin and width
# depend on the page layout (it shifted after more plots were unlocked), so the
# grid is detected from the black header bars each time.
FARM_CARD_HEIGHT = 440
FARM_ROW_OFFSET = 450

# Offsets inside a card, relative to its top-left corner (the header bar).
FARM_PRODUCT_BOX = (0, 0, 0, 50)  # width replaced per card
FARM_CLEAR_BOX = (130, 70, 0, 130)
FARM_PANEL_BOX = (60, 130, 0, 350)
FARM_COMPOST_BOX = (80, 150, 0, 240)
FARM_ACTION_BOX = (60, 240, 0, 345)
FARM_WATER_BOX = (150, 295, 400, 385)
FARM_TIMER_BOX = (0, 300, 220, 380)
# Empty plots show "Waiting..." near the top of the body. Ready/growing cards
# do not, so this is the reliable empty-state signal (the header's
# "Compost: ... Select" row is always present and is not a state).
FARM_EMPTY_TITLE_BOX = (100, 120, 350, 175)
# The empty plot has no plant art in this upper-body region. Growing crops do,
# which is how white flowers are kept from looking like the "Waiting..." title.
FARM_PLANT_ART_BOX = (0, 60, 0, 190)
# "Ready to Harvest" is teal text in the lower panel. It is checked before the
# red Clear button because red crop art (strawberries) can look like Clear.
FARM_READY_TITLE_BOX = (100, 260, 380, 300)
# The Plant button is green when it can be used and dark when the plot has no
# seed/product ("Not enough Seeds." / "No Product selected.").
FARM_PLANT_BUTTON_BOX = (120, 275, 320, 330)
# Unpurchased plot: white "Purchase to Unlock" text and a gold price line.
FARM_PURCHASE_BOX = (60, 160, 0, 245)
# Level/demo locked plot: orange "Locked" title and requirement line, no white
# control text. Growing/empty plots always carry white text in this band.
FARM_LOCKED_TITLE_BOX = (60, 185, 0, 245)


@dataclass(frozen=True)
class FarmCard:
    x: int
    y: int
    width: int
    height: int = FARM_CARD_HEIGHT

    def box(self, offset: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = offset
        if x1 == 0:
            x1 = self.width - 30
        return (self.x + x0, self.y + y0, self.x + x1, self.y + y1)

    @property
    def header(self) -> tuple[int, int, int, int]:
        return self.box((0, 0, self.width, 50))


def farming_badge(image: Image.Image) -> bool:
    """True when the farming skill icon shows the red attention badge."""
    array = np.asarray(image.crop(FARM_BADGE_BOX), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    badge = (red > 150) & (green < 100) & (blue < 100)
    return int(badge.sum()) > 25


def _dark_runs(image: Image.Image, y: int) -> list[tuple[int, int]]:
    row = np.asarray(image.crop((60, y, 2560, y + 1)), dtype=np.int16)[0]
    dark = row.max(axis=1) < 30
    runs: list[tuple[int, int]] = []
    start = None
    for index, value in enumerate(dark):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index - start > 40:
                runs.append((start + 60, index + 60))
            start = None
    if start is not None:
        runs.append((start + 60, 2560))
    return runs


def _paired_runs(
    runs: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Pair the two header runs of each card (left label + right label)."""
    pairs: list[tuple[int, int]] = []
    index = 0
    while index + 1 < len(runs):
        first, second = runs[index], runs[index + 1]
        gap = second[0] - first[1]
        offset = second[0] - first[0]
        if gap < 30 and 150 <= offset <= 280:
            pairs.append((first[0], second[1] - first[0]))
            index += 2
        else:
            index += 1
    return pairs


def _header_band(image: Image.Image, y_min: int = 230, y_max: int = 300) -> int | None:
    """Y of the plot header row that yields the most complete card pairs."""
    best_y = None
    best_count = 0
    for y in range(y_min, y_max):
        count = len(_paired_runs(_dark_runs(image, y)))
        if count > best_count:
            best_count = count
            best_y = y
    return best_y if best_count >= 1 else None


def _header_spans(image: Image.Image, y: int) -> list[tuple[int, int]]:
    """Card (left, width) pairs from the header bar row."""
    return _paired_runs(_dark_runs(image, y))


def farm_cards(image: Image.Image) -> list[FarmCard]:
    """Detect the active plot cards (first row) on the farming page.

    The second row is left alone: in the demo it holds locked/purchasable cards
    whose "Hold to Buy Plot" button must never be clicked by the bot.
    """
    band = _header_band(image, 230, 300)
    if band is None:
        return []
    return [
        FarmCard(left, band - 40, width)
        for left, width in _header_spans(image, band)
    ]


def farming_page_open(image: Image.Image) -> bool:
    """True when the farming page is showing with its plots visible.

    Requires the green category tabs too, so a skill page whose cards happen to
    look similar (woodcutting, mining, ...) is never serviced as a farm.
    """
    if not farming_tabs_visible(image):
        return False
    cards = farm_cards(image)
    return bool(cards) and _card_has_product_header(image, cards[0])


FARM_TABS_BOX = (100, 90, 2100, 200)
FARM_BUILDINGS_BOX = (2200, 90, 2540, 200)


def farming_tabs_visible(image: Image.Image) -> bool:
    """True when the farming page's category bar is on screen.

    The bar carries green tabs across the top (even when the active category is
    on the right), and the farm page also shows the bright "Farm Buildings /
    The Mill" panel at the top right. Other skill pages have neither, so the two
    signals together reject mining/fishing pages that also contain green.
    """
    return (
        _green_pixels(image, FARM_TABS_BOX) > 3000
        and _bright_pixels(image, FARM_BUILDINGS_BOX, 200) > 100
    )


def _bright_pixels(image: Image.Image, box, threshold: int = 150) -> int:
    array = np.asarray(image.crop(box), dtype=np.int16)
    return int((array.max(axis=2) > threshold).sum())


def _red_pixels(image: Image.Image, box) -> int:
    array = np.asarray(image.crop(box), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    return int(((red > 120) & (green < 80) & (blue < 80)).sum())


def _card_has_product_header(image: Image.Image, card: FarmCard) -> bool:
    return _bright_pixels(image, card.header, 170) > 120


def card_clear_button(image: Image.Image, card: FarmCard) -> bool:
    """A red Clear button means the plot is growing (not ready to harvest)."""
    return _red_pixels(image, card.box(FARM_CLEAR_BOX)) > 120


def card_timer(image: Image.Image, card: FarmCard) -> bool:
    """Growth timer text is present while the crop is growing."""
    return _bright_pixels(image, card.box(FARM_TIMER_BOX), 160) > 60


def card_watered(image: Image.Image, card: FarmCard) -> bool:
    """The teal "Watered" badge sits next to the timer."""
    array = np.asarray(image.crop(card.box(FARM_WATER_BOX)), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    teal = (
        (np.abs(red - 98) < 50)
        & (np.abs(green - 192) < 50)
        & (np.abs(blue - 137) < 50)
    )
    return int(teal.sum()) > 30


def card_not_watered(image: Image.Image, card: FarmCard) -> bool:
    """The white "Hold to Water" button is shown when the crop needs water."""
    array = np.asarray(image.crop(card.box(FARM_WATER_BOX)), dtype=np.int16)
    near_white = array.min(axis=2) > 200
    return int(near_white.sum()) > 80


def _brown_blobs(
    image: Image.Image, box
) -> list[tuple[int, int, int]]:
    """Tan/brown regions (compost bag icon) as (x, y, area) centres."""
    array = np.asarray(image.crop(box), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    mask = (
        (red > 120)
        & (green > 80)
        & (blue < 130)
        & ((red - blue) > 35)
    ).astype(np.uint8)
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=4
    )
    blobs: list[tuple[int, int, int]] = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 80:
            continue
        cx, cy = centroids[index]
        blobs.append((int(box[0] + cx), int(box[1] + cy), area))
    return sorted(blobs, key=lambda item: item[2], reverse=True)


def card_purchase(image: Image.Image, card: FarmCard) -> bool:
    """True for an unowned plot card ("Purchase to Unlock" + gold price)."""
    array = np.asarray(
        image.crop(card.box(FARM_PURCHASE_BOX)), dtype=np.int16
    )
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    white = int((array.min(axis=2) > 200).sum())
    gold = int(((red > 180) & (green > 140) & (blue < 110)).sum())
    return white > 200 and gold > 300


def card_locked_title(image: Image.Image, card: FarmCard) -> bool:
    """True when the card shows the orange Locked title (level/demo lock)."""
    array = np.asarray(
        image.crop(card.box(FARM_LOCKED_TITLE_BOX)), dtype=np.int16
    )
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    white = int((array.min(axis=2) > 200).sum())
    orange = int(
        (
            (red > 150)
            & (green > 40)
            & (green < 160)
            & (blue < 90)
            & ((red - green) > 40)
        ).sum()
    )
    return white < 100 and orange > 300


def card_empty(image: Image.Image, card: FarmCard) -> bool:
    """True when the plot body shows the empty state's "Waiting..." title.

    White crop art (strawberry flowers) can also be near-white, so the empty
    state additionally requires the dark empty panel and no plant art in the
    upper body.
    """
    title = np.asarray(
        image.crop(card.box(FARM_EMPTY_TITLE_BOX)), dtype=np.int16
    )
    near_white = title.min(axis=2) > 200
    if int(near_white.sum()) < 150:
        return False
    dark = title.max(axis=2) < 70
    if int(dark.sum()) < 6000:
        return False

    body = np.asarray(image.crop(card.box(FARM_PLANT_ART_BOX)), dtype=np.int16)
    green = (
        (body[..., 1] > 80)
        & ((body[..., 1] - body[..., 0]) > 30)
        & ((body[..., 1] - body[..., 2]) > 30)
    )
    return int(green.sum()) < 1500


def card_ready(image: Image.Image, card: FarmCard) -> bool:
    """True when the plot shows the teal "Ready to Harvest" title.

    Red crop art (for example strawberries) can trigger the red Clear-button
    detector, so this title is checked first to keep regrowing ready plots out
    of the growing branch.
    """
    array = np.asarray(image.crop(card.box(FARM_READY_TITLE_BOX)), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    teal = (
        (green > 110)
        & (blue > 95)
        & (red < 125)
        & ((green - red) > 30)
        & ((blue - red) > 20)
    )
    return int(teal.sum()) > 300


def card_plant_ready(image: Image.Image, card: FarmCard) -> bool:
    """True when the empty plot's green Plant button is enabled.

    A blocked plot (no seeds or no product selected) draws the button dark and
    shows an orange error below it, so the green fill is the discriminator.
    """
    array = np.asarray(image.crop(card.box(FARM_PLANT_BUTTON_BOX)), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    green_fill = (green > 60) & ((green - red) > 35) & ((green - blue) > 35)
    return int(green_fill.sum()) > 1000


def card_compost_button(image: Image.Image, card: FarmCard) -> bool:
    """True when an empty plot shows the body's "Apply Compost" button.

    The "Compost: ... Select" row in the card header is always present (it
    chooses which compost to use), so it must not be used as a state signal.
    The body button has white "Apply Compost" text and a tan bag icon; ready and
    growing cards have neither in this region. A plot that already has compost
    applied shows a green "Applied" label instead, which is excluded by
    requiring the white text to extend below the top edge of the region.
    """
    box = card.box(FARM_COMPOST_BOX)
    array = np.asarray(image.crop(box), dtype=np.int16)
    near_white = array.min(axis=2) > 200
    rows, _cols = np.where(near_white)
    if rows.size < 120:
        return False
    if int((rows > 15).sum()) < 80:
        return False
    return bool(_brown_blobs(image, box))


def _green_blobs(
    image: Image.Image, box
) -> list[tuple[int, int, int, int, int, int, int]]:
    """Green filled regions (buttons) as absolute (cx, cy, area, x, y, w, h)."""
    array = np.asarray(image.crop(box), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    mask = (green > 60) & ((green - red) > 35) & ((green - blue) > 35)
    mask = mask.astype(np.uint8)
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=4
    )
    blobs: list[tuple[int, int, int, int, int, int, int]] = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 400:
            continue
        cx, cy = centroids[index]
        x = int(stats[index, cv2.CC_STAT_LEFT]) + box[0]
        y = int(stats[index, cv2.CC_STAT_TOP]) + box[1]
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        blobs.append(
            (int(box[0] + cx), int(box[1] + cy), area, x, y, width, height)
        )
    return sorted(blobs, key=lambda item: item[2], reverse=True)


def card_action_button(
    image: Image.Image, card: FarmCard
) -> tuple[int, int] | None:
    """Centre of the primary (green) button in the plot card, if any.

    The grown plant/crop icon is also green, so the search prefers the largest
    green region in the lower half of the panel (where Plant/Harvest sit) and
    falls back to the largest region overall. The click point is then refined
    to the white button label inside that region, so a crop icon that touches
    the button cannot pull the click onto the icon.
    """
    box = card.box(FARM_ACTION_BOX)
    blobs = _green_blobs(image, box)
    if not blobs:
        return None
    middle = (box[1] + box[3]) / 2.0
    lower = [blob for blob in blobs if blob[1] > middle]
    chosen = max(lower, key=lambda blob: blob[2]) if lower else blobs[0]
    _cx, _cy, _area, left, top, width, height = chosen
    label_box = (left, top, left + width, top + height)
    if label_box[2] > label_box[0] and label_box[3] > label_box[1]:
        array = np.asarray(image.crop(label_box), dtype=np.int16)
        near_white = array.min(axis=2) > 200
        ys, xs = np.where(near_white)
        if len(xs) >= 20:
            return (
                label_box[0] + int(xs.mean()),
                label_box[1] + int(ys.mean()),
            )
    return chosen[0], chosen[1]


def card_compost_point(image: Image.Image, card: FarmCard) -> tuple[int, int]:
    """Centre of the Apply Compost button (bag icon + text)."""
    blobs = _brown_blobs(image, card.box(FARM_COMPOST_BOX))
    if blobs:
        return blobs[0][0] + 85, blobs[0][1]
    box = card.box(FARM_COMPOST_BOX)
    return (box[0] + box[2]) // 2, (box[1] + box[3]) // 2


FARM_COMPOST_SELECT_POINT = (410, 29)
FARM_COMPOST_PICKER_BOX = (60, 60, 400, 125)
# The three compost items in the picker, card-relative. Slot 1 is Fertiliser in
# the demo; slot 2 is Compost; slot 3 is the third compost.
FARM_COMPOST_PICKER_SLOTS = ((112, 175), (212, 175), (312, 175))


def card_compost_select_point(card: FarmCard) -> tuple[int, int]:
    """The header's Compost "Select" button (opens the compost picker)."""
    return (
        card.x + FARM_COMPOST_SELECT_POINT[0],
        card.y + FARM_COMPOST_SELECT_POINT[1],
    )


def card_compost_picker_open(image: Image.Image, card: FarmCard) -> bool:
    """True when the compost picker overlay is open in this card."""
    array = np.asarray(
        image.crop(card.box(FARM_COMPOST_PICKER_BOX)), dtype=np.int16
    )
    return int((array.min(axis=2) > 200).sum()) > 150


def card_compost_picker_point(
    card: FarmCard, slot: int
) -> tuple[int, int]:
    """Click point of a compost item in the picker (1-based slot)."""
    index = max(0, min(len(FARM_COMPOST_PICKER_SLOTS) - 1, slot - 1))
    dx, dy = FARM_COMPOST_PICKER_SLOTS[index]
    return (card.x + dx, card.y + dy)


def card_water_point(image: Image.Image, card: FarmCard) -> tuple[int, int]:
    """Centre of the "Hold to Water" label (or the right of the watering row)."""
    box = card.box(FARM_WATER_BOX)
    array = np.asarray(image.crop(box), dtype=np.int16)
    white = array.min(axis=2) > 200
    ys, xs = np.where(white)
    if len(xs):
        return box[0] + int(xs.mean()), box[1] + int(ys.mean())
    return box[0] + int((box[2] - box[0]) * 0.7), (box[1] + box[3]) // 2


# --- combat area / dungeon menu -------------------------------------------
# Combat page -> Select Area opens a full-screen menu.
AREA_PROMPT = (1470, 1030)  # "Select an Area to get started"
AREA_BUTTON = (1510, 1258)  # current area button in the bottom bar
# Bone farming: Combat Areas tab -> Corrupted Farmlands -> Giant Chicken's
# Fight button. Giant Chicken always drops a Big Bone (6 Prayer points).
BONE_FARM_AREA_TAB = (1025, 197)
BONE_FARM_AREA_ROW = (318, 535)
BONE_FARM_FIGHT = (2276, 668)
DUNGEON_TAB = (1715, 190)  # "Standard Dungeons" category
START_DUNGEON = (1092, 342)
VIEW_REWARDS = (837, 340)
REWARDS_CLOSE = (1315, 839)
MENU_CLOSE = (2420, 180)
MENU_CLOSE_BOX = (2400, 150, 2470, 215)
DUNGEON_PROGRESS_BOX = (2250, 80, 2520, 112)
DUNGEON_LIST_BOX = (200, 250, 800, 950)

# --- game menu / character selection ---------------------------------------
GAME_MENU_BUTTON = (2510, 20)  # hamburger in the top-right corner
GAME_MENU_TAB_BOX = (1190, 310, 1370, 365)  # beige "Menu" tab
GAME_MENU_EXIT = (1280, 850)  # "Save and Exit to Main Menu"
CHARACTER_SELECT_BOX = (798, 201, 1608, 259)  # green CREATE NEW CHARACTER bar
CHARACTER_LOAD_BOX = (1600, 280, 1780, 1150)  # green Load buttons
# "Welcome Back!" / results screen confirm button; the vertical position
# depends on the amount of saved-up progress, so detect it dynamically.
MODAL_CONFIRM_BOX = (1100, 400, 1460, 1320)


def area_menu_open(image: Image.Image) -> bool:
    """True when the combat area/dungeon selection menu is showing.

    Keyed on the white X of the menu's close button. The combat page has no
    white pixels in that region, and the menu's close button is always present
    (even before a dungeon is selected, when the Start Dungeon button is not).
    """
    array = np.asarray(image.crop(MENU_CLOSE_BOX), dtype=np.int16)
    bright = array.min(axis=2) > 200
    return int(bright.sum()) > 100


def dungeon_active(image: Image.Image) -> bool:
    """True when the "Dungeon Progress" label is on screen."""
    array = np.asarray(image.crop(DUNGEON_PROGRESS_BOX), dtype=np.int16)
    bright = array.min(axis=2) > 150
    return int(bright.sum()) > 80


def find_dungeon_row(
    image: Image.Image, template: np.ndarray
) -> tuple[int, int] | None:
    """Locate a dungeon name in the Standard Dungeons list (mask matching)."""
    box = DUNGEON_LIST_BOX
    search = np.asarray(image.crop(box), dtype=np.int16)
    mask = (search.min(axis=2) > 150).astype(np.float32)
    if mask.sum() < 50:
        return None
    result = cv2.matchTemplate(mask, template.astype(np.float32), cv2.TM_CCOEFF_NORMED)
    _min_v, max_v, _min_loc, max_loc = cv2.minMaxLoc(result)
    if max_v < 0.72:
        return None
    height, width = template.shape[:2]
    return box[0] + max_loc[0] + width // 2, box[1] + max_loc[1] + height // 2


def game_menu_open(image: Image.Image) -> bool:
    """True when the in-game hamburger menu is showing."""
    array = np.asarray(image.crop(GAME_MENU_TAB_BOX), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    beige = (red > 180) & (green > 170) & (blue > 120)
    return int(beige.sum()) > 1500


def modal_confirm_button(image: Image.Image) -> tuple[int, int] | None:
    """Centre of the largest green confirm button in the modal area."""
    box = MODAL_CONFIRM_BOX
    search = np.asarray(image.crop(box), dtype=np.int16)
    red, green, blue = search[..., 0], search[..., 1], search[..., 2]
    mask = (
        (green > 80)
        & (red < 60)
        & (blue < 60)
        & ((green - red) > 40)
        & ((green - blue) > 40)
    ).astype(np.uint8)
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, 8
    )
    best = None
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < 3000 or width < 80 or height < 25:
            continue
        if best is None or area > best[0]:
            best = (area, index)
    if best is None:
        return None
    index = best[1]
    return (
        box[0] + int(centroids[index][0]),
        box[1] + int(centroids[index][1]),
    )


def modal_confirm_visible(image: Image.Image) -> bool:
    """True when the bottom-centre green Confirm button is showing."""
    return modal_confirm_button(image) is not None


def character_select_open(image: Image.Image) -> bool:
    """True when the Melvor character-selection screen is showing."""
    array = np.asarray(image.crop(CHARACTER_SELECT_BOX), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    green_fill = (green > 80) & ((green - red) > 30) & ((green - blue) > 30)
    return int(green_fill.sum()) > 20000


def character_load_buttons(image: Image.Image) -> list[tuple[int, int]]:
    """Centres of the visible green Load buttons, top to bottom."""
    box = CHARACTER_LOAD_BOX
    search = np.asarray(image.crop(box), dtype=np.int16)
    red, green, blue = search[..., 0], search[..., 1], search[..., 2]
    mask = (
        (green > 80) & ((green - red) > 30) & ((green - blue) > 30)
    ).astype(np.uint8)
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, 8
    )
    buttons: list[tuple[int, int]] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < 3000 or width < 80 or height < 30:
            continue
        buttons.append(
            (
                box[0] + int(centroids[index][0]),
                box[1] + int(centroids[index][1]),
            )
        )
    buttons.sort(key=lambda point: point[1])
    return buttons


def card_state(image: Image.Image, card: FarmCard) -> str:
    """Classify a farming plot card: locked, growing, ready, empty or unknown."""
    if not _card_has_product_header(image, card):
        return "locked"
    if card_purchase(image, card):
        return "locked"
    if card_empty(image, card):
        return "empty"
    # Ready must come before the red Clear check: regrowing crops (strawberries)
    # can contain enough red art to look like a Clear button.
    if card_ready(image, card):
        return "ready"
    if card_locked_title(image, card):
        return "locked"
    if card_clear_button(image, card):
        return "growing"
    if (
        card_timer(image, card)
        or card_watered(image, card)
        or card_not_watered(image, card)
    ):
        return "growing"
    if card_action_button(image, card) is None:
        return "unknown"
    return "ready"


# --- the mill --------------------------------------------------------------
def mill_open(image: Image.Image) -> bool:
    """True when The Mill panel is showing (its Toggle Grain Mill label)."""
    return _bright_pixels(image, MILL_TOGGLE_BOX, 200) > 200


def mill_status(image: Image.Image) -> str:
    """``running`` (green label), ``stopped`` (orange-red) or ``unknown``."""
    array = np.asarray(image.crop(MILL_STATUS_BOX), dtype=np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    running = (green > 90) & ((green - red) > 40) & ((green - blue) > 40)
    stopped = (red > 150) & (green < 110) & (blue < 90) & ((red - green) > 60)
    if int(running.sum()) > 100:
        return "running"
    if int(stopped.sum()) > 100:
        return "stopped"
    return "unknown"


def mill_item_fill(image: Image.Image) -> float:
    """Largest contiguous fill run of the four mill storage bars (0.0 - 1.0)."""
    best = 0.0
    for box in MILL_ITEM_BARS:
        array = np.asarray(image.crop(box), dtype=np.int16)
        red, green, blue = array[..., 0], array[..., 1], array[..., 2]
        # The fill is a mid grey (~143); the empty track is darker and the
        # percentage label is white, so neither is counted.
        fill = (
            (np.abs(red - 143) < 16)
            & (np.abs(green - 144) < 16)
            & (np.abs(blue - 147) < 16)
        )
        columns = fill.any(axis=0)
        longest = current = 0
        for value in columns:
            current = current + 1 if value else 0
            longest = max(longest, current)
        if columns.size:
            best = max(best, float(longest) / float(columns.size))
    return best


# --- previous action restore ------------------------------------------------
# The game's skill page shows the skill artwork both in the page header and as
# the sidebar button, and the active action's name in a teal banner. Capturing
# those two elements at run start is enough to find the same action later,
# without OCR and without hardcoding a page/action registry.
PAGE_HEADER_ICON_BOX = (700, 0, 1500, 90)
# The sidebar's active-action button sits at the top (~y 223) and shows the
# same skill icon as the page header, so the page-icon search starts below it.
SIDEBAR_ICON_BOX = (0, 270, 90, 1369)
ACTIVE_PANEL_BOX = (1700, 700, 2560, 1250)
RESTORE_GRID_BOX = (240, 150, 1750, 1369)
RESTORE_ICON_MIN_SCORE = 0.55
RESTORE_TITLE_MIN_SCORE = 0.65


def find_page_icon(image: Image.Image) -> tuple[int, int] | None:
    """Find the sidebar button of the page shown in the header.

    The page header renders the skill artwork at a larger size than the
    sidebar, so the header icon is cropped and matched against the sidebar at
    several scales. Returns a reference-space click point inside the sidebar
    icon, or None when the header has no recognizable icon.
    """
    header = np.asarray(image.crop(PAGE_HEADER_ICON_BOX), dtype=np.uint8)
    hsv = cv2.cvtColor(header, cv2.COLOR_RGB2HSV)
    colorful = ((hsv[..., 1] > 90) & (hsv[..., 2] > 80)).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        colorful, 8
    )
    best: tuple[int, int, int, int, int] | None = None
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area > 400 and 30 < width < 120 and 30 < height < 120:
            if best is None or area > best[4]:
                best = (x, y, width, height, area)
    if best is None:
        return None

    x, y, width, height, _area = best
    margin = 18
    left = max(0, x - margin)
    top = max(0, y - margin)
    right = min(header.shape[1], x + width + margin)
    bottom = min(header.shape[0], y + height + margin)
    icon = image.crop(
        (
            PAGE_HEADER_ICON_BOX[0] + left,
            PAGE_HEADER_ICON_BOX[1] + top,
            PAGE_HEADER_ICON_BOX[0] + right,
            PAGE_HEADER_ICON_BOX[1] + bottom,
        )
    )

    template = np.asarray(icon.convert("RGB"), dtype=np.float32)
    sidebar = np.asarray(
        image.crop(SIDEBAR_ICON_BOX).convert("RGB"), dtype=np.float32
    )
    match: tuple[float, int, int, int, int] | None = None
    for scale in np.arange(0.45, 1.25, 0.03):
        scaled_w = max(8, int(template.shape[1] * scale))
        scaled_h = max(8, int(template.shape[0] * scale))
        if scaled_w >= sidebar.shape[1] or scaled_h >= sidebar.shape[0]:
            continue
        scaled = cv2.resize(
            template, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA
        )
        result = cv2.matchTemplate(sidebar, scaled, cv2.TM_CCOEFF_NORMED)
        _min_v, score, _min_loc, location = cv2.minMaxLoc(result)
        if match is None or score > match[0]:
            match = (score, location[0], location[1], scaled_w, scaled_h)
    if match is None or match[0] < RESTORE_ICON_MIN_SCORE:
        return None

    _score, x, y, scaled_w, scaled_h = match
    return (
        SIDEBAR_ICON_BOX[0] + x + scaled_w // 2,
        SIDEBAR_ICON_BOX[1] + y + scaled_h // 2,
    )


def action_panel_title(image: Image.Image) -> np.ndarray | None:
    """Extract the active action's name from its teal banner.

    Returns a binary mask of the white name text, used later to find the same
    action's card in the page grid. The search is text-first: white text bands
    are scored by how much teal surrounds them, so a teal panel body or the
    category label on the right (for example "Tree") cannot be mistaken for the
    name.
    """
    panel = np.asarray(image.crop(ACTIVE_PANEL_BOX), dtype=np.uint8)
    hsv = cv2.cvtColor(panel, cv2.COLOR_RGB2HSV)
    white = (panel.min(axis=2) > 190).astype(np.uint8)
    teal = (
        (hsv[..., 0] > 80)
        & (hsv[..., 0] < 110)
        & (hsv[..., 1] > 100)
        & (hsv[..., 2] > 60)
    )

    rows = np.where(white.any(axis=1))[0]
    if rows.size == 0:
        return None

    bands: list[list[int]] = []
    start = previous = int(rows[0])
    for row in rows[1:]:
        row = int(row)
        if row - previous > 6:
            bands.append([start, previous])
            start = row
        previous = row
    bands.append([start, previous])

    best: tuple[float, int, int, int, int] | None = None
    for top, bottom in bands:
        if bottom - top < 7:
            continue
        columns = white[top : bottom + 1].any(axis=0)
        runs: list[list[int]] = []
        start = None
        for index, value in enumerate(columns):
            if value and start is None:
                start = index
            elif not value and start is not None:
                runs.append([start, index - 1])
                start = None
        if start is not None:
            runs.append([start, len(columns) - 1])

        merged: list[list[int]] = []
        for run in runs:
            if merged and run[0] - merged[-1][1] < 25:
                merged[-1][1] = run[1]
            else:
                merged.append(run)
        if not merged:
            continue

        left, right = max(merged, key=lambda run: run[1] - run[0])
        if right - left < 30:
            continue

        pad = 5
        x0 = max(0, left - pad)
        x1 = min(panel.shape[1], right + pad + 1)
        y0 = max(0, top - pad)
        y1 = min(panel.shape[0], bottom + pad + 1)
        teal_fraction = float(teal[y0:y1, x0:x1].mean())
        if teal_fraction < 0.25:
            continue

        score = (right - left) * teal_fraction
        if best is None or score > best[0]:
            best = (score, left, top, right, bottom)
    if best is None:
        return None

    _score, left, top, right, bottom = best
    mask = white[top : bottom + 1, left : right + 1].astype(np.float32)
    name_rows, name_cols = np.where(mask > 0)
    if name_rows.size == 0:
        return None
    template = mask[
        name_rows.min() : name_rows.max() + 1,
        name_cols.min() : name_cols.max() + 1,
    ]
    if template.shape[0] < 8 or template.shape[1] < 30:
        return None
    if int(template.sum()) < 100:
        return None
    return template


def find_action_title(
    image: Image.Image, template: np.ndarray
) -> tuple[tuple[int, int], float] | None:
    """Find an action's card name in the page grid at any font scale.

    The active banner renders the name larger than the grid cards, so the
    template is matched across a range of scales. Returns the match centre and
    score, or None below the confidence threshold.
    """
    search = np.asarray(image.crop(RESTORE_GRID_BOX), dtype=np.int16)
    mask = (search.min(axis=2) > 150).astype(np.float32)
    best: tuple[float, int, int, int, int] | None = None
    for scale in np.arange(0.30, 1.10, 0.02):
        scaled_w = max(4, int(template.shape[1] * scale))
        scaled_h = max(4, int(template.shape[0] * scale))
        if scaled_w >= mask.shape[1] or scaled_h >= mask.shape[0]:
            continue
        scaled = cv2.resize(
            template.astype(np.float32),
            (scaled_w, scaled_h),
            interpolation=cv2.INTER_AREA,
        )
        result = cv2.matchTemplate(mask, scaled, cv2.TM_CCOEFF_NORMED)
        _min_v, score, _min_loc, location = cv2.minMaxLoc(result)
        if best is None or score > best[0]:
            best = (score, location[0], location[1], scaled_w, scaled_h)
    if best is None or best[0] < RESTORE_TITLE_MIN_SCORE:
        return None

    score, x, y, scaled_w, scaled_h = best
    return (
        (
            RESTORE_GRID_BOX[0] + x + scaled_w // 2,
            RESTORE_GRID_BOX[1] + y + scaled_h // 2,
        ),
        float(score),
    )


def find_action_buttons(image: Image.Image) -> list[tuple[int, int]]:
    """Centres of the green start-action buttons in the page grid.

    The game draws every skilling start button as the same tight dark-green
    rectangle. The page background is lighter green, so the narrow colour range
    below ignores it (and the tree/bush artwork).
    """
    search = np.asarray(image.crop(RESTORE_GRID_BOX), dtype=np.int16)
    red, green, blue = search[..., 0], search[..., 1], search[..., 2]
    mask = (
        (green > 80) & (green < 125) & (red < 35) & (blue < 35)
    ).astype(np.uint8)
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    buttons: list[tuple[int, int]] = []
    for index in range(1, count):
        _x, _y, width, height, area = stats[index]
        if area > 800 and 60 < width < 250 and 20 < height < 90:
            buttons.append(
                (
                    RESTORE_GRID_BOX[0] + int(centroids[index][0]),
                    RESTORE_GRID_BOX[1] + int(centroids[index][1]),
                )
            )
    return buttons


def choose_action_button(
    buttons: list[tuple[int, int]], name_point: tuple[int, int]
) -> tuple[int, int] | None:
    """Pick the start button that belongs to the card with this name.

    The button sits below the card's name and shares its column, so the nearest
    button below the name (within a widening horizontal window) is the one.
    """
    name_x, name_y = name_point
    for limit in (300, 450):
        candidates = [
            ((x - name_x) ** 2 + (y - name_y) ** 2, (x, y))
            for x, y in buttons
            if y > name_y and abs(x - name_x) <= limit
        ]
        if candidates:
            return min(candidates, key=lambda item: item[0])[1]
    return None


def same_title(left: np.ndarray, right: np.ndarray) -> bool:
    """True when two action-name masks look like the same rendered text."""
    if left.shape != right.shape:
        return False
    intersection = int(((left > 0) & (right > 0)).sum())
    union = int(((left > 0) | (right > 0)).sum())
    return union > 0 and intersection / union >= 0.75

