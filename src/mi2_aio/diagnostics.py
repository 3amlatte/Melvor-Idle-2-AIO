"""Environment diagnostics shared by ``doctor`` and the desktop app."""

from __future__ import annotations

import platform
from datetime import datetime
from importlib import metadata
from typing import Any

import numpy as np

from . import __version__, ui
from .config import Settings, load_settings
from .modes import resolve_mode
from .paths import LOGS_DIR
from .savefile import (
    SaveFileError,
    discover_saves,
    ensure_savetool,
    format_header,
    read_header,
)
from .ui import REFERENCE_SIZE
from .window import (
    capture_client,
    dpi_scale,
    ensure_reference_size,
    find_game_window,
    is_minimized,
    layout_ready,
    monitor_size,
)


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "missing"


def collect_diagnostics(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    problems: list[str] = []
    data: dict[str, Any] = {
        "ok": True,
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "platform": platform.platform(),
        "version": __version__,
        "packages": {
            name: _package_version(name)
            for name in (
                "pillow",
                "numpy",
                "opencv-python",
                "pyautogui",
                "mss",
                "tomlkit",
                "PySide6",
            )
        },
        "settings": str(settings.source or "defaults (no file)"),
        "logs": str(LOGS_DIR),
        "problems": problems,
        "saves": [],
        "selected": None,
        "window": None,
    }

    try:
        data["save_tool"] = str(ensure_savetool())
    except SaveFileError as exc:
        data["save_tool"] = None
        problems.append(str(exc))

    saves = discover_saves(settings)
    data["save_count"] = len(saves)
    for path in saves[:20]:
        entry: dict[str, Any] = {
            "path": str(path),
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                sep=" ", timespec="seconds"
            ),
        }
        try:
            header = read_header(path, settings=settings)
            mode = resolve_mode(header.gamemode, settings.gamemodes)
            entry.update(
                character=header.character_name,
                gamemode=header.gamemode,
                mode=mode.profile.display_name,
                level=header.total_level,
                action=header.active_action or "idle",
                uuid=header.uuid,
            )
        except SaveFileError as exc:
            entry["error"] = str(exc)
        data["saves"].append(entry)

    try:
        header = read_header(settings=settings)
        mode = resolve_mode(header.gamemode, settings.gamemodes)
        data["selected"] = {
            **header.to_dict(),
            "mode": {
                "raw": mode.raw,
                "matched": mode.matched,
                "key": mode.profile.key,
                "display_name": mode.profile.display_name,
                "permanent_death": mode.profile.permanent_death,
                "allow_risky_tasks": mode.profile.allow_risky_tasks,
                "min_hp_ratio": mode.profile.min_hp_ratio,
            },
            "formatted": format_header(header),
            "age_seconds": header.age_seconds,
        }
        if not mode.matched:
            problems.append(
                f"Unrecognized gamemode {mode.raw!r}; conservative profile "
                f"{mode.profile.key!r} is active."
            )
    except SaveFileError as exc:
        problems.append(str(exc))

    try:
        window = find_game_window(settings.game.window_title)
        data["window"] = {
            "describe": window.describe(),
            "hwnd": window.hwnd,
            "client_width": window.client_width,
            "client_height": window.client_height,
            "minimized": is_minimized(window.hwnd),
            "reference": list(REFERENCE_SIZE),
        }
        if is_minimized(window.hwnd):
            problems.append(
                "Game window is minimized. Restore it (covered or off-screen "
                "is fine); minimized windows capture black and cannot receive "
                "clicks."
            )
        display_w, display_h = monitor_size()
        data["display"] = {
            "width": display_w,
            "height": display_h,
            "scale": dpi_scale(),
        }
        resized = ensure_reference_size(window)
        data["window"]["client_width"] = resized.client_width
        data["window"]["client_height"] = resized.client_height
        ready, reason = layout_ready(resized)
        data["window"]["layout_ready"] = ready
        data["window"]["layout_reason"] = reason
        if not ready:
            problems.append(f"Game window layout is not usable: {reason}")
        image = ui.normalize(capture_client(resized))
        data["capture"] = {
            "width": image.width,
            "height": image.height,
            "mean_brightness": round(
                float(np.asarray(image.convert("L"), dtype=np.float32).mean()), 1
            ),
        }
    except (LookupError, OSError) as exc:
        data["window"] = {"error": str(exc)}
        problems.append(str(exc))

    data["ok"] = not problems
    return data


def format_diagnostics(data: dict[str, Any]) -> str:
    lines = ["MI2 AIO doctor"]
    lines.append(
        f"  python        {data.get('python')} ({data.get('architecture')})"
    )
    lines.append(f"  platform      {data.get('platform')}")
    lines.append(f"  mi2_aio       {data.get('version')}")
    packages = data.get("packages") or {}
    lines.append(
        "  packages      "
        + ", ".join(f"{name}={value}" for name, value in packages.items())
    )
    lines.append(f"  settings      {data.get('settings')}")
    lines.append(f"  logs          {data.get('logs')}")
    save_tool = data.get("save_tool")
    lines.append(
        f"  save tool     {save_tool if save_tool else 'FAILED'}"
    )
    lines.append(f"  saves found   {data.get('save_count', 0)}")
    for entry in data.get("saves", []):
        label = entry.get("character") or "?"
        action = entry.get("action", "")
        lines.append(
            f"                {entry.get('path')}  "
            f"({entry.get('modified')})  {label} {action}"
        )
    selected = data.get("selected")
    if selected:
        lines.append("  selected save")
        for line in str(selected.get("formatted", "")).splitlines():
            lines.append(f"                {line}")
        mode = selected.get("mode", {})
        lines.append(
            f"  mode          {mode.get('display_name')} "
            f"(key={mode.get('key')})"
        )
        lines.append(
            "                "
            f"permanent death={mode.get('permanent_death')} | "
            f"risky tasks={mode.get('allow_risky_tasks')} | "
            f"min hp={mode.get('min_hp_ratio')}"
        )
        age = selected.get("age_seconds")
        if age is not None:
            lines.append(f"  header age    {age:,.0f}s")

    window = data.get("window") or {}
    if window.get("error"):
        lines.append(f"  game window   FAILED ({window['error']})")
    else:
        lines.append(f"  game window   {window.get('describe')}")
        lines.append(
            f"  client size   {window.get('client_width')}x"
            f"{window.get('client_height')} (reference "
            f"{REFERENCE_SIZE[0]}x{REFERENCE_SIZE[1]})"
        )
        display = data.get("display") or {}
        lines.append(
            f"  display       {display.get('width')}x{display.get('height')} "
            f"at {round(float(display.get('scale', 1.0)) * 100)}% scale "
            "(physical pixels)"
        )
        capture = data.get("capture") or {}
        if capture:
            lines.append(
                f"  capture       {capture.get('width')}x{capture.get('height')}, "
                f"mean brightness {capture.get('mean_brightness')}"
            )
    problems = data.get("problems") or []
    if problems:
        lines.append("")
        lines.append("Problems:")
        for problem in problems:
            lines.append(f"  - {problem}")
    lines.append("")
    lines.append("RESULT: " + ("OK" if data.get("ok") else "PROBLEMS FOUND"))
    return "\n".join(lines)
