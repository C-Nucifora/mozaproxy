"""Native widgets with fake app state. No devices or HTTP server."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from copy import deepcopy

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from mozaproxy.desktop import MainWindow
from mozaproxy.settings import SETTINGS

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
        SETTINGS["torque"].schema(),
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

    def torque_state(self, percent=50):
        state = deepcopy(STATE)
        state["hardware"].update(
            connected=True,
            port="/dev/serial/by-id/usb-Gudsen_MOZA_R25_Ultra_Base_TEST-if00",
            values={"torque": percent},
        )
        return state

    def test_r25_torque_readback_is_nm_but_profiles_keep_percent(self):
        self.window.update_state(self.torque_state(70))
        row = self.window.rows["torque"]
        self.assertEqual(row.editor.value(), 17.5)
        self.assertIn("17.5 Nm", row.confirmed_label.text())
        self.assertEqual(self.window.profile_values()["torque"], 70)
        row.editor.setValue(13.1)
        self.assertEqual(self.window.pending_values()["torque"], 52)
        self.assertIn("13 Nm", row.description_label.text())
        self.assertIn("17.5 Nm", row.confirmed_label.text())

    def test_eight_nm_is_rejected_without_silently_raising_the_request(self):
        self.window.update_state(self.torque_state())
        row = self.window.rows["torque"]
        row.editor.lineEdit().setText("8 Nm")
        row.editor.lineEdit().textEdited.emit("8 Nm")
        self.assertIn("torque", self.window.invalid_fields)
        self.assertFalse(self.window.apply_button.isEnabled())
        self.assertFalse(self.window.save_profile_button.isEnabled())
        self.assertIn("12.5", row.error_label.text())
        self.window.update_state(self.torque_state())
        self.assertIn("8", row.editor.lineEdit().text())
        self.assertEqual(self.window.pending_values(), {})

    def test_excess_precision_cannot_hide_a_larger_torque_draft_on_focus_loss(self):
        self.window.update_state(self.torque_state())
        self.window.navigation.setCurrentRow(1)
        self.window.show()
        row = self.window.rows["torque"]
        row.editor.setFocus()
        row.editor.lineEdit().selectAll()
        QTest.keyClicks(row.editor.lineEdit(), "13.2499")
        self.window.connect_button.setFocus()
        self.qt.processEvents()
        self.assertIn("torque", self.window.invalid_fields)
        self.assertFalse(self.window.apply_button.isEnabled())
        self.assertIn("13.2499", row.editor.lineEdit().text())

    def test_unknown_base_does_not_inherit_r25_nm_conversion(self):
        state = self.torque_state()
        state["hardware"]["port"] = "/dev/ttyACM0"
        state["device"].update(connected=True, name="MOZA R25 Ultra Base")
        self.window.update_state(state)
        row = self.window.rows["torque"]
        self.assertEqual(row.editor.suffix(), " %")
        self.assertEqual(row.editor.value(), 50)
        self.window.update_state(self.torque_state())
        self.assertEqual(row.editor.value(), 12.5)
        row.editor.setValue(15)
        self.window.update_state(state)
        self.assertEqual(row.editor.value(), 60)
        self.assertEqual(self.window.draft["torque"], 60)

    def test_disconnected_torque_reading_is_unknown_and_draft_survives(self):
        self.window.update_state(self.torque_state())
        row = self.window.rows["torque"]
        row.editor.setValue(15)
        self.window.update_state(deepcopy(STATE))
        self.assertIn("Not read", row.confirmed_label.text())
        self.assertEqual(self.window.draft["torque"], 60)
        self.assertFalse(self.window.apply_button.isEnabled())

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
