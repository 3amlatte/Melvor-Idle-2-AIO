"""Structured run status shared by the CLI, the controller and the desktop app.

The bot itself is still a blocking loop. These dataclasses are the stable
boundary between that loop and any front end: a status snapshot contains
everything a dashboard needs without leaking task internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

# Run lifecycle. Strings (not an Enum) keep JSON/log output trivial and stable.
IDLE = "idle"
STARTING = "starting"
RUNNING = "running"
PAUSED = "paused"
STOPPING = "stopping"
STOPPED = "stopped"
FAILED = "failed"

_BOT_STATE_LABELS = {
    IDLE: "Bot Idle",
    STARTING: "Bot Starting",
    RUNNING: "Bot Running",
    PAUSED: "Bot Paused",
    STOPPING: "Bot Stopping",
    STOPPED: "Bot Stopped",
    FAILED: "Bot Failed",
}


def bot_state_label(state: str) -> str:
    """Human label for the bot run-state pill."""
    return _BOT_STATE_LABELS.get(state, f"Bot {state.replace('_', ' ').title()}")


@dataclass(frozen=True)
class SlayerStatus:
    master: str = ""
    enemy_id: str = ""
    length: int = 0
    progress: int = 0
    completed: int = 0

    @property
    def label(self) -> str:
        if not self.enemy_id:
            return ""
        name = self.enemy_id
        return f"{self.master}: {name} {self.progress}/{self.length}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "master": self.master,
            "enemy_id": self.enemy_id,
            "length": self.length,
            "progress": self.progress,
            "completed": self.completed,
            "label": self.label,
        }


@dataclass(frozen=True)
class RunStatus:
    """A single dashboard snapshot.

    ``state`` is one of the module-level lifecycle constants. The rest is
    best-effort: missing values stay empty/zero rather than raising, because a
    UI must keep rendering while the game or save is unavailable.
    """

    state: str = IDLE
    task: str = ""
    task_description: str = ""
    message: str = ""
    started_at: datetime | None = None
    elapsed_seconds: float = 0.0
    character: str = ""
    mode: str = ""
    action: str = ""
    entity: str = ""
    enemy_id: str = ""
    level: int = 0
    gp: int = 0
    slayer_coins: int = 0
    hp_ratio: float | None = None
    food: str = "unknown"
    ammo_available: bool | None = None
    prayer_points: int = 0
    bones: int = 0
    bank_items: int = 0
    slayer: SlayerStatus = field(default_factory=SlayerStatus)
    dry_run: bool = False
    last_error: str | None = None
    exit_code: int | None = None
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def active(self) -> bool:
        return self.state in {STARTING, RUNNING, PAUSED, STOPPING}

    def with_state(self, state: str, **changes: Any) -> RunStatus:
        return replace(self, state=state, updated_at=datetime.now(), **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "task": self.task,
            "task_description": self.task_description,
            "message": self.message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "character": self.character,
            "mode": self.mode,
            "action": self.action,
            "entity": self.entity,
            "enemy_id": self.enemy_id,
            "level": self.level,
            "gp": self.gp,
            "slayer_coins": self.slayer_coins,
            "hp_ratio": (
                round(self.hp_ratio, 3) if self.hp_ratio is not None else None
            ),
            "food": self.food,
            "ammo_available": self.ammo_available,
            "prayer_points": self.prayer_points,
            "bones": self.bones,
            "bank_items": self.bank_items,
            "slayer": self.slayer.to_dict(),
            "dry_run": self.dry_run,
            "last_error": self.last_error,
            "exit_code": self.exit_code,
            "updated_at": self.updated_at.isoformat(),
        }
