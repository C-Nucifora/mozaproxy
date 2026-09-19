"""Native widgets with fake app state. No devices or HTTP server."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from copy import deepcopy

from PySide6.QtWidgets import QApplication

from mozaproxy.desktop import MainWindow

STATE = {
    "device": {
        "connected": False,
        "name": None,
        "axes": [],
        "buttons": [],
        "effects": [],
        "slots": 0,
    },
    "hardware": {"connected": False, "values": {}, "conflict": None, "error": None},
    "relay": {"running": False, "profile": None, "log": []},
    "profiles": [],
    "active_profile": None,
    "games": [],
    "diagnostics": {"items": []},
}
SCHEMA = {
    "groups": [{"id": "base", "label": "Wheelbase"}],
    "settings": [
        {
            "id": "rotation",
            "label": "Steering rotation",
            "group": "base",
            "type": "number",
            "min": 90,
            "max": 2700,
            "step": 2,
            "unit": "°",
        },
        {
            "id": "protection",
            "label": "Protection",
            "group": "base",
            "type": "boolean",
            "min": 0,
            "max": 1,
        },
    ],
}


class Fake:
    def schema_provider(self):
        return deepcopy(SCHEMA)

    def snapshot(self):
        return deepcopy(STATE)

    def close(self):
        pass


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(Fake(), start_polling=False)
        self.window.update_state(deepcopy(STATE))

    def tearDown(self):
        self.window.controller.shutdown()
        for _ in range(200):
            self.qt.processEvents()
            if self.window._can_close:
                break
            import time

            time.sleep(0.005)
        self.window.close()

    def test_six_native_pages_and_disconnected_apply(self):
        self.assertEqual(self.window.pages.count(), 6)
        self.window.set_draft("rotation", 900)
        self.assertFalse(self.window.apply_button.isEnabled())
        self.assertEqual(self.window.draft, {"rotation": 900})

    def test_system_mode_has_fixed_identity_and_service_lifetime_copy(self):
        state = deepcopy(STATE)
        state['integration'] = {'mode': 'system', 'available': True}
        self.window.update_state(state)
        self.assertEqual(self.window.relay_choice.currentData(), 'compact')
        self.assertFalse(self.window.relay_choice.isEnabled())
        self.assertIn('Closing', self.window.relay_help.text())
        self.assertIn('system service', self.window.relay_help.text())
        self.assertIn('direct physical wheel access', self.window.relay_help.text())
        self.assertIn('Relay off', self.window.relay_label.text())
        state['relay'].update(running=True, pid=123, ready=None)
        self.window.update_state(state)
        self.assertIn('readiness unverified', self.window.relay_label.text())

    def test_service_unavailable_disables_device_actions(self):
        state = deepcopy(STATE)
        state['integration'] = {'mode': 'system', 'available': False}
        self.window.update_state(state)
        self.assertFalse(self.window.relay_button.isEnabled())
        self.assertFalse(self.window.connect_button.isEnabled())

    def test_device_refresh_preserves_draft(self):
        s = deepcopy(STATE)
        s["hardware"].update(connected=True, values={"rotation": 900})
        self.window.update_state(s)
        self.window.set_draft("rotation", 1080)
        s["hardware"]["values"]["rotation"] = 720
        self.window.update_state(s)
        self.assertEqual(self.window.rows["rotation"].value(), 1080)
        self.assertTrue(self.window.apply_button.isEnabled())

    def test_invalid_value_blocks_apply_and_profile_save(self):
        s = deepcopy(STATE)
        s["hardware"].update(connected=True, values={"rotation": 900})
        self.window.update_state(s)
        self.window.set_draft("rotation", 1080)
        self.window.set_invalid("rotation", True)
        self.assertFalse(self.window.apply_button.isEnabled())
        self.assertFalse(self.window.save_profile_button.isEnabled())

    def test_saved_profile_override_matching_device_is_preserved(self):
        s = deepcopy(STATE)
        s["hardware"].update(connected=True, values={"rotation": 1080})
        self.window.update_state(s)
        self.window.load_profile(
            {"id": "a", "name": "Saved", "game_id": None, "settings": {"rotation": 900}}
        )
        self.window.set_draft("rotation", 1080)
        self.assertEqual(self.window.profile_values()["rotation"], 1080)

    def test_running_compact_relay_selects_reported_profile(self):
        s = deepcopy(STATE)
        s["relay"].update(running=True, profile="compact", pid=123)
        self.window.update_state(s)
        self.assertEqual(self.window.relay_choice.currentData(), "compact")
        self.assertFalse(self.window.relay_choice.isEnabled())

    def test_applied_profile_edit_remains_in_profile_save(self):
        s = deepcopy(STATE)
        s["hardware"].update(connected=True, values={"rotation": 900})
        self.window.update_state(s)
        self.window.load_profile(
            {"id": "a", "name": "Saved", "settings": {"rotation": 900}}
        )
        self.window.set_draft("rotation", 1080)
        self.window._apply_requested = {"rotation": 1080}
        self.window._operation_done(
            "apply",
            {"applied": {"rotation": 1080}, "errors": {}, "values": {"rotation": 1080}},
        )
        self.assertEqual(self.window.profile_values()["rotation"], 1080)

    def test_failed_apply_keeps_field_error_through_refresh(self):
        s = deepcopy(STATE)
        s["hardware"].update(connected=True, values={"rotation": 900})
        self.window.update_state(s)
        self.window.set_draft("rotation", 1080)
        self.window._apply_requested = {"rotation": 1080}
        self.window._operation_done(
            "apply",
            {"applied": {}, "errors": {"rotation": "No response"}, "values": {}},
        )
        self.window.update_state(self.window.state)
        self.assertEqual(self.window.rows["rotation"].error_label.text(), "No response")

    def test_unchanged_loaded_profile_does_not_enable_apply(self):
        s = deepcopy(STATE)
        s["hardware"].update(connected=True, values={"rotation": 900})
        self.window.update_state(s)
        self.window.load_profile(
            {"id": "a", "name": "Saved", "settings": {"rotation": 900}}
        )
        self.assertFalse(self.window.apply_button.isEnabled())

    def test_edit_back_to_previous_reading_survives_inflight_apply(self):
        s = deepcopy(STATE)
        s["hardware"].update(connected=True, values={"rotation": 900})
        self.window.update_state(s)
        self.window.set_draft("rotation", 1080)
        self.window._apply_requested = {"rotation": 1080}
        self.window._active_operation = "apply"
        self.window.set_draft("rotation", 900)
        self.window._operation_done(
            "apply",
            {"applied": {"rotation": 1080}, "errors": {}, "values": {"rotation": 1080}},
        )
        self.assertEqual(self.window.draft, {"rotation": 900})
        self.assertEqual(self.window.rows["rotation"].value(), 900)
