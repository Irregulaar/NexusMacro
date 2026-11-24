"""Main-window page builders (presentation only).

Kept as a mixin so ``ui.py`` can own the window lifecycle, config binding and
engine/launcher wiring without carrying every page layout.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import config as config_module
from .paths import APP_VERSION, DISPLAY_NAME, captures_dir, icon_path
from .ui_widgets import (
    Card,
    InfoCard,
    LogView,
    SectionHeader,
    ToggleRow,
    ToggleSwitch,
)


class UiPagesMixin:
    def _build_automation_page(self) -> QWidget:
        page = QWidget()
        page = self._dark_page(page)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        palette = scroll.viewport().palette()
        palette.setColor(QPalette.Window, QColor("#0a0810"))
        palette.setColor(QPalette.Base, QColor("#0a0810"))
        scroll.setPalette(palette)
        scroll.viewport().setPalette(palette)
        scroll.viewport().setAutoFillBackground(True)
        container = QWidget()
        container.setAutoFillBackground(True)
        container_palette = container.palette()
        container_palette.setColor(QPalette.Window, QColor("#0a0810"))
        container_palette.setColor(QPalette.Base, QColor("#0a0810"))
        container.setPalette(container_palette)
        content = QVBoxLayout(container)
        content.setContentsMargins(0, 0, 3, 0)
        content.setSpacing(6)

        # Features
        features = Card()
        features_layout = QVBoxLayout(features)
        features_layout.setContentsMargins(8, 6, 8, 6)
        features_layout.setSpacing(0)
        features_layout.addWidget(SectionHeader("Features"))

        self.battle_toggle = ToggleSwitch()
        features_layout.addWidget(
            ToggleRow(
                "Auto Battle",
                "Find the Battle button and start matches.",
                self.battle_toggle,
            )
        )
        features_layout.addWidget(self._divider())

        self.spawners_toggle = ToggleSwitch()
        features_layout.addWidget(
            ToggleRow(
                "Auto Spawners",
                "Open the shop, buy spawners and scroll to the end.",
                self.spawners_toggle,
            )
        )
        self.spawner_refresh_label = QLabel("Next spawner refresh: --:--")
        self.spawner_refresh_label.setObjectName("tiny")
        self.spawner_refresh_label.setContentsMargins(8, 0, 0, 2)
        features_layout.addWidget(self.spawner_refresh_label)
        features_layout.addWidget(self._divider())

        self.fuse_toggle = ToggleSwitch()
        features_layout.addWidget(
            ToggleRow(
                "Auto Fuse",
                "Fuse before starting a battle.",
                self.fuse_toggle,
            )
        )
        features_layout.addWidget(self._divider())

        self.place_toggle = ToggleSwitch()
        features_layout.addWidget(
            ToggleRow(
                "Auto Best Place",
                "Place before starting a battle.",
                self.place_toggle,
            )
        )
        content.addWidget(features)

        # Actions
        action_card = Card()
        action_layout = QVBoxLayout(action_card)
        action_layout.setContentsMargins(8, 6, 8, 6)
        action_layout.setSpacing(4)
        action_layout.addWidget(SectionHeader("Actions"))

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.buy_spawners_btn = QPushButton("Buy Spawners Now")
        self.buy_spawners_btn.setObjectName("primary")
        self.buy_spawners_btn.setCursor(Qt.PointingHandCursor)
        self.fuse_now_btn = QPushButton("Fuse Now")
        self.fuse_now_btn.setObjectName("primary")
        self.fuse_now_btn.setCursor(Qt.PointingHandCursor)
        self.fuse_now_btn.clicked.connect(self._fuse_now)
        self.place_now_btn = QPushButton("Best Place Now")
        self.place_now_btn.setObjectName("primary")
        self.place_now_btn.setCursor(Qt.PointingHandCursor)
        self.place_now_btn.clicked.connect(self._place_now)
        for button in (
            self.buy_spawners_btn,
            self.fuse_now_btn,
            self.place_now_btn,
        ):
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            action_row.addWidget(button, 1)
        action_layout.addLayout(action_row)
        content.addWidget(action_card)

        content.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)
        return page

    def _build_connection_page(self) -> QWidget:
        page = QWidget()
        page = self._dark_page(page)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        palette = scroll.viewport().palette()
        palette.setColor(QPalette.Window, QColor("#0a0810"))
        palette.setColor(QPalette.Base, QColor("#0a0810"))
        scroll.setPalette(palette)
        scroll.viewport().setPalette(palette)
        scroll.viewport().setAutoFillBackground(True)
        container = QWidget()
        container.setAutoFillBackground(True)
        container_palette = container.palette()
        container_palette.setColor(QPalette.Window, QColor("#0a0810"))
        container_palette.setColor(QPalette.Base, QColor("#0a0810"))
        container.setPalette(container_palette)
        content = QVBoxLayout(container)
        content.setContentsMargins(0, 0, 3, 0)
        content.setSpacing(6)

        # Overview row (moved from the old Main tab)
        info_row = QHBoxLayout()
        info_row.setSpacing(5)
        self.info_user = InfoCard("User", "Sober / Local")
        self.info_platform = InfoCard("Platform", "Linux · gamescope")
        self.info_attached = InfoCard("Attached to", "Not attached")
        self.info_uptime = InfoCard("Uptime", "00:00:00")
        for card in (
            self.info_user,
            self.info_platform,
            self.info_attached,
            self.info_uptime,
        ):
            info_row.addWidget(card)
        info_row.addStretch(1)
        content.addLayout(info_row)

        status_card = Card()
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(8, 5, 8, 5)
        status_layout.setSpacing(8)
        self.session_stats = QLabel("Battles 0 · Buys 0 · Scrolls 0 · Cycles 0")
        self.session_stats.setObjectName("tiny")
        status_layout.addWidget(self.session_stats)
        status_layout.addStretch(1)
        content.addWidget(status_card)

        # Game session
        session = Card()
        session_layout = QVBoxLayout(session)
        session_layout.setContentsMargins(8, 6, 8, 6)
        session_layout.setSpacing(5)
        session_layout.addWidget(SectionHeader("Game Session"))

        game_row = QHBoxLayout()
        game_row.setSpacing(8)
        self.game_dot = QLabel("●")
        self.game_dot.setStyleSheet("color: #6c6c78; font-size: 16px;")
        game_row.addWidget(self.game_dot, 0, Qt.AlignTop)
        game_text = QVBoxLayout()
        game_text.setSpacing(0)
        self.game_title = QLabel("Sober is not running")
        self.game_title.setObjectName("rowTitle")
        self.game_detail = QLabel("Launch Sober to attach the macro.")
        self.game_detail.setObjectName("cardSubtitle")
        self.game_detail.setWordWrap(True)
        game_text.addWidget(self.game_title)
        game_text.addWidget(self.game_detail)
        game_row.addLayout(game_text, 1)
        session_layout.addLayout(game_row)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.launch_btn = QPushButton("Launch Sober")
        self.launch_btn.setObjectName("primary")
        self.launch_btn.setCursor(Qt.PointingHandCursor)
        self.stop_game_btn = QPushButton("Stop Game")
        self.stop_game_btn.setObjectName("ghost")
        self.stop_game_btn.setCursor(Qt.PointingHandCursor)
        self.reconnect_btn = QPushButton("Reconnect")
        self.reconnect_btn.setObjectName("ghost")
        self.reconnect_btn.setCursor(Qt.PointingHandCursor)
        actions.addWidget(self.launch_btn)
        actions.addWidget(self.stop_game_btn)
        actions.addWidget(self.reconnect_btn)
        actions.addStretch(1)
        session_layout.addLayout(actions)

        join_row = QHBoxLayout()
        join_row.setSpacing(8)
        self.join_toggle = ToggleSwitch()
        join_row.addWidget(
            ToggleRow(
                "Join game on launch",
                "Auto-join the configured Roblox place after Sober starts.",
                self.join_toggle,
            )
        )
        session_layout.addLayout(join_row)

        place_row = QHBoxLayout()
        place_row.setSpacing(6)
        place_label = QLabel("Place ID")
        place_label.setObjectName("muted")
        self.game_place_id_edit = QLineEdit()
        self.game_place_id_edit.setPlaceholderText("Place ID or roblox.com/games/...")
        self.game_place_id_edit.setText(str(self.config.game_place_id or ""))
        self.game_place_id_edit.textChanged.connect(
            lambda v: self._set_config("game_place_id", v.strip())
        )
        self._fields["game_place_id"] = self.game_place_id_edit
        place_row.addWidget(place_label)
        place_row.addWidget(self.game_place_id_edit, 1)
        session_layout.addLayout(place_row)

        place_note = QLabel(
            "Passed to Sober as roblox://experience?placeId=..."
        )
        place_note.setObjectName("tiny")
        place_note.setWordWrap(True)
        session_layout.addWidget(place_note)

        content.addWidget(session)

        # Window controls
        window_card = Card()
        window_layout = QVBoxLayout(window_card)
        window_layout.setContentsMargins(8, 6, 8, 6)
        window_layout.setSpacing(5)
        window_layout.addWidget(SectionHeader("Window"))

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_label = QLabel("Mode")
        mode_label.setObjectName("muted")
        self.window_mode_combo = self._make_combo(
            "gamescope_backend",
            (
                ("Visible window", "sdl"),
                ("Headless (no window)", "headless"),
                ("Visible (Wayland)", "wayland"),
            ),
        )
        self.window_mode_combo.setMinimumWidth(140)
        self.minimize_check = self._make_check(
            "minimize_on_start", "Minimize on Start"
        )
        self.grab_check = self._make_check(
            "gamescope_grab_cursor", "Grab cursor"
        )
        self.grab_check.setToolTip(
            "Gamescope --force-grab-cursor. Fixes the camera snapping back."
        )
        self.window_btn = QPushButton("Minimize")
        self.window_btn.setObjectName("mini")
        self.window_btn.setFixedWidth(84)
        self.window_btn.setCursor(Qt.PointingHandCursor)
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.window_mode_combo)
        mode_row.addWidget(self.minimize_check)
        mode_row.addWidget(self.grab_check)
        mode_row.addStretch(1)
        mode_row.addWidget(self.window_btn)
        window_layout.addLayout(mode_row)

        reconnect_row = QHBoxLayout()
        reconnect_row.setSpacing(8)
        self.reconnect_toggle = ToggleSwitch()
        reconnect_row.addWidget(
            ToggleRow(
                "Auto Reconnect",
                "Retry attaching to the game window automatically.",
                self.reconnect_toggle,
            )
        )
        window_layout.addLayout(reconnect_row)
        content.addWidget(window_card)

        # Captures
        capture_card = Card()
        capture_layout = QVBoxLayout(capture_card)
        capture_layout.setContentsMargins(8, 6, 8, 6)
        capture_layout.setSpacing(5)
        capture_layout.addWidget(SectionHeader("Captures"))
        self.open_captures_btn = QPushButton("Open Captures")
        self.open_captures_btn.setObjectName("ghost")
        self.open_captures_btn.setCursor(Qt.PointingHandCursor)
        capture_layout.addWidget(self.open_captures_btn)
        content.addWidget(capture_card)

        content.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page = self._dark_page(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        palette = scroll.viewport().palette()
        palette.setColor(QPalette.Window, QColor("#0a0810"))
        palette.setColor(QPalette.Base, QColor("#0a0810"))
        scroll.setPalette(palette)
        scroll.viewport().setPalette(palette)
        scroll.viewport().setAutoFillBackground(True)
        container = QWidget()
        container.setAutoFillBackground(True)
        container_palette = container.palette()
        container_palette.setColor(QPalette.Window, QColor("#0a0810"))
        container_palette.setColor(QPalette.Base, QColor("#0a0810"))
        container.setPalette(container_palette)
        content = QVBoxLayout(container)
        content.setContentsMargins(0, 0, 3, 0)
        content.setSpacing(6)

        note = QLabel(
            "Settings autosave and apply live. Window/gamescope changes take "
            "effect on the next launch."
        )
        note.setObjectName("tiny")
        note.setWordWrap(True)
        content.addWidget(note)
        content.addWidget(self._build_detection_card())
        content.addWidget(self._build_shopping_card())
        content.addWidget(self._build_game_settings_card())
        content.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll)
        return page

    def _build_detection_card(self) -> Card:
        card, form = self._form_card(
            "Detection",
            "",
        )
        self._add_form_row(
            form,
            "Ignore price area",
            self._make_double("ignore_buy_price", 0.0, 0.80, 0.01, 2),
            "Right-side fraction of the Buy button to ignore.",
        )
        self._add_form_row(
            form,
            "Spawner threshold",
            self._make_double("spawner_threshold", 0.50, 0.99, 0.01, 2),
            "Lower this if the spawner button is not detected.",
        )
        self._add_form_row(
            form,
            "Buy threshold",
            self._make_double("shop_threshold", 0.50, 0.99, 0.01, 2),
            "Lower this if the shop opens but Buy buttons are not detected.",
        )
        self._add_form_row(
            form,
            "Detection threshold",
            self._make_double("threshold", 0.50, 0.99, 0.01, 2),
        )
        self._add_form_row(
            form,
            "Template scale",
            self._make_double("scale", 0.50, 2.00, 0.01, 2),
        )
        return card

    def _build_shopping_card(self) -> Card:
        card, form = self._form_card(
            "Buying & Scrolling",
            "How many clicks per item and how to move through the list.",
        )
        self._add_form_row(
            form,
            "Delay between clicks",
            self._make_double("buy_click_delay", 0.0, 2.0, 0.01, 2),
            "Seconds between clicks on each Buy button.",
        )
        self._add_form_row(
            form,
            "Max Buy per pass",
            self._make_spin("max_buy_buttons", 1, 30, 1),
        )
        self._add_form_row(
            form,
            "Max clicks per shop",
            self._make_spin("max_cycle_buy_clicks", 10, 1000, 10),
            "Safety limit for one shop visit.",
        )
        self._add_form_row(
            form,
            "Scroll method",
            self._make_combo(
                "scroll_method",
                (("Drag scrollbar", "drag"), ("Mouse wheel", "wheel")),
            ),
        )
        self._add_form_row(
            form,
            "Scroll distance (px)",
            self._make_spin("scroll_drag_px", 20, 800, 10),
        )
        self._add_form_row(
            form,
            "Scroll duration (ms)",
            self._make_spin("scroll_drag_ms", 100, 5000, 50),
        )
        self._add_form_row(
            form,
            "Scroll probe steps",
            self._make_spin("scroll_probe_steps", 2, 30, 1),
            "More steps = finer checks, but slower.",
        )
        self._add_form_row(
            form,
            "Scroll settle (s)",
            self._make_double("scroll_settle_delay", 0.0, 5.0, 0.1, 1),
            "Wait after a scroll before clicking the Buy buttons.",
        )
        self._add_form_row(
            form,
            "Max scrolls",
            self._make_spin("max_scrolls", 1, 50, 1),
        )
        self._add_form_row(
            form,
            "Spawner preference",
            self._make_combo(
                "spawner_preference",
                (
                    ("Auto (compact first)", "auto"),
                    ("Spawner (big) only", "1"),
                    ("Spawner (compact) only", "2"),
                ),
            ),
        )
        self._add_form_row(
            form,
            "Clock window (s)",
            self._make_spin("spawner_window_seconds", 5, 60, 1),
            "How long after hh:mm:00 the macro keeps trying.",
        )
        self._add_form_row(
            form,
            "Close shop",
            self._make_check("close_shop", "Close the shop when done"),
        )
        return card

    def _build_game_settings_card(self) -> Card:
        card, form = self._form_card(
            "Game & gamescope",
            "How the macro finds and launches the Sober window.",
        )
        display = QLineEdit()
        display.setPlaceholderText("auto (:1, :2...)")
        display.textChanged.connect(lambda v: self._set_config("display", v.strip()))
        self._fields["display"] = display
        self._add_form_row(form, "X display", display)

        window_class = QLineEdit()
        window_class.textChanged.connect(
            lambda v: self._set_config("window_class", v.strip())
        )
        self._fields["window_class"] = window_class
        self._add_form_row(form, "WM_CLASS", window_class)

        size_row = QWidget()
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(6)
        size_layout.addWidget(self._make_spin("window_width", 320, 3840, 10))
        x_label = QLabel("×")
        x_label.setObjectName("muted")
        size_layout.addWidget(x_label)
        size_layout.addWidget(self._make_spin("window_height", 240, 2160, 10))
        size_layout.addStretch(1)
        self._add_form_row(form, "Resolution", size_row)

        self._add_form_row(
            form,
            "FPS",
            self._make_spin("gamescope_fps", 15, 240, 5),
        )

        gs_row = QWidget()
        gs_layout = QHBoxLayout(gs_row)
        gs_layout.setContentsMargins(0, 0, 0, 0)
        gs_layout.setSpacing(6)
        gs_path = QLineEdit()
        gs_path.setPlaceholderText("auto: system or vendor/gamescope")
        gs_path.textChanged.connect(
            lambda v: self._set_config("gamescope_path", v.strip())
        )
        self._fields["gamescope_path"] = gs_path
        gs_browse = QPushButton("…")
        gs_browse.setObjectName("ghost")
        gs_browse.setFixedWidth(36)
        gs_browse.clicked.connect(self._browse_gamescope)
        gs_layout.addWidget(gs_path, 1)
        gs_layout.addWidget(gs_browse)
        self._add_form_row(form, "gamescope", gs_row)

        buttons = QHBoxLayout()
        detect_btn = QPushButton("Detect Game")
        detect_btn.setObjectName("ghost")
        detect_btn.clicked.connect(self._refresh_game_status_clicked)
        buttons.addWidget(detect_btn)
        buttons.addStretch(1)
        self._add_form_row(form, "", buttons)
        return card

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        page = self._dark_page(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        header = Card()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(3)
        header_layout.addWidget(SectionHeader("Output & Status"))
        layout.addWidget(header)
        self.log_view = LogView()
        layout.addWidget(self.log_view, 1)
        footer = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ghost")
        clear_btn.clicked.connect(self.log_view.clear)
        copy_btn = QPushButton("Copy All")
        copy_btn.setObjectName("ghost")
        copy_btn.clicked.connect(self._copy_log)
        captures_btn = QPushButton("Open Captures")
        captures_btn.setObjectName("ghost")
        captures_btn.clicked.connect(self._open_captures)
        footer.addWidget(clear_btn)
        footer.addWidget(copy_btn)
        footer.addStretch(1)
        footer.addWidget(captures_btn)
        layout.addLayout(footer)
        return page

    def _build_about_page(self) -> QWidget:
        page = QWidget()
        page = self._dark_page(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(6)

        logo = QLabel()
        try:
            logo.setPixmap(
                QPixmap(str(icon_path())).scaled(
                    48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        except Exception:
            pass
        card_layout.addWidget(logo)
        title = QLabel(f"{DISPLAY_NAME} v{APP_VERSION}")
        title.setObjectName("brandTitle")
        subtitle = QLabel(
            "Headless autopilot for Build a Tower Defense on Roblox / Sober."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)

        body = QLabel(
            f"{DISPLAY_NAME} runs Sober inside gamescope and injects clicks with XTest. "
            "You can show the game window for setup, or let the macro minimize it "
            "while the engine runs. Your real pointer and focus stay untouched.\n\n"
            "Auto Battle finds the Battle button and starts matches. Auto Spawners "
            "opens the shop, clicks every Buy button, drags the scrollbar while "
            "looking for new items, and stops at the end."
        )
        body.setObjectName("muted")
        body.setWordWrap(True)
        card_layout.addWidget(body)

        info = QLabel(
            f"Config: {config_module.config_file()}\n"
            f"Captures: {captures_dir()}\n"
            "Requires: Linux Wayland, Sober Flatpak and gamescope."
        )
        info.setObjectName("tiny")
        info.setWordWrap(True)
        card_layout.addWidget(info)

        buttons = QHBoxLayout()
        config_btn = QPushButton("Open Config Folder")
        config_btn.setObjectName("ghost")
        config_btn.clicked.connect(self._open_config_dir)
        captures_btn = QPushButton("Open Captures")
        captures_btn.setObjectName("ghost")
        captures_btn.clicked.connect(self._open_captures)
        buttons.addWidget(config_btn)
        buttons.addWidget(captures_btn)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)
        layout.addWidget(card)
        layout.addStretch(1)
        return page
