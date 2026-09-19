import unittest
from types import SimpleNamespace

from evdev import AbsInfo, InputEvent, ecodes as e

from mozaproxy.profiles import make_profile
from mozaproxy.input import InputRelay


def capabilities():
    return {
        e.EV_ABS: [(e.ABS_X, AbsInfo(32768, 0, 65535, 0, 0, 0)),
                   (e.ABS_Z, AbsInfo(-32768, -32768, 32767, 8, 0, 0))],
        e.EV_KEY: list(range(288, 304)) + list(range(624, 736)),
        e.EV_FF: [e.FF_CONSTANT, e.FF_PERIODIC, e.FF_SINE, e.FF_GAIN],
    }


class Sink:
    def __init__(self):
        self.events = []

    def write(self, *event):
        self.events.append(event)

    def syn(self):
        self.write(e.EV_SYN, e.SYN_REPORT, 0)


class InputTests(unittest.TestCase):
    def test_native_preserves_noncontiguous_buttons_and_axis_ranges(self):
        caps = capabilities()
        profile = make_profile(caps, 'native')
        self.assertEqual(profile.buttons[653], 653)
        self.assertEqual(len(profile.buttons), 128)
        self.assertEqual(profile.events[e.EV_ABS], caps[e.EV_ABS])

    def test_compact_keeps_measured_controls_without_gamepad_codes(self):
        profile = make_profile(capabilities(), 'compact')
        self.assertEqual(len(profile.buttons), 32)
        for code in [288, 289, 300, 301, 626, 639, 640, 641, 642, 643, 653, 655]:
            self.assertIn(code, profile.buttons)
        self.assertNotIn(e.BTN_GAMEPAD, profile.buttons.values())
        self.assertEqual(len(set(profile.buttons.values())), 32)

    def test_button_limit_does_not_invent_source_buttons(self):
        caps = capabilities()
        caps[e.EV_KEY] = [288, 626]
        profile = make_profile(caps, 'compact', 24)
        self.assertEqual(len(profile.buttons), 2)
        self.assertEqual(set(profile.buttons), {288, 626})

    def test_custom_waveform_is_not_advertised(self):
        caps = capabilities()
        caps[e.EV_FF].append(e.FF_CUSTOM)
        self.assertNotIn(e.FF_CUSTOM, make_profile(caps, 'native').events[e.EV_FF])

    def make_relay(self):
        profile = make_profile(capabilities(), 'compact')
        real = SimpleNamespace(
            absinfo=lambda code: SimpleNamespace(value={0: 12345, 2: -32768}[code]),
            active_keys=lambda: [301],
        )
        sink = Sink()
        return InputRelay(real, sink, profile), sink, profile

    def test_initial_snapshot_includes_held_and_released_buttons(self):
        relay, sink, profile = self.make_relay()
        relay.sync_state()
        self.assertIn((e.EV_ABS, 0, 12345), sink.events)
        self.assertIn((e.EV_KEY, profile.buttons[301], 1), sink.events)
        self.assertIn((e.EV_KEY, profile.buttons[300], 0), sink.events)
        self.assertEqual(sink.events[-1], (e.EV_SYN, e.SYN_REPORT, 0))

    def test_rotary_pulses_survive_mapping(self):
        relay, sink, profile = self.make_relay()
        for value in [1, 0, 1, 0]:
            relay.handle(InputEvent(0, 0, e.EV_KEY, 653, value))
        self.assertEqual(sink.events, [(e.EV_KEY, profile.buttons[653], v)
                                       for v in [1, 0, 1, 0]])

    def test_dropped_stream_is_discarded_until_snapshot(self):
        relay, sink, profile = self.make_relay()
        relay.handle(InputEvent(0, 0, e.EV_SYN, e.SYN_DROPPED, 0))
        relay.handle(InputEvent(0, 0, e.EV_KEY, 300, 1))
        relay.handle(InputEvent(0, 0, e.EV_ABS, 0, 999))
        self.assertEqual(sink.events, [])
        relay.handle(InputEvent(0, 0, e.EV_SYN, e.SYN_REPORT, 0))
        self.assertIn((e.EV_KEY, profile.buttons[300], 0), sink.events)
        self.assertIn((e.EV_ABS, 0, 12345), sink.events)
        self.assertNotIn((e.EV_ABS, 0, 999), sink.events)


if __name__ == '__main__':
    unittest.main()
