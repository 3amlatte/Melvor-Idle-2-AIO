from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mi2_aio import savefile
from mi2_aio.config import SaveSettings, Settings
from mi2_aio.savefile import SaveFileError, select_save


def _fake_saves(tmp_path: Path) -> list[Path]:
    paths = [
        tmp_path / "save_aaaa1111-0000-0000-0000-000000000001.sav",
        tmp_path / "save_bbbb2222-0000-0000-0000-000000000002.sav",
    ]
    for path in paths:
        path.write_bytes(b"not a real save")
    return paths


def _patch(monkeypatch: pytest.MonkeyPatch, paths: list[Path], names: dict[str, str]):
    monkeypatch.setattr(savefile, "discover_saves", lambda settings=None: paths)
    monkeypatch.setattr(
        savefile,
        "read_header",
        lambda path, settings=None, retries=3: SimpleNamespace(
            character_name=names[path.name]
        ),
    )


def test_empty_selector_uses_newest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _fake_saves(tmp_path)
    _patch(monkeypatch, paths, {})
    assert select_save(Settings()) == paths[0]


def test_uuid_fragment_selects_one_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _fake_saves(tmp_path)
    _patch(monkeypatch, paths, {})
    settings = Settings(save=SaveSettings(character="bbbb2222"))
    assert select_save(settings) == paths[1]


def test_character_name_is_case_insensitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _fake_saves(tmp_path)
    _patch(
        monkeypatch,
        paths,
        {
            paths[0].name: "DrinkWater",
            paths[1].name: "HardcoreGuy",
        },
    )
    settings = Settings(save=SaveSettings(character="hardcoreguy"))
    assert select_save(settings) == paths[1]


def test_ambiguous_name_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _fake_saves(tmp_path)
    _patch(
        monkeypatch,
        paths,
        {paths[0].name: "Same", paths[1].name: "Same"},
    )
    with pytest.raises(SaveFileError, match="matches multiple"):
        select_save(Settings(save=SaveSettings(character="Same")))


def test_unknown_selector_lists_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _fake_saves(tmp_path)
    _patch(
        monkeypatch,
        paths,
        {paths[0].name: "DrinkWater", paths[1].name: "HardcoreGuy"},
    )
    with pytest.raises(SaveFileError) as excinfo:
        select_save(Settings(save=SaveSettings(character="Nobody")))
    assert "DrinkWater" in str(excinfo.value)
    assert "HardcoreGuy" in str(excinfo.value)
