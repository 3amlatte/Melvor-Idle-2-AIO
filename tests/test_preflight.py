from __future__ import annotations

from pathlib import Path

from mi2_aio import preflight
from mi2_aio.config import Settings
from mi2_aio.preflight import (
    Check,
    PreflightResult,
    check_environment,
    check_runtime,
    format_report,
)


def test_environment_checks_are_identified() -> None:
    result = check_environment()
    by_key = {check.key: check for check in result.checks}
    assert {"platform", "python", "packages", "savetool"} <= set(by_key)
    assert by_key["platform"].ok
    assert by_key["python"].ok
    assert by_key["packages"].ok


def test_missing_packages_explain_the_install_command(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "_missing_modules", lambda: ["PySide6"])
    check = preflight._packages_check()
    assert check.failed
    assert "PySide6" in check.detail
    assert "pip install" in check.fix


def test_runtime_checks_warn_without_game_or_saves(monkeypatch) -> None:
    def no_saves(settings):
        return []

    def no_window(title):
        raise LookupError("no Melvor2 window")

    monkeypatch.setattr("mi2_aio.savefile.discover_saves", no_saves)
    monkeypatch.setattr("mi2_aio.window.find_game_window", no_window)
    result = check_runtime(Settings())
    by_key = {check.key: check for check in result.checks}
    assert by_key["saves"].state == preflight.WARN
    assert by_key["game"].state == preflight.WARN
    assert not result.failed


def test_runtime_checks_pass_with_saves_and_window(monkeypatch) -> None:
    class FakeWindow:
        def describe(self) -> str:
            return "Melvor2 2560x1369"

    monkeypatch.setattr(
        "mi2_aio.savefile.discover_saves",
        lambda settings: [Path("save_test.sav")],
    )
    monkeypatch.setattr(
        "mi2_aio.window.find_game_window", lambda title: FakeWindow()
    )
    result = check_runtime(Settings())
    by_key = {check.key: check for check in result.checks}
    assert by_key["saves"].ok
    assert by_key["game"].ok
    assert not result.failed


def test_report_sorts_states_and_includes_fixes() -> None:
    result = PreflightResult(
        (
            Check("ok", "Ready thing", preflight.OK, "fine"),
            Check("warn", "Optional thing", preflight.WARN, "check it", "Do X"),
            Check("fail", "Missing thing", preflight.FAIL, "not found", "Install Y"),
        )
    )
    report = format_report(result)
    assert "[OK] Ready thing" in report
    assert "[WARN] Optional thing" in report
    assert "[FAIL] Missing thing" in report
    assert "Install Y" in report
    assert "cannot run correctly" in report
