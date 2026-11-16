from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from mi2_aio import prayer as prayer_module
from mi2_aio import ui
from mi2_aio.config import PrayerSettings, Settings, load_settings
from mi2_aio.prayer import PrayerMaintenance, should_bury
from mi2_aio.savefile import SaveHeader
from mi2_aio.tasks.base import TaskContext
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


def header(
    *, bones: int = 0, prayer: int = 0, stacks: dict[str, int] | None = None
) -> SaveHeader:
    bank = dict(stacks or {})
    if bones:
        bank["Bone"] = bones
    return SaveHeader(
        save_version=28,
        uuid="X",
        character_name="DrinkWater",
        gamemode="Test",
        timestamp=None,
        active_entity="Combat",
        active_entity_icon="",
        active_action="Golbin",
        active_action_icon="",
        total_level=1,
        gp=0,
        slayer_coins=0,
        is_demo=True,
        bank_stacks=bank,
        prayer_points=prayer,
    )


def test_should_bury_batches_bones() -> None:
    settings = PrayerSettings(bone_threshold=50, low_prayer_threshold=100)
    assert should_bury(0, 0, settings) is False
    # Waiting for the batch: enough Prayer points and under 50 bones.
    assert should_bury(49, 100, settings) is False
    assert should_bury(49, 99, settings) is True
    # 50 bones trigger regardless of Prayer points.
    assert should_bury(50, 5000, settings) is True
    assert should_bury(51, 0, settings) is True


def test_should_bury_with_low_threshold_disabled() -> None:
    settings = PrayerSettings(bone_threshold=50, low_prayer_threshold=0)
    assert should_bury(49, 0, settings) is False
    assert should_bury(50, 0, settings) is True


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, **prayer: object) -> None:
        self.settings = Settings(prayer=PrayerSettings(**prayer))
        self.ctx = TaskContext(
            settings=self.settings,
            window=WINDOW,
            logger=logging.getLogger("test.prayer"),
            stop=threading.Event(),
        )
        self.prayer = PrayerMaintenance(self.settings)
        self.buried: list[int] = []
        self.prayer.bury = lambda ctx: self.buried.append(1) or (0, 0, None)  # type: ignore[method-assign]
        monkeypatch.setattr(
            prayer_module, "is_minimized", lambda hwnd: False
        )

    def poll(self, ctx_header: SaveHeader) -> None:
        self.ctx.header = ctx_header
        self.prayer._last_check = 0.0
        self.prayer.poll(self.ctx)


def test_poll_buries_when_the_batch_is_due(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.poll(header(bones=60, prayer=5000))
    assert h.buried == [1]


def test_poll_buries_when_prayer_is_low(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.poll(header(bones=3, prayer=2))
    assert h.buried == [1]


def test_poll_waits_for_a_batch(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.poll(header(bones=3, prayer=150))
    assert h.buried == []


def test_poll_without_bones_does_nothing(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.poll(header(bones=0, prayer=0))
    assert h.buried == []


def test_poll_disabled_does_nothing(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=False)
    h.poll(header(bones=60, prayer=0))
    assert h.buried == []


def test_poll_dry_run_sends_no_input(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True)
    h.ctx.dry_run = True
    h.poll(header(bones=60, prayer=0))
    assert h.buried == []


def test_poll_throttles_repeated_checks(monkeypatch) -> None:
    h = Harness(monkeypatch, enabled=True, check_seconds=60.0)
    h.ctx.header = header(bones=60, prayer=0)
    h.prayer.poll(h.ctx)
    h.prayer.poll(h.ctx)
    assert h.buried == [1]


def test_bank_bury_panel_detector() -> None:
    image = Image.new("RGB", ui.REFERENCE_SIZE, (30, 30, 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle(ui.BANK_BURY_GAIN_BOX, fill=(0, 200, 0))
    draw.rectangle(ui.BANK_BURY_ROW_BOX, fill=(235, 235, 235))
    assert ui.bank_bury_panel_visible(image) is True
    assert ui.bank_bury_row_visible(image) is True

    equip_panel = Image.new("RGB", ui.REFERENCE_SIZE, (30, 30, 30))
    assert ui.bank_bury_panel_visible(equip_panel) is False
    assert ui.bank_bury_row_visible(equip_panel) is False


def test_config_loads_prayer_settings(tmp_path: Path) -> None:
    config = tmp_path / "settings.toml"
    config.write_text(
        "[combat.prayer]\n"
        "enabled = true\n"
        "bone_threshold = 25\n"
        "low_prayer_threshold = 80\n"
        "check_seconds = 30\n"
        "verify_seconds = 5\n",
        encoding="utf-8",
    )
    settings = load_settings(config)
    assert settings.prayer.enabled is True
    assert settings.prayer.bone_threshold == 25
    assert settings.prayer.low_prayer_threshold == 80
    assert settings.prayer.check_seconds == 30.0
    assert settings.prayer.verify_seconds == 5.0
