"""MI2 AIO desktop application (PySide6).

The app is a thin front end over :mod:`mi2_aio.service`: it never touches the
game directly, and the runner communicates through ``RunController`` status and
the shared logger.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QIntValidator,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from . import status as st
from .bones import item_name as pretty_name
from .config import load_settings
from .cooking_db import load_cooking
from .diagnostics import collect_diagnostics
from .fishing_db import load_fishing
from .instance import SingleInstance
from .log import get_logger
from .overlay import OverlayWindow
from .paths import ASSETS_DIR, CONFIG_FILE, LOGS_DIR, ensure_runtime_dirs
from .savefile import (
    MAX_TOTAL_LEVEL,
    SKILL_NAMES,
    UNAVAILABLE_SKILLS,
)
from .service import AppService, ServiceError
from .settings_schema import (
    BOOL,
    CHOICE,
    FLOAT,
    INT,
    LIST_STR,
    PAIR_INT,
    POINT,
    SECTIONS,
    feature_sections,
)
from .status import RunStatus, bot_state_label
from .window import find_game_window, is_minimized

APP_LOG_NAME = "app.log"


# --------------------------------------------------------------------------
# Qt bridges (worker threads -> GUI thread)
# --------------------------------------------------------------------------
class StatusBridge(QObject):
    status = Signal(object)


class LogBridge(QObject):
    message = Signal(str)


class JobBridge(QObject):
    finished = Signal(object)
    failed = Signal(str)


class PointBridge(QObject):
    captured = Signal(object)
    failed = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: LogBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.message.emit(self.format(record))
        except Exception:
            pass


# --------------------------------------------------------------------------
# Small editor widgets
# --------------------------------------------------------------------------
class PairEditor(QWidget):
    def __init__(self, spec) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.first = QSpinBox()
        self.second = QSpinBox()
        low = int(spec.minimum or 0)
        high = int(spec.maximum or 1_000_000)
        step = int(spec.step or 1)
        for box in (self.first, self.second):
            box.setRange(low, high)
            box.setSingleStep(step)
            layout.addWidget(box)

    def value(self) -> list[int]:
        return [self.first.value(), self.second.value()]

    def set_value(self, values) -> None:
        if values and len(values) == 2:
            self.first.setValue(int(values[0]))
            self.second.setValue(int(values[1]))


class NumberInput(QWidget):
    """A typed number field with an always-visible unit and no spin buttons.

    Used for task amounts and durations. The value is read with :meth:`value`;
    an empty field counts as 0, and 0 means "no limit / until stopped" for the
    duration and cooking amount fields.
    """

    valueChanged = Signal(int)

    def __init__(
        self,
        *,
        unit: str = "",
        maximum: int = 1_000_000,
        value: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("numberInput")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#numberInput { background: #26272b;"
            " border: 1px solid #3b3e44; border-radius: 4px; }"
            "QLineEdit#numberInputEdit { background: transparent; border: none;"
            " padding: 0; color: #e6e6e6; selection-background-color: #2d6a4f; }"
            "QLabel#numberInputUnit { background: transparent; color: #b9bdc4; }"
        )
        self._maximum = max(0, int(maximum))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 0, 4, 0)
        layout.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.setObjectName("numberInputEdit")
        self.edit.setFrame(False)
        self.edit.setValidator(QIntValidator(0, self._maximum, self))
        self.unit_label = None
        if unit:
            self.edit.setFixedWidth(45)
            self.edit.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            layout.addWidget(self.edit, 0)
            self.unit_label = QLabel(unit)
            self.unit_label.setObjectName("numberInputUnit")
            layout.addWidget(self.unit_label, 0)
            layout.addStretch(1)
        else:
            layout.addWidget(self.edit, 1)
        self.setFixedHeight(26)
        self.setValue(value)
        self.edit.textChanged.connect(self._emit_value)

    def _emit_value(self, _text: str) -> None:
        self.valueChanged.emit(self.value())

    def value(self) -> int:
        text = self.edit.text().strip()
        if not text:
            return 0
        try:
            number = int(text)
        except ValueError:
            return 0
        return min(max(0, number), self._maximum)

    def setValue(self, value: int) -> None:
        number = min(max(0, int(value)), self._maximum)
        self.edit.setText(str(number))

    def text(self) -> str:
        return self.edit.text()

    def mousePressEvent(self, event) -> None:
        # The frame belongs to this widget; focus the editor when its padding or
        # unit label is clicked too.
        self.edit.setFocus()
        super().mousePressEvent(event)


class PathEditor(QWidget):
    def __init__(self, value: str, *, directory: bool, image: bool = False) -> None:
        super().__init__()
        self.directory = directory
        self.image = image
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.edit = QLineEdit(str(value or ""))
        button = QPushButton("…")
        button.setFixedWidth(30)
        button.clicked.connect(self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(button)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, value) -> None:
        self.edit.setText(str(value or ""))

    def _browse(self) -> None:
        if self.directory:
            path = QFileDialog.getExistingDirectory(self, "Choose folder", self.edit.text())
        else:
            filters = "Images (*.png *.jpg *.jpeg);;All files (*.*)" if self.image else "All files (*.*)"
            path, _ = QFileDialog.getOpenFileName(self, "Choose file", self.edit.text(), filters)
        if path:
            self.edit.setText(path)


# --------------------------------------------------------------------------
# Fallback learning wizard
# --------------------------------------------------------------------------
class FallbackWizard(QDialog):
    """Learn the idle-failsafe page icon and action button from real clicks."""

    def __init__(self, service: AppService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.page_point: tuple[int, int] | None = None
        self.button_point: tuple[int, int] | None = None
        self._capturing = ""
        self._stop = threading.Event()
        self._bridge: PointBridge | None = None
        self._thread: threading.Thread | None = None

        self.setWindowTitle("Learn fallback action")
        self.setModal(True)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "This records where the bot should click when the character is idle.\n\n"
            "1. Bring Melvor to the front and open the fallback skill page.\n"
            "2. Click the skill's sidebar icon.\n"
            "3. Click the action's Start button (for example Spikemoss Shrub).\n\n"
            "The wizard hides while it waits for each click."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.page_label = QLabel("Page icon: not captured")
        self.button_label = QLabel("Action button: not captured")
        layout.addWidget(self.page_label)
        layout.addWidget(self.button_label)

        buttons = QHBoxLayout()
        self.capture_page = QPushButton("Capture page icon")
        self.capture_action = QPushButton("Capture action button")
        self.capture_page.clicked.connect(lambda: self._capture("page"))
        self.capture_action.clicked.connect(lambda: self._capture("button"))
        buttons.addWidget(self.capture_page)
        buttons.addWidget(self.capture_action)
        layout.addLayout(buttons)

        form = QFormLayout()
        self.action_edit = QLineEdit()
        status = self.service.idle_status()
        self.action_edit.setText(status.action or self.service.settings.failsafe.action)
        form.addRow("Action name", self.action_edit)
        layout.addLayout(form)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.save_button = QPushButton("Save fallback")
        self.save_button.setObjectName("startButton")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)

    def _capture(self, kind: str) -> None:
        if self._capturing:
            return
        self._capturing = kind
        self._stop.clear()
        self.capture_page.setEnabled(False)
        self.capture_action.setEnabled(False)
        self.save_button.setEnabled(False)
        self.status_label.setText(
            "Waiting for your click in the Melvor window… switch to the game and click."
        )
        try:
            from .window import find_game_window, focus

            focus(find_game_window(self.service.settings.game.window_title).hwnd)
        except Exception:
            pass
        self.hide()
        bridge = PointBridge(self)
        self._bridge = bridge
        bridge.captured.connect(self._captured)
        bridge.failed.connect(self._failed)
        self._thread = threading.Thread(
            target=self._worker,
            args=(bridge,),
            name="mi2-point-capture",
            daemon=True,
        )
        self._thread.start()

    def _worker(self, bridge: PointBridge) -> None:
        from .capture_points import CaptureError, capture_next_click

        try:
            point = capture_next_click(
                self.service.settings, self._stop, timeout=30.0
            )
            bridge.captured.emit(point)
        except CaptureError as exc:
            bridge.failed.emit(str(exc))
        except Exception as exc:
            bridge.failed.emit(str(exc))

    def _restore(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._capturing = ""
        self.capture_page.setEnabled(self.page_point is None)
        self.capture_action.setEnabled(True)
        self.save_button.setEnabled(
            self.page_point is not None and self.button_point is not None
        )

    def _captured(self, point) -> None:
        kind = self._capturing
        self._restore()
        value = (int(point[0]), int(point[1]))
        if kind == "page":
            self.page_point = value
            self.page_label.setText(f"Page icon: {value}")
        else:
            self.button_point = value
            self.button_label.setText(f"Action button: {value}")
        self.status_label.setText(f"Captured {value} in reference coordinates.")

    def _failed(self, message: str) -> None:
        self._restore()
        self.status_label.setText(message)
        QMessageBox.warning(self, "Capture failed", message)

    def _save(self) -> None:
        if self.page_point is None or self.button_point is None:
            return
        action = self.action_edit.text().strip()
        if not action:
            QMessageBox.warning(self, "Fallback", "Enter the fallback action name.")
            return
        try:
            self.service.save_settings(
                {
                    "failsafe.enabled": True,
                    "failsafe.action": action,
                    "failsafe.page": list(self.page_point),
                    "failsafe.button": list(self.button_point),
                }
            )
        except Exception as exc:
            QMessageBox.warning(self, "Fallback", str(exc))
            return
        self.accept()

    def reject(self) -> None:
        self._stop.set()
        super().reject()


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
class NoFocusRectDelegate(QStyledItemDelegate):
    """Draw list items without the keyboard-focus outline.

    The Features category sidebar is click-driven, and the focus rectangle the
    style paints inside the selected bubble reads as a stray border. Keyboard
    focus still works; only the visual outline is suppressed.
    """

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.state &= ~QStyle.StateFlag.State_HasFocus


class MainWindow(QMainWindow):
    def __init__(self, service: AppService, logger: logging.Logger) -> None:
        super().__init__()
        self.service = service
        self.logger = logger
        self._status = RunStatus()
        self._hold_final_until = 0.0
        self._last_idle_refresh = 0.0
        self._last_window_refresh = 0.0
        self._farming_job = False
        self._job_bridge: JobBridge | None = None
        self._queue_busy = False
        self._queue_bridge: JobBridge | None = None
        self._queue_stop_requested = False
        self._run_from_queue = False
        self._character_switch_job = False
        self._character_bridge: JobBridge | None = None
        self._field_widgets: dict[str, QWidget] = {}
        # Feature-specific settings (for example farming) rendered on their
        # Features page instead of the general Settings tab.
        self._feature_field_widgets: dict[str, dict[str, QWidget]] = {}
        self._feature_settings_hosts: dict[
            str, tuple[QVBoxLayout, QLabel]
        ] = {}
        self._last_error_text = ""
        self._last_hp: float | None = None
        self._game_hwnd_cache: tuple[int, float] = (0, 0.0)
        self._env = self.service.environment()
        self._dungeons = self._env.get("dungeons", [])

        self.setWindowTitle(f"MI2 AIO {__version__}")
        self.setMinimumSize(1080, 720)
        self.resize(1180, 800)
        self.setWindowIcon(make_icon())

        self._status_bridge = StatusBridge()
        self._status_bridge.status.connect(self._on_status)
        self._log_bridge = LogBridge()
        self._log_bridge.message.connect(self._append_log)
        self.service.controller.subscribe(self._status_bridge.status.emit)
        self._qt_log_handler = QtLogHandler(self._log_bridge)
        self.logger.addHandler(self._qt_log_handler)

        self._build_ui()
        self._restore_geometry()
        self._build_tray()
        self._apply_start_tab()
        self.overlay = OverlayWindow(self.service.settings)
        self._hotkey = None
        self._setup_hotkey()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._tick)
        self._status_timer.start(1000)
        self._apply_status(self.service.idle_status())
        self._refresh_settings()
        self._refresh_diagnostics()
        self._refresh_skills()
        self._skills_timer = QTimer(self)
        self._skills_timer.setInterval(10000)
        self._skills_timer.timeout.connect(self._refresh_skills)
        self._skills_timer.start()
        self.logger.info("MI2 AIO desktop app ready.")
        QTimer.singleShot(700, self._run_startup_check)

    def _run_startup_check(self, force: bool = False) -> None:
        from .preflight_ui import show_startup_check

        result = show_startup_check(
            self.service.settings, self, force=force
        )
        if result.failed:
            self.logger.warning(
                "Startup check: %d requirement(s) missing.", len(result.failed)
            )
        elif result.warnings:
            self.logger.info(
                "Startup check: %d warning(s).", len(result.warnings)
            )
        else:
            self.logger.info("Startup check passed.")

    # -- UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setObjectName("appLogo")
        logo.setFixedSize(36, 36)
        logo.setPixmap(make_icon().pixmap(36, 36))
        header.addWidget(logo)
        title = QLabel("MI2 AIO")
        title.setObjectName("appTitle")
        header.addWidget(title)
        self.character_bar = QWidget()
        self.character_layout = QHBoxLayout(self.character_bar)
        self.character_layout.setContentsMargins(0, 0, 0, 0)
        self.character_layout.setSpacing(6)
        self.character_buttons: dict[str, QPushButton] = {}
        header.addWidget(self.character_bar)
        header.addStretch(1)
        self.window_badge = QLabel("Game: checking…")
        self.window_badge.setObjectName("badge")
        header.addWidget(self.window_badge)
        self.hide_button = QPushButton("Hide UI")
        self.hide_button.setObjectName("hideButton")
        self.hide_button.setToolTip("Hide the UI (Ctrl+A in the game)")
        self.hide_button.clicked.connect(self._toggle_visibility)
        header.addWidget(self.hide_button)
        self.window_badge.setFixedHeight(self.hide_button.sizeHint().height())
        self.window_badge.setAlignment(Qt.AlignCenter)
        self.dry_run_badge = QLabel("DRY RUN")
        self.dry_run_badge.setObjectName("dryRunBadge")
        self.dry_run_badge.setVisible(False)
        header.addWidget(self.dry_run_badge)
        self.state_label = QLabel("Bot Idle")
        self.state_label.setObjectName("statePill")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setMinimumWidth(105)
        header.addWidget(self.state_label)
        self.client_state_label = QLabel("Idle")
        self.client_state_label.setObjectName("clientStatePill")
        self.client_state_label.setAlignment(Qt.AlignCenter)
        self.client_state_label.setMinimumWidth(90)
        header.addWidget(self.client_state_label)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_dashboard(), "Dashboard")
        self.tabs.addTab(self._build_features(), "Features")
        self.tabs.addTab(self._build_queue(), "Queue")
        self.tabs.addTab(self._build_settings(), "Settings")
        self.tabs.addTab(self._build_diagnostics(), "Diagnostics")
        self.tabs.currentChanged.connect(self._tab_changed)
        self._build_character_bubbles()

        self._update_window_badge()
        self.statusBar().showMessage(f"Config: {CONFIG_FILE}")

    def _build_dashboard(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        controls = QGroupBox("Quick Controls")
        controls_layout = QHBoxLayout(controls)
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("stopButton")
        self.pause_button.clicked.connect(self._pause_run)
        self.resume_button.clicked.connect(self._resume_run)
        self.stop_button.clicked.connect(self._stop_run)
        self.farm_button = QPushButton("Farm Run")
        self.farm_button.setToolTip(
            "Pauses the current action, performs a full farm run, then "
            "continues the same action."
        )
        self.farm_button.clicked.connect(self._run_farming)
        self.farm_bones_button = QPushButton("Farm Prayer Points")
        self.farm_bones_button.setToolTip(
            "Uses current combat setup to farm Giant Chicken for prayer "
            "points.\n"
            "Corrupted Farmlands: Giant Chicken drops a Big Bone (6 Prayer "
            "points). Prayer maintenance buries the bones automatically."
        )
        self.farm_bones_button.clicked.connect(self._start_bone_farm)
        for button in (
            self.pause_button,
            self.resume_button,
            self.stop_button,
            self.farm_button,
            self.farm_bones_button,
        ):
            controls_layout.addWidget(button)
        controls_layout.addStretch(1)
        outer.addWidget(controls)

        stats = QGroupBox("Status")
        grid = QGridLayout(stats)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self.stat_labels: dict[str, QLabel] = {}
        self._add_stat(grid, "character", "Character", 0, 0)
        self._add_stat(grid, "mode", "Mode", 0, 1)
        self._add_stat(grid, "action", "Current action", 0, 2)
        self._add_stat(grid, "gp", "Gold", 1, 0)
        self._add_stat(grid, "prayer", "Prayer points", 1, 1)
        self._add_stat(grid, "bank", "Bank items", 1, 2)
        hp_label = QLabel("HP")
        hp_label.setObjectName("statTitle")
        grid.addWidget(hp_label, 2, 0)
        self.hp_bar = QProgressBar()
        self.hp_bar.setRange(0, 100)
        self.hp_bar.setTextVisible(True)
        self.hp_bar.setFixedWidth(340)
        self.hp_bar.setFixedHeight(20)
        grid.addWidget(self.hp_bar, 2, 1)
        outer.addWidget(stats)

        skills_box = QGroupBox("Skills")
        skills_grid = QGridLayout(skills_box)
        skills_grid.setHorizontalSpacing(10)
        skills_grid.setVerticalSpacing(4)
        self.skill_labels: dict[str, QLabel] = {}
        columns = 4
        for index, name in enumerate(SKILL_NAMES):
            label = QLabel()
            label.setObjectName(
                "skillValueMuted" if name in UNAVAILABLE_SKILLS else "skillValue"
            )
            if name in UNAVAILABLE_SKILLS:
                label.setToolTip("Not available in the demo yet.")
            label.setTextFormat(Qt.TextFormat.RichText)
            skills_grid.addWidget(label, index // columns, index % columns)
            self.skill_labels[name] = label
        rows = (len(SKILL_NAMES) + columns - 1) // columns
        last_row_items = len(SKILL_NAMES) % columns or columns
        self.total_level_label = QLabel()
        self.total_level_label.setObjectName("totalLevel")
        self.total_level_label.setTextFormat(Qt.TextFormat.RichText)
        self.total_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if last_row_items < columns:
            skills_grid.addWidget(
                self.total_level_label,
                rows - 1,
                last_row_items,
                1,
                columns - last_row_items,
            )
        else:
            skills_grid.addWidget(self.total_level_label, rows, 0, 1, columns)
        outer.addWidget(skills_box)

        activity = QGroupBox("Recent activity")
        activity_layout = QVBoxLayout(activity)
        self.activity_view = QPlainTextEdit()
        self.activity_view.setReadOnly(True)
        self.activity_view.setMaximumBlockCount(200)
        self.activity_view.setMaximumHeight(200)
        activity_layout.addWidget(self.activity_view)
        outer.addWidget(activity)
        outer.addStretch(1)
        return page

    def _add_stat(self, grid: QGridLayout, key: str, title: str, row: int, column: int) -> None:
        label = QLabel(title)
        label.setObjectName("statTitle")
        value = QLabel("—")
        value.setObjectName("statValue")
        grid.addWidget(label, row, column * 2)
        grid.addWidget(value, row, column * 2 + 1)
        self.stat_labels[key] = value

    def _build_features(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.features_sidebar = QListWidget()
        self.features_sidebar.setObjectName("featureSidebar")
        self.features_sidebar.setItemDelegate(
            NoFocusRectDelegate(self.features_sidebar)
        )
        self.features_sidebar.setFixedWidth(170)
        self.features_sidebar.setSpacing(4)
        self.features_sidebar.setUniformItemSizes(True)
        for name in ("Combat", "Farming", "Fishing", "Cooking"):
            item = QListWidgetItem(name)
            item.setSizeHint(QSize(140, 40))
            self.features_sidebar.addItem(item)
        self.features_sidebar.currentRowChanged.connect(
            self._feature_category_changed
        )
        layout.addWidget(self.features_sidebar)

        self.feature_stack = QStackedWidget()
        for builder in (
            self._build_combat_features,
            self._build_farming_features,
            self._build_fishing_features,
            self._build_cooking_features,
        ):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(builder())
            self.feature_stack.addWidget(scroll)
        layout.addWidget(self.feature_stack, 1)
        self.features_sidebar.setCurrentRow(0)
        import os

        feature = os.environ.get("MI2_AIO_FEATURE", "").strip().lower()
        if feature == "farming":
            self.features_sidebar.setCurrentRow(1)
        elif feature == "fishing":
            self.features_sidebar.setCurrentRow(2)
        elif feature == "cooking":
            self.features_sidebar.setCurrentRow(3)
        elif feature == "combat":
            self.features_sidebar.setCurrentRow(0)
        return page

    def _feature_category_changed(self, index: int) -> None:
        if hasattr(self, "feature_stack"):
            self.feature_stack.setCurrentIndex(max(0, index))
            self.features_sidebar.scrollToTop()

    def _feature_labels(self, category: str) -> QGroupBox:
        titles = {
            "combat": "Combat features",
            "farming": "Farming features",
            "fishing": "Fishing features",
            "cooking": "Cooking features",
        }
        box = QGroupBox(titles.get(category, "Features"))
        box_layout = QVBoxLayout(box)
        for feature in self._env.get("features", []):
            if feature.get("category") != category:
                continue
            label = QLabel(
                f"<b>{feature['name']}</b> — {feature['description']}"
            )
            label.setWordWrap(True)
            label.setObjectName("muted")
            box_layout.addWidget(label)
        return box

    def _build_combat_features(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        start_box = QGroupBox("Combat tasks")
        start_layout = QGridLayout(start_box)
        start_layout.addWidget(QLabel("Task"), 0, 0)
        self.task_combo = QComboBox()
        wanted = {"slayer", "dungeons", "farm_bones"}
        task_labels = {
            "slayer": "Slayer",
            "dungeons": "Dungeons",
            "farm_bones": "Farm Prayer Points",
        }
        tasks = [
            task
            for task in self._env.get("tasks", [])
            if task.get("name") in wanted
        ] or self._env.get("tasks", [])
        for task in tasks:
            self.task_combo.addItem(
                task_labels.get(task["name"], task["name"]), task["name"]
            )
            index = self.task_combo.count() - 1
            self.task_combo.setItemData(
                index, task.get("description", ""), Qt.ToolTipRole
            )
        if any(task["name"] == "slayer" for task in tasks):
            self.task_combo.setCurrentIndex(self.task_combo.findData("slayer"))
        self.task_combo.currentIndexChanged.connect(self._task_changed)
        start_layout.addWidget(self.task_combo, 0, 1, 1, 3)
        self.task_description = QLabel("")
        self.task_description.setWordWrap(True)
        self.task_description.setObjectName("muted")
        start_layout.addWidget(self.task_description, 1, 0, 1, 4)

        start_layout.addWidget(QLabel("Duration"), 2, 0)
        self.duration_input = NumberInput(unit="Minutes", maximum=1440)
        self.duration_input.setToolTip(
            "Run duration in minutes. 0 Minutes = until the run is stopped."
        )
        start_layout.addWidget(self.duration_input, 2, 1)
        start_layout.addWidget(QLabel("Task limit"), 2, 2)
        self.max_tasks_spin = QSpinBox()
        self.max_tasks_spin.setObjectName("taskLimitSpin")
        self.max_tasks_spin.setRange(0, 1000)
        self.max_tasks_spin.setSingleStep(1)
        self.max_tasks_spin.setSpecialValueText("Unlimited")
        self.max_tasks_spin.setValue(0)
        self.max_tasks_spin.setToolTip(
            "Completed Slayer tasks before stopping. 0 = Unlimited; this "
            "overrides the configured task limit for this run."
        )
        start_layout.addWidget(self.max_tasks_spin, 2, 3)
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("startButton")
        self.start_button.setToolTip(
            "Start the task. Dry-run/no-click mode is under Diagnostics."
        )
        self.start_button.clicked.connect(self._start_run)
        self.queue_button = QPushButton("Add to queue")
        self.queue_button.setToolTip(
            "Add this task to the Queue tab. The queue runs it after the "
            "current task stops."
        )
        self.queue_button.clicked.connect(self._queue_selected_task)
        action_row = QHBoxLayout()
        action_row.addWidget(self.start_button, 1)
        action_row.addWidget(self.queue_button)
        start_layout.addLayout(action_row, 3, 0, 1, 4)
        outer.addWidget(start_box)

        slayer_box = QGroupBox("Slayer task")
        slayer_layout = QVBoxLayout(slayer_box)
        slayer_header = QHBoxLayout()
        self.slayer_label = QLabel("No active task")
        self.slayer_label.setObjectName("statValue")
        slayer_header.addWidget(self.slayer_label, 1)
        self.completed_label = QLabel("Completed: 0")
        self.completed_label.setObjectName("muted")
        slayer_header.addWidget(self.completed_label)
        slayer_layout.addLayout(slayer_header)
        self.slayer_bar = QProgressBar()
        self.slayer_bar.setRange(0, 100)
        self.slayer_bar.setValue(0)
        slayer_layout.addWidget(self.slayer_bar)
        outer.addWidget(slayer_box)

        outer.addWidget(self._feature_labels("combat"))
        outer.addStretch(1)
        self._task_changed()
        return page

    def _build_farming_features(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        farming_box = QGroupBox("Farming maintenance")
        farming_layout = QVBoxLayout(farming_box)
        description = QLabel(
            "Farming runs alongside the active task, harvests ready plots, "
            "composts, replants, waters and keeps The Mill running."
        )
        description.setWordWrap(True)
        description.setObjectName("muted")
        farming_layout.addWidget(description)
        farming_buttons = QHBoxLayout()
        self.farm_feature_button = QPushButton("Farm Run")
        self.farm_feature_button.setToolTip(
            "Pauses the current action, performs a full farm run, then "
            "continues the same action."
        )
        self.farm_feature_button.clicked.connect(self._run_farming)
        farming_buttons.addWidget(self.farm_feature_button)
        farming_buttons.addStretch(1)
        farming_layout.addLayout(farming_buttons)
        outer.addWidget(farming_box)

        self.farming_settings_layout = QVBoxLayout()
        outer.addLayout(self.farming_settings_layout)

        settings_buttons = QHBoxLayout()
        self.farming_settings_save = QPushButton("Save farming settings")
        self.farming_settings_save.setObjectName("startButton")
        self.farming_settings_save.clicked.connect(
            lambda: self._save_feature_settings("farming")
        )
        self.farming_settings_reload = QPushButton("Reload")
        self.farming_settings_reload.clicked.connect(
            lambda: self._refresh_feature_settings("farming")
        )
        self.farming_settings_status = QLabel("")
        self.farming_settings_status.setObjectName("muted")
        settings_buttons.addWidget(self.farming_settings_save)
        settings_buttons.addWidget(self.farming_settings_reload)
        settings_buttons.addWidget(self.farming_settings_status, 1)
        outer.addLayout(settings_buttons)

        self._feature_settings_hosts["farming"] = (
            self.farming_settings_layout,
            self.farming_settings_status,
        )
        self._refresh_feature_settings("farming")

        outer.addWidget(self._feature_labels("farming"))
        outer.addStretch(1)
        return page

    def _build_fishing_features(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.fishing_db = load_fishing()
        location_box = QGroupBox("Fishing task")
        location_layout = QGridLayout(location_box)
        location_layout.addWidget(QLabel("Location"), 0, 0)
        self.fishing_location_combo = QComboBox()
        self.fishing_location_combo.setObjectName("fishingLocationCombo")
        for index, location in enumerate(self.fishing_db.locations):
            text = f"{location.name} (level {location.level})"
            if location.demo_locked:
                text = f"{location.name} (locked in the demo)"
            self.fishing_location_combo.addItem(text, index)
            if location.demo_locked:
                item = self.fishing_location_combo.model().item(index)
                if item is not None:
                    item.setEnabled(False)
        self.fishing_location_combo.currentIndexChanged.connect(
            self._fishing_location_changed
        )
        location_layout.addWidget(self.fishing_location_combo, 0, 1, 1, 3)

        self.fishing_location_info = QLabel("")
        self.fishing_location_info.setObjectName("muted")
        self.fishing_location_info.setWordWrap(True)
        location_layout.addWidget(self.fishing_location_info, 1, 0, 1, 4)

        location_layout.addWidget(QLabel("Spot"), 2, 0)
        self.fishing_spot_combo = QComboBox()
        self.fishing_spot_combo.setObjectName("fishingSpotCombo")
        self.fishing_spot_combo.currentIndexChanged.connect(
            self._fishing_spot_changed
        )
        location_layout.addWidget(self.fishing_spot_combo, 2, 1, 1, 3)

        location_layout.addWidget(QLabel("Duration"), 3, 0)
        self.fishing_duration_input = NumberInput(
            unit="Minutes", maximum=1440
        )
        self.fishing_duration_input.setToolTip(
            "How long to keep fishing. 0 Minutes = until the run is stopped."
        )
        location_layout.addWidget(self.fishing_duration_input, 3, 1)

        fishing_buttons = QHBoxLayout()
        self.fishing_start_button = QPushButton("Start Fishing")
        self.fishing_start_button.setObjectName("startButton")
        self.fishing_start_button.setToolTip(
            "Open Fishing, select this location and spot, and start fishing."
        )
        self.fishing_start_button.clicked.connect(self._start_fishing)
        self.fishing_queue_button = QPushButton("Add to queue")
        self.fishing_queue_button.setToolTip(
            "Add this location and spot to the Queue tab. The queue runs it "
            "after the current task stops."
        )
        self.fishing_queue_button.clicked.connect(self._queue_fishing)
        fishing_buttons.addWidget(self.fishing_start_button, 1)
        fishing_buttons.addWidget(self.fishing_queue_button)
        location_layout.addLayout(fishing_buttons, 4, 0, 1, 4)
        outer.addWidget(location_box)

        fish_box = QGroupBox("Fish at this spot")
        fish_layout = QVBoxLayout(fish_box)
        self.fishing_fish_preview = QLabel("")
        self.fishing_fish_preview.setWordWrap(True)
        self.fishing_fish_preview.setTextFormat(Qt.TextFormat.RichText)
        fish_layout.addWidget(self.fishing_fish_preview)
        outer.addWidget(fish_box)

        outer.addWidget(self._feature_labels("fishing"))
        outer.addStretch(1)
        self._fishing_location_changed(
            self.fishing_location_combo.currentIndex()
        )
        return page

    def _fishing_location_changed(self, index: int) -> None:
        if not hasattr(self, "fishing_spot_combo"):
            return
        location = self._fishing_location(index)
        self.fishing_spot_combo.blockSignals(True)
        self.fishing_spot_combo.clear()
        if location is None:
            self.fishing_spot_combo.blockSignals(False)
            self._update_fishing_preview()
            return
        for spot_index, spot in enumerate(location.spots):
            text = f"{spot.name} (level {spot.level})"
            if spot.demo_locked:
                text = f"{spot.name} (locked in the demo)"
            self.fishing_spot_combo.addItem(text, spot_index)
            if spot.demo_locked:
                item = self.fishing_spot_combo.model().item(spot_index)
                if item is not None:
                    item.setEnabled(False)
        available = location.available_spots
        if available:
            self.fishing_spot_combo.setCurrentIndex(
                location.spots.index(available[0])
            )
        self.fishing_spot_combo.blockSignals(False)
        if location.demo_locked:
            self.fishing_location_info.setText(
                "This location is not available in the demo."
            )
        else:
            self.fishing_location_info.setText(
                f"Requires Fishing level {location.level} · "
                f"{len(available)} fishing "
                f"{'spot' if len(available) == 1 else 'spots'} available."
            )
        self._update_fishing_preview()

    def _fishing_spot_changed(self, _index: int) -> None:
        self._update_fishing_preview()

    def _fishing_location(self, index: int):
        if not hasattr(self, "fishing_db") or index < 0:
            return None
        if index >= len(self.fishing_db.locations):
            return None
        return self.fishing_db.locations[index]

    def _selected_fishing(self):
        location = self._fishing_location(
            self.fishing_location_combo.currentIndex()
        )
        if location is None:
            return None, None
        spot_index = self.fishing_spot_combo.currentData()
        if spot_index is None:
            return location, None
        try:
            spot = location.spots[int(spot_index)]
        except (IndexError, TypeError, ValueError):
            return location, None
        if spot.demo_locked:
            return location, None
        return location, spot

    def _update_fishing_preview(self) -> None:
        if not hasattr(self, "fishing_fish_preview"):
            return
        _location, spot = self._selected_fishing()
        if spot is None:
            self.fishing_fish_preview.setText(
                "Select an available location and spot to see its fish."
            )
            return
        if not spot.fish:
            self.fishing_fish_preview.setText(
                "This spot has no fish in the demo database."
            )
            return
        rows = [
            f"<b>{fish.name}</b> — {fish.chance:.0%} · "
            f"{fish.quantity_label} per catch"
            for fish in spot.fish
        ]
        specials = ", ".join(
            f"{item.name} ({item.chance:.2%})" for item in spot.special
        )
        lines = [
            *rows,
            "",
            f"Fish chance {spot.fish_chance:.0%} · "
            f"Junk {spot.junk_chance:.0%} · "
            f"XP {spot.experience} · {spot.interval_label}",
        ]
        if specials:
            lines.append(f"Special items: {specials}")
        self.fishing_fish_preview.setText("<br>".join(lines))

    def _build_queue(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.queue_status_label = QLabel("Queue idle.")
        self.queue_status_label.setObjectName("muted")
        toolbar.addWidget(self.queue_status_label, 1)
        self.queue_pause_button = QPushButton("Pause queue")
        self.queue_pause_button.clicked.connect(self._toggle_queue_pause)
        self.queue_remove_button = QPushButton("Remove selected")
        self.queue_remove_button.clicked.connect(self._remove_selected_queued)
        self.queue_clear_button = QPushButton("Clear queue")
        self.queue_clear_button.clicked.connect(self._clear_queue)
        toolbar.addWidget(self.queue_pause_button)
        toolbar.addWidget(self.queue_remove_button)
        toolbar.addWidget(self.queue_clear_button)
        layout.addLayout(toolbar)

        note = QLabel(
            "Tasks are added with the Queue button on Features → Combat, "
            "Fishing or Cooking. The queue runs them in order and switches "
            "characters in Melvor when the next task belongs to another save. "
            "Stop pauses the queue; Resume continues it. The queue is kept in "
            "memory for this app session."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)

        self.queue_table = QTableWidget(0, 4)
        self.queue_table.setHorizontalHeaderLabels(
            ["Character", "Task", "Duration", "Limit"]
        )
        self.queue_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.queue_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.queue_table.horizontalHeader().setStretchLastSection(True)
        self.queue_table.setColumnWidth(0, 150)
        self.queue_table.setColumnWidth(1, 240)
        self.queue_table.setColumnWidth(2, 140)
        self.queue_table.setColumnWidth(3, 110)
        self.queue_table.itemSelectionChanged.connect(
            self._update_queue_controls
        )
        layout.addWidget(self.queue_table, 1)
        self._refresh_queue()
        return page

    def _refresh_queue(self) -> None:
        if not hasattr(self, "queue_table"):
            return
        items = self.service.queue.items()
        paused = self.service.queue.paused
        self.queue_table.setRowCount(len(items))
        for row, queued in enumerate(items):
            duration = (
                "0 Minutes"
                if not queued.duration_minutes
                else f"{queued.duration_minutes:g} Minutes"
            )
            limit = "Unlimited" if not queued.max_tasks else str(queued.max_tasks)
            values = [
                queued.character or "newest save",
                queued.label,
                duration,
                limit,
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, queued.id)
                self.queue_table.setItem(row, column, cell)
        if not items:
            status = "Queue paused — no tasks." if paused else "Queue idle — no tasks."
        elif paused:
            status = f"Queue paused — {len(items)} task(s) waiting."
        else:
            status = f"{len(items)} task(s) queued."
        self.queue_status_label.setText(status)
        self.queue_pause_button.setText(
            "Resume queue" if paused else "Pause queue"
        )
        self._update_queue_controls()

    def _update_queue_controls(self) -> None:
        if not hasattr(self, "queue_table"):
            return
        has_rows = self.queue_table.rowCount() > 0
        self.queue_table.setEnabled(has_rows)
        self.queue_remove_button.setEnabled(
            has_rows and self.queue_table.currentRow() >= 0
        )
        self.queue_clear_button.setEnabled(has_rows)

    def _selected_queue_id(self) -> int | None:
        row = self.queue_table.currentRow()
        if row < 0:
            return None
        item = self.queue_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _toggle_queue_pause(self) -> None:
        paused = not self.service.queue.paused
        self.service.queue.set_paused(paused)
        if paused:
            self.statusBar().showMessage(
                "Queue paused. The current task is not interrupted.", 5000
            )
        else:
            self.statusBar().showMessage("Queue resumed.", 4000)
            self._maybe_start_queued()
        self._refresh_queue()

    def _remove_selected_queued(self) -> None:
        item_id = self._selected_queue_id()
        if item_id is None:
            return
        self.service.queue.remove(item_id)
        self._refresh_queue()

    def _clear_queue(self) -> None:
        self.service.queue.clear()
        self._refresh_queue()
        self.statusBar().showMessage("Queue cleared.", 4000)

    def _build_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        toolbar = QHBoxLayout()
        self.save_settings_button = QPushButton("Save settings")
        self.save_settings_button.setObjectName("startButton")
        self.save_settings_button.clicked.connect(lambda: self._save_settings())
        self.reload_settings_button = QPushButton("Reload")
        self.reload_settings_button.clicked.connect(self._refresh_settings)
        self.learn_fallback_button = QPushButton("Learn fallback…")
        self.learn_fallback_button.clicked.connect(self._learn_fallback)
        self.settings_status = QLabel("")
        self.settings_status.setObjectName("muted")
        toolbar.addWidget(self.save_settings_button)
        toolbar.addWidget(self.reload_settings_button)
        toolbar.addWidget(self.learn_fallback_button)
        toolbar.addWidget(self.settings_status, 1)
        layout.addLayout(toolbar)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        layout.addWidget(self.settings_scroll, 1)
        return page

    def _make_log_view(self) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setMaximumBlockCount(5000)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        view.setFont(font)
        return view

    def _build_diagnostics(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        toolbar = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_diagnostics)
        startup = QPushButton("Startup check")
        startup.setToolTip(
            "Check Python, packages, the save helper, saves and the game window."
        )
        startup.clicked.connect(lambda: self._run_startup_check(force=True))
        screenshot = QPushButton("Capture screenshot")
        screenshot.clicked.connect(self._capture)
        open_logs = QPushButton("Open logs")
        open_logs.clicked.connect(lambda: self._open_path(LOGS_DIR))
        open_config = QPushButton("Open settings file")
        open_config.clicked.connect(lambda: self._open_path(CONFIG_FILE))
        self.logs_button = QPushButton("Logs")
        self.logs_button.setObjectName("logsButton")
        self.logs_button.setCheckable(True)
        self.logs_button.setToolTip(
            "Show the live log; click again to return to the report."
        )
        self.logs_button.toggled.connect(self._toggle_logs_view)
        toolbar.addWidget(refresh)
        toolbar.addWidget(startup)
        toolbar.addWidget(screenshot)
        toolbar.addWidget(open_logs)
        toolbar.addWidget(open_config)
        toolbar.addWidget(self.logs_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        options = QGroupBox("Run options")
        options_layout = QHBoxLayout(options)
        self.dry_run_check = QCheckBox("Dry run (no clicks)")
        self.dry_run_check.setToolTip(
            "Log the bot's decisions without sending clicks or keystrokes. "
            "The game and save must still be available. Start from the Dashboard."
        )
        options_layout.addWidget(self.dry_run_check)
        dry_note = QLabel(
            "Logs what the bot would do without sending input. Useful for "
            "checking task recognition, gear/style choices and farming or "
            "prayer triggers safely."
        )
        dry_note.setWordWrap(True)
        dry_note.setObjectName("muted")
        options_layout.addWidget(dry_note, 1)

        maintenance_box = QGroupBox("Settings maintenance")
        maintenance_layout = QHBoxLayout(maintenance_box)
        reset_button = QPushButton("Reset to default settings")
        reset_button.setObjectName("resetSettingsButton")
        reset_button.setToolTip(
            "Replace the active settings file with the bundled defaults. "
            "This cannot be undone."
        )
        reset_button.clicked.connect(self._reset_settings)
        maintenance_layout.addWidget(reset_button)
        reset_note = QLabel(
            "Overwrites the active settings.toml with the bundled default "
            "template. Existing settings will be lost."
        )
        reset_note.setWordWrap(True)
        reset_note.setObjectName("muted")
        maintenance_layout.addWidget(reset_note, 1)

        self.diagnostics_view = QPlainTextEdit()
        self.diagnostics_view.setReadOnly(True)
        self.diagnostics_view.setMaximumBlockCount(10000)
        self.diagnostics_view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
        )
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.diagnostics_view.setFont(font)

        self.log_view = self._make_log_view()

        saves_box = QGroupBox("Characters / saves")
        saves_layout = QVBoxLayout(saves_box)
        self.saves_table = QTableWidget(0, 5)
        self.saves_table.setHorizontalHeaderLabels(
            ["Character", "Mode", "Level", "Action", "Modified"]
        )
        self.saves_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.saves_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.saves_table.horizontalHeader().setStretchLastSection(True)
        self.saves_table.setMaximumHeight(150)
        saves_layout.addWidget(self.saves_table)
        row = QHBoxLayout()
        use = QPushButton("Use selected character")
        use.clicked.connect(self._use_selected_character)
        clear = QPushButton("Use newest save")
        clear.clicked.connect(self._clear_character)
        row.addWidget(use)
        row.addWidget(clear)
        row.addStretch(1)
        saves_layout.addLayout(row)

        report_page = QWidget()
        report_layout = QVBoxLayout(report_page)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.setSpacing(8)
        report_layout.addWidget(options)
        report_layout.addWidget(maintenance_box)
        report_layout.addWidget(self.diagnostics_view, 2)
        report_layout.addWidget(saves_box, 1)

        logs_page = QWidget()
        logs_layout = QVBoxLayout(logs_page)
        logs_layout.setContentsMargins(0, 0, 0, 0)
        log_tools = QHBoxLayout()
        clear_logs = QPushButton("Clear")
        clear_logs.clicked.connect(lambda: self.log_view.clear())
        log_tools.addStretch(1)
        log_tools.addWidget(clear_logs)
        logs_layout.addLayout(log_tools)
        logs_layout.addWidget(self.log_view, 1)

        self.diagnostics_stack = QStackedWidget()
        self.diagnostics_stack.addWidget(report_page)
        self.diagnostics_stack.addWidget(logs_page)
        layout.addWidget(self.diagnostics_stack, 1)
        self.diagnostics_stack.setCurrentIndex(0)
        return page

    def _toggle_logs_view(self, checked: bool) -> None:
        if hasattr(self, "diagnostics_stack"):
            self.diagnostics_stack.setCurrentIndex(1 if checked else 0)

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("MI2 AIO")
        tray_menu = QMenu(self)
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self._show_from_tray)
        toggle_action = tray_menu.addAction("Hide / Show UI")
        toggle_action.triggered.connect(self._toggle_visibility)
        self.tray_pause = tray_menu.addAction("Pause")
        self.tray_pause.triggered.connect(self._pause_run)
        self.tray_stop = tray_menu.addAction("Stop")
        self.tray_stop.triggered.connect(self._stop_run)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    # -- settings --------------------------------------------------------
    def _refresh_settings(self) -> None:
        values = self.service.settings_values()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        self._field_widgets = {}
        for section in SECTIONS:
            if section.feature:
                # Feature-specific settings live on their Features page.
                continue
            visible = [spec for spec in section.fields if not spec.hidden]
            if not visible:
                continue
            group = QGroupBox(section.title)
            form = QFormLayout(group)
            if section.description:
                description = QLabel(section.description)
                description.setWordWrap(True)
                description.setObjectName("muted")
                form.addRow(description)
            for spec in visible:
                widget = self._make_field_widget(spec, values.get(spec.dotted, spec.default))
                widget.setToolTip(spec.help or spec.label)
                form.addRow(spec.label, widget)
                self._field_widgets[spec.dotted] = widget
            layout.addWidget(group)
        layout.addStretch(1)
        old = self.settings_scroll.takeWidget() if self.settings_scroll else None
        if old is not None:
            old.deleteLater()
        if self.settings_scroll is not None:
            self.settings_scroll.setWidget(content)
        self.settings_status.setText(f"Loaded {len(self._field_widgets)} settings.")
        for feature in self._feature_settings_hosts:
            self._refresh_feature_settings(feature)

    def _refresh_feature_settings(self, feature: str) -> None:
        """Rebuild one Features-page settings form from the current config."""
        host = self._feature_settings_hosts.get(feature)
        if host is None:
            return
        layout, status = host
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        values = self.service.settings_values()
        widgets: dict[str, QWidget] = {}
        for section in feature_sections(feature):
            visible = [spec for spec in section.fields if not spec.hidden]
            if not visible:
                continue
            group = QGroupBox(section.title)
            form = QFormLayout(group)
            if section.description:
                description = QLabel(section.description)
                description.setWordWrap(True)
                description.setObjectName("muted")
                form.addRow(description)
            for spec in visible:
                widget = self._make_field_widget(
                    spec, values.get(spec.dotted, spec.default)
                )
                widget.setToolTip(spec.help or spec.label)
                form.addRow(spec.label, widget)
                widgets[spec.dotted] = widget
            layout.addWidget(group)
        layout.addStretch(1)
        self._feature_field_widgets[feature] = widgets
        status.setText(f"Loaded {len(widgets)} settings.")

    def _save_feature_settings(self, feature: str) -> None:
        if not self._save_settings():
            return
        host = self._feature_settings_hosts.get(feature)
        if host is None:
            return
        status = host[1]
        status.setText("Saved.")
        QTimer.singleShot(4000, lambda: status.setText(""))

    def _make_field_widget(self, spec, value):
        if spec.kind == BOOL:
            widget = QCheckBox()
            widget.setChecked(bool(value))
            return widget
        if spec.kind in {INT, FLOAT}:
            if spec.kind == INT:
                widget = QSpinBox()
                widget.setRange(int(spec.minimum or 0), int(spec.maximum or 1_000_000_000))
                widget.setSingleStep(int(spec.step or 1))
                widget.setValue(int(value))
            else:
                widget = QDoubleSpinBox()
                widget.setRange(float(spec.minimum or 0), float(spec.maximum or 1_000_000.0))
                widget.setDecimals(2)
                widget.setSingleStep(float(spec.step or 0.5))
                widget.setValue(float(value))
            if spec.suffix:
                widget.setSuffix(" " + spec.suffix)
            return widget
        if spec.kind == CHOICE:
            widget = QComboBox()
            widget.addItems(list(spec.choices))
            widget.setCurrentText(str(value))
            return widget
        if spec.kind in {POINT, PAIR_INT}:
            widget = PairEditor(spec)
            widget.set_value(value)
            return widget
        if spec.kind == LIST_STR:
            widget = QLineEdit(", ".join(str(item) for item in value))
            return widget
        # Strings. Path-like fields get a browse button.
        if spec.dotted == "combat.dungeons.dungeon":
            widget = QComboBox()
            names = [entry.get("name", "") for entry in self._dungeons]
            widget.addItems(names)
            for index, entry in enumerate(self._dungeons):
                supported = bool(entry.get("supported"))
                widget.setItemData(
                    index,
                    "Template available" if supported else "No template captured yet",
                    Qt.ToolTipRole,
                )
            if str(value) not in names:
                widget.addItem(str(value))
            widget.setCurrentText(str(value))
            return widget
        if spec.key in {"root", "template"}:
            return PathEditor(
                str(value),
                directory=spec.key == "root",
                image=spec.key == "template",
            )
        widget = QLineEdit(str(value))
        return widget

    def _collect_settings(self) -> dict[str, object]:
        values: dict[str, object] = {}
        sources = [self._field_widgets]
        sources.extend(self._feature_field_widgets.values())
        for widgets in sources:
            for path, widget in widgets.items():
                if isinstance(widget, QCheckBox):
                    values[path] = widget.isChecked()
                elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    values[path] = widget.value()
                elif isinstance(widget, QComboBox):
                    values[path] = widget.currentText()
                elif isinstance(widget, (PairEditor, PathEditor)):
                    values[path] = widget.value()
                elif isinstance(widget, QLineEdit):
                    values[path] = widget.text()
        return values

    def _save_settings(self, silent: bool = False) -> bool:
        values = self._collect_settings()
        selected_dungeon = values.get("combat.dungeons.dungeon")
        if not silent and selected_dungeon:
            supported = any(
                entry.get("name") == selected_dungeon and entry.get("supported")
                for entry in self._dungeons
            )
            if not supported:
                QMessageBox.information(
                    self,
                    "Dungeon template",
                    f"No name template is captured for {selected_dungeon!r} yet. "
                    "The dungeon task cannot select it until a template exists.",
                )
        try:
            self.service.save_settings(values)
        except (ServiceError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Settings not saved", str(exc))
            self.settings_status.setText("Save failed.")
            return False
        self.settings_status.setText("Saved.")
        self.statusBar().showMessage("Settings saved.", 4000)
        self._refresh_maintenance_labels()
        if not silent:
            self._refresh_settings()
        QTimer.singleShot(4000, lambda: self.settings_status.setText(""))
        return True

    def _learn_fallback(self) -> None:
        if self.service.controller.active:
            QMessageBox.information(
                self,
                "Learn fallback",
                "Stop the active bot run before learning a fallback action.",
            )
            return
        wizard = FallbackWizard(self.service, self)
        if wizard.exec() == QDialog.Accepted:
            self._refresh_settings()
            self._refresh_maintenance_labels()
            self.statusBar().showMessage("Fallback action learned.", 5000)

    # -- run control -----------------------------------------------------
    def _task_changed(self) -> None:
        task = self.task_combo.currentData()
        description = ""
        for entry in self._env.get("tasks", []):
            if entry.get("name") == task:
                description = entry.get("description", "")
                break
        self.task_description.setText(description)

    def _start_run(self) -> None:
        task = self.task_combo.currentData()
        if not task:
            return
        if not self._save_settings(silent=True):
            return
        duration = self.duration_input.value()
        max_tasks = self.max_tasks_spin.value()
        self._run_from_queue = False
        self.service.refresh_health()
        try:
            self.service.start_run(
                str(task),
                duration_minutes=duration if duration > 0 else None,
                dry_run=self.dry_run_check.isChecked(),
                max_tasks=max_tasks,
            )
        except ServiceError as exc:
            QMessageBox.warning(self, "Cannot start", str(exc))
            return
        self._hold_final_until = 0.0
        self.activity_view.appendPlainText(f"Started {task}.")

    def _start_bone_farm(self) -> None:
        if self._farming_job:
            self.statusBar().showMessage(
                "Wait for the farming pass to finish.", 4000
            )
            return
        if self.service.controller.active:
            self.statusBar().showMessage(
                "Stop the active run before starting Farm Prayer Points.", 4000
            )
            return
        if not self._save_settings(silent=True):
            return
        self._run_from_queue = False
        self.service.refresh_health()
        try:
            self.service.start_run(
                "farm_bones",
                dry_run=self.dry_run_check.isChecked(),
                max_tasks=0,
            )
        except ServiceError as exc:
            QMessageBox.warning(self, "Cannot start", str(exc))
            return
        self._hold_final_until = 0.0
        self.activity_view.appendPlainText(
            "Started Farm Prayer Points: Corrupted Farmlands (Giant Chicken)."
        )

    def _start_fishing(self) -> None:
        location, spot = self._selected_fishing()
        if location is None or spot is None:
            QMessageBox.warning(
                self,
                "Cannot start",
                "Choose a fishing location and spot that are available in the "
                "demo first.",
            )
            return
        if not self._save_settings(silent=True):
            return
        duration = self.fishing_duration_input.value()
        self._run_from_queue = False
        self.service.refresh_health()
        try:
            self.service.start_run(
                "fishing",
                duration_minutes=duration if duration > 0 else None,
                dry_run=self.dry_run_check.isChecked(),
                max_tasks=0,
                options={"location": location.id, "spot": spot.id},
            )
        except ServiceError as exc:
            QMessageBox.warning(self, "Cannot start", str(exc))
            return
        self._hold_final_until = 0.0
        self.activity_view.appendPlainText(
            f"Started Fishing: {location.name} / {spot.name}."
        )

    def _build_cooking_features(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.cooking_db = load_cooking()
        cooking_box = QGroupBox("Cooking task")
        cooking_layout = QGridLayout(cooking_box)
        cooking_layout.addWidget(QLabel("Recipe"), 0, 0)
        self.cooking_recipe_combo = QComboBox()
        self.cooking_recipe_combo.setObjectName("cookingRecipeCombo")
        for recipe in self.cooking_db.available_recipes():
            self.cooking_recipe_combo.addItem(
                f"{recipe.name} (level {recipe.level})", recipe.id
            )
        self.cooking_recipe_combo.currentIndexChanged.connect(
            self._cooking_recipe_changed
        )
        cooking_layout.addWidget(self.cooking_recipe_combo, 0, 1, 1, 3)

        cooking_layout.addWidget(QLabel("Amount"), 1, 0)
        self.cooking_amount_input = NumberInput(maximum=1_000_000)
        self.cooking_amount_input.setToolTip(
            "Products to cook. The bot sets the in-game Products Gained stop "
            "condition to this number. 0 = until the run is stopped."
        )
        self.cooking_amount_input.valueChanged.connect(
            self._update_cooking_preview
        )
        cooking_layout.addWidget(self.cooking_amount_input, 1, 1)

        cooking_layout.addWidget(QLabel("Duration"), 1, 2)
        self.cooking_duration_input = NumberInput(
            unit="Minutes", maximum=1440
        )
        self.cooking_duration_input.setToolTip(
            "Optional safety limit for the run. The Amount setting normally "
            "ends the task. 0 Minutes = until stopped."
        )
        cooking_layout.addWidget(self.cooking_duration_input, 1, 3)

        cooking_buttons = QHBoxLayout()
        self.cooking_start_button = QPushButton("Start Cooking")
        self.cooking_start_button.setObjectName("startButton")
        self.cooking_start_button.setToolTip(
            "Select the recipe, set the optional Products Gained stop "
            "condition and press Create."
        )
        self.cooking_start_button.clicked.connect(self._start_cooking)
        self.cooking_queue_button = QPushButton("Add to queue")
        self.cooking_queue_button.setToolTip(
            "Add this recipe and amount to the Queue tab. The queue runs it "
            "after the current task stops."
        )
        self.cooking_queue_button.clicked.connect(self._queue_cooking)
        cooking_buttons.addWidget(self.cooking_start_button, 1)
        cooking_buttons.addWidget(self.cooking_queue_button)
        cooking_layout.addLayout(cooking_buttons, 2, 0, 1, 4)
        outer.addWidget(cooking_box)

        recipe_box = QGroupBox("Recipe")
        recipe_layout = QVBoxLayout(recipe_box)
        self.cooking_preview = QLabel("")
        self.cooking_preview.setWordWrap(True)
        self.cooking_preview.setTextFormat(Qt.TextFormat.RichText)
        recipe_layout.addWidget(self.cooking_preview)
        outer.addWidget(recipe_box)

        outer.addWidget(self._feature_labels("cooking"))
        outer.addStretch(1)
        self._update_cooking_preview()
        return page

    def _cooking_recipe_changed(self, _index: int) -> None:
        self._update_cooking_preview()

    def _selected_cooking(self):
        recipe_id = self.cooking_recipe_combo.currentData()
        if not recipe_id:
            return None, 0
        recipe = self.cooking_db.recipe(str(recipe_id))
        return recipe, int(self.cooking_amount_input.value())

    def _update_cooking_preview(self, _value: int | None = None) -> None:
        if not hasattr(self, "cooking_preview"):
            return
        recipe, amount = self._selected_cooking()
        if recipe is None:
            self.cooking_preview.setText(
                "Select an available Basic Food recipe."
            )
            return
        product = recipe.product
        item_ids = [item.id for item in recipe.ingredients]
        if product is not None:
            item_ids.append(product.id)
        counts = self.service.bank_counts(item_ids)
        lines = [
            f"<b>{recipe.ingredients_label}</b> → "
            f"<b>{product.name if product else recipe.name}</b>",
            f"Level {recipe.level} · XP {recipe.experience} · "
            f"{recipe.interval_label} per cook · difficulty "
            f"{recipe.difficulty}",
        ]
        stock = [f"{item.name} {counts.get(item.id, 0):,}" for item in recipe.ingredients]
        if product is not None:
            stock.append(f"{product.name} {counts.get(product.id, 0):,}")
        if stock:
            lines.append("Bank: " + " · ".join(stock))
        if amount > 0:
            lines.append(
                f"<b>Stop:</b> Products Gained = {amount:,} "
                f"({product.name if product else recipe.name})"
            )
        else:
            lines.append("<b>Stop:</b> none (0 = until stopped)")
        self.cooking_preview.setText("<br>".join(lines))

    def _start_cooking(self) -> None:
        recipe, amount = self._selected_cooking()
        if recipe is None:
            QMessageBox.warning(
                self,
                "Cannot start",
                "Choose an available Basic Food recipe first.",
            )
            return
        if not self._save_settings(silent=True):
            return
        duration = self.cooking_duration_input.value()
        self._run_from_queue = False
        self.service.refresh_health()
        try:
            self.service.start_run(
                "cooking",
                duration_minutes=duration if duration > 0 else None,
                dry_run=self.dry_run_check.isChecked(),
                max_tasks=0,
                options={"recipe": recipe.id, "amount": str(amount)},
            )
        except ServiceError as exc:
            QMessageBox.warning(self, "Cannot start", str(exc))
            return
        self._hold_final_until = 0.0
        target = f" × {amount}" if amount else ""
        self.activity_view.appendPlainText(
            f"Started Cooking: {recipe.name}{target}."
        )

    def _queue_cooking(self) -> None:
        recipe, amount = self._selected_cooking()
        if recipe is None:
            QMessageBox.warning(
                self,
                "Cannot queue",
                "Choose an available Basic Food recipe first.",
            )
            return
        label = f"Cooking · {recipe.name}"
        if amount:
            label += f" × {amount}"
        self._queue_task(
            "cooking",
            label,
            self.cooking_duration_input.value(),
            0,
            options={"recipe": recipe.id, "amount": str(amount)},
        )

    # -- queue -----------------------------------------------------------
    def _queue_selected_task(self) -> None:
        task = self.task_combo.currentData()
        if not task:
            return
        self._queue_task(
            str(task),
            self.task_combo.currentText(),
            self.duration_input.value(),
            self.max_tasks_spin.value(),
        )

    def _queue_fishing(self) -> None:
        location, spot = self._selected_fishing()
        if location is None or spot is None:
            QMessageBox.warning(
                self,
                "Cannot queue",
                "Choose a fishing location and spot that are available in the "
                "demo first.",
            )
            return
        self._queue_task(
            "fishing",
            f"Fishing · {location.name} / {spot.name}",
            self.fishing_duration_input.value(),
            0,
            options={"location": location.id, "spot": spot.id},
        )

    def _queue_task(
        self,
        task: str,
        label: str,
        duration: float,
        max_tasks: int,
        options: dict[str, str] | None = None,
    ) -> None:
        if not self._save_settings(silent=True):
            return
        selected = self._env.get("selected") or {}
        character = str(selected.get("character_name") or "")
        character_uuid = str(selected.get("uuid") or "")
        self.service.queue.add(
            task,
            label,
            character=character,
            character_uuid=character_uuid,
            duration_minutes=duration if duration > 0 else None,
            max_tasks=max_tasks,
            options=options,
        )
        self._refresh_queue()
        self.activity_view.appendPlainText(
            f"Queued {label} for {character or 'the newest save'}."
        )
        self.statusBar().showMessage(
            f"Queued {label} for {character or 'the newest save'}.", 5000
        )
        self._maybe_start_queued()

    def _maybe_start_queued(self) -> None:
        if self._queue_busy or self._character_switch_job:
            return
        if self._farming_job or self.service.controller.active:
            return
        if self.service.queue.paused:
            self._refresh_queue()
            return
        item = self.service.queue.peek()
        if item is None:
            self._refresh_queue()
            return

        self._queue_busy = True
        if hasattr(self, "queue_status_label"):
            self.queue_status_label.setText(
                f"Preparing {item.label} for "
                f"{item.character or 'the newest save'}…"
            )
        bridge = JobBridge(self)
        self._queue_bridge = bridge
        bridge.finished.connect(
            lambda _result, item_id=item.id: self._on_queue_ready(item_id)
        )
        bridge.failed.connect(
            lambda message, item_id=item.id: self._on_queue_failed(
                item_id, message
            )
        )
        threading.Thread(
            target=self._prepare_queued_task,
            args=(bridge, item),
            daemon=True,
        ).start()

    def _prepare_queued_task(self, bridge: JobBridge, item) -> None:
        try:
            if item.character_uuid or item.character:
                self.service.switch_character(
                    item.character_uuid or item.character
                )
        except Exception as exc:
            bridge.failed.emit(str(exc))
        else:
            bridge.finished.emit(item.id)

    def _on_queue_ready(self, item_id: int) -> None:
        self._queue_busy = False
        self._run_from_queue = False
        item = self.service.queue.get(item_id)
        if item is None or self.service.queue.paused:
            self._refresh_queue()
            self._maybe_start_queued()
            return
        self._refresh_environment()
        self._run_from_queue = True
        try:
            self.service.start_run(
                item.task,
                duration_minutes=item.duration_minutes,
                max_tasks=item.max_tasks,
                options=item.options,
            )
        except ServiceError as exc:
            self._run_from_queue = False
            self.service.queue.set_paused(True)
            self._refresh_queue()
            QMessageBox.warning(self, "Queue paused", str(exc))
            return
        self.service.queue.pop(item_id)
        self._hold_final_until = 0.0
        self.activity_view.appendPlainText(
            f"Queue started {item.label} for "
            f"{item.character or 'the newest save'}."
        )
        self._refresh_queue()

    def _on_queue_failed(self, item_id: int, message: str) -> None:
        self._queue_busy = False
        self.service.queue.set_paused(True)
        self._refresh_queue()
        QMessageBox.warning(
            self,
            "Queue paused",
            f"The next queued task could not start:\n\n{message}",
        )

    # -- characters ------------------------------------------------------
    def _build_character_bubbles(self, env: dict | None = None) -> None:
        if not hasattr(self, "character_layout"):
            return
        while self.character_layout.count():
            item = self.character_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.character_buttons = {}
        env = env or self.service.environment()
        self._env = env
        selected = env.get("selected") or {}
        active_uuid = str(selected.get("uuid") or "").lower()
        saves = [save for save in env.get("saves", []) if save.get("character")]
        saves.sort(key=lambda save: str(save.get("character", "")).lower())
        names: dict[str, int] = {}
        for save in saves:
            name = str(save.get("character", "?"))
            names[name.lower()] = names.get(name.lower(), 0) + 1
        for save in saves:
            name = str(save.get("character", "?"))
            uuid = str(save.get("uuid", ""))
            label = name
            if names.get(name.lower(), 0) > 1:
                label = f"{name} ({uuid[:8]})"
            button = QPushButton(label)
            button.setObjectName("characterBubble")
            button.setCheckable(True)
            button.setFixedHeight(22)
            button.setToolTip(
                f"Switch Melvor to {name}. The bot saves the current character "
                "and loads this save."
            )
            button.setChecked(uuid.lower() == active_uuid)
            button.clicked.connect(
                lambda _checked=False, target=uuid: self._switch_character(target)
            )
            self.character_layout.addWidget(button)
            self.character_buttons[uuid.lower()] = button
        if not saves:
            button = QPushButton("No character")
            button.setObjectName("characterBubble")
            button.setFixedHeight(22)
            button.setEnabled(False)
            self.character_layout.addWidget(button)

    def _update_character_bubble_checks(self) -> None:
        selected = self._env.get("selected") or {}
        active_uuid = str(selected.get("uuid") or "").lower()
        for uuid, button in self.character_buttons.items():
            button.setChecked(uuid == active_uuid)

    def _set_character_buttons_enabled(self, enabled: bool) -> None:
        for button in getattr(self, "character_buttons", {}).values():
            button.setEnabled(enabled)

    def _switch_character(self, target_uuid: str) -> None:
        if self._character_switch_job:
            return
        self._update_character_bubble_checks()
        if not target_uuid:
            try:
                self.service.save_settings({"save.character": ""})
            except ServiceError as exc:
                QMessageBox.warning(self, "Character selection", str(exc))
                return
            self._refresh_environment()
            self.statusBar().showMessage("Following the newest save.", 5000)
            return
        if (
            self._queue_busy
            or self._farming_job
            or self.service.controller.active
        ):
            self.statusBar().showMessage(
                "Stop the current run or queue before switching characters.",
                5000,
            )
            return

        self._character_switch_job = True
        self._set_character_buttons_enabled(False)
        self.statusBar().showMessage("Switching character in Melvor…", 0)
        bridge = JobBridge(self)
        self._character_bridge = bridge
        bridge.finished.connect(self._character_switched)
        bridge.failed.connect(self._character_switch_failed)
        threading.Thread(
            target=self._run_character_switch,
            args=(bridge, target_uuid),
            daemon=True,
        ).start()

    def _run_character_switch(self, bridge: JobBridge, target: str) -> None:
        try:
            result = self.service.switch_character(target)
        except Exception as exc:
            bridge.failed.emit(str(exc))
        else:
            bridge.finished.emit(result)

    def _character_switched(self, result) -> None:
        self._character_switch_job = False
        self._refresh_environment()
        self._set_character_buttons_enabled(True)
        name = (
            str(result.get("character_name", "character"))
            if isinstance(result, dict)
            else "character"
        )
        self.statusBar().showMessage(f"Switched to {name}.", 5000)
        self.activity_view.appendPlainText(f"Switched to {name}.")
        QTimer.singleShot(500, self._maybe_start_queued)

    def _character_switch_failed(self, message: str) -> None:
        self._character_switch_job = False
        self._update_character_bubble_checks()
        self._set_character_buttons_enabled(True)
        self.statusBar().showMessage("Character switch failed.", 5000)
        QMessageBox.warning(self, "Character switch failed", message)

    def _refresh_environment(self) -> None:
        try:
            self._env = self.service.environment()
            self._dungeons = self._env.get("dungeons", [])
        except Exception:
            self.logger.debug("Environment refresh failed", exc_info=True)
        self._build_character_bubbles(self._env)
        try:
            self._apply_status(self.service.idle_status())
        except Exception:
            self.logger.debug("Idle status refresh failed", exc_info=True)
        self._refresh_skills()
        self._update_cooking_preview()

    def _pause_run(self) -> None:
        if not self.service.pause_run():
            self.statusBar().showMessage("Nothing to pause.", 3000)

    def _resume_run(self) -> None:
        if not self.service.resume_run():
            self.statusBar().showMessage("Nothing to resume.", 3000)

    def _stop_run(self) -> None:
        if not self.service.stop_run():
            self._queue_stop_requested = False
            self.statusBar().showMessage("No active run.", 3000)
        else:
            self._queue_stop_requested = (
                self._run_from_queue or len(self.service.queue) > 0
            )

    def _set_farm_buttons_enabled(self, enabled: bool) -> None:
        self.farm_button.setEnabled(enabled)
        if hasattr(self, "farm_feature_button"):
            self.farm_feature_button.setEnabled(enabled)
        if hasattr(self, "farm_bones_button"):
            self.farm_bones_button.setEnabled(enabled)

    def _run_farming(self) -> None:
        if self._farming_job:
            return
        if self.service.controller.active:
            if self.service.request_farming():
                self.activity_view.appendPlainText(
                    "Farming pass queued; it will run between task steps and "
                    "then the current task will continue."
                )
                self.statusBar().showMessage(
                    "Farming pass queued; the current task will continue afterwards.",
                    6000,
                )
            else:
                QMessageBox.information(
                    self, "Farming", "The active run cannot accept a farm request."
                )
            return
        self._farming_job = True
        self._set_farm_buttons_enabled(False)
        self.start_button.setEnabled(False)
        bridge = JobBridge(self)
        self._job_bridge = bridge
        bridge.finished.connect(self._farming_finished)
        bridge.failed.connect(self._farming_failed)
        threading.Thread(
            target=self._farming_worker, args=(bridge,), name="mi2-farm", daemon=True
        ).start()

    def _farming_worker(self, bridge: JobBridge) -> None:
        try:
            bridge.finished.emit(self.service.run_farming_once())
        except Exception as exc:
            self.logger.exception("Manual farming pass failed")
            bridge.failed.emit(str(exc))

    def _farming_finished(self, counts) -> None:
        self._farming_job = False
        self._set_farm_buttons_enabled(True)
        self.start_button.setEnabled(not self.service.controller.active)
        summary = ", ".join(f"{key}={value}" for key, value in (counts or {}).items())
        self.activity_view.appendPlainText(f"Farming pass complete: {summary}")
        self.statusBar().showMessage("Farming pass complete.", 5000)

    def _farming_failed(self, message: str) -> None:
        self._farming_job = False
        self._set_farm_buttons_enabled(True)
        self.start_button.setEnabled(not self.service.controller.active)
        QMessageBox.warning(self, "Farming pass failed", message)

    # -- status updates --------------------------------------------------
    def _on_status(self, status: RunStatus) -> None:
        if status.state in {st.STOPPED, st.FAILED}:
            self._hold_final_until = time.monotonic() + 12.0
        self._apply_status(status)
        if status.state in {st.STOPPED, st.FAILED}:
            if getattr(self, "queue_table", None) is not None:
                if status.state == st.FAILED:
                    self.service.queue.set_paused(True)
                elif self._queue_stop_requested:
                    self.service.queue.set_paused(True)
                self._queue_stop_requested = False
                self._run_from_queue = False
                self._refresh_queue()
                if status.state == st.STOPPED and not self.service.queue.paused:
                    QTimer.singleShot(800, self._maybe_start_queued)

    def _apply_status(self, status: RunStatus) -> None:
        self._status = status
        state = status.state
        label = bot_state_label(state)
        self.state_label.setText(label)
        colors = {
            st.IDLE: ("#3a3c40", "#d0d0d0"),
            st.STARTING: ("#7a6418", "#fff2b3"),
            st.RUNNING: ("#1f6f43", "#d9ffe8"),
            st.PAUSED: ("#8a5a12", "#fff0c2"),
            st.STOPPING: ("#7a3c18", "#ffe0c9"),
            st.STOPPED: ("#3a3c40", "#d0d0d0"),
            st.FAILED: ("#7a2424", "#ffd8d8"),
        }
        background, foreground = colors.get(state, colors[st.IDLE])
        self.state_label.setStyleSheet(
            f"background:{background}; color:{foreground}; border-radius:10px;"
            "padding:4px 10px; font-weight:600;"
        )
        self.state_label.setToolTip(
            f"Bot run state: {label}. The client pill shows the character's "
            "current skill or Idle."
        )
        client_state = status.entity.strip() or "Idle"
        self.client_state_label.setText(client_state)
        active_client = bool(status.entity.strip())
        client_background = "#1f6f43" if active_client else "#3a3c40"
        client_foreground = "#d9ffe8" if active_client else "#d0d0d0"
        self.client_state_label.setStyleSheet(
            f"background:{client_background}; color:{client_foreground};"
            "border-radius:10px; padding:4px 10px; font-weight:600;"
        )
        if active_client:
            detail = status.action.strip()
            self.client_state_label.setToolTip(
                f"Client state: {client_state}"
                + (f" ({detail})" if detail else "")
                + "."
            )
        else:
            self.client_state_label.setToolTip("Client is idle.")
        self._set_stat("character", status.character or "—")
        self._set_stat("mode", status.mode or "—")
        self._set_stat("action", status.action or "—")
        self._set_stat("gp", f"{status.gp:,}" if status.gp else "—")
        self._set_stat("prayer", str(status.prayer_points))
        bank_text = str(status.bank_items) if status.bank_items else "—"
        self._set_stat("bank", bank_text)
        self.stat_labels["bank"].setStyleSheet(
            "color:#ffb4a2; font-weight:600;" if status.bank_items >= 300 else ""
        )
        if status.hp_ratio is not None:
            self._last_hp = status.hp_ratio
        if self._last_hp is None:
            self.hp_bar.setValue(0)
            self.hp_bar.setFormat("—")
            self.hp_bar.setStyleSheet("")
        else:
            value = max(0, min(100, round(self._last_hp * 100)))
            self.hp_bar.setValue(value)
            self.hp_bar.setFormat(f"{value}%")
            color = "#c0392b" if value < 35 else "#d68910" if value < 60 else "#2d8a4f"
            self.hp_bar.setStyleSheet(
                "QProgressBar::chunk {background:" + color + ";}"
            )
        if status.slayer.enemy_id:
            name = pretty_name(status.slayer.enemy_id)
            self.slayer_label.setText(f"{status.slayer.master}: {name}")
            length = max(1, status.slayer.length)
            self.slayer_bar.setRange(0, length)
            self.slayer_bar.setValue(min(length, status.slayer.progress))
            self.slayer_bar.setFormat(f"{status.slayer.progress}/{status.slayer.length}")
        else:
            self.slayer_label.setText("No active task")
            self.slayer_bar.setRange(0, 1)
            self.slayer_bar.setValue(0)
            self.slayer_bar.setFormat("—")
        self.completed_label.setText(f"Completed: {status.slayer.completed}")
        self.dry_run_badge.setVisible(bool(status.dry_run))
        active = status.active
        self.start_button.setEnabled(not active and not self._farming_job)
        self.farm_bones_button.setEnabled(not active and not self._farming_job)
        self._set_character_buttons_enabled(
            not active
            and not self._farming_job
            and not self._queue_busy
            and not self._character_switch_job
        )
        self.task_combo.setEnabled(not active)
        self.duration_input.setEnabled(not active)
        self.max_tasks_spin.setEnabled(not active)
        self.dry_run_check.setEnabled(not active)
        self.pause_button.setEnabled(status.state == st.RUNNING)
        self.resume_button.setEnabled(status.state == st.PAUSED)
        self.stop_button.setEnabled(active)
        if self.tray is not None:
            self.tray.setToolTip(
                f"MI2 AIO — {status.state}"
                + (f" — {status.task}" if status.task else "")
            )
        if status.last_error:
            text = status.last_error.strip()
            if text != self._last_error_text:
                self._last_error_text = text
                self.activity_view.appendPlainText(
                    f"ERROR: {text.splitlines()[-1]}"
                )
        else:
            self._last_error_text = ""

    def _set_stat(self, key: str, value: str) -> None:
        label = self.stat_labels.get(key)
        if label is not None:
            label.setText(value)

    def _refresh_skills(self) -> None:
        levels = self.service.skill_levels()
        total = 0
        for name, label in self.skill_labels.items():
            if name in UNAVAILABLE_SKILLS:
                label.setText(
                    f"<span style='color:#5f646c'>{name}</span> "
                    "<span style='color:#4a4f56'>—</span>"
                )
                continue
            level = levels.get(name)
            display = "—" if level is None else str(level)
            if level is not None:
                total += level
            label.setText(
                f"<span style='color:#8f949c'>{name}</span> "
                f"<b>{display}</b>"
            )
        total_display = str(total) if levels else "—"
        self.total_level_label.setText(
            "<span style='color:#8f949c'>Total Level</span> "
            f"<b>{total_display}</b>"
            f"<span style='color:#6e737b'>/{MAX_TOTAL_LEVEL}</span>"
        )

    def _tick(self) -> None:
        now = time.monotonic()
        if self.service.controller.active:
            self._apply_status(self.service.controller.status)
        elif now >= self._hold_final_until and now - self._last_idle_refresh >= 5.0:
            self._last_idle_refresh = now
            try:
                self._apply_status(self.service.idle_status())
            except Exception:
                self.logger.debug("Idle status refresh failed", exc_info=True)
        if now - self._last_window_refresh >= 5.0:
            self._last_window_refresh = now
            self._update_window_badge()

    def _update_window_badge(self) -> None:
        try:
            window = find_game_window(self.service.settings.game.window_title)
            if is_minimized(window.hwnd):
                self.window_badge.setText("Game: minimized")
            else:
                self.window_badge.setText(
                    f"Game: {window.client_width}×{window.client_height}"
                )
        except (LookupError, OSError):
            self.window_badge.setText("Game: not found")

    # -- logs / diagnostics ----------------------------------------------
    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        self.activity_view.appendPlainText(text)

    def _refresh_diagnostics(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data = collect_diagnostics(self.service.settings)
            from .diagnostics import format_diagnostics

            self.diagnostics_view.setPlainText(format_diagnostics(data))
            self._fill_saves(data.get("saves", []))
        except Exception:
            self.logger.exception("Diagnostics refresh failed")
            self.diagnostics_view.setPlainText("Diagnostics failed; see the log.")
        finally:
            QApplication.restoreOverrideCursor()

    def _fill_saves(self, saves: list[dict]) -> None:
        self.saves_table.setRowCount(0)
        for entry in saves:
            row = self.saves_table.rowCount()
            self.saves_table.insertRow(row)
            cells = [
                entry.get("character", "?"),
                entry.get("mode", "?"),
                str(entry.get("level", "")),
                entry.get("action", ""),
                entry.get("modified", ""),
            ]
            for column, value in enumerate(cells):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, entry.get("uuid") or entry.get("character"))
                self.saves_table.setItem(row, column, item)
        self.saves_table.resizeColumnsToContents()
        self.saves_table.horizontalHeader().setStretchLastSection(True)

    def _use_selected_character(self) -> None:
        row = self.saves_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Character", "Select a save row first.")
            return
        item = self.saves_table.item(row, 0)
        selector = item.data(Qt.UserRole) if item is not None else None
        if not selector:
            return
        try:
            self.service.save_settings({"save.character": str(selector)})
        except ServiceError as exc:
            QMessageBox.warning(self, "Character", str(exc))
            return
        self._env = self.service.environment()
        self._refresh_diagnostics()
        self._refresh_settings()
        self.statusBar().showMessage(f"Using save {selector}.", 5000)

    def _clear_character(self) -> None:
        try:
            self.service.save_settings({"save.character": ""})
        except ServiceError as exc:
            QMessageBox.warning(self, "Character", str(exc))
            return
        self._env = self.service.environment()
        self._refresh_diagnostics()
        self._refresh_settings()

    def _capture(self) -> None:
        try:
            path = self.service.capture_screenshot()
        except Exception as exc:
            QMessageBox.warning(self, "Screenshot", str(exc))
            return
        self.statusBar().showMessage(f"Saved {path}", 5000)
        self._open_path(path.parent)

    def _reset_settings(self) -> None:
        prefix = (
            "A bot run is active; the reset will apply to the next run.\n\n"
            if self.service.controller.active
            else ""
        )
        answer = QMessageBox.warning(
            self,
            "Reset settings",
            prefix
            + "Replace the active settings file with the bundled defaults?\n\n"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.reset_settings()
        except ServiceError as exc:
            QMessageBox.warning(self, "Reset settings", str(exc))
            return
        self._env = self.service.environment()
        self._refresh_settings()
        self._refresh_maintenance_labels()
        self._update_window_badge()
        self.activity_view.appendPlainText("Settings reset to defaults.")
        self.statusBar().showMessage("Settings reset to defaults.", 6000)

    def _open_path(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _tab_changed(self, index: int) -> None:
        if self.tabs.tabText(index) == "Diagnostics":
            self._refresh_diagnostics()
        elif self.tabs.tabText(index) == "Settings":
            # Pick up character changes made from Diagnostics.
            self._refresh_settings()

    # -- tray / window ---------------------------------------------------
    def _setup_hotkey(self) -> None:
        try:
            from .hotkey import KeyboardToggleHook

            self._hotkey = KeyboardToggleHook(
                lambda: QTimer.singleShot(0, self._toggle_visibility),
                self._should_toggle,
            )
            if not self._hotkey.install():
                self.logger.warning(
                    "Could not install the Ctrl+A hook; use the Hide UI button."
                )
                self._hotkey = None
        except Exception:
            self.logger.exception("Could not set up the Ctrl+A hotkey")
            self._hotkey = None

    def _should_toggle(self) -> bool:
        """Only consume Ctrl+A in the game or the non-text UI.

        In a text field (or another application) the key must behave normally
        so select-all keeps working.
        """
        try:
            if QApplication.activeModalWidget() is not None:
                return False
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            foreground = user32.GetForegroundWindow()
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(
                foreground, ctypes.byref(process_id)
            )
            if process_id.value == os.getpid():
                focus = QApplication.focusWidget()
                if isinstance(
                    focus,
                    (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox),
                ):
                    return False
                return True

            now = time.monotonic()
            if now - self._game_hwnd_cache[1] > 2.0:
                try:
                    from .window import find_game_window

                    game_hwnd = find_game_window(
                        self.service.settings.game.window_title
                    ).hwnd
                except (LookupError, OSError):
                    game_hwnd = 0
                self._game_hwnd_cache = (game_hwnd, now)
            return bool(
                self._game_hwnd_cache[0]
                and foreground == self._game_hwnd_cache[0]
            )
        except Exception:
            return False

    def _toggle_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
            self.logger.debug("UI hidden; the Ctrl+A overlay remains visible.")
        else:
            self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()
            self.logger.debug("UI shown.")
        if getattr(self, "overlay", None) is not None:
            self.overlay.reposition()

    def _show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        if getattr(self, "overlay", None) is not None:
            self.overlay.reposition()

    def _tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _refresh_maintenance_labels(self) -> None:
        settings = self.service.settings
        enabled = []
        for label, value in (
            ("Farming", settings.farming.enabled),
            ("Prayer", settings.prayer.enabled),
            ("Failsafe", settings.failsafe.enabled),
            ("Restore", settings.restore.enabled),
        ):
            enabled.append(f"{label}: {'on' if value else 'off'}")
        self.statusBar().showMessage(
            f"Config: {CONFIG_FILE} | " + " · ".join(enabled), 8000
        )

    def _restore_geometry(self) -> None:
        settings = QSettings("MI2 AIO", "MI2 AIO")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def _apply_start_tab(self) -> None:
        """Development/diagnostic hook: MI2_AIO_START_TAB=settings|diagnostics."""
        import os

        name = os.environ.get("MI2_AIO_START_TAB", "").strip().lower()
        indexes = {
            "dashboard": 0,
            "features": 1,
            "queue": 2,
            "settings": 3,
            "diagnostics": 4,
            "logs": 4,
        }
        if name in indexes:
            self.tabs.setCurrentIndex(indexes[name])

    def closeEvent(self, event) -> None:
        if self.service.controller.active:
            if not self.isVisible():
                self.show()
            answer = QMessageBox.question(
                self,
                "Run active",
                "A bot run is active. Stop it and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.service.stop_run()
            if not self.service.controller.wait(20.0):
                answer = QMessageBox.question(
                    self,
                    "Still stopping",
                    "The run has not stopped yet. Quit anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
        QSettings("MI2 AIO", "MI2 AIO").setValue("geometry", self.saveGeometry())
        if self._hotkey is not None:
            self._hotkey.uninstall()
            self._hotkey = None
        if getattr(self, "overlay", None) is not None:
            self.overlay.close()
            self.overlay = None
        self.logger.removeHandler(self._qt_log_handler)
        event.accept()


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------
def make_icon() -> QIcon:
    asset = ASSETS_DIR / "icon.png"
    if asset.exists():
        return QIcon(str(asset))
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#2d6a4f"))
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
    painter.setPen(QColor("#e9fff5"))
    font = QFont("Segoe UI", 20, QFont.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "MI2")
    painter.end()
    return QIcon(pixmap)


DARK_STYLE = """
QWidget { background: #1e1f22; color: #e6e6e6; }
QMainWindow { background: #18191c; }
QGroupBox { border: 1px solid #35373c; border-radius: 7px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9fd3c7; }
QTabWidget::pane { border: 1px solid #35373c; border-radius: 6px; }
QTabBar::tab { background: #26272b; padding: 8px 18px; margin-right: 2px; border-top-left-radius: 5px; border-top-right-radius: 5px; }
QTabBar::tab:selected { background: #2d6a4f; color: #ffffff; }
QListWidget#featureSidebar { background: #202124; border: 1px solid #35373c; border-radius: 6px; padding: 6px; }
QListWidget#featureSidebar::item { padding: 10px 12px; border-radius: 4px; }
QListWidget#featureSidebar::item:selected { background: #2d6a4f; color: #ffffff; }
QPushButton { background: #2f3136; border: 1px solid #44474d; border-radius: 5px; padding: 6px 12px; }
QPushButton:hover { background: #3a3d43; }
QPushButton:disabled { background: #26272b; color: #777a80; border-color: #303237; }
QPushButton#startButton { background: #2d6a4f; border-color: #3b8a68; font-weight: 600; }
QPushButton#startButton:hover { background: #367d5d; }
QPushButton#stopButton { background: #7a2e2e; border-color: #9c4141; font-weight: 600; }
QPushButton#stopButton:hover { background: #913737; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: #26272b; border: 1px solid #3b3e44; border-radius: 4px; padding: 4px;
    selection-background-color: #2d6a4f;
}
QWidget#numberInput {
    background: #26272b; border: 1px solid #3b3e44; border-radius: 4px;
}
QLineEdit#numberInputEdit {
    background: transparent; border: none; padding: 0; color: #e6e6e6;
    selection-background-color: #2d6a4f;
}
QLabel#numberInputUnit {
    background: transparent; color: #b9bdc4;
}
QComboBox QAbstractItemView { background: #26272b; selection-background-color: #2d6a4f; }
QProgressBar { background: #26272b; border: 1px solid #3b3e44; border-radius: 4px; text-align: center; font-size: 12px; }
QProgressBar::chunk { background: #2d6a4f; border-radius: 3px; }
QHeaderView::section { background: #26272b; border: 1px solid #35373c; padding: 4px; }
QTableWidget { background: #202124; alternate-background-color: #24262a; gridline-color: #35373c; }
QLabel#appTitle { font-size: 22px; font-weight: 700; color: #d9ffe8; }
QLabel#appLogo { background: transparent; }
QPushButton#characterBubble {
    background: #202124;
    border: 1px solid #35373c;
    border-radius: 11px;
    padding: 0 12px;
    color: #b9bdc4;
    font-weight: 600;
    font-size: 12px;
}
QPushButton#characterBubble:hover { background: #2a2c30; }
QPushButton#characterBubble:checked {
    background: #1f3a2e;
    border-color: #2d6a4f;
    color: #d9ffe8;
}
QMenu { background: #202124; border: 1px solid #35373c; }
QMenu::item { padding: 5px 24px; }
QMenu::item:selected { background: #2d6a4f; color: #ffffff; }
QLabel#badge { background: #2f3136; border: 1px solid #44474d; border-radius: 5px; padding: 4px 9px; color: #e6e6e6; }
QLabel#dryRunBadge { background: #8a5a12; color: #fff0c2; border-radius: 9px; padding: 3px 9px; font-weight: 600; }
QPushButton#hideButton { background: #2f3136; padding: 4px 9px; }
QPushButton#logsButton:checked {
    background: #2d6a4f;
    border-color: #3b8a68;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#resetSettingsButton { background: #6b3a1f; border-color: #8f5030; font-weight: 600; }
QPushButton#resetSettingsButton:hover { background: #7d4425; }
QLabel#statTitle { color: #8f949c; font-size: 12px; }
QLabel#statValue { color: #f1f3f5; font-weight: 600; font-size: 12px; }
QLabel#skillValue { background: #202124; border: 1px solid #2f3136; border-radius: 4px; padding: 5px 8px; font-size: 12px; }
QLabel#skillValueMuted { background: #1b1c1f; border: 1px dashed #2a2c30; border-radius: 4px; padding: 5px 8px; font-size: 12px; }
QLabel#totalLevel { color: #8f949c; font-size: 12px; padding: 5px 8px; }
QLabel#muted { color: #8f949c; }
"""


def build_stylesheet() -> str:
    """Dark theme plus the light spin buttons and settings scrollbar."""
    up = (ASSETS_DIR / "spin_up.png").as_posix()
    down = (ASSETS_DIR / "spin_down.png").as_posix()
    left = (ASSETS_DIR / "spin_left.png").as_posix()
    right = (ASSETS_DIR / "spin_right.png").as_posix()
    return DARK_STYLE + f"""
QSpinBox, QDoubleSpinBox {{ padding-right: 14.5px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 13px;
    background: #f2f3f5;
    border-left: 1px solid #9a9ca3;
    border-bottom: 1px solid #9a9ca3;
    border-top-right-radius: 4px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 13px;
    background: #f2f3f5;
    border-left: 1px solid #9a9ca3;
    border-top: 1px solid #9a9ca3;
    border-bottom-right-radius: 4px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: #ffffff;
}}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed,
QDoubleSpinBox::up-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: #d9dde3;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{up}");
    width: 7.6px; height: 7.6px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{down}");
    width: 7.6px; height: 7.6px;
}}
QScrollBar:vertical {{
    background: #1e1f22; width: 13px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #f2f3f5; border-radius: 6px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #ffffff;
}}
QScrollBar::sub-line:vertical {{
    subcontrol-origin: margin; subcontrol-position: top;
    height: 13px; background: #f2f3f5; border: 1px solid #9a9ca3;
}}
QScrollBar::add-line:vertical {{
    subcontrol-origin: margin; subcontrol-position: bottom;
    height: 13px; background: #f2f3f5; border: 1px solid #9a9ca3;
}}
QScrollBar::up-arrow:vertical {{
    image: url("{up}"); width: 6.5px; height: 6.5px;
}}
QScrollBar::down-arrow:vertical {{
    image: url("{down}"); width: 6.5px; height: 6.5px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: #1e1f22; height: 13px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #f2f3f5; border-radius: 6px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #ffffff;
}}
QScrollBar::sub-line:horizontal {{
    subcontrol-origin: margin; subcontrol-position: left;
    width: 13px; background: #f2f3f5; border: 1px solid #9a9ca3;
}}
QScrollBar::add-line:horizontal {{
    subcontrol-origin: margin; subcontrol-position: right;
    width: 13px; background: #f2f3f5; border: 1px solid #9a9ca3;
}}
QScrollBar::left-arrow:horizontal {{
    image: url("{left}"); width: 6.5px; height: 6.5px;
}}
QScrollBar::right-arrow:horizontal {{
    image: url("{right}"); width: 6.5px; height: 6.5px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
"""


def configure_app_logging(level: str) -> logging.Logger:
    logger = get_logger()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    has_file = any(
        isinstance(handler, RotatingFileHandler) for handler in logger.handlers
    )
    if not has_file:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOGS_DIR / APP_LOG_NAME,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    return logger


def main(argv: list[str] | None = None, config_path: Path | None = None) -> int:
    ensure_runtime_dirs()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("MI2 AIO")
    app.setOrganizationName("MI2 AIO")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(make_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet())

    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MI2.AIO")
    except Exception:
        pass

    app_lock = SingleInstance("MI2_AIO_App")
    if not app_lock.acquire():
        QMessageBox.warning(
            None,
            "MI2 AIO",
            "MI2 AIO is already running. Close the other window first.",
        )
        return 1

    try:
        settings = load_settings(config_path)
        logger = configure_app_logging(settings.logging.level)
        service = AppService(settings_path=config_path, logger=logger)
        window = MainWindow(service, logger)
        window.show()
        return app.exec()
    finally:
        app_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
