from __future__ import annotations

import logging
import threading
import time

import pytest
from helpers import make_combat_frame

from mi2_aio import ui
from mi2_aio.config import Settings, SlayerSettings
from mi2_aio.modes import resolve_mode
from mi2_aio.tasks import slayer as slayer_module
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


class Harness:
    def __init__(self, *, dry_run: bool = False, **slayer: object) -> None:
        settings = Settings(slayer=SlayerSettings(**slayer))
        self.ctx = TaskContext(
            settings=settings,
            window=WINDOW,
            logger=logging.getLogger("test.slayer"),
            stop=threading.Event(),
            dry_run=dry_run,
            mode=resolve_mode("Test", settings.gamemodes).profile,
        )
        self.task = SlayerTask()
        self.clicks: list[tuple[int, int]] = []
        self.frame = make_combat_frame()

        self.task._capture = lambda ctx: self.frame  # type: ignore[method-assign]
        self.task._click = lambda ctx, point: self.clicks.append(point)  # type: ignore[method-assign]

    def step(self) -> None:
        self.task.step(self.ctx)

    def run(self, steps: int = 1) -> None:
        for _ in range(steps):
            self.step()


@pytest.fixture(autouse=True)
def switch_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Never touch the real bank during tests."""
    calls: list[str] = []

    def fake_switch(window, settings, name):
        calls.append(name)

    monkeypatch.setattr(slayer_module.equipment, "switch_weapon", fake_switch)
    return calls


def test_startup_jumps_once() -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.step()  # initialise
    assert h.clicks == [ui.JUMP_BUTTON]
    h.run(2)
    assert h.clicks == [ui.JUMP_BUTTON], "must not spam jumps"


def test_startup_jump_can_be_disabled() -> None:
    h = Harness(jump_on_start=False)
    h.task.start(h.ctx)
    h.run(2)
    assert h.clicks == []


def test_new_task_triggers_jump() -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.run(2)
    h.clicks.clear()
    h.task._last_jump_at = 0.0  # long after the startup jump
    h.frame = make_combat_frame(task="Goblin")
    h.step()
    assert h.clicks == [ui.JUMP_BUTTON]


def test_progress_change_resets_stall() -> None:
    h = Harness(stall_minutes=10)
    h.task.start(h.ctx)
    h.run(2)
    h.clicks.clear()
    h.frame = make_combat_frame(progress="6 / 37")
    h.step()
    assert h.clicks == []
    assert h.task._stalls == 0


def test_stall_jumps_then_stops() -> None:
    h = Harness(stall_minutes=10, max_stalls=1)
    h.task.start(h.ctx)
    h.run(2)
    h.clicks.clear()

    h.task._last_jump_at = 0.0
    h.task._last_progress_at = time.monotonic() - 11 * 60
    h.step()
    assert h.clicks == [ui.JUMP_BUTTON]
    assert h.ctx.stop.is_set() is False

    h.task._last_jump_at = 0.0
    h.task._last_progress_at = time.monotonic() - 11 * 60
    h.step()
    assert h.ctx.stop.is_set() is True


def test_no_task_panel_does_not_jump() -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(jump=False)
    h.run(2)
    assert h.clicks == []


def test_disadvantage_switches_to_counter_weapon(switch_calls) -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.step()  # initialise + startup jump
    h.clicks.clear()
    h.step()
    assert switch_calls == ["Normal Bow"]


def test_advantage_does_not_switch(switch_calls) -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(word="ranged", advantage="advantaged")
    h.run(3)
    assert switch_calls == []


def test_disadvantaged_style_without_weapon_does_not_switch(
    switch_calls,
) -> None:
    h = Harness(weapons={"melee": "Bone Scythe", "ranged": "", "magic": ""})
    h.task.start(h.ctx)
    h.run(3)
    assert switch_calls == []


def test_switch_is_verified_and_failure_backs_off(switch_calls) -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.step()  # initialise + jump
    h.step()  # triggers switch
    assert h.task._pending_style == "ranged"

    # Simulate the UI still showing Melee after the switch.
    h.task._pending_since = time.monotonic() - 10
    h.step()
    assert h.task._pending_style is None
    assert h.task._switch_blocked_until > time.monotonic()

    # A second disadvantaged poll must not switch again while backed off.
    h.step()
    assert switch_calls == ["Normal Bow"]


def test_successful_switch_verification(switch_calls) -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.step()
    h.step()  # switch requested
    h.frame = make_combat_frame(word="ranged", advantage="advantaged")
    h.task._pending_since = time.monotonic() - 10
    h.step()
    assert h.task._pending_style is None
    assert h.task._switch_blocked_until == 0.0


def test_switch_reverts_when_no_progress(switch_calls) -> None:
    h = Harness(switch_grace_minutes=4)
    h.task.start(h.ctx)
    h.step()  # initialise + jump
    h.step()  # switch requested
    h.frame = make_combat_frame(word="ranged", advantage="advantaged")
    h.task._pending_since = time.monotonic() - 10
    h.step()  # verify the switch
    assert h.task._switch_to == "ranged"
    switch_calls.clear()

    h.task._switch_at = time.monotonic() - 5 * 60
    h.step()  # grace elapsed with no progress -> revert
    assert switch_calls == ["Bone Scythe"]
    assert "ranged" in h.task._blocked_targets
    assert h.task._switch_to is None


def test_blocked_style_is_not_retried(switch_calls) -> None:
    h = Harness(switch_grace_minutes=4)
    h.task.start(h.ctx)
    h.step()
    h.step()
    h.frame = make_combat_frame(word="ranged", advantage="advantaged")
    h.task._pending_since = time.monotonic() - 10
    h.step()
    h.task._switch_at = time.monotonic() - 5 * 60
    h.step()  # revert
    switch_calls.clear()

    h.task._last_switch_at = 0.0
    h.task._switch_blocked_until = 0.0
    h.frame = make_combat_frame(word="melee", advantage="disadvantaged")
    h.step()
    assert switch_calls == []


def test_switch_is_kept_when_progress_moves(switch_calls) -> None:
    h = Harness(switch_grace_minutes=4)
    h.task.start(h.ctx)
    h.step()
    h.step()
    h.frame = make_combat_frame(word="ranged", advantage="advantaged")
    h.task._pending_since = time.monotonic() - 10
    h.step()
    switch_calls.clear()

    h.frame = make_combat_frame(
        word="ranged", advantage="advantaged", progress="6 / 37"
    )
    h.task._switch_at = time.monotonic() - 5 * 60
    h.step()
    assert switch_calls == []
    assert h.task._switch_to is None
    assert h.task._blocked_targets == set()


def test_new_task_clears_blocked_styles(switch_calls) -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.run(2)
    h.task._blocked_targets.add("ranged")
    h.task._last_jump_at = 0.0
    h.frame = make_combat_frame(task="Goblin")
    h.step()
    assert h.task._blocked_targets == set()


def test_no_ammo_uses_other_style_instead_of_ranged(switch_calls) -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(ammo=False)
    h.run(3)
    assert switch_calls == ["Water Staff"]


def test_no_ammo_without_alternative_stays_put(switch_calls) -> None:
    h = Harness(weapons={"melee": "Bone Scythe", "ranged": "Normal Bow", "magic": ""})
    h.task.start(h.ctx)
    h.frame = make_combat_frame(ammo=False)
    h.run(3)
    assert switch_calls == []


def test_ranged_without_ammo_falls_back_to_melee(switch_calls) -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(
        word="ranged", advantage="advantaged", ammo=False
    )
    h.run(3)
    assert switch_calls == ["Bone Scythe"]


def test_ranged_with_ammo_keeps_the_bow(switch_calls) -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(word="ranged", advantage="advantaged", ammo=True)
    h.run(3)
    assert switch_calls == []


def test_out_of_food_stops_after_two_polls() -> None:
    h = Harness(stop_when_out_of_food=True)
    h.task.start(h.ctx)
    h.step()
    h.frame = make_combat_frame(food="disabled")
    h.step()
    assert h.ctx.stop.is_set() is False
    h.step()
    assert h.ctx.stop.is_set() is True
    assert ui.RUN_FROM_COMBAT in h.clicks


def test_out_of_food_does_not_flee_when_disabled() -> None:
    h = Harness(stop_when_out_of_food=True, flee_when_out_of_food=False)
    h.task.start(h.ctx)
    h.frame = make_combat_frame(food="disabled")
    h.run(3)
    assert h.ctx.stop.is_set() is True
    assert ui.RUN_FROM_COMBAT not in h.clicks


def test_critical_hp_flees_then_stops() -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(hp=0.02)
    h.step()
    h.step()
    assert h.ctx.stop.is_set() is True
    assert ui.RUN_FROM_COMBAT in h.clicks


def test_out_of_food_can_continue() -> None:
    h = Harness(stop_when_out_of_food=False)
    h.task.start(h.ctx)
    h.frame = make_combat_frame(food="disabled")
    h.run(4)
    assert h.ctx.stop.is_set() is False


def test_covered_eat_button_is_not_out_of_food() -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(food="covered")
    h.run(4)
    assert h.ctx.stop.is_set() is False


def test_critical_hp_stops() -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(hp=0.02)
    h.step()  # initialise
    h.step()  # HP check
    assert h.ctx.stop.is_set() is True


def test_low_hp_above_critical_keeps_working(switch_calls) -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(hp=0.3)  # below the 0.35 floor, above critical
    h.run(3)
    assert h.ctx.stop.is_set() is False
    assert switch_calls == ["Normal Bow"]


def test_dry_run_sends_no_input(switch_calls) -> None:
    h = Harness(dry_run=True)
    h.task.start(h.ctx)
    h.run(3)
    assert h.clicks == []
    assert switch_calls == []


def test_waits_for_combat_page_without_crashing() -> None:
    h = Harness()
    h.task.start(h.ctx)
    h.frame = make_combat_frame(word="")
    h.run(2)
    assert h.task._initialized is False
    assert h.ctx.stop.is_set() is False


def test_combat_page_recovery_alternates_nav_and_stats_tab() -> None:
    h = Harness()
    h.task._fix_combat_page(h.ctx)
    assert h.clicks[-1] == ui.NAV_COMBAT
    assert h.task._page_fix_stage == 1
    h.task._fix_combat_page(h.ctx)
    assert h.clicks[-1] == ui.COMBAT_STATS_TAB
    assert h.task._page_fix_stage == 0
