"""Game setup and attended results, using the existing serialized UI controller."""
import json
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QGroupBox, QPushButton, QLabel
from .game_setup import CHECKS, RESULTS, preflight


class GameSetupPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner, self.game, self.signature = owner, None, None
        layout = QVBoxLayout(self)
        self.detection = QCheckBox('Detect running Steam games and select linked profiles')
        self.automatic = QCheckBox('Allow automatic Apply on new game launches')
        for key, widget in [('detection', self.detection), ('automatic', self.automatic)]:
            widget.clicked.connect(lambda checked, k=key: self.save({k: checked}))
            layout.addWidget(widget)
        note = QLabel('Automatic Apply is off by default and also requires permission for each game. Use the desktop app or optional mozaproxy-games user service before launching the game. Busy or disconnected settings and unsaved edits skip that launch. Steam options and relay starts remain manual.')
        note.setWordWrap(True)
        layout.addWidget(note)
        link_box = QGroupBox("Profile on game launch")
        form = QFormLayout(link_box)
        layout.addWidget(link_box)
        self.profile = QComboBox()
        form.addRow('Linked profile', self.profile)
        self.game_auto = QCheckBox('Allow automatic Apply for this game')
        form.addRow(self.game_auto)
        save = QPushButton('Save game link')
        save.clicked.connect(lambda: self.save(dict(game_id=self.game, profile_id=self.profile.currentData(), game_automatic=self.game_auto.isChecked())))
        form.addRow(save)
        record_box = QGroupBox("Attended test record")
        form = QFormLayout(record_box)
        layout.addWidget(record_box)
        self.fields = {}
        for key, title in [('route', 'Input route'), ('runtime', 'Proton or native version'), ('wheel', 'Wheel / firmware')]:
            editor = QLineEdit()
            editor.setMaxLength(200)
            form.addRow(title, editor)
            self.fields[key] = editor
        for key in CHECKS:
            combo = QComboBox()
            combo.addItems(RESULTS)
            form.addRow(key.replace('_', ' ').title(), combo)
            self.fields[key] = combo
        self.notes = QLineEdit()
        self.notes.setMaxLength(2000)
        form.addRow('Test notes', self.notes)
        record = QPushButton('Record attended test result')
        record.clicked.connect(self.record)
        form.addRow(record)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(160)
        self.report.setAccessibleName('Game prerequisites and recorded evidence')
        layout.addWidget(self.report)

    def save(self, patch):
        if self.game is None and 'game_id' in patch:
            return
        self.owner._submit('game-setup', lambda: self.owner.backend.game_setup.save(patch, self.owner.backend.profiles.snapshot()[0]))

    def record(self):
        if self.game is None:
            return
        data = dict(game_id=self.game, notes=self.notes.text())
        for key, widget in self.fields.items():
            data[key] = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
        self.owner._submit('game-result', lambda: self.owner.backend.game_setup.record(data))

    def select(self, game):
        if game != self.game:
            self.game, self.signature = game, None
            for widget in self.fields.values():
                widget.setCurrentIndex(0) if isinstance(widget, QComboBox) else widget.clear()
            self.notes.clear()
        self.refresh(self.owner.state)

    def refresh(self, state):
        setup = state.get('game_setup', {})
        self.setEnabled(bool(self.game) and hasattr(self.owner.backend, 'game_setup') and not setup.get('error') and not self.owner.controller.busy)
        for key, widget in [('detection', self.detection), ('automatic', self.automatic)]:
            with QSignalBlocker(widget):
                widget.setChecked(setup.get(key, False))
        profiles = state.get('profiles', [])
        link = setup.get('links', {}).get(self.game, {})
        signature = (self.game, profiles, link)
        if signature != self.signature:
            self.profile.clear()
            self.profile.addItem('No linked profile', None)
            for profile in profiles:
                self.profile.addItem(profile['name'], profile['id'])
            self.profile.setCurrentIndex(max(0, self.profile.findData(link.get('profile_id'))))
            self.game_auto.setChecked(link.get('automatic', False))
            self.signature = json.loads(json.dumps(signature))
            # Compare serializable lists consistently across refreshes.
            self.signature = (self.signature[0], self.signature[1], self.signature[2])
        if self.game:
            report = dict(watcher=setup.get('watcher', {}), prerequisites=preflight(self.game, state.get('protection', {}).get('enabled', False)),
                          records=[r for r in setup.get('records', []) if r['game_id'] == self.game][-10:], error=setup.get('error'))
            text = json.dumps(report, indent=2)
            if text != self.report.toPlainText():
                self.report.setPlainText(text)
