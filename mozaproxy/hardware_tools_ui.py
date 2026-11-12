"""Explicit calibration and telemetry controls, separate from saved profiles."""
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QComboBox, QPushButton, QCheckBox, QSpinBox, QPlainTextEdit, QMessageBox


class HardwareToolsPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        layout = QVBoxLayout(self)
        note = QLabel('Pedal calibration changes the learned range. Stop driving first. Fully depress and release the selected pedal during the seven-second window. Stop ends capture; it does not restore the old calibration.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.pedal = QComboBox()
        self.pedal.addItems(['throttle', 'brake', 'clutch'])
        form.addRow('Base-connected pedal', self.pedal)
        self.start_calibration = QPushButton('Start seven-second calibration…')
        self.start_calibration.clicked.connect(self.calibrate)
        form.addRow(self.start_calibration)
        self.stop_calibration = QPushButton('Stop calibration')
        self.stop_calibration.clicked.connect(lambda: owner._submit('calibration-stop', owner.backend.hardware.calibration_stop))
        form.addRow(self.stop_calibration)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(20777)
        form.addRow('FH5 Data Out UDP port', self.port)
        self.output = QCheckBox('Send RPM LEDs to the connected wheel')
        form.addRow(self.output)
        self.start_telemetry = QPushButton('Start FH5 telemetry')
        self.start_telemetry.clicked.connect(self.telemetry)
        form.addRow(self.start_telemetry)
        self.stop_telemetry = QPushButton('Stop telemetry')
        self.stop_telemetry.clicked.connect(lambda: owner._submit('telemetry-stop', owner.backend.telemetry.stop))
        form.addRow(self.stop_telemetry)
        layout.addLayout(form)
        note = QLabel('Preview is the default and sends no device commands. Configure FH5 Data Out to 127.0.0.1 and the port above yourself. Only the 324-byte FH5 format is accepted. Stale data clears the LEDs after 0.5 seconds. The bar uses reported maximum RPM, not a verified shift point. LED output requires the local connection and readable newer wheel RGB controls.')
        note.setWordWrap(True)
        layout.addWidget(note)
        firmware = QLabel('<a href="https://support.mozaracing.com/en/support/solutions/articles/70000628053-downloads">Official MOZA firmware and recovery tools</a><br>Firmware flashing and independent USB accessory configuration are not implemented. No supported flashing/recovery protocol has been established here.')
        firmware.setWordWrap(True)
        firmware.setOpenExternalLinks(True)
        layout.addWidget(firmware)
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setAccessibleName('Calibration and telemetry status')
        layout.addWidget(self.status)

    def calibrate(self):
        if QMessageBox.question(self, 'Calibrate pedal', 'Is driving stopped and are you ready to fully depress and release this pedal? Calibration changes its learned range.') != QMessageBox.StandardButton.Yes:
            return
        pedal = self.pedal.currentText()
        self.owner._submit('calibration-start', lambda: self.owner.backend.hardware.calibration_start(pedal, True))

    def telemetry(self):
        port, output = self.port.value(), self.output.isChecked()
        self.owner._submit('telemetry-start', lambda: self.owner.backend.telemetry.start(port, output))

    def refresh(self, state):
        hardware, telemetry = state.get('hardware', {}), state.get('telemetry', {})
        busy = self.owner.controller.busy or self.owner._pending_job is not None
        active = hardware.get('calibration', {}).get('active', False)
        available = hasattr(getattr(self.owner.backend, 'hardware', None), 'calibration_start')
        self.start_calibration.setEnabled(available and hardware.get('connected', False) and not active and not busy)
        self.stop_calibration.setEnabled(available and active and not busy)
        self.start_telemetry.setEnabled(hasattr(self.owner.backend, 'telemetry') and not telemetry.get('running') and not active and not busy)
        self.stop_telemetry.setEnabled(bool(telemetry.get('running') or hardware.get('telemetry_restore_pending')) and not busy)
        self.output.setEnabled(state.get('integration', {}).get('mode') != 'system' and not telemetry.get('running'))
        report = json.dumps(dict(calibration=hardware.get('calibration', {}), telemetry=telemetry, led_output_active=hardware.get('telemetry_active', False), restore_pending=hardware.get('telemetry_restore_pending', False), recovery_error=hardware.get('telemetry_error')), indent=2)
        if self.status.toPlainText() != report:
            self.status.setPlainText(report)
