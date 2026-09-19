import tempfile
import unittest
from pathlib import Path

from mozaproxy.launch import isolation_command, moza_nodes


class LaunchTests(unittest.TestCase):
    def test_command_preserves_game_arguments_and_masks_only_requested_nodes(self):
        command = isolation_command(['/dev/input/event8', '/dev/input/js0'],
                                    ['/game with spaces/launch', 'literal;$value'])
        self.assertEqual(command[-3:], ['--', '/game with spaces/launch', 'literal;$value'])
        self.assertEqual(command.count('/dev/null'), 2)
        self.assertIn('/dev/input/event8', command)
        self.assertNotIn('/dev/input/event4', command)

    def test_empty_game_command_is_rejected(self):
        with self.assertRaises(ValueError):
            isolation_command(['/dev/input/event8'], [])

    def test_discovery_masks_only_matching_usb_device_interfaces(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sys = root / 'sys'
            dev = root / 'dev'
            for name, vendor, product, event, hid in [
                ('wheel', '346e', '0000', 'event8', 'hidraw9'),
                ('mouse', '046d', 'c547', 'event4', 'hidraw1'),
            ]:
                usb = sys / 'devices' / name
                usb.mkdir(parents=True)
                for field, value in [('idVendor', vendor), ('idProduct', product),
                                     ('busnum', '1'), ('devnum', '14' if name == 'wheel' else '8')]:
                    (usb / field).write_text(value)
                for kind, node in [('input', event), ('hidraw', hid)]:
                    entry = sys / 'class' / kind / node
                    entry.mkdir(parents=True)
                    (entry / 'device').symlink_to(usb, target_is_directory=True)
                    target = dev / ('input' if kind == 'input' else '') / node
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
            nodes = moza_nodes(sys, dev)
            self.assertEqual(set(nodes), {str(dev / 'input/event8'), str(dev / 'hidraw9')})


if __name__ == '__main__':
    unittest.main()
