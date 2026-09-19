import errno
import unittest
from unittest.mock import patch

from evdev import ecodes as e

from mozaproxy.probe import parse_args, play_pulses


class ProbeTests(unittest.TestCase):
    def test_nonfinite_or_excessive_strength_rejected(self):
        for strength in ['nan', 'inf', '-1', '0', '0.11']:
            with self.subTest(strength=strength), self.assertRaises(SystemExit):
                parse_args(['--device', '/fake', '--strength', strength])

    def test_play_requires_explicit_flag(self):
        self.assertFalse(parse_args(['--device', '/fake']).play)

    def test_interrupted_pulse_is_stopped_and_erased(self):
        events = []

        class Device:
            def capabilities(self):
                return {e.EV_FF: [e.FF_CONSTANT]}

            def upload_effect(self, effect):
                self.effect = effect
                return 7

            def write(self, *event):
                events.append(event)

            def erase_effect(self, eid):
                events.append(('erase', eid))

        dev = Device()
        with patch('mozaproxy.probe.time.sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                play_pulses(dev, .05, 350)
        self.assertEqual(dev.effect.ff_replay.length, 350)
        self.assertEqual(dev.effect.u.ff_constant_effect.level, 1638)
        self.assertEqual(events, [(e.EV_FF, 7, 1), (e.EV_FF, 7, 0), ('erase', 7)])


if __name__ == '__main__':
    unittest.main()
