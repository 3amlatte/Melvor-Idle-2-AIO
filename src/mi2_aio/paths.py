"""Project, user-data and resource paths.

Development runs use the repository; a frozen/bundled app keeps read-only
resources next to the executable and writes configuration/logs under
``%APPDATA%\\MI2 AIO``. Everything else asks this module instead of guessing.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "MI2 AIO"
FROZEN = bool(getattr(sys, "frozen", False))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# A PyInstaller bundle exposes resources under sys._MEIPASS; a simple copied
# folder layout uses a "resources" directory next to the executable.
if FROZEN:
    RESOURCE_ROOT = Path(
        getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent / "resources")
    )
else:
    RESOURCE_ROOT = PROJECT_ROOT

USER_DATA_DIR = Path(
    os.environ.get(
        "APPDATA",
        str(Path.home() / "AppData" / "Roaming" if os.name == "nt" else Path.home() / ".local" / "share"),
    )
) / APP_NAME
USER_CONFIG_DIR = USER_DATA_DIR / "config"
USER_CONFIG_FILE = USER_CONFIG_DIR / "settings.toml"
USER_LOGS_DIR = USER_DATA_DIR / "logs"

DEFAULT_CONFIG_FILE = RESOURCE_ROOT / "config" / "settings.default.toml"
DEV_CONFIG_FILE = RESOURCE_ROOT / "config" / "settings.toml"
CONFIG_DIR = USER_CONFIG_DIR if FROZEN else DEV_CONFIG_FILE.parent
CONFIG_FILE = USER_CONFIG_FILE if FROZEN else DEV_CONFIG_FILE
LOGS_DIR = USER_LOGS_DIR if FROZEN else PROJECT_ROOT / "logs"
ERRORS_DIR = LOGS_DIR / "errors"
ASSETS_DIR = RESOURCE_ROOT / "assets"
DATA_DIR = RESOURCE_ROOT / "data"
STOP_FILE_DIR = USER_DATA_DIR if FROZEN else PROJECT_ROOT

TOOLS_DIR = RESOURCE_ROOT / "tools"
SAVETOOL_PROJECT = TOOLS_DIR / "SaveTool" / "SaveTool.csproj"
SAVETOOL_BIN_DIR = TOOLS_DIR / "bin"
SAVETOOL_EXE = SAVETOOL_BIN_DIR / "SaveTool.exe"
BUILD_SCRIPT = TOOLS_DIR.parent / "scripts" / "build_savetool.ps1"

DEFAULT_SAVE_ROOT = Path(
    os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
) / "Games By Malcs" / "Melvor Idle 2"


def ensure_runtime_dirs() -> None:
    """Create writable directories and seed the user config on first run."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ERRORS_DIR.mkdir(parents=True, exist_ok=True)
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if FROZEN:
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not USER_CONFIG_FILE.exists() and DEFAULT_CONFIG_FILE.exists():
            shutil.copy2(DEFAULT_CONFIG_FILE, USER_CONFIG_FILE)
    else:
        (ASSETS_DIR / "templates").mkdir(parents=True, exist_ok=True)


def stop_file_path(name: str) -> Path:
    return STOP_FILE_DIR / name


def resolve_resource(path: str | Path) -> Path:
    """Resolve a user/config path against the resource folder."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    resource = RESOURCE_ROOT / candidate
    if resource.exists():
        return resource
    project = PROJECT_ROOT / candidate
    return project if project.exists() else resource
