from __future__ import annotations

from mi2_aio.tasks import create_task, get_task, list_tasks
from mi2_aio.tasks.bone_farming import BoneFarmingTask
from mi2_aio.tasks.cooking import CookingTask
from mi2_aio.tasks.dungeons import DungeonTask
from mi2_aio.tasks.fishing import FishingTask
from mi2_aio.tasks.observe import ObserveTask
from mi2_aio.tasks.slayer import SlayerTask


def test_create_task_returns_fresh_instances() -> None:
    first = create_task("slayer")
    second = create_task("slayer")
    assert isinstance(first, SlayerTask)
    assert isinstance(second, SlayerTask)
    assert first is not second


def test_get_task_is_a_fresh_instance_alias() -> None:
    assert get_task("observe") is not get_task("observe")
    assert isinstance(get_task("dungeons"), DungeonTask)


def test_list_tasks_is_independent() -> None:
    tasks = list_tasks()
    names = {task.name for task in tasks}
    assert {"observe", "slayer", "dungeons", "farm_bones", "fishing", "cooking"} <= names
    assert all(
        isinstance(
            task,
            (
                ObserveTask,
                SlayerTask,
                DungeonTask,
                BoneFarmingTask,
                FishingTask,
                CookingTask,
            ),
        )
        for task in tasks
    )
    assert list_tasks() is not tasks
