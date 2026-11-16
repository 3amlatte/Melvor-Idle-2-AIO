from __future__ import annotations

import os
import subprocess
import time
from types import SimpleNamespace

import pytest

from mi2_aio import savefile


def test_header_cache_reuses_until_the_save_changes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "save.sav"
    path.write_bytes(b"save")
    calls: list[int] = []
    sentinel = object()

    def fake_read(save_path, retries=3):
        calls.append(1)
        return sentinel

    monkeypatch.setattr(savefile, "_read_header_uncached", fake_read)
    savefile._HEADER_CACHE.clear()
    try:
        assert savefile.read_header(path) is sentinel
        assert savefile.read_header(path) is sentinel
        assert len(calls) == 1

        # A new autosave changes mtime/size and must invalidate the cache.
        path.write_bytes(b"save-new")
        os.utime(path, (time.time() + 2, time.time() + 2))
        assert savefile.read_header(path) is sentinel
        assert len(calls) == 2
    finally:
        savefile._HEADER_CACHE.clear()


def test_save_reader_hides_the_console_window(tmp_path, monkeypatch) -> None:
    if os.name != "nt":
        pytest.skip("CREATE_NO_WINDOW is Windows-specific")
    tool = tmp_path / "SaveTool.exe"
    tool.write_bytes(b"")
    output = tmp_path / "snapshot.raw"
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        output.write_bytes(b"raw")
        return SimpleNamespace(returncode=0, stdout="1", stderr="")

    monkeypatch.setattr(savefile, "ensure_savetool", lambda: tool)
    monkeypatch.setattr(savefile.subprocess, "run", fake_run)
    savefile.decompress_save(tmp_path / "input.sav", output)

    assert captured["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert captured["startupinfo"] is not None
