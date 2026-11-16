"""Application service shared by the CLI and the desktop UI.

The UI must not import ``__main__`` or reach into argparse namespaces. This
module is the single place for settings, diagnostics, environment snapshots and
run control.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__, settings_io, ui
from .bones import load_bones
from .character_switch import CharacterSwitchError, ensure_character
from .config import Settings, load_settings
from .control import AlreadyRunning, RunController, RunRequest
from .diagnostics import collect_diagnostics, format_diagnostics
from .dungeon_db import load_dungeons
from .farming import FarmingMaintenance
from .features import FEATURES
from .instance import SingleInstance
from .log import get_logger
from .modes import resolve_mode
from .paths import (
    CONFIG_FILE,
    DEFAULT_CONFIG_FILE,
    FROZEN,
    LOGS_DIR,
    RESOURCE_ROOT,
    ensure_runtime_dirs,
)
from .savefile import SaveFileError, discover_saves, read_header, read_skills
from .status import IDLE, RunStatus, SlayerStatus
from .task_queue import TaskQueue
from .tasks import list_tasks
from .tasks.base import TaskContext
from .window import (
    capture_client,
    ensure_reference_size,
    find_game_window,
    is_minimized,
    layout_ready,
)


class ServiceError(RuntimeError):
    """A recoverable operation failure suitable for showing in the UI."""


class AppService:
    def __init__(
        self,
        settings_path: Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings_path = Path(settings_path or CONFIG_FILE)
        self.settings: Settings = load_settings(self.settings_path)
        self.logger = logger or get_logger()
        self.controller = RunController(self.logger)
        self.queue = TaskQueue()
        self._probe_done = False
        self._probe_at = 0.0
        self._last_probe: tuple[float | None, str, bool | None] = (
            None,
            "unknown",
            None,
        )
        ensure_runtime_dirs()

    # -- settings --------------------------------------------------------
    def reload_settings(self) -> Settings:
        self.settings = load_settings(self.settings_path)
        return self.settings

    def settings_values(self) -> dict[str, Any]:
        return settings_io.read_values(self.settings_path)

    def save_settings(self, values: Mapping[str, Any]) -> Settings:
        try:
            self.settings = settings_io.save_values(values, self.settings_path)
        except settings_io.SettingsError as exc:
            raise ServiceError(str(exc)) from exc
        self.logger.setLevel(
            getattr(logging, self.settings.logging.level.upper(), logging.INFO)
        )
        return self.settings

    def diagnostics(self) -> dict[str, Any]:
        return collect_diagnostics(self.settings)

    def skill_levels(self) -> dict[str, int]:
        """Return every parsed skill level, or an empty map if unavailable."""
        try:
            levels = read_skills(settings=self.settings)
        except SaveFileError:
            return {}
        return {name: skill.level for name, skill in levels.skills.items()}

    def diagnostics_text(self) -> str:
        return format_diagnostics(self.diagnostics())

    def bank_counts(self, item_ids: list[str]) -> dict[str, int]:
        """Return current bank stacks for the requested item ids."""
        try:
            header = read_header(settings=self.settings)
        except SaveFileError:
            return {}
        return {
            item_id: int(header.bank_stacks.get(item_id, 0))
            for item_id in item_ids
        }

    def reset_settings(self) -> Settings:
        """Replace the active settings file with the bundled defaults."""
        if not DEFAULT_CONFIG_FILE.exists():
            raise ServiceError(
                f"Default settings template is missing: {DEFAULT_CONFIG_FILE}"
            )
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            data = DEFAULT_CONFIG_FILE.read_bytes()
            fd, temp_name = tempfile.mkstemp(
                prefix="settings_reset_",
                suffix=".toml",
                dir=str(self.settings_path.parent),
            )
            temp_path = Path(temp_name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            # Validate before replacing the working configuration.
            load_settings(temp_path)
            os.replace(temp_path, self.settings_path)
            temp_path = None
        except Exception as exc:
            raise ServiceError(f"Could not reset settings: {exc}") from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        self.settings = load_settings(self.settings_path)
        self.logger.setLevel(
            getattr(logging, self.settings.logging.level.upper(), logging.INFO)
        )
        return self.settings

    # -- environment snapshot -------------------------------------------
    def environment(self) -> dict[str, Any]:
        settings = self.settings
        selected = None
        try:
            header = read_header(settings=settings)
            mode = resolve_mode(header.gamemode, settings.gamemodes)
            selected = {
                **header.to_dict(),
                "mode": mode.profile.display_name,
                "mode_key": mode.profile.key,
                "mode_matched": mode.matched,
            }
        except SaveFileError as exc:
            selected = {"error": str(exc)}

        saves = []
        for path in discover_saves(settings)[:20]:
            entry: dict[str, Any] = {
                "path": str(path),
                "modified": datetime.fromtimestamp(
                    path.stat().st_mtime
                ).isoformat(sep=" ", timespec="seconds"),
            }
            try:
                header = read_header(path, settings=settings)
                mode = resolve_mode(header.gamemode, settings.gamemodes)
                entry.update(
                    character=header.character_name,
                    level=header.total_level,
                    action=header.active_action or "idle",
                    mode=mode.profile.display_name,
                    uuid=header.uuid,
                )
            except SaveFileError as exc:
                entry["error"] = str(exc)
            saves.append(entry)

        window = None
        try:
            info = find_game_window(settings.game.window_title)
            ready, reason = layout_ready(info)
            window = {
                "hwnd": info.hwnd,
                "title": info.title,
                "describe": info.describe(),
                "client_width": info.client_width,
                "client_height": info.client_height,
                "minimized": is_minimized(info.hwnd),
                "layout_ready": ready,
                "layout_reason": reason,
            }
        except (LookupError, OSError) as exc:
            window = {"error": str(exc)}

        return {
            "version": __version__,
            "frozen": FROZEN,
            "config_path": str(self.settings_path),
            "logs_dir": str(LOGS_DIR),
            "resource_root": str(RESOURCE_ROOT),
            "selected": selected,
            "saves": saves,
            "window": window,
            "settings": self.settings_values(),
            "features": [
                {
                    "key": feature.key,
                    "category": feature.category,
                    "name": feature.name,
                    "description": feature.description,
                    "config_section": feature.config_section,
                    "task": feature.task,
                }
                for feature in FEATURES
            ],
            "tasks": [
                {
                    "name": task.name,
                    "description": task.description,
                    "page": task.page,
                    "risky": task.risky,
                    "changes_action": task.changes_action,
                    "supported_modes": (
                        sorted(task.supported_modes)
                        if task.supported_modes
                        else None
                    ),
                }
                for task in list_tasks()
            ],
            "dungeons": self._dungeon_entries(),
            "bones": [bone.name for bone in load_bones().bones],
        }

    def _dungeon_entries(self) -> list[dict[str, Any]]:
        entries = []
        templates = RESOURCE_ROOT / "assets" / "templates"
        for dungeon in load_dungeons().dungeons:
            slug = re.sub(
                r"(?<=[a-z0-9])(?=[A-Z])", "_", dungeon.id
            ).lower()
            supported = (templates / f"dungeon_{slug}.png").exists()
            entries.append(
                {
                    "id": dungeon.id,
                    "name": dungeon.name,
                    "difficulty": dungeon.difficulty,
                    "supported": supported,
                }
            )
        return entries

    # -- idle status -----------------------------------------------------
    def idle_status(self) -> RunStatus:
        settings = self.settings
        header = None
        try:
            header = read_header(settings=settings)
        except SaveFileError:
            pass
        hp, food, ammo = self._probe()
        if header is not None and header.hp_ratio is not None:
            hp = header.hp_ratio
        slayer = SlayerStatus()
        if header is not None and header.slayer_task is not None:
            task = header.slayer_task
            slayer = SlayerStatus(
                master=task.master,
                enemy_id=task.enemy_id,
                length=task.length,
                progress=task.progress,
            )
        mode = ""
        if header is not None:
            mode = resolve_mode(header.gamemode, settings.gamemodes).profile.display_name
        return RunStatus(
            state=IDLE,
            message="Idle",
            character=header.character_name if header else "",
            mode=mode,
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
            bones=load_bones().count(header.bank_stacks) if header else 0,
            bank_items=len(header.bank_items) if header else 0,
            slayer=slayer,
        )

    def refresh_health(self) -> tuple[float | None, str, bool | None]:
        """Take one fresh HP/food/ammo probe and cache it.

        Screen captures are relatively expensive, so the dashboard only asks
        for this when the bot launches instead of polling every UI tick.
        """
        return self._probe(force=True)

    def _probe(self, *, force: bool = False) -> tuple[float | None, str, bool | None]:
        if self._probe_done and not force:
            return self._last_probe
        now = time.monotonic()
        if not force and now - self._probe_at < 2.0:
            return self._last_probe
        self._probe_at = now
        try:
            window = find_game_window(self.settings.game.window_title)
            if is_minimized(window.hwnd):
                return self._last_probe
            image = ui.normalize(capture_client(ensure_reference_size(window)))
            hp = ui.hp_ratio(image)
            food = ui.eat_button_state(image)
            ammo = ui.ammo_available(image)
            # Keep the last readable HP rather than replacing it with None
            # when the game is on a non-Combat page.
            if hp is None:
                hp = self._last_probe[0]
            self._last_probe = (hp, food, ammo)
            self._probe_done = True
        except Exception:
            self.logger.debug("Status probe failed", exc_info=True)
        return self._last_probe

    # -- run control -----------------------------------------------------
    def start_run(
        self,
        task_name: str,
        *,
        duration_minutes: float | None = None,
        dry_run: bool = False,
        max_tasks: int | None = None,
        options: Mapping[str, str] | None = None,
    ) -> RunStatus:
        try:
            return self.controller.start(
                RunRequest(
                    settings=self.settings,
                    task_name=task_name,
                    duration_minutes=duration_minutes,
                    dry_run=dry_run,
                    max_tasks=max_tasks,
                    options=dict(options or {}),
                )
            )
        except AlreadyRunning as exc:
            raise ServiceError(str(exc)) from exc

    def stop_run(self) -> bool:
        return self.controller.request_stop()

    def switch_character(self, target: str) -> dict[str, Any]:
        """Load ``target`` in the running Melvor client and pin its save."""
        lock = SingleInstance("MI2_AIO_Bot")
        if not lock.acquire():
            raise ServiceError(
                "The bot is busy. Stop the current run before switching "
                "characters."
            )
        try:
            header = ensure_character(self.settings, target, self.logger)
            self.settings = self.save_settings(
                {"save.character": header.uuid}
            )
            return header.to_dict()
        except CharacterSwitchError as exc:
            raise ServiceError(str(exc)) from exc
        finally:
            lock.release()

    def pause_run(self) -> bool:
        return self.controller.pause()

    def request_farming(self) -> bool:
        """Queue a farming pass for the active run, or return False if idle."""
        return self.controller.request_farming()

    def resume_run(self) -> bool:
        return self.controller.resume()

    # -- one-shot actions ------------------------------------------------
    def run_farming_once(self) -> dict[str, int]:
        if self.controller.active:
            raise ServiceError("Stop the active bot run before a manual farm pass.")
        lock = SingleInstance("MI2_AIO_Bot")
        if not lock.acquire():
            raise ServiceError("Another MI2 AIO bot run is already active.")
        try:
            window = find_game_window(self.settings.game.window_title)
            window = ensure_reference_size(window)
            ready, reason = layout_ready(window)
            if not ready:
                raise ServiceError(f"Game window layout is not usable: {reason}")
            header = None
            try:
                header = read_header(settings=self.settings)
            except SaveFileError:
                pass
            ctx = TaskContext(
                settings=self.settings,
                window=window,
                logger=self.logger,
                stop=threading.Event(),
                header=header,
                page=None,
            )
            return FarmingMaintenance(self.settings).run_pass(
                ctx, reason="manual", restore=True
            )
        finally:
            lock.release()

    def capture_screenshot(self) -> Path:
        window = find_game_window(self.settings.game.window_title)
        target = LOGS_DIR / "captures"
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"capture_{datetime.now():%Y%m%d_%H%M%S}.png"
        ui.normalize(capture_client(window)).save(path)
        return path

    def environment_status(self) -> dict[str, Any]:
        """Small, cheap snapshot for periodic UI refresh."""
        env = self.environment()
        return {
            "window": env["window"],
            "selected": env["selected"],
            "saves": env["saves"],
        }


def feature_rows() -> list[dict[str, Any]]:
    return [asdict(feature) for feature in FEATURES]
