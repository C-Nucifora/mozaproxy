"""Native setting editors and passive input instruments for the Qt desktop app."""

import math

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPalette, QPen, QValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _label(text="", parent=None):
    label = QLabel(str(text), parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class _NumberEditor(QDoubleSpinBox):
    """Keep incomplete or invalid input visible instead of silently correcting it."""

    def __init__(self, definition, parent=None):
        super().__init__(parent)
        self.lower = float(definition.get("min", 0))
        self.upper = float(definition.get("max", 100))
        step = float(definition.get("step", 1))
        self.unknown = self.lower - max(step, 0.001)
        self.setDecimals(3)
        self.setRange(self.unknown, self.upper)
        self.setSingleStep(step)
        self.setSpecialValueText("Not read")
        unit = definition.get("unit", "")
        self.setSuffix(" " + unit if unit else "")
        self.setValue(self.unknown)
        self.setKeyboardTracking(False)

    def parsed_value(self):
        text = self.lineEdit().text().strip()
        suffix = self.suffix()
        if suffix and text.endswith(suffix):
            text = text[: -len(suffix)].strip()
        value, valid = self.locale().toDouble(text)
        if valid and math.isfinite(value) and self.lower <= value <= self.upper:
            return value
        return None

    def validate(self, text, position):
        state, _, _ = super().validate(text, position)
        # Intermediate allows the user to see and repair even out-of-range text.
        if state == QValidator.State.Invalid:
            state = QValidator.State.Intermediate
        return state, text, position

    def focusOutEvent(self, event):
        if self.parsed_value() is None:
            QWidget.focusOutEvent(self, event)
            return
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.parsed_value() is None
        ):
            event.accept()
            return
        super().keyPressEvent(event)

    def stepBy(self, steps):
        value = self.parsed_value()
        if value is None:
            self.setValue(self.lower)
        else:
            self.setValue(
                max(self.lower, min(self.upper, value + steps * self.singleStep()))
            )


class SettingRow(QWidget):
    """One typed draft editor with a separately displayed device readback."""

    edited = Signal(str, object)
    invalid = Signal(str, bool)

    def __init__(self, definition, parent=None):
        super().__init__(parent)
        self.definition = definition
        self.key = definition["id"]
        self.reading = None
        self._invalid = False
        self.setObjectName("setting_" + self.key)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(3)
        self.name_label = _label(definition["label"])
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label, 0, 0)
        self.description_label = _label(definition.get("description", ""))
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label, 1, 0)
        self.description_label.setVisible(bool(definition.get("description")))

        if definition.get("type") in ("boolean", "select"):
            self.editor = QComboBox(self)
            self.editor.addItem("Not read", None)
            if definition.get("type") == "boolean":
                self.editor.addItem("Off", False)
                self.editor.addItem("On", True)
            else:
                for choice in definition.get("choices", []):
                    self.editor.addItem(str(choice["label"]), choice["value"])
            self.editor.currentIndexChanged.connect(self._changed)
        else:
            self.editor = _NumberEditor(definition, self)
            self.editor.valueChanged.connect(self._changed)
            self.editor.lineEdit().textEdited.connect(self._text_edited)
        self.editor.setObjectName("editor_" + self.key)
        self.editor.setAccessibleName(definition["label"])
        self.editor.setAccessibleDescription(definition.get("description", ""))
        self.editor.setMinimumWidth(160)
        self.editor.setMaximumWidth(245)
        self.name_label.setBuddy(self.editor)
        layout.addWidget(self.editor, 0, 1, alignment=Qt.AlignmentFlag.AlignRight)
        self.confirmed_label = _label("Device: Not read")
        self.confirmed_label.setWordWrap(True)
        layout.addWidget(self.confirmed_label, 1, 1)
        self.error_label = _label()
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label, 2, 0, 1, 2)
        layout.setColumnStretch(0, 1)

    def _format_value(self, value):
        if value is None:
            return "Not read"
        if self.definition.get("type") == "boolean":
            return "On" if value is True else "Off" if value is False else str(value)
        for choice in self.definition.get("choices", []):
            if choice["value"] == value:
                return str(choice["label"])
        text = f"{value:g}" if isinstance(value, (int, float)) else str(value)
        unit = self.definition.get("unit", "")
        return text + (" " + unit if unit else "")

    def set_reading(self, value):
        """Update only the confirmed value. The window owns draft replacement."""
        self.reading = value
        self.confirmed_label.setText("Device: " + self._format_value(value))

    def set_value(self, value):
        """Replace the editor without emitting a user edit."""
        with QSignalBlocker(self.editor):
            if isinstance(self.editor, QComboBox):
                index = self.editor.findData(value) if value is not None else 0
                self.editor.setCurrentIndex(max(0, index))
            else:
                with QSignalBlocker(self.editor.lineEdit()):
                    self.editor.setValue(
                        self.editor.unknown if value is None else float(value)
                    )
                    # setValue can leave intermediate text intact if its number did not change.
                    text = (
                        self.editor.specialValueText()
                        if value is None
                        else self.editor.textFromValue(self.editor.value())
                        + self.editor.suffix()
                    )
                    self.editor.lineEdit().setText(text)
        self._invalid = False
        self.set_error("")

    def value(self):
        if isinstance(self.editor, QComboBox):
            return self.editor.currentData()
        return self.editor.parsed_value()

    def _text_edited(self, _text):
        self._changed()

    def _changed(self, *_args):
        value = self.value()
        self._invalid = value is None
        self.invalid.emit(self.key, self._invalid)
        if self._invalid:
            if isinstance(self.editor, QComboBox):
                self.set_error("Choose a value before applying.")
            else:
                self.set_error(
                    f"Enter a number from {self.editor.lower:g} to {self.editor.upper:g}."
                )
        else:
            self.set_error("")
            self.edited.emit(self.key, value)

    def set_error(self, message):
        self.error_label.setText(str(message or ""))
        self.error_label.setVisible(bool(message))
        self.editor.setToolTip(str(message or self.definition.get("description", "")))


class _SteeringWheel(QWidget):
    """An original, palette-aware steering diagram drawn directly by Qt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0.0
        self.known = False
        self.setMinimumSize(140, 140)
        self.setMaximumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Steering wheel position")

    def sizeHint(self):
        return QSize(180, 180)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) * 0.39
        color = self.palette().color(
            QPalette.ColorRole.Text if self.known else QPalette.ColorRole.Mid
        )
        painter.rotate(self.angle)
        painter.setPen(
            QPen(color, radius * 0.13, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        for end in (
            QPointF(-radius * 0.84, -radius * 0.12),
            QPointF(radius * 0.84, -radius * 0.12),
            QPointF(0, radius * 0.84),
        ):
            painter.drawLine(QPointF(0, 0), end)
        painter.setBrush(self.palette().brush(QPalette.ColorRole.Window))
        painter.setPen(QPen(color, radius * 0.045))
        painter.drawEllipse(
            QRectF(-radius * 0.25, -radius * 0.25, radius * 0.5, radius * 0.5)
        )
        painter.setPen(
            QPen(
                self.palette().color(QPalette.ColorRole.Highlight),
                radius * 0.075,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawLine(QPointF(0, -radius * 0.9), QPointF(0, -radius * 1.05))


class InputBench(QWidget):
    """Passive steering and pedal readings. Missing axes remain explicitly unknown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        steering = QVBoxLayout()
        steering.setSpacing(4)
        steering.addStretch()
        steering.addWidget(_label("Steering"), alignment=Qt.AlignmentFlag.AlignHCenter)
        self.wheel = _SteeringWheel(self)
        steering.addWidget(self.wheel, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.steering_label = _label("Not available")
        self.steering_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        steering.addWidget(self.steering_label)
        steering.addStretch()
        layout.addLayout(steering, 1)

        pedals = QGridLayout()
        pedals.setVerticalSpacing(16)
        pedals.setRowStretch(0, 1)
        self.pedal_bars = {}
        for index, name in enumerate(("Throttle", "Brake", "Clutch")):
            label = _label(name)
            bar = QProgressBar(self)
            bar.setRange(0, 1000)
            bar.setValue(0)
            bar.setFormat("Not available")
            bar.setAccessibleName(name)
            label.setBuddy(bar)
            self.pedal_bars[name.lower()] = bar
            pedals.addWidget(label, index * 2 + 1, 0)
            pedals.addWidget(bar, index * 2 + 2, 0)
        pedals.setRowStretch(7, 1)
        layout.addLayout(pedals, 2)

    @staticmethod
    def _axis(axes, label, code):
        for axis in axes:
            if str(axis.get("label", "")).lower() == label or axis.get("code") == code:
                value = axis.get("value")
                if isinstance(value, (int, float)) and math.isfinite(value):
                    return max(0.0, min(1.0, float(value)))
        return None

    def update_device(self, device, rotation=None):
        device = device or {}
        axes = device.get("axes", []) if device.get("connected") else []
        steering = self._axis(axes, "steering", 0)
        self.wheel.known = steering is not None
        valid_rotation = (
            isinstance(rotation, (int, float))
            and not isinstance(rotation, bool)
            and math.isfinite(rotation)
            and rotation > 0
        )
        if steering is None:
            self.wheel.angle = 0
            self.steering_label.setText("Not available")
        else:
            normalized = (steering - 0.5) * 2
            self.wheel.angle = normalized * (rotation / 2 if valid_rotation else 135)
            self.steering_label.setText(
                f"{self.wheel.angle:+.1f}°"
                if valid_rotation
                else f"{normalized * 100:+.1f}% from center"
            )
        self.wheel.setAccessibleDescription(self.steering_label.text())
        self.wheel.update()
        for name, code in (("throttle", 2), ("brake", 5), ("clutch", 6)):
            value = self._axis(axes, name, code)
            bar = self.pedal_bars[name]
            bar.setValue(round(value * 1000) if value is not None else 0)
            bar.setFormat(
                f"{value * 100:.1f}%" if value is not None else "Not available"
            )
            bar.setAccessibleDescription(bar.format())
