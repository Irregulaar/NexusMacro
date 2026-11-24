"""Nexus Macro main UI."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QLocale, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPalette,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .backend import BackendError, X11Backend, list_displays
from . import config as config_module
from .config import Config
from .controller import EngineController
from .engine import Stats
from .launcher import GamescopeLauncher
from .paths import (
    APP_VERSION,
    DISPLAY_NAME,
    bundled_template_dir,
    captures_dir,
    config_dir,
    icon_path,
    resource_path,
    user_template_dir,
)
from .schedule import spawner_countdown_text
from .vision import Matcher, SPECS_BY_KEY
from .ui_pages import UiPagesMixin
from .ui_widgets import (
    Card,
    FeatureCard,
    InfoCard,
    LogView,
    SectionHeader,
    StatCard,
    ToggleRow,
    ToggleSwitch,
)


class LauncherBridge(QObject):
    log = Signal(str, str)
    status = Signal(str)
    ready = Signal(object)
    error = Signal(str)


class MainWindow(UiPagesMixin, QMainWindow):
    PAGE_TITLES = (
        ("Connection", "Launch, auto-join, window and reconnect controls."),
        ("Automation", "Features and buying schedule."),
        ("Settings", "Detection, buying and gamescope."),
        ("Log", "Full output and status."),
        ("About", f"About {DISPLAY_NAME}."),
    )

    def __init__(
        self,
        config: Optional[Config] = None,
        demo: bool = False,
    ) -> None:
        super().__init__()
        self.config = config or Config.load()
        self.config.validate()
        self.matcher = Matcher(bundled_template_dir(), user_template_dir(), self.config)
        self.controller = EngineController(self)
        self.launcher = GamescopeLauncher(self.config)
        self.launcher_bridge = LauncherBridge(self)
        self._running = False
        self._loading = True
        self._launch_busy = False
        self._fields: dict[str, QWidget] = {}
        self._uptime_start = time.monotonic()
        self._flatpak_running = False
        self._engine_started_at: Optional[float] = None
        self._minimized_by_app = False
        self._engine_expected = False
        self._game_expected = False
        self._auto_reconnect_at = 0.0
        self._auto_reconnect_silent = False
        self._restart_in_progress = False
        self._last_game_restart_at = 0.0

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._save_config_now)

        self._build_ui()
        self._wire_signals()
        self._load_config_into_widgets()
        self._loading = False
        self._set_running(False)
        self._show_last_saved()
        self._update_game_status()
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._update_uptime)
        self._uptime_timer.start()
        self._update_uptime()
        self._update_spawner_countdown()
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(5000)
        self._reconnect_timer.timeout.connect(self._auto_reconnect_tick)
        self._reconnect_timer.start()
        self._append_log(
            f"{DISPLAY_NAME} v{APP_VERSION} ready. Config: {config_module.config_file()}",
            "success",
        )
        if config_module.LAST_LOAD_ERROR:
            self._append_log(
                "Config warning: " + config_module.LAST_LOAD_ERROR, "warning"
            )
            self.footer_status.setText("Config had invalid values")
            self.footer_status.setToolTip(config_module.LAST_LOAD_ERROR)
        self._append_log(
            "The game runs in gamescope's private Xwayland. Use the Connection "
            "tab for launch and window controls.",
            "info",
        )
        if not demo:
            QTimer.singleShot(500, self._auto_detect)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle(f"{DISPLAY_NAME} — Build a Tower Defense Autopilot")
        self.setFixedSize(880, 560)
        try:
            icon = QIcon(str(icon_path()))
            if not icon.isNull():
                self.setWindowIcon(icon)
        except Exception:
            pass

        style_path = resource_path("assets", "style.qss")
        try:
            self.setStyleSheet(style_path.read_text(encoding="utf-8"))
        except Exception:
            pass

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 6)
        root_layout.setSpacing(5)

        root_layout.addWidget(self._build_top_bar())
        root_layout.addWidget(self._build_tab_bar())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_connection_page())
        self.stack.addWidget(self._build_automation_page())
        self.stack.addWidget(self._build_settings_page())
        self.stack.addWidget(self._build_log_page())
        self.stack.addWidget(self._build_about_page())
        root_layout.addWidget(self.stack, 1)
        root_layout.addWidget(self._build_footer())

        self._switch_page(0)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(DISPLAY_NAME.upper())
        title.setObjectName("brandTitle")
        subtitle = QLabel(f"v{APP_VERSION} — BUILD A TOWER DEFENSE AUTOPILOT")
        subtitle.setObjectName("brandSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch(1)

        self.status_pill = QLabel("STOPPED")
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_pill)

        self.start_btn = QPushButton("▶ START")
        self.start_btn.setObjectName("primary")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setMinimumWidth(78)
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■ STOP")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setMinimumWidth(78)
        layout.addWidget(self.stop_btn)

        self._shortcut_stop = QShortcut(QKeySequence("F7"), self)
        self._shortcut_stop.activated.connect(self._stop_engine)
        return bar

    def _build_tab_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        labels = (
            "Connection",
            "Automation",
            "Settings",
            "Log",
            "About",
        )
        for index, text in enumerate(labels):
            button = QPushButton(text)
            button.setObjectName("tab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            self.nav_group.addButton(button, index)
            layout.addWidget(button)
        layout.addStretch(1)
        self.nav_group.idClicked.connect(self._switch_page)
        return bar


    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.footer_status = QLabel("Ready")
        self.footer_status.setObjectName("tiny")
        layout.addWidget(self.footer_status)

        # Hidden legacy sidebar-status widgets kept for method compatibility.
        self._hidden_status = QWidget(footer)
        self._hidden_status.hide()
        hidden_layout = QHBoxLayout(self._hidden_status)
        hidden_layout.setContentsMargins(0, 0, 0, 0)
        self.side_dot = QLabel("●", self._hidden_status)
        self.side_dot.setStyleSheet("color: #6c6c78; font-size: 12px;")
        self.side_status = QLabel("Ready", self._hidden_status)
        self.side_detail = QLabel("Not attached", self._hidden_status)
        hidden_layout.addWidget(self.side_dot)
        hidden_layout.addWidget(self.side_status)
        hidden_layout.addWidget(self.side_detail)

        self.footer_save = QLabel("")
        self.footer_save.setObjectName("tiny")
        self.footer_save.setStyleSheet("color:#a855f7;")
        self.footer_save.setToolTip(
            f"Settings are written to {config_module.config_file()}"
        )
        self.footer_attached = QLabel("Not attached")
        self.footer_attached.setObjectName("tiny")
        self.footer_version = QLabel(f"v{APP_VERSION}")
        self.footer_version.setObjectName("tiny")
        layout.addStretch(1)
        layout.addWidget(self.footer_save)
        layout.addWidget(self.footer_attached)
        layout.addWidget(self.footer_version)
        return footer

    @staticmethod
    def _dark_page(page: QWidget) -> QWidget:
        page.setAutoFillBackground(True)
        palette = page.palette()
        palette.setColor(QPalette.Window, QColor("#0a0810"))
        palette.setColor(QPalette.Base, QColor("#0a0810"))
        page.setPalette(palette)
        return page

    def _divider(self) -> QFrame:
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.HLine)
        divider.setFixedHeight(1)
        return divider

    def _form_card(self, title: str, subtitle: str) -> tuple[Card, QFormLayout]:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        layout.addWidget(SectionHeader(title, subtitle))

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 2, 0, 0)
        form.setSpacing(4)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addWidget(form_widget)
        return card, form

    def _add_form_row(
        self,
        form: QFormLayout,
        label: str,
        widget: QWidget,
        hint: str = "",
    ) -> None:
        if hint:
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(2)
            box_layout.addWidget(widget)
            hint_label = QLabel(hint)
            hint_label.setObjectName("tiny")
            hint_label.setWordWrap(True)
            box_layout.addWidget(hint_label)
            form.addRow(label, box)
        else:
            form.addRow(label, widget)

    # ------------------------------------------------------------------
    # Config / widget helpers
    # ------------------------------------------------------------------

    def _make_spin(
        self,
        key: str,
        minimum: int,
        maximum: int,
        step: int,
    ) -> QSpinBox:
        widget = QSpinBox()
        widget.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        widget.setValue(int(getattr(self.config, key)))
        widget.valueChanged.connect(lambda value, k=key: self._set_config(k, value))
        widget.editingFinished.connect(
            lambda k=key, w=widget: self._set_config(k, w.value())
        )
        self._fields[key] = widget
        return widget

    def _make_double(
        self,
        key: str,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
        widget.setDecimals(decimals)
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        widget.setValue(float(getattr(self.config, key)))
        widget.valueChanged.connect(lambda value, k=key: self._set_config(k, value))
        widget.editingFinished.connect(
            lambda k=key, w=widget: self._set_config(k, w.value())
        )
        self._fields[key] = widget
        return widget

    def _make_combo(self, key: str, options: tuple[tuple[str, str], ...]) -> QComboBox:
        widget = QComboBox()
        for label, value in options:
            widget.addItem(label, value)
        index = widget.findData(getattr(self.config, key))
        if index >= 0:
            widget.setCurrentIndex(index)
        widget.currentIndexChanged.connect(
            lambda _index, k=key, w=widget: self._set_config(
                k, w.currentData()
            )
        )
        self._fields[key] = widget
        return widget

    def _make_check(self, key: str, text: str) -> QCheckBox:
        widget = QCheckBox(text)
        widget.setChecked(bool(getattr(self.config, key)))
        widget.toggled.connect(lambda value, k=key: self._set_config(k, value))
        self._fields[key] = widget
        return widget

    def _reflect_config_in_widget(self, key: str) -> None:
        """Keep a widget in sync when the config is changed programmatically.

        User edits already update both sides; this only matters for tests and
        for code that changes config directly, so a later full widget sync
        cannot revert the change. Text fields are skipped on purpose: validate
        rewrites the normalised value and we do not want to move the caret.
        """
        value = getattr(self.config, key, None)
        widget = self._fields.get(key)
        try:
            if isinstance(widget, QSpinBox):
                widget.blockSignals(True)
                widget.setValue(int(value))
                widget.blockSignals(False)
            elif isinstance(widget, QDoubleSpinBox):
                widget.blockSignals(True)
                widget.setValue(float(value))
                widget.blockSignals(False)
            elif isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index >= 0 and index != widget.currentIndex():
                    widget.blockSignals(True)
                    widget.setCurrentIndex(index)
                    widget.blockSignals(False)
            elif isinstance(widget, QCheckBox):
                if widget.isChecked() != bool(value):
                    widget.blockSignals(True)
                    widget.setChecked(bool(value))
                    widget.blockSignals(False)
        except Exception:
            pass
        toggles = {
            "auto_battle": "battle_toggle",
            "auto_spawners": "spawners_toggle",
            "auto_fuse": "fuse_toggle",
            "auto_best_place": "place_toggle",
            "auto_reconnect": "reconnect_toggle",
            "auto_join": "join_toggle",
        }
        name = toggles.get(key)
        toggle = getattr(self, name, None) if name else None
        if toggle is not None and toggle.isChecked() != bool(value):
            try:
                toggle.set_checked_silent(bool(value))
            except Exception:
                pass

    def _set_config(self, key: str, value: Any) -> None:
        if self._loading:
            return
        setattr(self.config, key, value)
        self.config.validate()
        self._reflect_config_in_widget(key)
        if key in ("scale", "ignore_spawner_timer", "ignore_buy_price"):
            self.matcher.reload()
        if key in ("width", "window_width", "window_height"):
            self._update_game_status()
        if key == "gamescope_backend":
            self.minimize_check.setEnabled(value == "sdl")
            self._update_window_button()
        if key in (
            "auto_spawners",
            "spawner_timing",
            "spawner_window_seconds",
            "spawner_interval_minutes",
            "spawner_poll_seconds",
        ):
            self._update_spawner_countdown()
        if key in (
            "gamescope_backend",
            "gamescope_fps",
            "gamescope_grab_cursor",
            "window_width",
            "window_height",
            "gamescope_path",
            "display",
        ):
            self._append_log(
                "Window setting saved; relaunch Sober to apply it.", "info"
            )
        self.controller.update_config(self.config, key)
        if isinstance(value, (bool, str)):
            if self._save_timer.isActive():
                self._save_timer.stop()
            self._save_config_now()
        else:
            self._queue_save()

    def _queue_save(self) -> None:
        self._save_timer.start()

    def _sync_config_from_widgets(self) -> None:
        """Read every visible widget before saving.

        QSpinBox/QDoubleSpinBox only emit valueChanged after Enter or focus
        loss; this catches values typed and left uncommitted when the window
        is closed.
        """
        for key, widget in self._fields.items():
            try:
                if isinstance(widget, QSpinBox):
                    value: Any = widget.value()
                elif isinstance(widget, QDoubleSpinBox):
                    value = widget.value()
                elif isinstance(widget, QComboBox):
                    value = widget.currentData()
                    if value is None:
                        continue
                elif isinstance(widget, QCheckBox):
                    value = widget.isChecked()
                elif isinstance(widget, QLineEdit):
                    value = widget.text().strip()
                else:
                    continue
                setattr(self.config, key, value)
            except Exception:
                continue
        self.config.auto_battle = self.battle_toggle.isChecked()
        self.config.auto_spawners = self.spawners_toggle.isChecked()
        self.config.auto_fuse = self.fuse_toggle.isChecked()
        self.config.auto_best_place = self.place_toggle.isChecked()
        self.config.auto_reconnect = self.reconnect_toggle.isChecked()
        self.config.auto_join = self.join_toggle.isChecked()
        self.config.validate()

    def _show_last_saved(self) -> None:
        """Show the last write time of the config file at startup."""
        try:
            stamp = time.strftime(
                "%H:%M", time.localtime(config_module.config_file().stat().st_mtime)
            )
            self.footer_save.setText(f"Saved {stamp}")
        except Exception:
            self.footer_save.setText("No config yet")

    def _save_config_now(self) -> None:
        self._sync_config_from_widgets()
        try:
            self.config.save()
            stamp = time.strftime("%H:%M:%S")
            self.footer_status.setText(f"Settings saved {stamp}")
            self.footer_save.setText(f"Saved {stamp}")
            self.footer_save.setStyleSheet("color:#a855f7;")
            self.footer_status.setToolTip(
                f"Autosaved to {config_module.config_file()}\n"
                f"Backup: {config_module.config_file().with_suffix('.json.bak')}"
            )
            self._last_save_ok = stamp
        except Exception as exc:
            self.footer_status.setText("Settings NOT saved")
            self.footer_save.setText("NOT saved")
            self.footer_save.setStyleSheet("color:#f87171;")
            self.footer_status.setToolTip(str(exc))
            self._append_log(
                f"Couldn't save settings to {config_module.config_file()}: {exc}", "error"
            )
            if not getattr(self, "_save_error_shown", False):
                self._save_error_shown = True
                QMessageBox.critical(
                    self,
                    "Settings not saved",
                    f"Could not write:\n{config_module.config_file()}\n\n{exc}\n\n"
                    "Check that the folder is writable.",
                )

    def _load_config_into_widgets(self) -> None:
        self._loading = True
        try:
            self.battle_toggle.set_checked_silent(self.config.auto_battle)
            self.spawners_toggle.set_checked_silent(self.config.auto_spawners)
            self.fuse_toggle.set_checked_silent(self.config.auto_fuse)
            self.place_toggle.set_checked_silent(self.config.auto_best_place)
            self.reconnect_toggle.set_checked_silent(self.config.auto_reconnect)
            self.join_toggle.set_checked_silent(self.config.auto_join)
            for key, widget in self._fields.items():
                value = getattr(self.config, key, None)
                if isinstance(widget, QSpinBox):
                    widget.setValue(int(value))
                elif isinstance(widget, QDoubleSpinBox):
                    widget.setValue(float(value))
                elif isinstance(widget, QComboBox):
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value or ""))
        finally:
            self._loading = False
        self.minimize_check.setEnabled(self.config.gamescope_backend == "sdl")
        self._update_spawner_countdown()

    def _reset_config(self) -> None:
        if self._running:
            QMessageBox.warning(
                self,
                "Engine running",
                "Stop the engine before resetting settings.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Reset settings",
            "Restore all defaults?",
        )
        if answer != QMessageBox.Yes:
            return
        self.config = Config()
        self.config.validate()
        self.matcher.config = self.config
        self.launcher.config = self.config
        self._load_config_into_widgets()
        self._save_config_now()
        self._append_log("Settings restored to defaults.", "warning")

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        self.start_btn.clicked.connect(self._start_engine)
        self.stop_btn.clicked.connect(self._stop_engine)
        self.launch_btn.clicked.connect(self._launch_sober)
        self.stop_game_btn.clicked.connect(self._stop_sober)
        self.reconnect_btn.clicked.connect(self._refresh_game_status_clicked)
        self.window_btn.clicked.connect(self._toggle_host_window)
        self.buy_spawners_btn.clicked.connect(self._buy_spawners_now)
        self.open_captures_btn.clicked.connect(self._open_captures)

        self.battle_toggle.toggled.connect(
            lambda checked: self._set_config("auto_battle", checked)
        )
        self.spawners_toggle.toggled.connect(
            lambda checked: self._set_config("auto_spawners", checked)
        )
        self.fuse_toggle.toggled.connect(
            lambda checked: self._set_config("auto_fuse", checked)
        )
        self.place_toggle.toggled.connect(
            lambda checked: self._set_config("auto_best_place", checked)
        )
        self.reconnect_toggle.toggled.connect(
            lambda checked: self._set_config("auto_reconnect", checked)
        )
        self.join_toggle.toggled.connect(
            lambda checked: self._set_config("auto_join", checked)
        )

        self.controller.log.connect(self._append_log)
        self.controller.status.connect(self._on_engine_status)
        self.controller.stats.connect(self._update_stats)
        self.controller.finished.connect(self._on_engine_finished)
        self.controller.spawner_once_done.connect(self._on_spawner_once_done)
        self.controller.game_restart_requested.connect(
            self._on_game_restart_requested
        )

        self.launcher_bridge.log.connect(self._append_log)
        self.launcher_bridge.status.connect(self._on_launcher_status)
        self.launcher_bridge.ready.connect(self._on_launcher_ready)
        self.launcher_bridge.error.connect(self._on_launcher_error)

    # ------------------------------------------------------------------
    # Navigation / state
    # ------------------------------------------------------------------

    def _switch_page(self, index: int) -> None:
        if not 0 <= index < self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        button = self.nav_group.button(index)
        if button and not button.isChecked():
            button.setChecked(True)
        title, subtitle = self.PAGE_TITLES[index]
        self.setWindowTitle(f"{DISPLAY_NAME} — {title}")

    def _update_uptime(self) -> None:
        elapsed = max(0, int(time.monotonic() - self._uptime_start))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.info_uptime.set_value(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self._update_spawner_countdown()

    def _update_spawner_countdown(self) -> None:
        if not hasattr(self, "spawner_refresh_label"):
            return
        if not self.config.auto_spawners:
            text = "Spawner buying disabled"
        elif self.config.spawner_timing == "clock":
            text = spawner_countdown_text(
                window_seconds=self.config.spawner_window_seconds
            )
        elif self.config.spawner_timing == "interval":
            text = (
                "Spawners: every "
                f"{self.config.spawner_interval_minutes} min from Start"
            )
        else:
            text = (
                "Spawners: polling every "
                f"{self.config.spawner_poll_seconds} s"
            )
        self.spawner_refresh_label.setText(text)

    def _append_log(self, message: str, level: str = "info") -> None:
        try:
            self.log_view.append_log(message, level)
        except Exception:
            pass

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        # Feature toggles stay enabled while running and apply live.
        if running:
            self._engine_started_at = time.monotonic()
            self.status_pill.setText("RUNNING")
            self.status_pill.setStyleSheet(
                "background:#2e1065; color:#c084fc; border:1px solid #7c3aed;"
            )
            self.footer_status.setText("Engine running")
            self.side_dot.setStyleSheet("color:#a855f7; font-size:12px;")
            self.side_status.setText("Running")
            self.side_detail.setText("Engine active")
        else:
            self._engine_started_at = None
            self.status_pill.setText("STOPPED")
            self.status_pill.setStyleSheet(
                "background:#141020; color:#8b8b96; border:1px solid #2c2440;"
            )
            self.footer_status.setText("Ready")

    def _on_engine_status(self, text: str) -> None:
        self.footer_status.setText(text)

    def _update_stats(self, stats: Stats) -> None:
        self.session_stats.setText(
            f"Battles {stats.battles} · Buys {stats.buy_clicks} · "
            f"Scrolls {stats.scrolls} · Cycles {stats.cycles}"
        )

    def _on_engine_finished(self) -> None:
        if self._running:
            if self._minimized_by_app:
                if self.launcher.restore_host():
                    self._append_log("Game window restored.", "info")
                self._minimized_by_app = False
            self._set_running(False)
            self._restore_action_buttons()
            self._update_game_status()
            self._update_window_button()
        if self._engine_expected and self.config.auto_reconnect:
            QTimer.singleShot(3000, self._restart_engine_if_needed)

    def _stop_engine(self) -> None:
        if not self._running:
            return
        # Stop also cancels Auto Reconnect for this game: closing Sober after
        # pressing Stop must not make the macro launch gamescope again.
        self._engine_expected = False
        self._game_expected = False
        self._auto_reconnect_at = 0.0
        self._auto_reconnect_silent = False
        self._restart_in_progress = False
        self._last_game_restart_at = 0.0
        self.controller.stop()
        self.stop_btn.setEnabled(False)
        self.status_pill.setText("STOPPING")
        self.status_pill.setStyleSheet(
            "background:#2b2411; color:#f5b84b; border:1px solid #5a4714;"
        )
        self.footer_status.setText("Stopping engine...")
        self._append_log("Stopping engine...", "info")
        QTimer.singleShot(6000, self._force_stop_timeout)

    def _force_stop_timeout(self) -> None:
        if self._running and not self.controller.running:
            self._on_engine_finished()

    def _fuse_now(self) -> None:
        self._run_optional_manual("fuse")

    def _place_now(self) -> None:
        self._run_optional_manual("place")

    def _run_optional_manual(self, kind: str) -> None:
        title = "Fuse" if kind == "fuse" else "Best Place"
        target_key = "fuseall" if kind == "fuse" else "placebest"
        required = ["build", target_key, "stop", "forfeit", "confirm"]
        statuses = {item["key"]: item for item in self.matcher.template_status()}
        missing = [
            SPECS_BY_KEY[key].filename
            for key in required
            if key not in statuses or not statuses[key]["exists"]
        ]
        if missing:
            QMessageBox.critical(
                self,
                "Missing templates",
                f"{title} needs these images:\n\n"
                + "\n".join(f"• {name}" for name in missing),
            )
            return
        if self.controller.spawner_once_running:
            self._append_log(
                "Another manual action is already running.", "warning"
            )
            return
        if not list_displays(self.config.window_class):
            self._append_log("No game window attached.", "warning")
            self.footer_status.setText("Not attached")
            return
        cfg = self.config.copy()
        matcher = Matcher(bundled_template_dir(), user_template_dir(), cfg)
        button = self.fuse_now_btn if kind == "fuse" else self.place_now_btn
        button.setText("Fusing..." if kind == "fuse" else "Placing...")
        self._set_manual_buttons_enabled(False)
        self.footer_status.setText(f"Manual {title}...")

        if self._running:
            if self.controller.request_optional_action(kind):
                self._append_log(
                    f"Manual {title} requested for the running engine.",
                    "action",
                )
                return
            self._restore_action_buttons()
            self._append_log(
                "The engine is not ready yet; try again in a moment.",
                "warning",
            )
            return

        self._append_log(f"Starting manual {title.lower()}...", "action")
        if not self.controller.start_optional_once(kind, cfg, matcher):
            self._restore_action_buttons()
            self._append_log(
                "Couldn't start the manual action.", "warning"
            )

    def _set_manual_buttons_enabled(self, enabled: bool) -> None:
        self.buy_spawners_btn.setEnabled(enabled)
        self.fuse_now_btn.setEnabled(enabled)
        self.place_now_btn.setEnabled(enabled)
        if enabled and not self._running:
            self.start_btn.setEnabled(True)

    def _restore_action_buttons(self) -> None:
        self.buy_spawners_btn.setText("Buy Spawners Now")
        self.fuse_now_btn.setText("Fuse Now")
        self.place_now_btn.setText("Best Place Now")
        self._set_manual_buttons_enabled(True)

    def _buy_spawners_now(self) -> None:
        required = ["buy"]
        if self.config.scroll_method == "drag":
            required.append("scroll")
        if self.config.close_shop:
            required.append("close")
        statuses = {item["key"]: item for item in self.matcher.template_status()}
        missing = [
            SPECS_BY_KEY[key].filename
            for key in required
            if key not in statuses or not statuses[key]["exists"]
        ]
        if not any(
            statuses.get(key, {}).get("exists")
            for key in ("spawner1", "spawner2", "spawner3")
        ):
            missing.append("a spawner button template")
        if missing:
            QMessageBox.critical(
                self,
                "Missing templates",
                "A spawner purchase needs these images:\n\n"
                + "\n".join(f"• {name}" for name in missing)
                + "\n\nAdd them to the templates folder.",
            )
            return

        if self._running:
            if self.controller.request_spawner_purchase():
                self._append_log(
                    "Spawner purchase requested for the running engine.", "action"
                )
                self.footer_status.setText("Spawner purchase requested")
                self.buy_spawners_btn.setText("Requested...")
                self._set_manual_buttons_enabled(False)
            else:
                self._append_log(
                    "The engine is not ready yet; try again in a moment.",
                    "warning",
                )
            return

        if self.controller.spawner_once_running:
            self._append_log(
                "A manual spawner purchase is already running.", "warning"
            )
            return

        cfg = self.config.copy()
        cfg.auto_spawners = True
        matcher = Matcher(bundled_template_dir(), user_template_dir(), cfg)
        self.buy_spawners_btn.setText("Buying...")
        self._set_manual_buttons_enabled(False)
        self.footer_status.setText("Manual spawner purchase...")
        self._append_log("Starting manual spawner purchase...", "action")
        if not self.controller.start_spawner_once(cfg, matcher):
            self._restore_action_buttons()

    def _on_spawner_once_done(self) -> None:
        self._restore_action_buttons()
        self._append_log("Manual action finished.", "info")
        self.footer_status.setText("Ready")

    def _start_engine(self) -> None:
        if self._running:
            return
        # Commit anything typed but not yet confirmed (spin boxes, text)
        # before the engine copies the config.
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._save_config_now()
        if not any(
            (
                self.config.auto_battle,
                self.config.auto_spawners,
                self.config.auto_fuse,
                self.config.auto_best_place,
            )
        ):
            QMessageBox.information(
                self,
                "Nothing to run",
                "Enable Auto Battle, Auto Spawners, Auto Fuse or Auto Best Place.",
            )
            return

        missing = self._missing_templates()
        if missing:
            QMessageBox.critical(
                self,
                "Missing templates",
                "Can't start without these images:\n\n"
                + "\n".join(f"• {name}" for name in missing)
                + "\n\nAdd them to the templates folder.",
            )
            return

        if not list_displays(self.config.window_class):
            self._engine_expected = True
            self._game_expected = True
            self.status_pill.setText("LAUNCHING")
            self.status_pill.setStyleSheet(
                "background:#2b2411; color:#f5b84b; border:1px solid #5a4714;"
            )
            self.footer_status.setText("Launching Sober...")
            self._append_log(
                "Game not attached; launching Sober automatically.", "action"
            )
            self._auto_launch_sober()
            return

        backend = X11Backend(
            display_name=self.config.display or None,
            wm_class=self.config.window_class,
        )
        try:
            backend.connect()
            display = backend.display_name
            size = backend.size
        except BackendError as exc:
            headless = self.launcher.connected_display()
            flatpak = self.launcher.flatpak_running()
            if headless:
                title = "Sober is not responding"
                body = (
                    f"Found a Sober game window on {headless}, "
                    "but couldn't connect to it. Try Reconnect or restart the "
                    "gamescope instance."
                )
            elif flatpak:
                title = "Sober is open outside the macro"
                body = (
                    "Sober is running on your desktop, but the macro needs its "
                    "own gamescope instance. Close it and click Launch Sober."
                )
            else:
                title = "Sober is not running"
                body = (
                    "Sober isn't open. Click Launch Sober to start the game, then "
                    "press Start again."
                )
            QMessageBox.critical(self, title, f"{body}\n\nDetails: {exc}")
            self._append_log(str(exc), "error")
            self._update_game_status()
            return
        finally:
            backend.close()

        self._append_log(
            f"Connected to {display} ({size[0]}×{size[1]}); starting {DISPLAY_NAME}.",
            "success",
        )
        self._update_game_status()
        self._minimized_by_app = False
        if self.config.minimize_on_start:
            if self.config.gamescope_backend == "sdl":
                if self.launcher.minimize_host():
                    self._minimized_by_app = True
                    self._append_log(
                        "Game window minimized; the engine continues in the background.",
                        "success",
                    )
                    self._update_window_button()
                else:
                    self._append_log(
                        "Couldn't minimize the game window; you can minimize it manually.",
                        "warning",
                    )
            elif self.config.gamescope_backend == "wayland":
                self._append_log(
                    "Automatic minimize requires the visible SDL/X11 mode.",
                    "warning",
                )
        cfg = self.config.copy()
        matcher = Matcher(bundled_template_dir(), user_template_dir(), cfg)
        self._engine_expected = True
        self.controller.start(cfg, matcher)
        self._set_running(True)
        self._append_log(
            "Engine started. Settings can be changed live.",
            "info",
        )

    # ------------------------------------------------------------------
    # Game / launcher
    # ------------------------------------------------------------------

    def _auto_reconnect_tick(self) -> None:
        if not self.config.auto_reconnect or not self._game_expected:
            return
        if self._launch_busy:
            return
        now = time.monotonic()
        if now < self._auto_reconnect_at:
            return
        if list_displays(self.config.window_class):
            return
        self._auto_reconnect_at = now + 30.0
        self._append_log(
            "Auto Reconnect: game window lost; relaunching Sober...", "warning"
        )
        if self._running:
            self._stop_engine()
            # _stop_engine cancels the expected states; this relaunch is the
            # intentional Auto Reconnect, so re-arm both for the new engine.
            self._engine_expected = True
            self._game_expected = True
        self._auto_reconnect_silent = True
        self._launch_busy = True
        self.launch_btn.setEnabled(False)
        self.stop_game_btn.setEnabled(False)
        self.reconnect_btn.setEnabled(False)
        self.game_detail.setText("Auto Reconnect: launching gamescope...")
        self.side_status.setText("Reconnecting...")
        self.side_dot.setStyleSheet("color:#f5b84b; font-size:12px;")
        self.launcher.start_async(
            on_log=self.launcher_bridge.log.emit,
            on_status=self.launcher_bridge.status.emit,
            on_ready=self.launcher_bridge.ready.emit,
            on_error=self.launcher_bridge.error.emit,
            kill_existing=True,
        )

    def _restart_engine_if_needed(self, attempt: int = 0) -> None:
        if not self._engine_expected or self._running:
            return
        if not list_displays(self.config.window_class):
            if attempt < 8:
                QTimer.singleShot(
                    1500, lambda: self._restart_engine_if_needed(attempt + 1)
                )
            return
        self._append_log("Auto Reconnect: restarting the engine.", "action")
        self._start_engine()

    def _auto_detect(self) -> None:
        if self._launch_busy:
            return
        self._update_game_status()
        if self.launcher.connected_display() is None:
            if self.launcher.flatpak_running():
                self._append_log(
                    "Sober is open on the desktop, but not in the macro's "
                    "gamescope instance.",
                    "warning",
                )
            else:
                self._append_log(
                    "No Sober game instance is attached. Click Launch Sober.",
                    "info",
                )

    def _refresh_game_status_clicked(self) -> None:
        self._update_game_status()
        displays = list_displays(self.config.window_class)
        if displays:
            info = displays[0]
            self._append_log(
                f"Game detected on {info['display']} "
                f"({info['width']}×{info['height']}).",
                "success",
            )
        elif self.launcher.flatpak_running():
            self._append_log(
                "Sober is running, but not in the macro's gamescope instance.",
                "warning",
            )
        else:
            self._append_log("Sober is not running.", "warning")

    def _update_game_status(self) -> None:
        if self._launch_busy:
            self.game_dot.setStyleSheet("color:#f5b84b; font-size:16px;")
            self.game_title.setText("Launching Sober...")
            self.game_detail.setText("Starting gamescope and waiting for the game.")
            self.side_dot.setStyleSheet("color:#f5b84b; font-size:12px;")
            self.side_status.setText("Launching...")
            self.side_detail.setText("Please wait")
            self.info_attached.set_value("Starting...")
            self.footer_attached.setText("Starting...")
            self.launch_btn.setEnabled(False)
            self.stop_game_btn.setEnabled(False)
            self._update_window_button()
            return
        displays = list_displays(self.config.window_class)
        self._flatpak_running = self.launcher.flatpak_running()
        if displays:
            info = displays[0]
            self.game_dot.setStyleSheet("color:#42d392; font-size:16px;")
            self.game_title.setText("Sober is attached")
            self.game_detail.setText(
                f"Display {info['display']} · {info['width']}×{info['height']} · "
                f"{info['title'] or 'sober'}"
            )
            self.side_dot.setStyleSheet("color:#42d392; font-size:12px;")
            self.side_status.setText("Attached")
            self.side_detail.setText(
                f"{info['display']} · {info['width']}×{info['height']}"
            )
            self.info_attached.set_value(f"Gamescope {info['display']}")
            self.footer_attached.setText(f"Attached {info['display']}")
            self.launch_btn.setEnabled(False)
            self.stop_game_btn.setEnabled(self.launcher.owns_process)
        elif self._flatpak_running:
            self.game_dot.setStyleSheet("color:#f5b84b; font-size:16px;")
            self.game_title.setText("Sober is open outside the macro")
            self.game_detail.setText(
                "Close it and launch the gamescope instance from the macro."
            )
            self.side_dot.setStyleSheet("color:#f5b84b; font-size:12px;")
            self.side_status.setText("Desktop")
            self.side_detail.setText("Not attached")
            self.info_attached.set_value("Not attached")
            self.footer_attached.setText("Not attached")
            self.launch_btn.setEnabled(not self._launch_busy)
            self.stop_game_btn.setEnabled(False)
        else:
            self.game_dot.setStyleSheet("color:#6c6c78; font-size:16px;")
            self.game_title.setText("Sober is not running")
            self.game_detail.setText("Click Launch Sober to start the game.")
            self.side_dot.setStyleSheet("color:#6c6c78; font-size:12px;")
            self.side_status.setText("Ready")
            self.side_detail.setText("Not attached")
            self.info_attached.set_value("Not attached")
            self.footer_attached.setText("Not attached")
            self.launch_btn.setEnabled(not self._launch_busy)
            self.stop_game_btn.setEnabled(False)
        self._update_window_button()

    def _launch_sober(self) -> None:
        if self._launch_busy:
            return
        if self.launcher.connected_display():
            self._refresh_game_status_clicked()
            return
        gamescope = self.launcher.find_gamescope()
        if gamescope is None:
            QMessageBox.critical(
                self,
                "gamescope is missing",
                "I couldn't find gamescope.\n\n"
                "Install it with:\n"
                "  sudo pacman -S --needed gamescope\n\n"
                "or use the bundled copy in vendor/gamescope.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Launch Sober",
            "Sober will be launched inside gamescope.\n\n"
            "If Sober is already open, it will be closed (only one instance "
            "is allowed).\n\nContinue?",
        )
        if answer != QMessageBox.Yes:
            return

        self._game_expected = True
        self._auto_reconnect_at = 0.0
        self._auto_reconnect_silent = False
        self._restart_in_progress = False
        self._last_game_restart_at = 0.0
        self._begin_launch("Launching Sober...")

    def _auto_launch_sober(self) -> None:
        """Launch Sober without asking, used when Start finds no game."""
        if self._launch_busy:
            return
        if self.launcher.connected_display():
            self._refresh_game_status_clicked()
            return
        if self.launcher.find_gamescope() is None:
            QMessageBox.critical(
                self,
                "gamescope is missing",
                "I couldn't find gamescope.\n\n"
                "Install it with:\n"
                "  sudo pacman -S --needed gamescope\n\n"
                "or use the bundled copy in vendor/gamescope.",
            )
            return
        self._game_expected = True
        self._auto_reconnect_at = 0.0
        self._auto_reconnect_silent = False
        self._restart_in_progress = False
        self._last_game_restart_at = 0.0
        self._begin_launch("Game not attached; launching Sober automatically...")

    def _begin_launch(self, message: str) -> None:
        if self._launch_busy:
            return
        self._launch_busy = True
        self.launch_btn.setEnabled(False)
        self.stop_game_btn.setEnabled(False)
        self.reconnect_btn.setEnabled(False)
        self.game_detail.setText("Launching gamescope...")
        self.side_status.setText("Launching...")
        self.side_dot.setStyleSheet("color:#f5b84b; font-size:12px;")
        self._append_log(message, "action")
        self.launcher.start_async(
            on_log=self.launcher_bridge.log.emit,
            on_status=self.launcher_bridge.status.emit,
            on_ready=self.launcher_bridge.ready.emit,
            on_error=self.launcher_bridge.error.emit,
            kill_existing=True,
        )

    def _on_launcher_status(self, text: str) -> None:
        self.game_detail.setText(text)
        self.footer_status.setText(text)
        self._append_log(text, "info")

    def _on_launcher_ready(self, info: dict) -> None:
        self._launch_busy = False
        self._restart_in_progress = False
        self.reconnect_btn.setEnabled(True)
        display = info.get("display", "")
        external = bool(info.get("external"))
        self._append_log(
            f"Sober ready on {display}"
            + (" (external instance)." if external else "."),
            "success",
        )
        # Do not re-arm Auto Reconnect if the user pressed Stop while the
        # launcher was still starting. A manual Launch sets this before it
        # starts; Auto Reconnect sets it explicitly too.
        if external:
            self._game_expected = False
        if self._auto_reconnect_silent:
            self._auto_reconnect_silent = False
            self._append_log("Auto Reconnect: game window is back.", "success")
        if self._engine_expected:
            QTimer.singleShot(2000, self._restart_engine_if_needed)
        self._update_game_status()
        self.stop_game_btn.setEnabled(self.launcher.owns_process)
        self._update_window_button()
        if self.config.gamescope_backend == "sdl" and not info.get("host_window"):
            self._append_log(
                "Couldn't find the gamescope host window; use the window manager "
                "to minimize it manually.",
                "warning",
            )
        elif self.config.gamescope_backend == "wayland":
            self._append_log(
                "Automatic window minimize is only available in SDL/X11 mode.",
                "info",
            )

    def _on_launcher_error(self, message: str) -> None:
        self._launch_busy = False
        self._restart_in_progress = False
        self.reconnect_btn.setEnabled(True)
        self._append_log(message, "error")
        self._update_game_status()
        if self._auto_reconnect_silent:
            self._auto_reconnect_silent = False
            self._append_log(
                "Auto Reconnect will retry in 30 seconds.", "warning"
            )
            return
        QMessageBox.critical(self, "Couldn't launch Sober", message)

    def _on_game_restart_requested(self, reason: str) -> None:
        """Reconnect screen: close Sober/gamescope and relaunch from scratch.

        The Reconnect button is never clicked: if the connection is down it
        can leave the client stuck. A full relaunch is deterministic; if it
        fails, Auto Reconnect retries later.
        """
        if self._restart_in_progress:
            self._append_log(
                "Game restart is already in progress.", "info"
            )
            return
        if not self._running and not self._engine_expected:
            self._append_log(
                "Game restart request ignored after Stop.", "info"
            )
            return

        now = time.monotonic()
        if now - self._last_game_restart_at < 25.0:
            self._append_log(
                "Reconnect screen is back; waiting before another full restart.",
                "warning",
            )
            return

        self._last_game_restart_at = now
        self._restart_in_progress = True
        self._append_log(
            f"Reconnect detected ({reason}); closing Sober/gamescope and "
            "relaunching.",
            "warning",
        )
        self.footer_status.setText("Restarting Sober...")

        if self._running:
            self._stop_engine()
        self._minimized_by_app = False

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if self.launcher.owns_process:
                try:
                    self.launcher.stop()
                except Exception as exc:
                    self._append_log(
                        f"Could not stop gamescope cleanly: {exc}", "warning"
                    )
            else:
                # External instance: close Sober; gamescope should follow.
                subprocess.run(
                    ["flatpak", "kill", "org.vinegarhq.Sober"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                time.sleep(1.0)
        finally:
            QApplication.restoreOverrideCursor()

        self._engine_expected = True
        self._game_expected = True
        self._auto_reconnect_at = 0.0
        self._auto_reconnect_silent = True

        if self._launch_busy:
            self._append_log(
                "A launch is already running; it will restart the engine.",
                "info",
            )
            return
        self._begin_launch("Reconnect screen: restarting Sober...")

    def _update_window_button(self) -> None:
        if not hasattr(self, "window_btn"):
            return
        visible = self.config.gamescope_backend in ("sdl", "wayland")
        available = visible and self.launcher.has_host_window()
        self.window_btn.setEnabled(available)
        if not available:
            self.window_btn.setText("No window")
            self.window_btn.setToolTip("No visible gamescope window found.")
            return
        if self.launcher.host_minimized():
            self.window_btn.setText("Show")
            self.window_btn.setToolTip("Restore the game window.")
        else:
            self.window_btn.setText("Minimize")
            self.window_btn.setToolTip("Minimize the game window.")

    def _toggle_host_window(self) -> None:
        if not self.launcher.has_host_window():
            self._append_log(
                "No visible gamescope window found. Switch Window to Visible "
                "and relaunch Sober.",
                "warning",
            )
            self._update_window_button()
            return
        if self.launcher.host_minimized():
            ok = self.launcher.restore_host()
            message = "Game window restored."
        else:
            ok = self.launcher.minimize_host()
            message = "Game window minimized."
        if ok:
            self._append_log(message, "success")
            self.footer_status.setText(message)
        else:
            self._append_log(
                "Couldn't change the game window state; use the title bar.",
                "warning",
            )
        self._update_window_button()

    def _stop_sober(self) -> None:
        if self._running:
            QMessageBox.warning(
                self,
                "Engine running",
                "Stop the engine before closing Sober.",
            )
            return
        if not self.launcher.owns_process:
            QMessageBox.information(
                self,
                "External instance",
                "This Sober instance was not launched by the macro. "
                "Close it from the process that started it.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Stop Sober",
            "Close the Sober instance?",
        )
        if answer != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.launcher.stop()
        finally:
            QApplication.restoreOverrideCursor()
        self._game_expected = False
        self._engine_expected = False
        self._append_log("Headless Sober stopped.", "warning")
        self._update_game_status()

    def _open_captures(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(captures_dir())))

    def _open_config_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir())))

    def _browse_gamescope(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select gamescope",
            str(Path.home()),
            "Executables (*)",
        )
        if path:
            widget = self._fields.get("gamescope_path")
            if isinstance(widget, QLineEdit):
                widget.setText(path)

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainText())
        self.footer_status.setText("Log copied")

    def _missing_templates(self) -> list[str]:
        required = []
        if self.config.auto_battle:
            required.append("battle")
        if self.config.auto_spawners:
            required.extend(["spawner1", "spawner2", "buy", "scroll"])
            if self.config.close_shop:
                required.append("close")
        if self.config.auto_fuse:
            required.extend(["build", "fuseall", "stop"])
        if self.config.auto_best_place:
            required.extend(["build", "placebest", "stop"])
        missing = []
        statuses = {item["key"]: item for item in self.matcher.template_status()}
        for key in required:
            entry = statuses.get(key)
            if entry is None or not entry["exists"]:
                spec = SPECS_BY_KEY.get(key)
                missing.append(spec.filename if spec else f"{key}.png")
        return missing

    # ------------------------------------------------------------------
    # Demo / close
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._running:
            answer = QMessageBox.question(
                self,
                f"Exit {DISPLAY_NAME}",
                "The engine is running. Stop it and exit?",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.controller.stop()
            time.sleep(0.15)
        if self._minimized_by_app:
            self.launcher.restore_host()
            self._minimized_by_app = False
        self._save_timer.stop()
        self._save_config_now()
        event.accept()
