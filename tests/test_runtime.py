import errno
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import patch

from evdev import ecodes as e, UInputError

from mozaproxy.cli import parse_args
from mozaproxy.runtime import Session, find_device, supervise


class Device:
    def __init__(self, path, *, phys='usb/test', vendor=0x346e, product=0):
        self.path = path
        self.phys = phys
        self.name = 'Gudsen MOZA R25 Ultra Base'
        self.info = SimpleNamespace(vendor=vendor, product=product, bustype=3)
        self.closed = False
        self.grab_error = None
        self.ungrabbed = False
        self.ff_effects_count = 10

    def capabilities(self):
        return {e.EV_ABS: [], e.EV_FF: [e.FF_CONSTANT], e.EV_KEY: [288]}

    def close(self):
        self.closed = True

    def grab(self):
        if self.grab_error:
            raise self.grab_error

    def ungrab(self):
        self.ungrabbed = True


class RuntimeTests(unittest.TestCase):
    def discover(self, devices, args=None):
        by_path = {d.path: d for d in devices}
        with patch('mozaproxy.runtime.evdev.list_devices', return_value=list(by_path)), \
             patch('mozaproxy.runtime.InputDevice', side_effect=by_path.__getitem__):
            return find_device(args or parse_args([]))

    def test_discovery_excludes_own_virtual_even_with_physical_ids(self):
        virtual = Device('/fake/virtual', phys='mozaproxy/native')
        real = Device('/fake/real')
        self.assertIs(self.discover([virtual, real]), real)
        self.assertTrue(virtual.closed)

    def test_ambiguous_physical_devices_require_explicit_selection(self):
        devices = [Device('/fake/one'), Device('/fake/two')]
        with self.assertRaisesRegex(ValueError, 'Multiple'):
            self.discover(devices)
        self.assertTrue(all(d.closed for d in devices))

    def test_matching_name_does_not_override_wrong_identity(self):
        wrong = Device('/fake/wrong', vendor=0x1234)
        self.assertIsNone(self.discover([wrong]))
        self.assertTrue(wrong.closed)

    def test_grab_conflict_aborts_without_creating_virtual(self):
        real = Device('/fake/real')
        real.grab_error = OSError(errno.EBUSY, 'busy')
        with patch('mozaproxy.runtime.UInput') as virtual:
            with self.assertRaises(OSError):
                with Session(real, parse_args([])):
                    self.fail('Entered session without an exclusive grab')
            virtual.assert_not_called()
        self.assertTrue(real.closed)

    def test_virtual_creation_failure_releases_grab_and_closes_real(self):
        real = Device('/fake/real')
        with patch('mozaproxy.runtime.UInput', side_effect=OSError(errno.EACCES, 'denied')):
            with self.assertRaises(OSError):
                with Session(real, parse_args([])):
                    self.fail('Entered failed session')
        self.assertTrue(real.ungrabbed)
        self.assertTrue(real.closed)

    def test_invalid_button_counts_and_ids_rejected_before_opening_hardware(self):
        for args in [['--buttons', '0'], ['--buttons', '129'],
                     ['--vendor', '-1'], ['--product', '65536'],
                     ['--profile', 'compact', '--buttons', '57']]:
            with self.subTest(args=args), self.assertRaises(SystemExit):
                parse_args(args)

    def test_uinput_error_has_nonzero_one_shot_exit(self):
        with patch('mozaproxy.runtime.find_device', return_value=Device('/fake/real')), \
             patch('mozaproxy.runtime.UInput', side_effect=UInputError('unavailable')):
            self.assertEqual(supervise(parse_args(['--once']), threading.Event()), 1)


if __name__ == '__main__':
    unittest.main()
