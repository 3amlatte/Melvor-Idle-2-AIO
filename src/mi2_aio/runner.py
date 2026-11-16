"""Task loop with watchdogs: STOP file, Ctrl+C, max runtime, error budget."""

from __future__ import annotations

import logging
import signal
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pyautogui

from . import status as st
from . import ui
from .bones import load_bones
from .config import Settings, load_settings
from .failsafe import IdleFailsafe
from .farming import FarmingMaintenance
from .log import configure, get_logger
from .modes import resolve_mode, task_allowed
from .paths import ERRORS_DIR, ensure_runtime_dirs, stop_file_path
from .prayer import PrayerMaintenance
from .restore import PreviousActionRestore
from .savefile import SaveFileError, SaveHeader, read_header
from .status import RunStatus, SlayerStatus
from .tasks import DEFAULT_TASK, create_task
from .tasks.base import TaskContext
from .ui import REFERENCE_SIZE
from .window import (
    WindowInfo,
    capture,
    capture_client,
    dpi_scale,
    ensure_reference_size,
    find_game_window,
    is_minimized,
    layout_ready,
    monitor_size,
    window_info,
)

if TYPE_CHECKING:
    from .control import RunHandle

MAX_CONSECUTIVE_ERRORS = 5
WINDOW_REFRESH_SECONDS = 30.0
STATUS_EVERY_SECONDS = 60.0
# Do not start a long maintenance pass when the run is about to end; otherwise
# a 1-minute test can spend 40 seconds inside farming and overrun its deadline.
FARMING_MIN_REMAINING_SECONDS = 60.0
PRAYER_MIN_REMAINING_SECONDS = 20.0
# HP/food/ammo are captured once when the run launches. A short retry window
# covers the first task step while it opens its page; after that the cached
# values are reused so status updates never compete with the task loop.
PROBE_RETRY_SECONDS = 1.0
PROBE_MAX_ATTEMPTS = 3


def _save_error_screenshot(window: WindowInfo, logger) -> Path | None:
    try:
        ERRORS_DIR.mkdir(parents=True, exist_ok=True)
        path = ERRORS_DIR / f"error_{datetime.now():%Y%m%d_%H%M%S}.png"
        capture(window).save(path)
        logger.info("Saved error screenshot to %s", path)
        return path
    except Exception:
        logger.exception("Could not capture an error screenshot")
        return None


def _header_signature(header: SaveHeader) -> tuple[object, ...]:
    return (
        header.active_action,
        header.active_entity,
        header.active_enemy_id,
        tuple(sorted(header.equipment.items())),
        header.total_level,
        header.gp,
        header.slayer_coins,
    )


def run(
    task_name: str = DEFAULT_TASK,
    settings: Settings | None = None,
    duration_minutes: float | None = None,
    dry_run: bool = False,
    max_tasks: int | None = None,
    *,
    options: Mapping[str, str] | None = None,
    control: RunHandle | None = None,
    on_status: Callable[[RunStatus], None] | None = None,
    logger: logging.Logger | None = None,
    configure_logging: bool = True,
) -> int:
    settings = settings or load_settings()
    if max_tasks is not None:
        settings = replace(
            settings,
            slayer=replace(settings.slayer, max_tasks=max(0, max_tasks)),
        )
    if logger is None:
        logger = (
            configure(settings.logging.level)
            if configure_logging
            else get_logger()
        )
    ensure_runtime_dirs()

    # A fresh task instance per run; tasks are stateful and were previously
    # shared singletons (which leaked state across UI Start/Stop cycles).
    task = create_task(task_name)
    bones = load_bones()
    started_at = datetime.now()
    start_monotonic = time.monotonic()
    last_error: str | None = None
    last_probe_at = 0.0
    probe_values: tuple[float | None, str, bool | None] = (
        None,
        "unknown",
        None,
    )
    probe_done = False
    probe_ready = False
    probe_attempts = 0
    stop_reason = "Stopped"
    exit_code = 0

    def publish(
        state: str | None = None,
        message: str = "Running",
        *,
        ctx: TaskContext | None = None,
        header: SaveHeader | None = None,
        **changes,
    ) -> None:
        nonlocal last_probe_at, probe_done, probe_attempts, probe_values
        if on_status is None:
            return
        header = header or (ctx.header if ctx is not None else None)
        hp, food, ammo = probe_values
        # HP is a launch-time snapshot. Capturing the game every couple of
        # seconds competes with the task loop and shows stale/misread bars on
        # non-Combat pages, so probe once after the task has opened its page
        # (with a few short retries in case the page is still loading).
        if ctx is not None and probe_ready and not probe_done:
            now = time.monotonic()
            if now - last_probe_at >= PROBE_RETRY_SECONDS:
                last_probe_at = now
                probe_attempts += 1
                try:
                    if not is_minimized(ctx.window.hwnd):
                        image = ui.normalize(capture_client(ctx.window))
                        found_hp = ui.hp_ratio(image)
                        food = ui.eat_button_state(image)
                        ammo = ui.ammo_available(image)
                        if found_hp is not None:
                            hp = found_hp
                            probe_values = (hp, food, ammo)
                            probe_done = True
                except Exception:
                    logger.debug("Status probe failed", exc_info=True)
                if probe_attempts >= PROBE_MAX_ATTEMPTS:
                    probe_done = True
        # The save carries the authoritative current HP, including while the
        # game is not showing the Combat page; prefer it over the screenshot.
        if header is not None and header.hp_ratio is not None:
            hp = header.hp_ratio

        slayer_status = SlayerStatus()
        if header is not None and header.slayer_task is not None:
            task_state = header.slayer_task
            slayer_status = SlayerStatus(
                master=task_state.master,
                enemy_id=task_state.enemy_id,
                length=task_state.length,
                progress=task_state.progress,
                completed=int(getattr(task, "completed_tasks", 0)),
            )

        status = RunStatus(
            state=state or st.RUNNING,
            task=task.name,
            task_description=task.description,
            message=message,
            started_at=started_at,
            elapsed_seconds=time.monotonic() - start_monotonic,
            character=header.character_name if header else "",
            mode=(
                ctx.mode.display_name
                if ctx is not None and ctx.mode is not None
                else ""
            ),
            action=header.active_action if header else "",
            entity=header.active_entity if header else "",
            enemy_id=header.active_enemy_id if header else "",
            level=header.total_level if header else 0,
            gp=header.gp if header else 0,
            slayer_coins=header.slayer_coins if header else 0,
            hp_ratio=hp,
            food=food,
            ammo_available=ammo,
            prayer_points=header.prayer_points if header else 0,
            bones=bones.count(header.bank_stacks) if header else 0,
            bank_items=len(header.bank_items) if header else 0,
            slayer=slayer_status,
            dry_run=dry_run,
            last_error=last_error,
        )
        if changes:
            status = replace(status, **changes)
        try:
            on_status(status)
        except Exception:
            logger.exception("Status callback failed")

    logger.info("Starting task %r%s", task.name, " (DRY RUN)" if dry_run else "")
    if dry_run:
        logger.info("Dry run: tasks should not send input in this mode.")

    try:
        window = find_game_window(settings.game.window_title)
    except LookupError as exc:
        last_error = str(exc)
        logger.error("%s", exc)
        publish(st.FAILED, "Game window not found", last_error=last_error)
        return 2

    logger.info("Game window: %s", window.describe())
    display_w, display_h = monitor_size()
    logger.info(
        "Display: %dx%d at %d%% scale; UI layout reference is %dx%d.",
        display_w,
        display_h,
        round(dpi_scale() * 100),
        *REFERENCE_SIZE,
    )

    previous_client = window.client_area
    window = ensure_reference_size(window)
    if window.client_area != previous_client:
        logger.info(
            "Resized the game window to a %dx%d client for the UI layout "
            "(was %dx%d). On a smaller display the window extends off-screen; "
            "that is fine.",
            *window.client_area,
            *previous_client,
        )
    ready, layout_reason = layout_ready(window)
    if not ready:
        last_error = f"Game window layout is not usable: {layout_reason}"
        logger.error(
            "Game window layout is not usable: %s. Keep the game unminimized; "
            "the UI readers are calibrated for a %dx%d client area. Stopping.",
            layout_reason,
            *REFERENCE_SIZE,
        )
        publish(st.FAILED, last_error, last_error=last_error)
        return 4

    stop = control.stop_event if control is not None else threading.Event()
    pause_event = control.pause_event if control is not None else None

    def _handle_signal(signum, _frame) -> None:
        logger.info("Signal %s received; stopping.", signum)
        stop.set()

    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle_signal)
            except (ValueError, OSError):
                pass

    initial_header: SaveHeader | None = None
    try:
        initial_header = read_header(settings=settings)
        logger.info(
            "Save: %s | %s | level %d",
            initial_header.character_name,
            initial_header.active_action or "idle",
            initial_header.total_level,
        )
    except SaveFileError as exc:
        logger.warning("Could not read a save header yet: %s", exc)

    mode = resolve_mode(
        initial_header.gamemode if initial_header else "", settings.gamemodes
    )
    if mode.matched:
        logger.info(
            "Game mode: %s | permanent death=%s | risky tasks=%s",
            mode.profile.display_name,
            mode.profile.permanent_death,
            mode.profile.allow_risky_tasks,
        )
    else:
        logger.warning(
            "Game mode %r is not configured; using conservative profile %r.",
            mode.raw or "<none>",
            mode.profile.display_name,
        )

    allowed, reason = task_allowed(
        task.name,
        supported_modes=task.supported_modes,
        risky=task.risky,
        mode=mode.profile,
    )
    if not allowed:
        last_error = reason
        logger.error("Refusing to run %r: %s", task.name, reason)
        publish(
            st.FAILED,
            f"Refused: {reason}",
            header=initial_header,
            last_error=reason,
        )
        return 3

    ctx = TaskContext(
        settings=settings,
        window=window,
        logger=logger,
        stop=stop,
        pause=pause_event,
        dry_run=dry_run,
        header=initial_header,
        mode=mode.profile,
        mode_raw=mode.raw,
        mode_matched=mode.matched,
        page=task.page,
        options=dict(options or {}),
    )
    maintenance = FarmingMaintenance(settings)
    prayer_settings = settings
    if getattr(task, "force_prayer", False) and not settings.prayer.enabled:
        prayer_settings = replace(
            settings, prayer=replace(settings.prayer, enabled=True)
        )
        logger.info("Prayer maintenance forced on for this task.")
    prayer = PrayerMaintenance(prayer_settings)
    failsafe = IdleFailsafe(settings)
    restore = PreviousActionRestore(settings.restore)
    if settings.restore.enabled:
        logger.info(
            "Restore previous action: enabled (verify %.0fs).",
            settings.restore.verify_seconds,
        )
    if settings.farming.enabled:
        if settings.farming.check_minutes > 0:
            schedule = (
                f"badge or every {settings.farming.check_minutes:.0f} min"
            )
        else:
            schedule = "badge only"
        logger.info(
            "Farming maintenance: %s (badge poll %.0fs), categories=%s",
            schedule,
            settings.farming.badge_poll_seconds,
            ", ".join(settings.farming.categories),
        )
    if settings.prayer.enabled:
        logger.info(
            "Prayer upkeep: bury at %d banked bones or below %d Prayer points "
            "(check %.0fs).",
            settings.prayer.bone_threshold,
            settings.prayer.low_prayer_threshold,
            settings.prayer.check_seconds,
        )

    stop_path = stop_file_path(settings.automation.emergency_stop_file)
    runtime_minutes = min(
        duration_minutes if duration_minutes is not None else float("inf"),
        settings.automation.max_runtime_minutes,
    )
    deadline = time.monotonic() + runtime_minutes * 60.0

    errors = 0
    last_save_signature = (
        _header_signature(initial_header) if initial_header is not None else None
    )
    next_save_check = 0.0
    next_status = time.monotonic() + STATUS_EVERY_SECONDS
    next_window_refresh = time.monotonic() + WINDOW_REFRESH_SECONDS
    started = time.monotonic()
    paused_since: float | None = None

    if task.changes_action:
        restore.capture(ctx, changes_action=True)
    task.start(ctx)
    publish(st.RUNNING, "Running", ctx=ctx)
    try:
        while not stop.is_set():
            now = time.monotonic()
            if pause_event is not None and pause_event.is_set():
                if paused_since is None:
                    paused_since = now
                    publish(st.PAUSED, "Paused", ctx=ctx)
                stop.wait(0.25)
                continue
            if paused_since is not None:
                # Pausing must not eat the configured runtime.
                deadline += time.monotonic() - paused_since
                paused_since = None
                publish(st.RUNNING, "Running", ctx=ctx)

            if now >= deadline:
                stop_reason = "Runtime limit reached"
                logger.info("Runtime limit reached; stopping.")
                break
            if stop_path.exists():
                stop_reason = f"Emergency stop file {stop_path.name} found"
                logger.warning("Found %s; stopping.", stop_path.name)
                break
            if now >= next_window_refresh:
                try:
                    refreshed = window_info(window.hwnd)
                    resized = ensure_reference_size(refreshed)
                    if resized.client_area != refreshed.client_area:
                        logger.info(
                            "Display/window changed; re-applied the %dx%d "
                            "client layout (was %dx%d).",
                            *resized.client_area,
                            *refreshed.client_area,
                        )
                    if is_minimized(resized.hwnd) or resized.client_width <= 0:
                        logger.warning(
                            "Game window is minimized; capture and input are "
                            "unavailable until it is restored."
                        )
                    ctx.window = resized
                except OSError as exc:
                    last_error = str(exc)
                    stop_reason = "Game window disappeared"
                    logger.error("Game window disappeared: %s", exc)
                    break
                next_window_refresh = now + WINDOW_REFRESH_SECONDS

            if now >= next_save_check:
                try:
                    header = read_header(settings=settings)
                    new_mode = resolve_mode(header.gamemode, settings.gamemodes)
                    if (
                        new_mode.profile.key != ctx.mode.key
                        or new_mode.raw != ctx.mode_raw
                    ):
                        allowed, reason = task_allowed(
                            task.name,
                            supported_modes=task.supported_modes,
                            risky=task.risky,
                            mode=new_mode.profile,
                        )
                        if not allowed:
                            last_error = reason
                            stop_reason = "Save mode changed"
                            logger.error(
                                "Save mode changed to %r; stopping: %s",
                                new_mode.raw,
                                reason,
                            )
                            break
                        ctx.mode = new_mode.profile
                        ctx.mode_raw = new_mode.raw
                        ctx.mode_matched = new_mode.matched
                        logger.info(
                            "Game mode: %s%s",
                            new_mode.profile.display_name,
                            "" if new_mode.matched else " (unrecognized)",
                        )

                    signature = _header_signature(header)
                    ctx.header = header
                    restore.observe(header)
                    if signature != last_save_signature:
                        if last_save_signature is not None:
                            task.on_save(ctx, header)
                        last_save_signature = signature
                except SaveFileError as exc:
                    logger.warning("Save read failed: %s", exc)
                next_save_check = time.monotonic() + max(
                    1.0, settings.save.poll_seconds
                )

            # Farming priority is configurable. By default it is serviced
            # before the main task step; when disabled, the task runs first and
            # farming is checked after the step. The fallback only runs after
            # farming and prayer have had a chance to act. Skip long passes when
            # the runtime limit is close.
            remaining = deadline - time.monotonic()
            manual_farm = False
            if control is not None and control.farm_event.is_set():
                control.farm_event.clear()
                if remaining >= FARMING_MIN_REMAINING_SECONDS:
                    manual_farm = True
                    publish(st.RUNNING, "Manual farming pass", ctx=ctx)
                    logger.info(
                        "Manual farming pass requested; servicing the farm "
                        "before continuing the task."
                    )
                    try:
                        maintenance.run_pass(
                            ctx, reason="manual", restore=True
                        )
                    except Exception:
                        logger.exception(
                            "Manual farming pass failed; continuing the task."
                        )
                else:
                    logger.warning(
                        "Manual farming pass skipped: only %.0fs of runtime "
                        "left.",
                        max(0.0, remaining),
                    )
            if (
                settings.farming.prioritise
                and not manual_farm
                and not stop.is_set()
                and remaining >= FARMING_MIN_REMAINING_SECONDS
            ):
                maintenance.poll(ctx)
            remaining = deadline - time.monotonic()
            if (
                not stop.is_set()
                and remaining >= PRAYER_MIN_REMAINING_SECONDS
            ):
                prayer.poll(ctx)
            if not stop.is_set() and not getattr(task, "skip_failsafe", False):
                failsafe.poll(ctx)
            if stop.is_set():
                break

            try:
                delay = task.step(ctx)
                probe_ready = True
                errors = 0
            except pyautogui.FailSafeException:
                stop_reason = "Mouse corner fail-safe"
                exit_code = 1
                logger.warning("Mouse corner fail-safe triggered; stopping.")
                break
            except Exception:
                errors += 1
                last_error = traceback.format_exc()
                logger.error(
                    "Task step failed (%d/%d):\n%s",
                    errors,
                    MAX_CONSECUTIVE_ERRORS,
                    last_error,
                )
                if settings.automation.screenshot_on_error:
                    _save_error_screenshot(ctx.window, logger)
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    stop_reason = "Too many consecutive errors"
                    exit_code = 1
                    logger.error("Too many consecutive errors; stopping.")
                    break
                delay = 2.0

            if stop.is_set():
                break
            if pause_event is not None and pause_event.is_set():
                publish(st.PAUSED, "Paused", ctx=ctx)
            else:
                publish(st.RUNNING, "Running", ctx=ctx)

            # Lower-priority farming: the task gets its step first, then the
            # farm pass is serviced if the red attention badge needs it.
            if (
                not settings.farming.prioritise
                and not manual_farm
                and not stop.is_set()
                and deadline - time.monotonic()
                >= FARMING_MIN_REMAINING_SECONDS
            ):
                maintenance.poll(ctx)

            if time.monotonic() >= next_status:
                uptime = time.monotonic() - started
                header = ctx.header
                detail = (
                    f"{header.active_action or 'idle'} | level "
                    f"{header.total_level} | {header.gp:,} gp"
                    if header
                    else "no save data"
                )
                logger.info("Uptime %s | %s", timedelta(seconds=int(uptime)), detail)
                next_status = time.monotonic() + STATUS_EVERY_SECONDS

            stop.wait(0.1 if delay is None else max(0.1, min(5.0, delay)))
    finally:
        try:
            task.stop(ctx)
        finally:
            try:
                restore.restore(ctx)
            except Exception:
                logger.exception("Could not restore the previous action")
            try:
                failsafe.ensure_active(ctx)
            except Exception:
                logger.exception("Could not start the fallback action")
            elapsed = timedelta(seconds=int(time.monotonic() - started))
            logger.info("%s after %s.", stop_reason, elapsed)
            publish(
                st.STOPPED if exit_code == 0 else st.FAILED,
                stop_reason,
                ctx=ctx,
                exit_code=exit_code,
                last_error=last_error,
            )

    return exit_code
