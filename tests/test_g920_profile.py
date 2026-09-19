"""Explicit G920 layout must not change native or compact routes."""
import unittest
from types import SimpleNamespace
from evdev import AbsInfo, InputEvent, ecodes as e
from mozaproxy.profiles import make_profile
from mozaproxy.input import InputRelay
from mozaproxy.cli import parse_args
from tests.test_input import Sink


def source_caps():
    return {e.EV_ABS: [(e.ABS_X, AbsInfo(32768, 0, 65535, 0, 0, 0)),
                      *[(i, AbsInfo(-32768, -32768, 32767, 8, 0, 0)) for i in range(1,8)],
                      (e.ABS_HAT0X, AbsInfo(0,-1,1,0,0,0)),
                      (e.ABS_HAT0Y, AbsInfo(0,-1,1,0,0,0))],
            e.EV_KEY: list(range(288,304)) + [627,639,640],
            e.EV_FF: [e.FF_CONSTANT,e.FF_DAMPER,e.FF_GAIN]}

class G920Tests(unittest.TestCase):
    def test_explicit_profile_selects_consistent_identity_only_when_requested(self):
        args=parse_args(['--profile','g920'])
        self.assertEqual((args.vendor,args.product,args.name),(0x046d,0xc262,'Logitech G920 Driving Force Racing Wheel'))
        old=parse_args([])
        self.assertEqual((old.profile,old.vendor,old.product),('native',0x346e,2))

    def test_layout_four_axes_hat_eleven_buttons_and_ff(self):
        p=make_profile(source_caps(),'g920')
        axes=dict(p.events[e.EV_ABS])
        self.assertEqual(set(axes),{e.ABS_X,e.ABS_Y,e.ABS_Z,e.ABS_RZ,e.ABS_HAT0X,e.ABS_HAT0Y})
        for code in (e.ABS_Y,e.ABS_Z,e.ABS_RZ):
            self.assertEqual(axes[code].value,65535)
        self.assertEqual(len(p.buttons),11)
        self.assertEqual(p.buttons[301],e.BTN_JOYSTICK+4)
        self.assertEqual(p.buttons[300],e.BTN_JOYSTICK+5)
        self.assertEqual(p.events[e.EV_FF],source_caps()[e.EV_FF])

    def test_pedals_snapshot_live_and_drop_recovery_use_same_mapping(self):
        p=make_profile(source_caps(),'g920'); sink=Sink()
        values={code: info.value for code,info in source_caps()[e.EV_ABS]}
        real=SimpleNamespace(absinfo=lambda code: SimpleNamespace(value=values[code]),active_keys=lambda:[])
        relay=InputRelay(real,sink,p);relay.sync_state()
        for target in (e.ABS_Y,e.ABS_Z,e.ABS_RZ):self.assertIn((e.EV_ABS,target,65535),sink.events)
        sink.events=[]
        for source,target in [(e.ABS_Z,e.ABS_Y),(e.ABS_RZ,e.ABS_Z),(e.ABS_THROTTLE,e.ABS_RZ)]:
            relay.handle(InputEvent(0,0,e.EV_ABS,source,32767))
            self.assertEqual(sink.events[-1],(e.EV_ABS,target,0))
        relay.handle(InputEvent(0,0,e.EV_ABS,e.ABS_X,60000))
        self.assertEqual(sink.events[-1],(e.EV_ABS,e.ABS_X,60000))
        count=len(sink.events);relay.handle(InputEvent(0,0,e.EV_ABS,e.ABS_RX,123))
        self.assertEqual(len(sink.events),count)
        values[e.ABS_Z]=32767
        relay.handle(InputEvent(0,0,e.EV_SYN,e.SYN_DROPPED,0))
        relay.handle(InputEvent(0,0,e.EV_SYN,e.SYN_REPORT,0))
        self.assertIn((e.EV_ABS,e.ABS_Y,0),sink.events[count:])

    def test_missing_pedal_rejected_instead_of_inventing_input(self):
        caps=source_caps();caps[e.EV_ABS]=[(c,a) for c,a in caps[e.EV_ABS] if c!=e.ABS_RZ]
        with self.assertRaisesRegex(ValueError,'axes'):make_profile(caps,'g920')

    def test_wrong_button_limit_rejected(self):
        with self.assertRaises(ValueError):make_profile(source_caps(),'g920',24)

    def test_axis_bounds_clamped_and_hat_untouched(self):
        p=make_profile(source_caps(),'g920')
        self.assertEqual(p.axis_event(e.ABS_Z,-99999),(e.ABS_Y,65535))
        self.assertEqual(p.axis_event(e.ABS_Z,99999),(e.ABS_Y,0))
        self.assertEqual(p.axis_event(e.ABS_Z,0),(e.ABS_Y,32767))
        self.assertEqual(p.axis_event(e.ABS_HAT0X,-1),(e.ABS_HAT0X,-1))
