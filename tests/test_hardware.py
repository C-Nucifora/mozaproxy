import unittest
from unittest.mock import Mock, patch

from mozaproxy.hardware import HardwareController, encode_packet, extract_packet
from mozaproxy.settings import SETTINGS, validate_settings


class ProtocolTests(unittest.TestCase):
    def test_read_packet_matches_big_endian_protocol(self):
        # 7e, payload length, group, device, command, big-endian read value, checksum.
        self.assertEqual(
            encode_packet(40, 19, b"\x01", b"\x00\x01"),
            bytes.fromhex("7e032813010001cb"),
        )

    def test_parser_handles_noise_split_frames_and_bad_checksum(self):
        good = encode_packet(168, 49, b"\x01", b"\x01\xc2")
        buf = bytearray(b"noise" + good[:5])
        self.assertIsNone(extract_packet(buf))
        buf.extend(good[5:])
        self.assertEqual(extract_packet(buf), (168, 49, b"\x01\x01\xc2"))
        bad = bytearray(good)
        bad[-1] ^= 1
        buf = bad + good
        self.assertEqual(extract_packet(buf), (168, 49, b"\x01\x01\xc2"))

    def test_validation_rejects_whole_batch_before_any_write(self):
        with self.assertRaises(ValueError):
            validate_settings({"rotation": 900, "torque": 999})
        for value in [float("nan"), float("inf"), True, "900", 0]:
            with self.assertRaises(ValueError):
                validate_settings({"rotation": value})
        with self.assertRaises(ValueError):
            validate_settings({"unknown": 1})
        with self.assertRaises(ValueError):
            validate_settings({"brake_min": 80, "brake_max": 20})
        self.assertEqual(validate_settings({"rotation": 900}), {"rotation": 900})

    def test_float_read_uses_float_sentinel_not_display_conversion(self):
        c = HardwareController()
        c._serial = Mock()
        c._serial.in_waiting = 10
        c._serial.read.return_value = encode_packet(
            163, 145, b"\x1a", bytes.fromhex("42480000")
        )
        self.assertEqual(c._read_setting(SETTINGS["brake_sensor_ratio"]), 50)
        c._serial.write.assert_called_once_with(
            encode_packet(35, 25, b"\x1a", bytes.fromhex("3f800000"))
        )
        c._serial = None

    def test_apply_does_not_claim_success_on_readback_failure(self):
        controller = HardwareController()
        controller._serial = object()
        controller._values = {"ffb_strength": 40}
        with (
            patch.object(controller, "_write_setting") as write,
            patch.object(
                controller, "_read_setting", side_effect=TimeoutError("No response")
            ),
        ):
            result = controller.apply({"ffb_strength": 35})
        write.assert_called_once()
        self.assertEqual(result["applied"], {})
        self.assertIn("ffb_strength", result["errors"])
        self.assertNotIn("ffb_strength", result["values"])
        controller._serial = None

    def test_unknown_hardware_setting_cannot_be_written(self):
        controller = HardwareController()
        controller._serial = object()
        with patch.object(controller, "_write_setting") as write:
            result = controller.apply({"ffb_strength": 30})
        self.assertIn("ffb_strength", result["errors"])
        write.assert_not_called()
        controller._serial = None

    def test_range_validation_uses_confirmed_existing_values(self):
        c = HardwareController()
        c._serial = object()
        c._values = {"brake_min": 10, "brake_max": 90}
        with patch.object(c, "_write_setting") as write:
            with self.assertRaises(ValueError):
                c.apply({"brake_min": 95})
        write.assert_not_called()
        c._serial = None

    def test_competing_owner_blocks_connect(self):
        c = HardwareController()
        with (
            patch("mozaproxy.hardware.discover_port", return_value="/dev/test-moza"),
            patch("mozaproxy.hardware.serial_owners", return_value=[(222, "Boxflat")]),
        ):
            status = c.connect()
        self.assertFalse(status["connected"])
        self.assertIn("Boxflat", status["conflict"])

    def test_failed_serial_close_clears_stale_connection_and_readings(self):
        controller = HardwareController()
        port = Mock()
        port.close.side_effect = OSError('serial close failed')
        controller._serial = port
        controller._values = {'rotation': 900}
        with patch('mozaproxy.hardware.fcntl.ioctl'):
            with self.assertRaisesRegex(OSError, 'serial close failed'):
                controller.disconnect()
        status = controller.status()
        self.assertFalse(status['connected'])
        self.assertEqual(status['values'], {})
        # A second close must not touch a potentially reused file descriptor.
        controller.disconnect()
        port.close.assert_called_once()

    def test_range_expansion_precedes_crossing_minimum(self):
        c = HardwareController()
        c._serial = object()
        c._values = {"brake_min": 0, "brake_max": 50}
        writes = []

        def write(setting, value):
            writes.append((setting.id, value))

        def read(setting):
            return dict(writes)[setting.id]

        with (
            patch.object(c, "_write_setting", side_effect=write),
            patch.object(c, "_read_setting", side_effect=read),
        ):
            r = c.apply({"brake_min": 60, "brake_max": 90})
        self.assertEqual(writes, [("brake_max", 90), ("brake_min", 60)])
        self.assertEqual(r["errors"], {})
        c._serial = None

    def test_success_requires_matching_readback(self):
        c = HardwareController()
        c._serial = object()
        c._values = {"ffb_strength": 40}
        with (
            patch.object(c, "_write_setting"),
            patch.object(c, "_read_setting", return_value=35),
        ):
            r = c.apply({"ffb_strength": 35})
        self.assertEqual(r["applied"], {"ffb_strength": 35})
        c._serial = None

    def test_wrong_boolean_enum_and_nonfinite_readback_are_failures(self):
        for key, old, wanted, actual in [
            ("protection", True, False, True),
            ("paddles_mode", 1, 2, 1),
            ("brake_sensor_ratio", 50, 40, float("nan")),
        ]:
            c = HardwareController()
            c._serial = object()
            c._values = {key: old}
            with (
                patch.object(c, "_write_setting"),
                patch.object(c, "_read_setting", return_value=actual),
            ):
                r = c.apply({key: wanted})
            self.assertEqual(r["applied"], {})
            self.assertIn(key, r["errors"])
            c._serial = None
