from __future__ import annotations

import logging
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from mi2_aio import service as service_module
from mi2_aio import settings_io, ui
from mi2_aio.diagnostics import format_diagnostics
from mi2_aio.paths import PROJECT_ROOT
from mi2_aio.savefile import SaveHeader
from mi2_aio.service import AppService
from mi2_aio.status import IDLE


def _config(tmp_path: Path) -> Path:
    target = tmp_path / "settings.toml"
    shutil.copy(PROJECT_ROOT / "config" / "settings.default.toml", target)
    return target


def _header() -> SaveHeader:
    return SaveHeader(
        save_version=28,
        uuid="X",
        character_name="DrinkWater",
        gamemode="Test",
        timestamp=None,
        active_entity="Fishing",
        active_entity_icon="",
        active_action="Shimmering Depths",
        active_action_icon="",
        total_level=731,
        gp=90442,
        slayer_coins=24422,
        is_demo=True,
        bank_stacks={"Bone": 12, "BoneScythe": 2},
        prayer_points=99,
    )


def test_service_settings_roundtrip(tmp_path: Path) -> None:
    path = _config(tmp_path)
    service = AppService(path, logger=logging.getLogger("test.service"))
    service.save_settings({"combat.prayer.bone_threshold": 25})
    assert service.settings.prayer.bone_threshold == 25
    assert settings_io.read_values(path)["combat.prayer.bone_threshold"] == 25
    service.save_settings({"farming.prioritise": False})
    assert service.settings.farming.prioritise is False
    assert settings_io.read_values(path)["farming.prioritise"] is False


def test_reset_settings_restores_bundled_defaults(tmp_path: Path) -> None:
    path = _config(tmp_path)
    service = AppService(path, logger=logging.getLogger("test.service"))
    service.save_settings(
        {
            "combat.slayer.max_tasks": 9,
            "combat.prayer.bone_threshold": 7,
            "automation.background_input": False,
        }
    )
    settings = service.reset_settings()
    assert settings.slayer.max_tasks == 0
    assert settings.prayer.bone_threshold == 50
    assert settings.automation.background_input is True
    text = path.read_text(encoding="utf-8")
    assert "# Stop after this many completed Slayer tasks" in text
    assert "max_tasks = 0" in text


def test_idle_status_uses_save_and_probe(tmp_path: Path, monkeypatch) -> None:
    path = _config(tmp_path)
    service = AppService(path, logger=logging.getLogger("test.service"))
    monkeypatch.setattr(service, "_probe", lambda: (0.5, "enabled", True))
    monkeypatch.setattr("mi2_aio.service.read_header", lambda **_: _header())
    status = service.idle_status()
    assert status.state == IDLE
    assert status.character == "DrinkWater"
    assert status.action == "Shimmering Depths"
    assert status.prayer_points == 99
    assert status.bones == 12
    assert status.hp_ratio == 0.5
    assert status.food == "enabled"


def test_idle_status_prefers_save_hp(tmp_path: Path, monkeypatch) -> None:
    path = _config(tmp_path)
    service = AppService(path, logger=logging.getLogger("test.service"))
    monkeypatch.setattr(service, "_probe", lambda: (0.1, "enabled", True))
    header = replace(_header(), current_hp=400, max_hp=510)
    monkeypatch.setattr("mi2_aio.service.read_header", lambda **_: header)
    status = service.idle_status()
    assert status.hp_ratio == pytest.approx(400 / 510)


def test_idle_status_probes_once_until_refreshed(tmp_path: Path, monkeypatch) -> None:
    path = _config(tmp_path)
    service = AppService(path, logger=logging.getLogger("test.service"))
    window = SimpleNamespace(hwnd=1)
    captures = []

    monkeypatch.setattr(service_module, "find_game_window", lambda *_: window)
    monkeypatch.setattr(service_module, "is_minimized", lambda _hwnd: False)
    monkeypatch.setattr(service_module, "ensure_reference_size", lambda w: w)
    monkeypatch.setattr(
        service_module,
        "capture_client",
        lambda _w: Image.new("RGB", ui.REFERENCE_SIZE),
    )
    monkeypatch.setattr(
        service_module.ui, "hp_ratio", lambda _image: captures.append(1) or 0.5
    )
    monkeypatch.setattr(service_module.ui, "eat_button_state", lambda _image: "enabled")
    monkeypatch.setattr(service_module.ui, "ammo_available", lambda _image: True)
    monkeypatch.setattr("mi2_aio.service.read_header", lambda **_: _header())

    first = service.idle_status()
    second = service.idle_status()
    assert first.hp_ratio == second.hp_ratio == 0.5
    assert first.food == "enabled"
    assert len(captures) == 1
    service.refresh_health()
    assert len(captures) == 2


def test_diagnostics_text_is_renderable() -> None:
    data = {
        "ok": True,
        "python": "3.12",
        "architecture": "AMD64",
        "platform": "Windows",
        "version": "0.1.0",
        "packages": {"PySide6": "6.12.0"},
        "settings": "config/settings.toml",
        "logs": "logs",
        "save_tool": "SaveTool.exe",
        "save_count": 0,
        "saves": [],
        "selected": None,
        "window": {"error": "not found"},
        "problems": [],
    }
    text = format_diagnostics(data)
    assert "MI2 AIO doctor" in text
    assert "RESULT: OK" in text
    assert "not found" in text
