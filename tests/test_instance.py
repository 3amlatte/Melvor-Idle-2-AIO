from __future__ import annotations

import uuid

from mi2_aio.instance import SingleInstance


def test_single_instance_lock() -> None:
    name = "MI2_AIO_Test_" + uuid.uuid4().hex
    first = SingleInstance(name)
    second = SingleInstance(name)
    assert first.acquire() is True
    assert first.acquired is True
    assert second.acquire() is False
    first.release()
    assert first.acquired is False
    assert second.acquire() is True
    second.release()


def test_acquire_is_idempotent() -> None:
    name = "MI2_AIO_Test_" + uuid.uuid4().hex
    lock = SingleInstance(name)
    assert lock.acquire() is True
    assert lock.acquire() is True
    lock.release()
