"""Task registry. Add new task classes here."""

from __future__ import annotations

from .base import Task, TaskContext
from .bone_farming import BoneFarmingTask
from .cooking import CookingTask
from .dungeons import DungeonTask
from .fishing import FishingTask
from .observe import ObserveTask
from .slayer import SlayerTask

# A class registry, not shared instances: tasks are stateful (counters, page
# repair stages, style decisions) and a UI must be able to start/stop/restart
# them in the same process without leaking state between runs.
_TASK_CLASSES: dict[str, type[Task]] = {
    ObserveTask.name: ObserveTask,
    SlayerTask.name: SlayerTask,
    DungeonTask.name: DungeonTask,
    BoneFarmingTask.name: BoneFarmingTask,
    FishingTask.name: FishingTask,
    CookingTask.name: CookingTask,
}

DEFAULT_TASK = ObserveTask.name


def create_task(name: str) -> Task:
    try:
        return _TASK_CLASSES[name]()
    except KeyError as exc:
        available = ", ".join(sorted(_TASK_CLASSES))
        raise KeyError(f"Unknown task {name!r}. Available: {available}") from exc


def get_task(name: str) -> Task:
    """Backward-compatible alias; always returns a fresh task."""
    return create_task(name)


def list_tasks() -> list[Task]:
    return [_TASK_CLASSES[name]() for name in sorted(_TASK_CLASSES)]


__all__ = [
    "DEFAULT_TASK",
    "Task",
    "TaskContext",
    "create_task",
    "get_task",
    "list_tasks",
]

