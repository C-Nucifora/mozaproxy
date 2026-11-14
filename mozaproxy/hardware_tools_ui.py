"""Explicit calibration and telemetry controls, separate from saved profiles."""
import json
from PySide6.QtCore import QSignalBlocker
from .lighting_service import start_if_enabled
from .telemetry import SOURCES
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QComboBox, QPushButton, QCheckBox, QSpinBox, QPlainTextEdit, QMessageBox, QGroupBox, QHBoxLayout


class HardwareToolsPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        managed = QGroupBox('Automatic LMU lighting')
        managed_form = QFormLayout(managed)
        self.managed_enabled = QCheckBox('Start RPM lighting with LMU')
        self.base_alerts = QCheckBox('R25 base: flags and pit limiter')
        self.activity_alerts = QCheckBox('Also show ABS and traction-control activity')
        for widget in (self.managed_enabled, self.base_alerts, self.activity_alerts):
            managed_form.addRow(widget)
        self.rpm_start = QSpinBox()
        self.rpm_start.setRange(0, 99)
        self.rpm_start.setSuffix(' %')
        self.rpm_end = QSpinBox()
        self.rpm_end.setRange(1, 100)
        self.rpm_end.setSuffix(' %')
        managed_form.addRow('Bar starts at rev-limit percentage', self.rpm_start)
        managed_form.addRow('Bar fills at rev-limit percentage', self.rpm_end)
        save_lighting = QPushButton('Save lighting settings')
        save_lighting.clicked.connect(self.save_lighting)
        managed_form.addRow(save_lighting)
        note = QLabel('Uses the existing Steam wrapper. The SDK reports rev limit, not optimal shift timing or dashboard LED thresholds. Defaults are 50–100%. Base effects require confirmed R25 support and telemetry mode; failures leave RPM lighting available. Disconnect manual settings before automatic lighting starts.')
        note.setWordWrap(True)
        managed_form.addRow(note)
        self.managed_box = managed
        layout.addWidget(managed)
        calibration = QGroupBox("Pedal calibration")
        calibration_layout = QVBoxLayout(calibration)
        layout.addWidget(calibration)
        note = QLabel('Pedal calibration changes the learned range. Stop driving first. Fully depress and release the selected pedal during the seven-second window. Stop ends capture; it does not restore the old calibration.')
        note.setWordWrap(True)
        calibration_layout.addWidget(note)
        form = QFormLayout()
        self.pedal = QComboBox()
        self.pedal.addItems(['throttle', 'brake', 'clutch'])
        form.addRow('Base-connected pedal', self.pedal)
        self.start_calibration = QPushButton('Start seven-second calibration…')
        self.start_calibration.clicked.connect(self.calibrate)
        calibration_actions = QHBoxLayout()
        calibration_actions.addWidget(self.start_calibration)
        self.stop_calibration = QPushButton('Stop calibration')
        self.stop_calibration.clicked.connect(lambda: owner._submit('calibration-stop', owner.backend.hardware.calibration_stop))
        self.stop_calibration.setObjectName("stopAction")
        calibration_actions.addWidget(self.stop_calibration)
        form.addRow(calibration_actions)
        calibration_layout.addLayout(form)
        telemetry = QGroupBox("Telemetry lighting")
        telemetry_layout = QVBoxLayout(telemetry)
        layout.addWidget(telemetry)
        form = QFormLayout()
        self.source = QComboBox()
        for key, label in SOURCES.items():
            self.source.addItem(label, key)
        self.source.setCurrentIndex(self.source.findData('fh5'))
        form.addRow('Telemetry game', self.source)
        self.maximum_rpm = QSpinBox()
        self.maximum_rpm.setRange(100, 100000)
        self.maximum_rpm.setValue(8000)
        self.maximum_rpm.setEnabled(False)
        self.source.currentIndexChanged.connect(lambda: self.maximum_rpm.setEnabled(self.source.currentData() == 'beamng'))
        form.addRow('BeamNG RPM scale', self.maximum_rpm)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(20777)
        form.addRow('Telemetry UDP port', self.port)
        self.output = QCheckBox('Send RPM LEDs to the connected wheel')
        form.addRow(self.output)
        self.start_telemetry = QPushButton('Start telemetry')
        self.start_telemetry.clicked.connect(self.telemetry)
        telemetry_actions = QHBoxLayout()
        telemetry_actions.addWidget(self.start_telemetry)
        self.stop_telemetry = QPushButton('Stop telemetry')
        self.stop_telemetry.clicked.connect(lambda: owner._submit('telemetry-stop', owner.backend.telemetry.stop))
        self.stop_telemetry.setObjectName("stopAction")
        telemetry_actions.addWidget(self.stop_telemetry)
        form.addRow(telemetry_actions)
        telemetry_layout.addLayout(form)
        note = QLabel('Preview is the default and sends no device commands. LMU, ACC and AC require the shared-memory helper in the game’s Proton context. ETS2 requires the telemetry plugin. FH5 uses Data Out; BeamNG uses OutGauge and the RPM scale above. Send to 127.0.0.1 on this port. See docs/telemetry.md for setup. Stale data clears the LEDs after 0.5 seconds. The bar uses reported maximum RPM or your BeamNG scale, not a verified shift point. LED output requires the local connection and readable newer wheel RGB controls.')
        note.setWordWrap(True)
        telemetry_layout.addWidget(note)
        firmware = QLabel('<a href="https://support.mozaracing.com/en/support/solutions/articles/70000628053-downloads">Official MOZA firmware and recovery tools</a><br>Firmware flashing and independent USB accessory configuration are not implemented. No supported flashing/recovery protocol has been established here.')
        firmware.setWordWrap(True)
        firmware.setOpenExternalLinks(True)
        layout.addWidget(firmware)
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setMinimumHeight(160)
        self.status.setAccessibleName('Calibration and telemetry status')
        layout.addWidget(self.status)

    def save_lighting(self):
        patch = dict(enabled=self.managed_enabled.isChecked(), base_alerts=self.base_alerts.isChecked(),
                     activity_alerts=self.activity_alerts.isChecked(), rpm_start_percent=self.rpm_start.value(),
                     rpm_end_percent=self.rpm_end.value())
        def save():
            result = self.owner.backend.lighting.save(patch)
            start_if_enabled(self.owner.backend.lighting.path.parent)
            return result
        self.owner._submit('lighting-settings', save)

    def calibrate(self):
        if QMessageBox.question(self, 'Calibrate pedal', 'Is driving stopped and are you ready to fully depress and release this pedal? Calibration changes its learned range.') != QMessageBox.StandardButton.Yes:
            return
        pedal = self.pedal.currentText()
        self.owner._submit('calibration-start', lambda: self.owner.backend.hardware.calibration_start(pedal, True))

    def telemetry(self):
        port, output = self.port.value(), self.output.isChecked()
        source, maximum = self.source.currentData(), self.maximum_rpm.value()
        self.owner._submit('telemetry-start', lambda: self.owner.backend.telemetry.start(port, output, source, maximum))

    def refresh(self, state):
        hardware, telemetry = state.get('hardware', {}), state.get('telemetry', {})
        busy = self.owner.controller.busy or self.owner._pending_job is not None
        lighting = state.get('lighting', {})
        self.managed_box.setEnabled(hasattr(self.owner.backend, 'lighting') and not busy and not lighting.get('error'))
        # Keep unsaved fields until the saved settings change.
        signature = tuple(lighting.get(k) for k in ('enabled', 'base_alerts', 'activity_alerts', 'rpm_start_percent', 'rpm_end_percent'))
        if getattr(self, '_lighting_signature', None) != signature:
            for key, widget in [('enabled', self.managed_enabled), ('base_alerts', self.base_alerts), ('activity_alerts', self.activity_alerts)]:
                with QSignalBlocker(widget):
                    widget.setChecked(lighting.get(key, False))
            self.rpm_start.setValue(lighting.get('rpm_start_percent', 50))
            self.rpm_end.setValue(lighting.get('rpm_end_percent', 100))
            self._lighting_signature = signature
        active = hardware.get('calibration', {}).get('active', False)
        available = hasattr(getattr(self.owner.backend, 'hardware', None), 'calibration_start')
        self.start_calibration.setEnabled(available and hardware.get('connected', False) and not active and not busy)
        self.stop_calibration.setEnabled(available and active and not busy)
        self.start_telemetry.setEnabled(hasattr(self.owner.backend, 'telemetry') and not telemetry.get('running') and not active and not busy)
        self.stop_telemetry.setEnabled(bool(telemetry.get('running') or hardware.get('telemetry_restore_pending')) and not busy)
        self.output.setEnabled(state.get('integration', {}).get('mode') != 'system' and not telemetry.get('running'))
        report = json.dumps(dict(managed_lighting=lighting, calibration=hardware.get('calibration', {}), telemetry=telemetry, led_output_active=hardware.get('telemetry_active', False), restore_pending=hardware.get('telemetry_restore_pending', False), recovery_error=hardware.get('telemetry_error')), indent=2)
        if self.status.toPlainText() != report:
            self.status.setPlainText(report)
