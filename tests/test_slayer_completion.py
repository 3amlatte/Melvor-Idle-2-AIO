from __future__ import annotations

import logging
import threading

from mi2_aio.config import Settings, SlayerSettings
from mi2_aio.modes import resolve_mode
from mi2_aio.savefile import SaveHeader, SlayerTaskState
from mi2_aio.tasks.base import TaskContext
from mi2_aio.tasks.slayer import SlayerTask
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


def make_header(task: SlayerTaskState | None) -> SaveHeader:
    return SaveHeader(
        save_version=28,
        uuid="X",
        character_name="DrinkWater",
        gamemode="Test",
        timestamp=None,
        active_entity="Combat",
        active_entity_icon="",
        active_action="Creeper Vines",
        active_action_icon="",
        total_level=727,
        gp=0,
        slayer_coins=0,
        is_demo=True,
        active_enemy_id="CreeperVines",
        slayer_task=task,
    )


def make_context(max_tasks: int = 0) -> TaskContext:
    settings = Settings(slayer=SlayerSettings(max_tasks=max_tasks))
    return TaskContext(
        settings=settings,
        window=WINDOW,
        logger=logging.getLogger("test.slayer_completion"),
        stop=threading.Event(),
        header=make_header(None),
        mode=resolve_mode("Test", settings.gamemodes).profile,
    )


def test_initial_task_is_not_counted() -> None:
    ctx = make_context()
    task = SlayerTask()
    task._check_task_completion(ctx)
    ctx.header = make_header(SlayerTaskState("Satsgar", "CreeperVines", 42, 0))
    task._check_task_completion(ctx)
    assert task._completed_tasks == 0


def test_new_task_key_counts_once() -> None:
    ctx = make_context()
    task = SlayerTask()
    task._check_task_completion(ctx)
    ctx.header = make_header(SlayerTaskState("Satsgar", "CreeperVines", 42, 0))
    task._check_task_completion(ctx)
    ctx.header = make_header(SlayerTaskState("Satsgar", "CreeperVines", 42, 3))
    task._check_task_completion(ctx)
    assert task._completed_tasks == 0

    ctx.header = make_header(SlayerTaskState("Satsgar", "RainbowSlime", 30, 0))
    task._check_task_completion(ctx)
    assert task._completed_tasks == 1


def test_same_task_progress_reset_counts() -> None:
    ctx = make_context()
    task = SlayerTask()
    ctx.header = make_header(SlayerTaskState("Satsgar", "CreeperVines", 42, 0))
    task._check_task_completion(ctx)
    ctx.header = make_header(SlayerTaskState("Satsgar", "CreeperVines", 42, 41))
    task._check_task_completion(ctx)
    assert task._completed_tasks == 0
    ctx.header = make_header(SlayerTaskState("Satsgar", "CreeperVines", 42, 0))
    task._check_task_completion(ctx)
    assert task._completed_tasks == 1


def test_completed_state_is_counted_once() -> None:
    ctx = make_context()
    task = SlayerTask()
    ctx.header = make_header(SlayerTaskState("Satsgar", "CreeperVines", 42, 0))
    task._check_task_completion(ctx)
    ctx.header = make_header(SlayerTaskState("Satsgar", "CreeperVines", 42, 42))
    task._check_task_completion(ctx)
    assert task._completed_tasks == 1
    # The following save shows the replacement task; it must not double-count.
    ctx.header = make_header(SlayerTaskState("Satsgar", "RainbowSlime", 30, 0))
    task._check_task_completion(ctx)
    assert task._completed_tasks == 1


def test_max_tasks_stops_the_run() -> None:
    ctx = make_context(max_tasks=1)
    task = SlayerTask()
    ctx.header = make_header(SlayerTaskState("Satsgar", "CreeperVines", 42, 0))
    task._check_task_completion(ctx)
    ctx.header = make_header(SlayerTaskState("Satsgar", "RainbowSlime", 30, 0))
    task._check_task_completion(ctx)
    assert task._completed_tasks == 1
    assert ctx.stop.is_set() is True
