"""Startup checks for the tools MI2 AIO needs.

The module is intentionally stdlib-only so the console launcher can run it
before importing PySide6 (or any other third-party package).
"""

from __future__ import annotations

import importlib.util
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .paths import FROZEN, SAVETOOL_EXE

MIN_PYTHON = (3, 11)
MIN_DOTNET_MAJOR = 8

# import name -> package name shown to the user
REQUIRED_MODULES: tuple[tuple[str, str], ...] = (
    ("PySide6", "PySide6"),
    ("PIL", "Pillow"),
    ("numpy", "NumPy"),
    ("cv2", "opencv-python"),
    ("pyautogui", "pyautogui"),
    ("tomlkit", "tomlkit"),
)

OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True)
class Check:
    key: str
    title: str
    state: str
    detail: str
    fix: str = ""

    @property
    def ok(self) -> bool:
        return self.state == OK

    @property
    def failed(self) -> bool:
        return self.state == FAIL


@dataclass(frozen=True)
class PreflightResult:
    checks: tuple[Check, ...]

    @property
    def failed(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if check.state == FAIL)

    @property
    def warnings(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if check.state == WARN)

    @property
    def ok(self) -> bool:
        return not self.failed


def format_report(result: PreflightResult) -> str:
    lines = ["MI2 AIO startup check", ""]
    labels = {OK: "[OK]", WARN: "[WARN]", FAIL: "[FAIL]"}
    for check in result.checks:
        lines.append(f"{labels.get(check.state, '[?]')} {check.title}: {check.detail}")
        if check.fix:
            for line in check.fix.splitlines():
                lines.append(f"       {line}")
    if result.failed:
        lines.append("")
        lines.append(
            "MI2 AIO cannot run correctly until the FAIL items above are fixed."
        )
    elif result.warnings:
        lines.append("")
        lines.append("MI2 AIO is installed; review the WARN items when convenient.")
    else:
        lines.append("")
        lines.append("Everything required is installed.")
    return "\n".join(lines)


def _platform_check() -> Check:
    is_windows = sys.platform == "win32" or platform.system() == "Windows"
    if is_windows:
        return Check(
            "platform",
            "Operating system",
            OK,
            f"{platform.system()} {platform.release()}",
        )
    return Check(
        "platform",
        "Operating system",
        FAIL,
        f"{platform.system()} is not supported.",
        "MI2 AIO runs on Windows 10 or 11. Run it on a Windows PC (a VM is fine).",
    )


def _python_check() -> Check:
    version = sys.version.split()[0]
    if sys.version_info >= MIN_PYTHON:
        return Check("python", "Python", OK, version)
    needed = ".".join(str(part) for part in MIN_PYTHON)
    return Check(
        "python",
        "Python",
        FAIL,
        f"{version} is too old; Python {needed}+ is required.",
        "Install Python 3.11 or newer from https://www.python.org/downloads/ "
        "and enable 'Add python.exe to PATH'.",
    )


def _missing_modules() -> list[str]:
    importlib.invalidate_caches()
    missing: list[str] = []
    for module, label in REQUIRED_MODULES:
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            missing.append(label)
    return missing


def _packages_check() -> Check:
    missing = _missing_modules()
    if not missing:
        return Check(
            "packages",
            "Python packages",
            OK,
            "all required packages are importable",
        )
    if FROZEN:
        fix = (
            "The packaged app is incomplete. Reinstall MI2 AIO from the "
            "release archive."
        )
    else:
        fix = (
            "From the project folder run:\n"
            '  pip install -e ".[dev]"\n'
            "or:\n"
            "  pip install -r requirements.txt"
        )
    return Check(
        "packages",
        "Python packages",
        FAIL,
        "missing: " + ", ".join(missing),
        fix,
    )


def _hidden_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def dotnet_sdks() -> list[str]:
    """Return installed .NET SDK version lines, or [] when dotnet is absent."""
    exe = shutil.which("dotnet")
    if exe is None:
        return []
    try:
        result = subprocess.run(
            [exe, "--list-sdks"],
            capture_output=True,
            text=True,
            timeout=20,
            **_hidden_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _sdk_major(line: str) -> int:
    match = re.match(r"(\d+)\.", line)
    return int(match.group(1)) if match else 0


def _local_build_check() -> Check:
    if not FROZEN:
        return Check("build", "Build version", OK, "source run")
    try:
        exe = Path(sys.executable)
        repo = exe.parents[2] if len(exe.parents) >= 3 else None
        pyproject = repo / "pyproject.toml" if repo is not None else None
        if pyproject is None or not pyproject.exists():
            return Check(
                "build", "Build version", OK, f"{__version__} (packaged)"
            )
        text = pyproject.read_text(encoding="utf-8")
        match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
        source = match.group(1) if match else ""
        if source and source != __version__:
            return Check(
                "build",
                "Build version",
                WARN,
                f"portable build {__version__} does not match source {source}",
                "Run scripts\\package_app.ps1, or launch with launch_dist.cmd "
                "to rebuild automatically.",
            )
        return Check("build", "Build version", OK, __version__)
    except Exception:
        return Check("build", "Build version", OK, f"{__version__} (packaged)")


def _savetool_check() -> Check:
    if SAVETOOL_EXE.exists():
        return Check(
            "savetool",
            "Save reader helper",
            OK,
            str(SAVETOOL_EXE),
        )

    sdks = dotnet_sdks()
    modern = [line for line in sdks if _sdk_major(line) >= MIN_DOTNET_MAJOR]
    if FROZEN:
        return Check(
            "savetool",
            "Save reader helper",
            FAIL,
            "tools/bin/SaveTool.exe is missing from the packaged app.",
            "Reinstall MI2 AIO from the release archive.",
        )
    if modern:
        return Check(
            "savetool",
            "Save reader helper",
            OK,
            ".NET SDK found; the helper will be built on first use",
        )
    if sdks:
        detail = (
            ".NET SDK is too old (found "
            + sdks[0]
            + f"; {MIN_DOTNET_MAJOR}.0+ is required)."
        )
    else:
        detail = "The .NET SDK is not installed."
    return Check(
        "savetool",
        "Save reader helper",
        FAIL,
        detail,
        "Install the .NET 8 SDK:\n"
        "  winget install Microsoft.DotNet.SDK.8\n"
        "Then run:\n"
        "  python -m mi2_aio doctor",
    )


def check_environment() -> PreflightResult:
    """OS, Python, packages and SaveTool (safe before importing the app)."""
    return PreflightResult(
        (
            _platform_check(),
            _python_check(),
            _packages_check(),
            _savetool_check(),
        )
    )


def check_runtime(settings) -> PreflightResult:
    """Settings, saves and the game window (needs the app modules)."""
    checks: list[Check] = []

    source = getattr(settings, "source", None)
    if source is None:
        fix = (
            "Copy config/settings.default.toml to config/settings.toml "
            "(development), or let the app save a settings file."
        )
        checks.append(
            Check(
                "settings",
                "Settings file",
                WARN,
                "using built-in defaults",
                fix,
            )
        )
    else:
        checks.append(
            Check("settings", "Settings file", OK, str(source))
        )

    try:
        from .savefile import discover_saves

        saves = discover_saves(settings)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        checks.append(
            Check(
                "saves",
                "Melvor saves",
                FAIL,
                f"could not search for saves: {exc}",
                "Run python -m mi2_aio doctor and check [save].root in "
                "config/settings.toml.",
            )
        )
    else:
        if saves:
            checks.append(
                Check(
                    "saves",
                    "Melvor saves",
                    OK,
                    f"{len(saves)} save file(s) found",
                )
            )
        else:
            checks.append(
                Check(
                    "saves",
                    "Melvor saves",
                    WARN,
                    "no save files found",
                    "Start Melvor Idle 2, create or load a character, and save "
                    "once. If your saves are in a custom folder, set "
                    "[save].root in config/settings.toml.",
                )
            )

    try:
        from .window import find_game_window

        window = find_game_window(settings.game.window_title)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        checks.append(
            Check(
                "game",
                "Melvor window",
                WARN,
                str(exc),
                "Start Melvor Idle 2 from Steam, then click Retry.",
            )
        )
    else:
        checks.append(
            Check("game", "Melvor window", OK, window.describe())
        )

    checks.append(_local_build_check())
    return PreflightResult(tuple(checks))


def run_preflight(settings) -> PreflightResult:
    """Full check used by the desktop app."""
    environment = check_environment()
    if environment.failed:
        # Runtime imports may fail or produce misleading errors when the core
        # install is broken; stop here.
        return environment
    runtime = check_runtime(settings)
    return PreflightResult(environment.checks + runtime.checks)


def main() -> int:
    """Console entry point used by launch_ui.cmd before starting the GUI."""
    result = check_environment()
    print(format_report(result))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
