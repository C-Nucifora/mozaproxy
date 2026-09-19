import io
from pathlib import Path
import struct
import unittest

from tools.jdm_reports import decode_capture, decode_report, summarize_log
from test_hid_descriptor import describe


class JdmReportsTests(unittest.TestCase):
    def test_set_effect_offsets_match_captured_descriptor(self):
        descriptor = Path(__file__).parent / 'fixtures/r25-ultra-descriptor.bin'
        _, fields = describe(descriptor.read_bytes())
        output = [(offset, globals_[7], globals_[9])
                  for key, offset, globals_, *_ in fields if key == (9, 1)]
        self.assertIn((104, 16, 2), output)
        self.assertIn((88, 8, 1), output)
        self.assertEqual(max(offset + bits * count for offset, bits, count in output), 168)

    def test_set_effect_decodes_direction_trigger_and_timing(self):
        report = struct.pack('<BBBHHHHBBBHHHH', 1, 3, 1, 65535, 0, 0,
                             20, 128, 255, 4, 9025, 0, 0, 0)
        decoded = decode_report(report)
        self.assertEqual(decoded['effect_id'], 3)
        self.assertEqual(decoded['duration_ms'], 65535)
        self.assertTrue(decoded['infinite_duration'])
        self.assertEqual(decoded['start_delay_ms'], 20)
        self.assertEqual(decoded['direction_raw'], [9025, 0])
        self.assertEqual(decoded['axes_enabled'], [])
        self.assertTrue(decoded['direction_enabled'])
        self.assertEqual(decoded['trigger_button'], 255)
        self.assertTrue(any('trigger' in issue for issue in decoded['observations']))

    def test_signed_constant_force_and_zero_padding(self):
        decoded = decode_report(bytes.fromhex('05 02 9a f9') + bytes(47))
        self.assertEqual(decoded['magnitude'], -1638)
        self.assertEqual(decoded['padding_bytes'], 47)
        self.assertFalse(decoded['padding_nonzero'])

    def test_effect_operation_does_not_confuse_repeat_count_and_effect_id(self):
        self.assertEqual(decode_report(bytes.fromhex('0a 02 01 03'))['iterations'], 3)
        self.assertEqual(decode_report(bytes.fromhex('0a 02 03 00'))['operation'], 'stop')

    def test_device_control_is_bitmask_not_array(self):
        self.assertEqual(decode_report(bytes.fromhex('0c 09'))['controls'],
                         ['enable_actuators', 'reset'])

    def test_rejects_truncated_and_unknown_reports(self):
        for value in [b'', bytes.fromhex('01 01 01'), bytes.fromhex('ff 00')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_report(value)

    def test_log_summary_does_not_claim_outbound_bytes_were_captured(self):
        report = summarize_log(io.StringIO(
            '0174:trace:dinput:hid_joystick_effect_Start iface 0x123, iterations 1, flags 0.\n'
            '0174:warn:dinput:set_parameter_value_angle unknown angle unit caps 0\n'
            '0174:trace:dinput:hid_joystick_read 00000000  01 02 03\n'))
        self.assertEqual(report['counts']['start'], 1)
        self.assertEqual(report['counts']['unknown_angle_unit'], 1)
        self.assertEqual(report['first_lines']['start'], 1)
        self.assertFalse(report['outbound_report_bytes_available'])

    def test_capture_decodes_output_and_feature_without_inventing_failed_bytes(self):
        records = decode_capture(io.StringIO(
            '{"operation":"write","hex":"05029af9","result":4,"errno":0}\n'
            '{"operation":"get_feature","hex":"1202010010","result":5,"errno":0}\n'
            '{"operation":"write","hex":"","result":-1,"errno":5}\n'))
        self.assertEqual(records[0]['decoded']['magnitude'], -1638)
        self.assertEqual(records[1]['decoded']['effect_id'], 2)
        self.assertEqual(records[1]['decoded']['status'], 'success')
        self.assertEqual(records[1]['decoded']['pool_available'], 4096)
        self.assertIsNone(records[2]['decoded'])

    def test_capture_keeps_unrecognized_reports_for_later_analysis(self):
        records = decode_capture(io.StringIO(
            '{"operation":"write","hex":"af010203","result":4,"errno":0}\n'))
        self.assertIsNone(records[0]['decoded'])
        self.assertEqual(records[0]['hex'], 'af010203')
