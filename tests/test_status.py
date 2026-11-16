from __future__ import annotations

from datetime import datetime

from mi2_aio.status import (
    IDLE,
    PAUSED,
    RUNNING,
    RunStatus,
    SlayerStatus,
    bot_state_label,
)


def test_status_serializes_for_the_ui() -> None:
    status = RunStatus(
        state=RUNNING,
        task="slayer",
        character="DrinkWater",
        action="Golbin",
        hp_ratio=0.5123,
        prayer_points=99,
        bones=12,
        slayer=SlayerStatus(
            master="Satsgar", enemy_id="MangroveMantis", length=98, progress=4
        ),
    )
    data = status.to_dict()
    assert data["state"] == RUNNING
    assert data["hp_ratio"] == 0.512
    assert data["slayer"]["label"] == "Satsgar: MangroveMantis 4/98"
    assert status.active is True


def test_with_state_keeps_previous_fields() -> None:
    status = RunStatus(state=RUNNING, character="X", started_at=datetime.now())
    paused = status.with_state(PAUSED, message="Paused")
    assert paused.state == PAUSED
    assert paused.character == "X"
    assert paused.started_at == status.started_at
    assert paused.updated_at >= status.updated_at


def test_bot_state_labels() -> None:
    assert bot_state_label(IDLE) == "Bot Idle"
    assert bot_state_label(RUNNING) == "Bot Running"
    assert bot_state_label(PAUSED) == "Bot Paused"
