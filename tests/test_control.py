from __future__ import annotations

import time
import uuid

import pytest

from mi2_aio import runner as runner_module
from mi2_aio import status as st
from mi2_aio.config import Settings
from mi2_aio.control import AlreadyRunning, RunController, RunRequest
from mi2_aio.status import RunStatus


def _fake_run(**kwargs):
    handle = kwargs["control"]
    on_status = kwargs["on_status"]
    task = kwargs["task_name"]
    on_status(RunStatus(state=st.RUNNING, task=task, message="Running"))
    while not handle.stop_event.is_set():
        if handle.pause_event.is_set():
            on_status(RunStatus(state=st.PAUSED, task=task, message="Paused"))
            time.sleep(0.02)
            continue
        time.sleep(0.02)
    on_status(RunStatus(state=st.STOPPED, task=task, message="Stopped"))
    return 0


def _controller(monkeypatch) -> RunController:
    name = "MI2_AIO_Test_" + uuid.uuid4().hex
    controller = RunController(bot_lock_name=name)
    monkeypatch.setattr(runner_module, "run", _fake_run)
    return controller


def _wait_for(controller: RunController, state: str, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if controller.status.state == state:
            return True
        time.sleep(0.02)
    return False


def test_options_reach_the_runner(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(**kwargs):
        seen["options"] = kwargs["options"]
        kwargs["on_status"](
            RunStatus(state=st.RUNNING, task=kwargs["task_name"])
        )
        kwargs["control"].stop_event.set()
        return 0

    controller = _controller(monkeypatch)
    monkeypatch.setattr(runner_module, "run", fake_run)
    options = {"location": "ShallowShores", "spot": "CalmShallows"}
    controller.start(
        RunRequest(settings=Settings(), task_name="fishing", options=options)
    )
    assert controller.wait(3.0)
    assert seen["options"] == options


def test_start_publish_pause_resume_stop(monkeypatch) -> None:
    controller = _controller(monkeypatch)
    statuses: list[str] = []
    controller.subscribe(lambda status: statuses.append(status.state))

    controller.start(RunRequest(settings=Settings(), task_name="observe"))
    assert _wait_for(controller, st.RUNNING)
    assert controller.active

    assert controller.pause() is True
    assert controller.status.state == st.PAUSED
    assert _wait_for(controller, st.PAUSED)

    assert controller.resume() is True
    assert _wait_for(controller, st.RUNNING)

    assert controller.request_stop() is True
    assert controller.wait(5.0) is True
    assert controller.status.state == st.STOPPED
    assert statuses[0] == st.STARTING
    assert st.PAUSED in statuses
    assert st.STOPPING in statuses
    assert st.STOPPED in statuses
    # The bot lock is released, so a second run can start.
    controller.start(RunRequest(settings=Settings(), task_name="observe"))
    assert controller.request_stop() is True
    assert controller.wait(5.0) is True


def test_second_start_is_refused(monkeypatch) -> None:
    controller = _controller(monkeypatch)
    controller.start(RunRequest(settings=Settings(), task_name="observe"))
    assert _wait_for(controller, st.RUNNING)
    with pytest.raises(AlreadyRunning):
        controller.start(RunRequest(settings=Settings(), task_name="observe"))
    controller.request_stop()
    controller.wait(5.0)


def test_controls_do_nothing_when_idle(monkeypatch) -> None:
    controller = _controller(monkeypatch)
    assert controller.pause() is False
    assert controller.resume() is False
    assert controller.request_stop() is False
    assert controller.request_farming() is False


def test_request_farming_reaches_the_active_run(monkeypatch) -> None:
    controller = RunController(bot_lock_name="MI2_AIO_Test_" + uuid.uuid4().hex)
    requests: list[str] = []

    def fake_run(**kwargs):
        handle = kwargs["control"]
        on_status = kwargs["on_status"]
        on_status(RunStatus(state=st.RUNNING, task="observe"))
        while not handle.stop_event.is_set():
            if handle.farm_event.is_set():
                requests.append("farm")
                handle.farm_event.clear()
            time.sleep(0.02)
        on_status(RunStatus(state=st.STOPPED, task="observe"))
        return 0

    monkeypatch.setattr(runner_module, "run", fake_run)
    controller.start(RunRequest(settings=Settings(), task_name="observe"))
    assert _wait_for(controller, st.RUNNING)
    assert controller.request_farming() is True
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not requests:
        time.sleep(0.02)
    assert requests == ["farm"]
    controller.request_stop()
    assert controller.wait(5.0) is True


def test_status_listener_failure_does_not_break_the_run(monkeypatch) -> None:
    controller = _controller(monkeypatch)
    calls: list[str] = []

    def broken(_status):
        calls.append("broken")
        raise RuntimeError("listener bug")

    controller.subscribe(broken)
    controller.start(RunRequest(settings=Settings(), task_name="observe"))
    assert _wait_for(controller, st.RUNNING)
    controller.request_stop()
    assert controller.wait(5.0) is True
    assert calls
