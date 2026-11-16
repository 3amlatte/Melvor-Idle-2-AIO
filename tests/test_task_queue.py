from __future__ import annotations

from mi2_aio.task_queue import TaskQueue


def test_queue_fifo_pause_and_removal() -> None:
    queue = TaskQueue()
    first = queue.add(
        "slayer",
        "Slayer",
        character="DrinkWater",
        character_uuid="uuid-1",
        duration_minutes=30,
        max_tasks=2,
    )
    second = queue.add(
        "fishing",
        "Fishing · Shallow Shores / Calm Shallows",
        character="Test",
        character_uuid="uuid-2",
        options={"location": "ShallowShores", "spot": "CalmShallows"},
    )
    assert first.options == {}
    assert second.options == {
        "location": "ShallowShores",
        "spot": "CalmShallows",
    }
    assert [item.id for item in queue.items()] == [first.id, second.id]
    assert queue.peek() is first
    assert not queue.paused

    queue.set_paused(True)
    assert queue.paused
    queue.set_paused(False)

    assert queue.remove(second.id) is True
    assert queue.get(second.id) is None
    assert queue.pop(first.id) is first
    assert queue.items() == ()
    assert queue.peek() is None

    third = queue.add("dungeons", "Dungeons")
    assert third.id > second.id
    queue.clear()
    assert len(queue) == 0
