"""Startup-check dialog for the desktop app."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .preflight import FAIL, OK, WARN, PreflightResult, format_report, run_preflight

STATUS_STYLE = {
    OK: ("OK", "#7fd6a4"),
    WARN: ("!", "#e6c35c"),
    FAIL: ("X", "#ff8b8b"),
}
SETTINGS_KEY = "preflight_seen"


class PreflightDialog(QDialog):
    """Show the checks that need attention, with copy/retry actions."""

    def __init__(
        self,
        result: PreflightResult,
        settings,
        parent=None,
        *,
        show_all: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MI2 AIO startup check")
        self.resize(780, 540)
        self.result = result
        self.settings = settings
        self._show_all = show_all

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copy details")
        self.copy_button.clicked.connect(self._copy)
        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self._retry)
        close_button = QPushButton("Close")
        close_button.setObjectName("startButton")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.retry_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._populate()

    # -- state -----------------------------------------------------------
    def _populate(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        checks = [
            check
            for check in self.result.checks
            if self._show_all or check.state != OK
        ]
        if not checks:
            checks = list(self.result.checks)

        for check in checks:
            self.body_layout.addWidget(self._card(check))
        self.body_layout.addStretch(1)

        if self.result.failed:
            self.summary.setText(
                "Some required items are missing. Fix the items marked X, "
                "then click Retry. MI2 AIO can still open, but tasks will not "
                "run correctly until these are fixed."
            )
        elif self.result.warnings:
            self.summary.setText(
                "MI2 AIO is installed. Review the items marked ! when "
                "convenient, then click Retry."
            )
        else:
            self.summary.setText(
                "Everything required is installed. MI2 AIO is ready to run."
            )

    def _card(self, check) -> QFrame:
        card = QFrame()
        card.setObjectName("preflightCard")
        card.setStyleSheet(
            "QFrame#preflightCard { background: #24262a;"
            " border: 1px solid #35373c; border-radius: 6px; }"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)

        label, color = STATUS_STYLE.get(check.state, ("?", "#d0d0d0"))
        status = QLabel(label)
        status.setFixedWidth(28)
        status.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignCenter)
        status.setStyleSheet(
            f"color: {color}; font-weight: 700; background: transparent;"
            " border: none;"
        )
        row.addWidget(status)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(check.title)
        title.setStyleSheet(
            "font-weight: 600; background: transparent; border: none;"
        )
        detail = QLabel(check.detail)
        detail.setWordWrap(True)
        detail.setStyleSheet(
            "color: #b9bdc4; background: transparent; border: none;"
        )
        text.addWidget(title)
        text.addWidget(detail)
        if check.fix:
            fix = QLabel("Fix: " + check.fix)
            fix.setWordWrap(True)
            fix.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            fix.setStyleSheet(
                "color: #ffd8a8; background: transparent; border: none;"
            )
            text.addWidget(fix)
        row.addLayout(text, 1)
        return card

    # -- actions ---------------------------------------------------------
    def _copy(self) -> None:
        QApplication.clipboard().setText(format_report(self.result))

    def _retry(self) -> None:
        self.result = run_preflight(self.settings)
        self._populate()


def show_startup_check(
    settings,
    parent=None,
    *,
    force: bool = False,
) -> PreflightResult:
    """Run the checks and show the dialog when needed.

    The first launch shows warnings (game closed, no save yet). Required
    failures are shown on every launch until fixed. A manual check from
    Diagnostics always shows every result.
    """
    store = QSettings("MI2 AIO", "MI2 AIO")
    seen = store.value(SETTINGS_KEY, False, type=bool)
    result = run_preflight(settings)
    stale_build = any(
        check.key == "build" and check.state != OK
        for check in result.checks
    )

    if (
        not force
        and not result.failed
        and not stale_build
        and not (not seen and result.warnings)
    ):
        if not seen:
            store.setValue(SETTINGS_KEY, True)
        return result

    dialog = PreflightDialog(
        result,
        settings,
        parent,
        show_all=force or not seen or stale_build,
    )
    dialog.exec()
    store.setValue(SETTINGS_KEY, True)
    return dialog.result
