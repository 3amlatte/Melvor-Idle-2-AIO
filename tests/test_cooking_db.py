from __future__ import annotations

from mi2_aio.cooking_db import load_cooking


def test_basic_food_category_and_demo_locks() -> None:
    db = load_cooking()
    basic = db.basic_food()
    assert basic is not None
    assert basic.name == "Basic Food"
    assert basic.subcategory == "Proteins"
    assert len(basic.recipes) == 26
    assert len(basic.available_recipes) == 13
    assert db.recipe("Cod").demo_locked is True
    assert db.recipe("Glowfin").demo_locked is False


def test_recipe_details_and_grid_slots() -> None:
    db = load_cooking()
    glowfin = db.recipe("Glowfin")
    assert glowfin is not None
    assert glowfin.level == 49
    assert glowfin.experience == 22
    assert glowfin.interval_label == "3.0s"
    assert glowfin.ingredients_label == "1x Raw Glowfin"
    assert glowfin.product_name == "Glowfin"
    assert glowfin.grid_slot == 12

    bream = db.recipe("Sea Bream")
    assert bream.ingredients[0].id == "RawSeaBream"
    assert bream.product.id == "SeaBream"
    assert bream.grid_slot == 13

    # The demo inserts a locked card after Pike, so Salmon starts at slot 10.
    assert db.recipe("Pike").grid_slot == 8
    assert db.recipe("Salmon").grid_slot == 10
    assert db.recipe("Lobster").grid_slot == 11


def test_available_recipe_order_matches_the_grid() -> None:
    db = load_cooking()
    names = [recipe.name for recipe in db.available_recipes()]
    assert names == [
        "Shrimp",
        "Sardine",
        "Beef",
        "Herring",
        "Chicken",
        "Perch",
        "Trout",
        "Mackerel",
        "Pike",
        "Salmon",
        "Lobster",
        "Glowfin",
        "Sea Bream",
    ]
    assert [recipe.grid_slot for recipe in db.available_recipes()] == [
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        10,
        11,
        12,
        13,
    ]


def test_recipe_lookup_accepts_ids_and_names() -> None:
    db = load_cooking()
    assert db.recipe("glowfin").name == "Glowfin"
    assert db.recipe("Sea Bream").id == "SeaBream"
    assert db.recipe("Basic Food") is None
    assert db.recipe("Not A Recipe") is None
    assert "Glowfin" in db.product_names()
