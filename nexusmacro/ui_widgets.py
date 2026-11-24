"""Reusable Nexus Macro UI widgets."""

from __future__ import annotations

import html
import time
from typing import Optional

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _mix(c1: str, c2: str, t: float) -> QColor:
    a = QColor(c1)
    b = QColor(c2)
    return QColor(
        _lerp(a.red(), b.red(), t),
        _lerp(a.green(), b.green(), t),
        _lerp(a.blue(), b.blue(), t),
    )


class Card(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")


class InfoCard(QFrame):
    """Compact label/value card used in status strips."""

    def __init__(
        self,
        label: str,
        value: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("infoCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(0)
        label_widget = QLabel(label.upper())
        label_widget.setObjectName("infoLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("infoValue")
        layout.addWidget(label_widget)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class SectionHeader(QWidget):
    """Title row with a small accent bar."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        accent: str = "#a855f7",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        bar = QFrame()
        bar.setFixedSize(2, 13)
        bar.setStyleSheet(f"background:{accent};")
        layout.addWidget(bar, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(0)
        title_label = QLabel(title.upper())
        title_label.setObjectName("sectionTitle")
        text.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("cardSubtitle")
            subtitle_label.setWordWrap(True)
            text.addWidget(subtitle_label)
        layout.addLayout(text, 1)


class ToggleSwitch(QAbstractButton):
    """Animated toggle switch with the Nexus Macro purple accent."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(36, 18)
        self.setCursor(Qt.PointingHandCursor)
        self._progress = 0.0
        self._animation = QPropertyAnimation(self, b"progress", self)
        self._animation.setDuration(120)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def set_checked_silent(self, checked: bool) -> None:
        self.blockSignals(True)
        self.setChecked(checked)
        self._progress = 1.0 if checked else 0.0
        self.blockSignals(False)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = self.width()
        height = self.height()
        track = QRectF(1, 1, width - 2, height - 2)
        radius = (height - 2) / 2

        off = QColor("#2c2440")
        on = QColor("#a855f7")
        track_color = _mix(off.name(), on.name(), self._progress)
        if not self.isEnabled():
            track_color.setAlpha(90)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, radius, radius)

        knob = height - 10
        x = 3 + self._progress * (width - knob - 6)
        y = (height - knob) / 2
        painter.setBrush(QColor("#f8fafc"))
        painter.drawEllipse(QRectF(x, y, knob, knob))
        painter.end()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(36, 18)


class ToggleRow(QWidget):
    """Compact settings row with a title, description and toggle."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        toggle: ToggleSwitch,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toggleRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(0)
        title_label = QLabel(title)
        title_label.setObjectName("rowTitle")
        text.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("cardSubtitle")
            subtitle_label.setWordWrap(True)
            text.addWidget(subtitle_label)
        layout.addLayout(text, 1)
        layout.addWidget(toggle, 0, Qt.AlignVCenter)


class FeatureCard(Card):
    def __init__(
        self,
        badge: str,
        title: str,
        subtitle: str,
        accent: str,
        toggle: ToggleSwitch,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        badge_label = QLabel(badge)
        badge_label.setAlignment(Qt.AlignCenter)
        badge_label.setFixedSize(40, 40)
        badge_label.setStyleSheet(
            f"background: {accent}; color: #0a0810; border-radius: 10px;"
            "font-size: 18px; font-weight: 900;"
        )
        layout.addWidget(badge_label)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("cardSubtitle")
        subtitle_label.setWordWrap(True)
        text_box.addWidget(title_label)
        text_box.addWidget(subtitle_label)
        layout.addLayout(text_box, 1)
        layout.addWidget(toggle, 0, Qt.AlignVCenter)


class StatCard(Card):
    def __init__(
        self,
        title: str,
        accent: str = "#a855f7",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        self.value_label = QLabel("0")
        self.value_label.setObjectName("statValue")
        self.value_label.setStyleSheet(f"color: {accent};")
        title_label = QLabel(title.upper())
        title_label.setObjectName("statLabel")
        layout.addWidget(self.value_label)
        layout.addWidget(title_label)

    def set_value(self, value: int | str) -> None:
        self.value_label.setText(str(value))


class LogView(QTextEdit):
    COLORS = {
        "info": "#b8b8c2",
        "success": "#42d392",
        "warning": "#f5b84b",
        "error": "#ff5c8a",
        "action": "#c084fc",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("logView")
        self.document().setMaximumBlockCount(2500)
        self.setFont(QFont("DejaVu Sans Mono", 9))

    def append_log(self, message: str, level: str = "info") -> None:
        color = self.COLORS.get(level, self.COLORS["info"])
        timestamp = time.strftime("%H:%M:%S")
        safe = html.escape(str(message)).replace("\n", "<br>")
        self.append(
            f'<span style="color:#5d6f86;">{timestamp}</span> '
            f'<span style="color:{color};">{safe}</span>'
        )
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
