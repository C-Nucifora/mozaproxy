"""Hide a physical R25 from one game's device namespace, not from the host."""

import argparse
import os
from pathlib import Path
import shutil
import sys


def moza_nodes(sys_root=Path('/sys'), dev_root=Path('/dev')):
    nodes = set()
    usb_devices = set()
    for subsystem in ('input', 'hidraw'):
        for entry in (sys_root / 'class' / subsystem).glob('*'):
            if subsystem == 'input' and not entry.name.startswith(('event', 'js')):
                continue
            resolved = (entry / 'device').resolve()
            for parent in (resolved, *resolved.parents):
                try:
                    vendor = (parent / 'idVendor').read_text().strip().lower()
                    product = (parent / 'idProduct').read_text().strip().lower()
                except OSError:
                    continue
                if (vendor, product) == ('346e', '0000'):
                    node = dev_root / ('input' if subsystem == 'input' else '') / entry.name
                    if node.exists():
                        nodes.add(str(node))
                    usb_devices.add(parent)
                break
    for usb in usb_devices:
        try:
            bus = int((usb / 'busnum').read_text())
            device = int((usb / 'devnum').read_text())
            node = dev_root / f'bus/usb/{bus:03d}/{device:03d}'
            if node.exists():
                nodes.add(str(node))
        except (OSError, ValueError):
            continue
    return sorted(nodes)


def isolation_command(nodes, command):
    if not command:
        raise ValueError('Missing game command after --')
    result = ['bwrap', '--bind', '/', '/', '--dev-bind', '/dev', '/dev', '--die-with-parent']
    for node in nodes:
        result.extend(['--ro-bind', '/dev/null', str(node)])
    return result + ['--', *command]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs=argparse.REMAINDER, help='Game command after --')
    args = parser.parse_args(argv)
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        parser.error('Supply the game command after --')
    if not shutil.which('bwrap'):
        parser.error('bubblewrap is required for per-game device isolation')
    nodes = moza_nodes()
    print('mozaproxy: hiding only in game namespace: ' + (', '.join(nodes) or 'no connected R25'),
          file=sys.stderr, flush=True)
    argv = isolation_command(nodes, command)
    os.execvp(argv[0], argv)


if __name__ == '__main__':
    main()
