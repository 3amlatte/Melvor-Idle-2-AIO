from __future__ import annotations

import logging
import threading

from mi2_aio.config import Settings
from mi2_aio.cooking_db import load_cooking
from mi2_aio.tasks.base import TaskContext
from mi2_aio.tasks.cooking import CookingTask
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


def make_context(**options: str) -> TaskContext:
    return TaskContext(
        settings=Settings(),
        window=WINDOW,
        logger=logging.getLogger("test.cooking"),
        stop=threading.Event(),
        options=options,
    )


def test_recipe_defaults_and_lookup() -> None:
    task = CookingTask()
    db = load_cooking()
    assert task._pick_recipe(db, "").name == "Shrimp"
    assert task._pick_recipe(db, "Glowfin").name == "Glowfin"
    assert task._pick_recipe(db, "sea bream").name == "Sea Bream"
    assert task._pick_recipe(db, "Cod").name == "Shrimp"
    assert task._pick_recipe(db, "Nope").name == "Shrimp"


def test_start_logs_amount_and_recipe(caplog) -> None:
    task = CookingTask()
    ctx = make_context(recipe="Glowfin", amount="100")
    with caplog.at_level(logging.INFO):
        task.start(ctx)
    assert task._recipe.name == "Glowfin"
    assert task._amount == 100
    assert "1x Raw Glowfin" in caplog.text
    assert "100 products" in caplog.text


def test_missing_amount_means_until_stopped(caplog) -> None:
    task = CookingTask()
    ctx = make_context(recipe="Sardine")
    with caplog.at_level(logging.INFO):
        task.start(ctx)
    assert task._amount == 0
    assert "until stopped" in caplog.text


def test_dry_run_logs_one_plan(caplog) -> None:
    task = CookingTask()
    ctx = make_context(recipe="Lobster", amount="25")
    ctx.dry_run = True
    task.start(ctx)
    with caplog.at_level(logging.INFO):
        assert task._act(ctx, "open the Cooking page") is False
        assert task._act(ctx, "open the Cooking page") is False
    assert caplog.text.count("DRY RUN") == 1
    assert "Products Gained = 25" in caplog.text
