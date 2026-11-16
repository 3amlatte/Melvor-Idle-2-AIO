"""In-memory task queue used by the desktop app.

The queue stores the task settings at the moment the user queues it, including
the character save. The app starts the next item when the runner is idle and the
queue is not paused.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class QueuedTask:
    id: int
    task: str
    label: str
    character: str = ""
    character_uuid: str = ""
    duration_minutes: float | None = None
    max_tasks: int = 0
    options: dict[str, str] = field(default_factory=dict)


class TaskQueue:
    """Small thread-safe FIFO queue with pause support."""

    def __init__(self) -> None:
        self._items: list[QueuedTask] = []
        self._next_id = 1
        self._paused = False
        self._lock = threading.RLock()

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused

    def add(
        self,
        task: str,
        label: str,
        *,
        character: str = "",
        character_uuid: str = "",
        duration_minutes: float | None = None,
        max_tasks: int = 0,
        options: dict[str, str] | None = None,
    ) -> QueuedTask:
        with self._lock:
            item = QueuedTask(
                id=self._next_id,
                task=task,
                label=label,
                character=character,
                character_uuid=character_uuid,
                duration_minutes=duration_minutes,
                max_tasks=max_tasks,
                options=dict(options or {}),
            )
            self._next_id += 1
            self._items.append(item)
            return item

    def items(self) -> tuple[QueuedTask, ...]:
        with self._lock:
            return tuple(self._items)

    def peek(self) -> QueuedTask | None:
        with self._lock:
            return self._items[0] if self._items else None

    def get(self, item_id: int) -> QueuedTask | None:
        with self._lock:
            for item in self._items:
                if item.id == item_id:
                    return item
            return None

    def pop(self, item_id: int) -> QueuedTask | None:
        with self._lock:
            for index, item in enumerate(self._items):
                if item.id == item_id:
                    return self._items.pop(index)
            return None

    def remove(self, item_id: int) -> bool:
        return self.pop(item_id) is not None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
