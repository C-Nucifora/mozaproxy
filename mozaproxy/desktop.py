"""Native Qt6 wheel manager. No HTTP server or browser is involved."""

import argparse
import json
import os
import signal
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .app_state import AppState, validate_settings
from .qt_controller import Controller
from .qt_widgets import InputBench, SettingRow
from .game_mapping_editor import GameMappingEditor
from .game_mappings import default_mapping


def label(text="", wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    return widget


def tree(headers):
    widget = QTreeWidget()
    widget.setHeaderLabels(headers)
    widget.setRootIsDecorated(False)
    widget.setAlternatingRowColors(True)
    widget.setWordWrap(True)
    widget.header().setStretchLastSection(True)
    return widget


class MainWindow(QMainWindow):
    def __init__(self, app_state, start_polling=True):
        super().__init__()
        self.backend = app_state
        self.controller = Controller(app_state)
        self.schema = app_state.schema_provider()
        self.state = {}
        self.draft = {}
        self.invalid_fields = set()
        self.apply_errors = {}
        self.editing_profile = None
        self._profile_base = {}
        self._profiles_signature = None
        self._games_signature = None
        self._input_signature = None
        self._can_close = False
        self._pending_job = None
        self._active_operation = None
        self.rows = {}
        self.setWindowTitle("Mozaproxy")
        self.setMinimumSize(820, 620)
        self.resize(1180, 820)
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "webui/wheel.svg")))
        self._build()
        self.controller.snapshot_ready.connect(self.update_state)
        self.controller.operation_done.connect(self._operation_done)
        self.controller.failed.connect(self._operation_failed)
        self.controller.closed.connect(self._closed)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.controller.refresh)
        if start_polling:
            self.timer.start()
            self.controller.refresh()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        horizontal = QHBoxLayout(root)
        horizontal.setContentsMargins(12, 12, 12, 12)
        self.navigation = QListWidget()
        self.navigation.setFixedWidth(175)
        self.navigation.setSpacing(5)
        self.navigation.setAccessibleName("App sections")
        self.navigation.addItems(
            [
                "Overview",
                "Wheelbase",
                "Pedals & controls",
                "Profiles",
                "Games",
                "Diagnostics",
            ]
        )
        horizontal.addWidget(self.navigation)
        right = QVBoxLayout()
        horizontal.addLayout(right, 1)
        self.device_label = label("Looking for wheelbase…")
        font = self.device_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.device_label.setFont(font)
        right.addWidget(self.device_label)
        self.connection_label = label(
            "Input observation does not start the relay.", True
        )
        right.addWidget(self.connection_label)
        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)
        for builder in [
            self._overview,
            self._wheelbase,
            self._controls,
            self._profiles,
            self._games,
            self._diagnostics,
        ]:
            self.pages.addWidget(builder())
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.feedback = label("Ready. Connect settings to read the device.", True)
        self.feedback.setAccessibleName("Operation result")
        right.addWidget(self.feedback)
        self.hardware_label = label("Settings disconnected", True)
        right.addWidget(self.hardware_label)
        actions = QHBoxLayout()
        self.connect_button = button("Connect settings", self.connect_hardware)
        self.disconnect_button = button(
            "Disconnect",
            lambda: self._submit("disconnect", self.backend.hardware.disconnect),
        )
        actions.addWidget(self.connect_button)
        actions.addWidget(self.disconnect_button)
        actions.addStretch()
        self.draft_label = label("No changes")
        actions.addWidget(self.draft_label)
        self.discard_button = button("Discard", self.discard)
        self.apply_button = button("Apply to device", self.apply)
        actions.addWidget(self.discard_button)
        actions.addWidget(self.apply_button)
        right.addLayout(actions)
        menu = self.menuBar().addMenu("&File")
        export_action = QAction("Export diagnostics…", self)
        export_action.triggered.connect(self.export_diagnostics)
        menu.addAction(export_action)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        view = self.menuBar().addMenu("&View")
        for i in range(self.navigation.count()):
            action = QAction(self.navigation.item(i).text(), self)
            action.setShortcut(QKeySequence(f"Alt+{i + 1}"))
            action.triggered.connect(
                lambda checked=False, index=i: self.navigation.setCurrentRow(index)
            )
            view.addAction(action)
        self.statusBar().showMessage("Local Qt6 desktop app")

    def _page(self, title, description):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = label(title)
        font = heading.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        layout.addWidget(label(description, True))
        return page, layout

    def _overview(self):
        page, layout = self._page(
            "Overview",
            "Live inputs from your wheel. Settings and the game relay are controlled separately.",
        )
        self.bench = InputBench()
        layout.addWidget(self.bench, 1)
        relay_box = QGroupBox("Game relay")
        controls = QVBoxLayout(relay_box)
        self.relay_help = label(
            "Both modes create a virtual input device. Keep the relay stopped for direct Assetto Corsa and ACC use.", True)
        controls.addWidget(self.relay_help)
        row = QHBoxLayout()
        self.relay_choice = QComboBox()
        self.relay_choice.addItem("Full input mapping", "native")
        self.relay_choice.addItem("Compact R9 compatibility", "compact")
        row.addWidget(self.relay_choice, 1)
        self.relay_button = button("Start relay", self.toggle_relay)
        row.addWidget(self.relay_button)
        self.relay_label = label("Stopped")
        row.addWidget(self.relay_label)
        controls.addLayout(row)
        layout.addWidget(relay_box)
        return page

    def _settings_tab(self, group):
        content = QWidget()
        layout = QVBoxLayout(content)
        for definition in self.schema["settings"]:
            if definition["group"] != group["id"]:
                continue
            row = SettingRow(definition)
            row.edited.connect(
                lambda key, value: self.set_draft(key, value, update_editor=False)
            )
            row.invalid.connect(self.set_invalid)
            self.rows[definition["id"]] = row
            layout.addWidget(row)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    def _wheelbase(self):
        page, layout = self._page(
            "Wheelbase",
            "Changes remain in draft until Apply. Confirmed device values appear beneath each control.",
        )
        tabs = QTabWidget()
        layout.addWidget(tabs)
        for group in self.schema["groups"]:
            if group["id"] not in ("pedals", "wheel", "handbrake"):
                tabs.addTab(self._settings_tab(group), group["label"])
        return page

    def _controls(self):
        page, layout = self._page(
            "Pedals & controls",
            "Observe axes and buttons, then adjust supported pedal and wheel settings.",
        )
        tabs = QTabWidget()
        layout.addWidget(tabs)
        inputs = QWidget()
        input_layout = QVBoxLayout(inputs)
        self.axes = tree(["Axis", "Position", "Raw", "Range"])
        input_layout.addWidget(self.axes, 2)
        self.buttons = QPlainTextEdit()
        self.buttons.setReadOnly(True)
        self.buttons.setMaximumHeight(130)
        self.buttons.setAccessibleName("Pressed buttons and paddles")
        input_layout.addWidget(self.buttons)
        tabs.addTab(inputs, "Live inputs")
        for group in self.schema["groups"]:
            if group["id"] in ("pedals", "wheel", "handbrake"):
                tabs.addTab(self._settings_tab(group), group["label"])
        return page

    def _profiles(self):
        page, layout = self._page(
            "Profiles",
            "Load a setup into draft. Saving or selecting a profile does not write to the wheel.",
        )
        split = QSplitter()
        self.profile_list = QListWidget()
        self.profile_list.setAccessibleName("Saved profiles")
        split.addWidget(self.profile_list)
        editor = QWidget()
        form = QVBoxLayout(editor)
        fields = QFormLayout()
        self.profile_name = QLineEdit()
        self.profile_name.setMaxLength(80)
        fields.addRow("Profile &name", self.profile_name)
        self.profile_game = QComboBox()
        self.profile_game.addItem("Any game", None)
        fields.addRow("&Game", self.profile_game)
        form.addLayout(fields)
        self.profile_summary = QPlainTextEdit()
        self.profile_summary.setReadOnly(True)
        form.addWidget(self.profile_summary, 1)
        form.addWidget(
            label(
                "The preview contains confirmed readings plus draft changes, or the loaded profile plus your edits.",
                True,
            )
        )
        self.save_profile_button = button("Save profile", self.save_profile)
        form.addWidget(self.save_profile_button)
        split.addWidget(editor)
        split.setSizes([280, 520])
        layout.addWidget(split, 1)
        row = QHBoxLayout()
        self.profile_actions = [
            button("New profile", self.new_profile),
            button("Load selected", self.load_selected_profile),
            button("Delete selected…", self.delete_profile),
        ]
        for action in self.profile_actions:
            row.addWidget(action)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _games(self):
        page, layout = self._page(
            "Games",
            "Observed compatibility and launch options. These controls do not change Steam configuration.",
        )
        self.games_tree = tree(["Game", "Input", "FFB"])
        self.games_tree.header().setStretchLastSection(False)
        self.games_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.games_tree.header().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.games_tree.currentItemChanged.connect(self.game_selected)
        layout.addWidget(self.games_tree, 1)
        self.game_tabs = QTabWidget()
        layout.addWidget(self.game_tabs, 3)
        notes = QWidget()
        self.game_tabs.addTab(notes, 'Setup & evidence')
        layout = QVBoxLayout(notes)
        self.game_detail = label(
            "Select a game to see its setup and test status.", True
        )
        layout.addWidget(self.game_detail)
        self.launch_options = QPlainTextEdit()
        self.launch_options.setReadOnly(True)
        self.launch_options.setMaximumHeight(120)
        self.launch_options.setAccessibleName("Steam launch options")
        layout.addWidget(self.launch_options)
        layout.addWidget(
            button(
                "Copy launch options",
                lambda: QApplication.clipboard().setText(
                    self.launch_options.toPlainText()
                ),
            )
        )
        self.mapping_editor = GameMappingEditor()
        self.game_tabs.addTab(self.mapping_editor, 'R25 mapping')
        self.mapping_editor.save_requested.connect(self.save_game_mapping)
        self.mapping_editor.start_requested.connect(self.start_game_mapping)
        self.mapping_editor.apply_requested.connect(self.apply_game_mapping)
        return page

    def _diagnostics(self):
        page, layout = self._page(
            "Diagnostics",
            "Device checks and recent relay output. Export contains app observations only.",
        )
        self.diagnostics_tree = tree(["Check", "Status", "Detail"])
        for column in (0, 1):
            self.diagnostics_tree.header().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        layout.addWidget(self.diagnostics_tree, 1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setAccessibleName("Relay output")
        layout.addWidget(self.log, 1)
        layout.addWidget(button("Export diagnostics…", self.export_diagnostics))
        return page

    def set_draft(self, key, value, update_editor=True):
        if (
            self.editing_profile
            or self._active_operation == "apply"
            or value != self.state.get("hardware", {}).get("values", {}).get(key)
        ):
            self.draft[key] = value
        else:
            self.draft.pop(key, None)
        if key in self.rows:
            if update_editor:
                self.rows[key].set_value(value)
            self.rows[key].set_error("")
        self.invalid_fields.discard(key)
        self.apply_errors.pop(key, None)
        self._update_actions()

    def set_invalid(self, key, invalid):
        if invalid:
            self.invalid_fields.add(key)
        else:
            self.invalid_fields.discard(key)
        self._update_actions()

    def update_state(self, state):
        self.state = state
        device = state.get("device", {})
        hardware = state.get("hardware", {})
        relay = state.get("relay", {})
        system_mode = state.get("integration", {}).get("mode") == "system"
        if system_mode:
            self.relay_choice.setCurrentIndex(self.relay_choice.findData("compact"))
            self.relay_help.setText(
                "The system service starts with direct physical wheel access and the relay off. "
                "Start the compact R9 relay only for a tested game setup; it does not hide the physical wheel. "
                "Closing this app leaves the service and any relay you started running.")
            self.statusBar().showMessage("System wheel service" if state["integration"].get("available") else "System wheel service unavailable")
        self.device_label.setText(device.get("name") or "No wheel detected")
        self.connection_label.setText(
            ("Input connected" if device.get("connected") else "Input disconnected")
            + " · "
            + ("Relay running" if relay.get("running") else "Relay stopped")
        )
        self.hardware_label.setText(
            hardware.get("conflict")
            or hardware.get("error")
            or (
                f"Settings connected · {len(hardware.get('values', {}))} values read"
                if hardware.get("connected")
                else "Settings disconnected"
            )
        )
        values = hardware.get("values", {})
        for key, row in self.rows.items():
            row.set_reading(values.get(key))
            if key not in self.invalid_fields and not row.isAncestorOf(
                QApplication.focusWidget()
            ):
                row.set_value(self.draft.get(key, values.get(key)))
            if key in self.apply_errors:
                row.set_error(self.apply_errors[key])
        self.bench.update_device(device, values.get("rotation"))
        self.mapping_editor.observe(device)
        axes = device.get("axes", [])
        signature = [(a["code"], a["label"]) for a in axes]
        if signature != self._input_signature:
            self.axes.clear()
            for axis in axes:
                self.axes.addTopLevelItem(QTreeWidgetItem([axis["label"], "", "", ""]))
            self._input_signature = signature
        for i, axis in enumerate(axes):
            item = self.axes.topLevelItem(i)
            item.setText(1, f"{axis['value'] * 100:.1f}%")
            item.setText(2, str(axis["raw"]))
            item.setText(3, f"{axis['min']} … {axis['max']}")
        pressed = [
            str(b["label"]) for b in device.get("buttons", []) if b.get("pressed")
        ]
        text = f"{len(device.get('buttons', []))} buttons reported\nPressed: " + (
            ", ".join(pressed) or "None"
        )
        if self.buttons.toPlainText() != text:
            self.buttons.setPlainText(text)
        if system_mode:
            self.relay_label.setText(
                f"Process running · PID {relay.get('pid')} · Wheel readiness unverified"
                if relay.get("running") else "Direct physical wheel · Relay off"
            )
        else:
            self.relay_label.setText(
                f"Running · PID {relay.get('pid')}" if relay.get("running") else "Stopped"
            )
        if relay.get("running"):
            index = self.relay_choice.findData(relay.get('profile'))
            self.relay_choice.setPlaceholderText('Per-game G920 mapping' if index < 0 else '')
            self.relay_choice.setCurrentIndex(index)
        elif self.relay_choice.currentIndex() < 0:
            self.relay_choice.setCurrentIndex(0)
        self.relay_button.setText(
            "Stop relay" if relay.get("running") else "Start relay"
        )
        profiles = state.get("profiles", [])
        sig = (profiles, state.get("active_profile"))
        if sig != self._profiles_signature:
            selected = self.profile_list.currentItem()
            selected_id = (
                selected.data(Qt.ItemDataRole.UserRole)["id"] if selected else None
            )
            self.profile_list.clear()
            for profile in profiles:
                item = QListWidgetItem(
                    profile["name"]
                    + (
                        " · selected"
                        if profile["id"] == state.get("active_profile")
                        else ""
                    )
                )
                item.setData(Qt.ItemDataRole.UserRole, deepcopy(profile))
                self.profile_list.addItem(item)
                if profile["id"] == selected_id:
                    self.profile_list.setCurrentItem(item)
            self._profiles_signature = deepcopy(sig)
        games = state.get("games", [])
        if games != self._games_signature:
            self.games_tree.clear()
            current = self.profile_game.currentData()
            self.profile_game.clear()
            self.profile_game.addItem("Any game", None)
            for game in games:
                item = QTreeWidgetItem(
                    [game["name"], game["input_status"], game["ffb_status"]]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, game)
                self.games_tree.addTopLevelItem(item)
                self.profile_game.addItem(game["name"], game["id"])
            self.profile_game.setCurrentIndex(
                max(0, self.profile_game.findData(current))
            )
            self._games_signature = deepcopy(games)
            if games:
                self.games_tree.setCurrentItem(self.games_tree.topLevelItem(0))
        diagnostics = state.get("diagnostics", {}).get("items", [])
        self.diagnostics_tree.clear()
        for item in diagnostics:
            self.diagnostics_tree.addTopLevelItem(
                QTreeWidgetItem([item["label"], item["status"], item["detail"]])
            )
        logs = (
            "\n".join(relay.get("log", []))
            or "No relay output. The app has not started a relay."
        )
        if self.log.toPlainText() != logs:
            self.log.setPlainText(logs)
        self._update_actions()

    def _update_actions(self):
        busy = (
            self.controller.busy
            or self.controller.closing
            or self._pending_job is not None
            or self.state.get("hardware", {}).get("busy", False)
        )
        hardware = self.state.get("hardware", {})
        self.apply_button.setEnabled(
            bool(self.pending_values())
            and not self.invalid_fields
            and not busy
            and hardware.get("connected", False)
            and not hardware.get("conflict")
        )
        self.discard_button.setEnabled(
            bool(self.draft or self.invalid_fields or self.editing_profile) and not busy
        )
        integration = self.state.get("integration", {})
        system_mode = integration.get("mode") == "system"
        service_available = not system_mode or integration.get("available", False)
        self.connect_button.setEnabled(not busy and service_available)
        self.connect_button.setText(
            "Read settings" if hardware.get("connected") else "Connect settings"
        )
        self.disconnect_button.setEnabled(hardware.get("connected", False) and not busy)
        self.save_profile_button.setEnabled(
            not busy and not self.invalid_fields and bool(self.profile_values())
        )
        self.relay_button.setEnabled(not busy and service_available)
        self.relay_choice.setEnabled(
            not busy and not system_mode and not self.state.get("relay", {}).get("running")
        )
        self.mapping_editor.set_runtime(busy=busy, running=self.state.get('relay', {}).get('running', False),
                                        system_mode=system_mode, storage_error=self.state.get('game_mapping_error'),
                                        live_game=self.state.get('relay', {}).get('mapping_game'),
                                        live_status=self.state.get('relay', {}).get('mapping_status'))
        for action in self.profile_actions:
            action.setEnabled(not busy)
        self.profile_name.setEnabled(not busy)
        self.profile_game.setEnabled(not busy)
        count = len(self.pending_values())
        self.draft_label.setText(
            f"{len(self.invalid_fields)} invalid entries"
            if self.invalid_fields
            else f"{count} draft settings"
            if count
            else "No changes"
        )
        summary = (
            "\n".join(
                f"{self.rows[key].definition['label']}: {self.rows[key]._format_value(value)}"
                if key in self.rows
                else f"{key}: {value}"
                for key, value in self.profile_values().items()
            )
            or "Read settings or prepare a draft to save a profile."
        )
        if self.profile_summary.toPlainText() != summary:
            self.profile_summary.setPlainText(summary)

    def _submit(self, name, callback):
        if self._pending_job is not None or self.controller.closing:
            return
        self._pending_job = (name, callback)
        self._active_operation = name
        self._dispatch_pending()

    def _dispatch_pending(self):
        if self._pending_job is None or self.controller.closing:
            return
        if self.controller.busy:
            self.feedback.setText("Waiting for the current operation…")
            QTimer.singleShot(20, self._dispatch_pending)
        else:
            name, callback = self._pending_job
            self._pending_job = None
            self.controller.submit(name, callback)
            self.feedback.setText("Working…")
        self._update_actions()

    def connect_hardware(self):
        self._submit("connect", self.backend.hardware.connect)

    def apply(self):
        if not self.apply_button.isEnabled():
            return
        requested = deepcopy(self.pending_values())
        self._apply_requested = requested
        self._submit("apply", lambda: self.backend.hardware.apply(requested))

    def discard(self):
        self.draft.clear()
        self.invalid_fields.clear()
        self.editing_profile = None
        self._profile_base = {}
        self.apply_errors.clear()
        for row in self.rows.values():
            row.set_error("")
        self.profile_name.clear()
        self.save_profile_button.setText("Save profile")
        # Explicit discard replaces the currently focused editor as well.
        for key, row in self.rows.items():
            row.set_value(self.state.get("hardware", {}).get("values", {}).get(key))
        self.update_state(self.state)
        self.feedback.setText("Draft discarded. Device settings unchanged.")

    def profile_values(self):
        base = (
            self._profile_base
            if self.editing_profile
            else self.state.get("hardware", {}).get("values", {})
        )
        return {**base, **self.draft}

    def pending_values(self):
        values = self.state.get("hardware", {}).get("values", {})
        target = self.profile_values() if self.editing_profile else self.draft
        return {
            key: value
            for key, value in target.items()
            if key not in values or values[key] != value
        }

    def new_profile(self):
        self.editing_profile = None
        self._profile_base = {}
        self.profile_name.clear()
        self.save_profile_button.setText("Save profile")
        self._update_actions()

    def load_profile(self, profile):
        self.editing_profile = profile["id"]
        self._profile_base = deepcopy(profile["settings"])
        self.draft = deepcopy(profile["settings"])
        self.invalid_fields.clear()
        self.apply_errors.clear()
        self.profile_name.setText(profile["name"])
        self.profile_game.setCurrentIndex(
            max(0, self.profile_game.findData(profile.get("game_id")))
        )
        self.save_profile_button.setText("Update profile")
        for key, row in self.rows.items():
            row.set_value(
                self.draft.get(
                    key, self.state.get("hardware", {}).get("values", {}).get(key)
                )
            )
            row.set_error("")
        self._update_actions()
        self.feedback.setText("Profile loaded into draft. Apply writes to the device.")

    def load_selected_profile(self):
        if self.controller.closing or self._pending_job is not None:
            return
        item = self.profile_list.currentItem()
        if item:
            profile = item.data(Qt.ItemDataRole.UserRole)
            self.load_profile(profile)
            self._submit(
                "select-profile", lambda: self.backend.profiles.activate(profile["id"])
            )

    def save_profile(self):
        if not self.save_profile_button.isEnabled():
            return
        name = self.profile_name.text().strip()
        if not name:
            self.feedback.setText("Enter a profile name.")
            self.profile_name.setFocus()
            return
        settings = self.profile_values()
        try:
            validate_settings(settings, self.schema)
        except ValueError as exc:
            self.feedback.setText(str(exc))
            return
        payload = {
            "name": name,
            "game_id": self.profile_game.currentData(),
            "settings": settings,
        }
        if self.editing_profile:
            payload["id"] = self.editing_profile
        self._submit("save-profile", lambda: self.backend.profiles.save(payload))

    def delete_profile(self):
        item = self.profile_list.currentItem()
        if not item or self.controller.closing:
            return
        profile = item.data(Qt.ItemDataRole.UserRole)
        if (
            QMessageBox.question(
                self,
                "Delete profile",
                f"Delete the saved profile “{profile['name']}”? Device settings will stay unchanged.",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._delete_id = profile["id"]
            self._submit(
                "delete-profile", lambda: self.backend.profiles.delete(profile["id"])
            )

    def game_selected(self, current, previous=None):
        if not current:
            return
        game = current.data(0, Qt.ItemDataRole.UserRole)
        self.game_detail.setText(game["detail"])
        self.launch_options.setPlainText(game["launch_options"])
        saved = next((p for p in self.state.get('game_mappings', []) if p['game_id'] == game['id']), None)
        saved = {k:v for k,v in saved.items() if k != 'id'} if saved else default_mapping(game['id'])
        self.mapping_editor.select_game(game['id'], saved)

    def save_game_mapping(self, mapping):
        self._submit('save-game-mapping', lambda: self.backend.game_mappings.save(mapping))

    def start_game_mapping(self, game_id):
        self._submit('start-game-mapping', lambda: self.backend.start_game_mapping(game_id))

    def apply_game_mapping(self, game_id):
        self._submit('apply-game-mapping', lambda: self.backend.apply_game_mapping(game_id))

    def toggle_relay(self):
        if self.state.get("relay", {}).get("running"):
            self._submit("stop-relay", self.backend.relay.stop)
        else:
            data = {"profile": self.relay_choice.currentData()}
            self._submit("start-relay", lambda: self.backend.relay.start(data))

    def export_diagnostics(self):
        if self.controller.closing:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export diagnostics",
            "mozaproxy-diagnostics.json",
            "JSON files (*.json)",
        )
        if filename:

            def export():
                Path(filename).write_text(
                    json.dumps(self.backend.export(), indent=2) + "\n"
                )
                return filename

            self._submit("export", export)

    def _operation_done(self, name, result):
        if name == 'save-game-mapping':
            self.mapping_editor.saved(result)
            self.feedback.setText('Game mapping saved. Running input is unchanged.')
        elif name == 'apply-game-mapping':
            self.feedback.setText('Live change requested. The mapping tab reports the relay acknowledgement.')
        elif name in ("connect", "disconnect"):
            self.state["hardware"] = result
            self.feedback.setText(
                result.get("error")
                or result.get("conflict")
                or (
                    f"Read {len(result.get('values', {}))} device settings."
                    if name == "connect"
                    else "Settings disconnected."
                )
            )
        elif name == "apply":
            self.state.setdefault("hardware", {})["values"] = result.get("values", {})
            self.apply_errors = dict(result.get("errors", {}))
            for key, actual in result.get("applied", {}).items():
                if self.editing_profile:
                    self._profile_base[key] = actual
                if key not in self.invalid_fields and self.draft.get(
                    key
                ) == self._apply_requested.get(key):
                    self.draft.pop(key, None)
                    self.rows[key].set_value(actual)
            for key, error in result.get("errors", {}).items():
                if key in self.rows:
                    self.rows[key].set_error(error)
            self.feedback.setText(
                f"{len(result.get('applied', {}))} settings confirmed; {len(result.get('errors', {}))} errors."
            )
        elif name == "save-profile":
            self.editing_profile = result["id"]
            self._profile_base = deepcopy(result["settings"])
            self.save_profile_button.setText("Update profile")
            self.feedback.setText("Profile saved. Device settings unchanged.")
        elif name == "delete-profile":
            if self.editing_profile == self._delete_id:
                self.new_profile()
            self.feedback.setText("Profile deleted.")
        elif name == "select-profile":
            self.feedback.setText(
                "Profile selected. Apply writes its draft to the device."
            )
        else:
            self.feedback.setText(
                "Completed." if name != "export" else f"Exported to {result}"
            )
        self._active_operation = None
        self.update_state(self.state)

    def _operation_failed(self, name, message):
        if name == self._active_operation:
            self._active_operation = None
        self.feedback.setText(message)
        self._update_actions()

    def closeEvent(self, event):
        if self._can_close:
            event.accept()
            return
        event.ignore()
        self.timer.stop()
        self.feedback.setText(
            "Closing the app. The system wheel service will keep running."
            if self.state.get("integration", {}).get("mode") == "system"
            else "Closing connections and stopping the app’s relay…")
        self._pending_job = None
        self.controller.shutdown()
        self._update_actions()

    def _closed(self):
        self._can_close = True
        self.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--backend", choices=("auto", "local", "system"), default="auto")
    parser.add_argument("--service-socket", type=Path)
    args = parser.parse_args(argv)
    # Publish native controls on desktops without an active screen reader.
    os.environ.setdefault("QT_LINUX_ACCESSIBILITY_ALWAYS_ON", "1")
    app = QApplication.instance() or QApplication(["mozaproxy"])
    app.setApplicationName("Mozaproxy")
    app.setDesktopFileName("mozaproxy")
    app.setOrganizationName("Mozaproxy")
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.RuntimeLocation
    )
    lock = QLockFile(str(Path(location) / "mozaproxy-desktop.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(
            None,
            "Mozaproxy",
            "Mozaproxy is already running. Switch to its existing window.",
        )
        return 0
    from .service_client import select_backend, ServiceError
    try:
        backend = select_backend(args.backend, data_dir=args.data_dir, socket_path=args.service_socket)
    except (ServiceError, ValueError) as exc:
        QMessageBox.critical(None, "Mozaproxy", str(exc))
        return 1
    window = MainWindow(backend)
    window.show()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: window.close())
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
