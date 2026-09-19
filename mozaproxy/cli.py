"""Command line and read-only device diagnostics."""

import argparse
import json
import logging
import signal
import threading

from evdev import ecodes as e

from .profiles import make_profile
from .game_mappings import load_mapping, compile_mapping, G920_IDENTITY
from .runtime import find_device, supervise


def usb_id(value):
    number = int(value, 0)
    if not 0 <= number <= 0xffff:
        raise argparse.ArgumentTypeError('USB identifier must be 0..65535')
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Linux wheel input and force-feedback relay')
    parser.add_argument('--profile', choices=['native', 'compact', 'g920'], default='native')
    parser.add_argument('--mapping-file', help='Saved per-game source assignments for a fixed wheel layout')
    parser.add_argument('--buttons', type=int, help='Limit real buttons; compact defaults to 32')
    parser.add_argument('--device', help='Exact physical evdev path, preferably /dev/input/by-id/...')
    parser.add_argument('--name')
    parser.add_argument('--vendor', type=usb_id)
    parser.add_argument('--product', type=usb_id)
    parser.add_argument('--vendor-real', type=usb_id, default=0x346e)
    parser.add_argument('--product-real', type=usb_id, default=0)
    parser.add_argument('--name-hint', help='Additional name filter; never overrides physical IDs')
    parser.add_argument('--once', action='store_true', help='Exit on missing wheel or session failure')
    parser.add_argument('--diagnose', action='store_true', help='Print capabilities and mapping without grabbing')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args(argv)
    args.mapping = None
    if args.mapping_file:
        if any(getattr(args, key) is not None for key in ('name', 'vendor', 'product', 'buttons')) or args.profile != 'native':
            parser.error('--mapping-file defines the fixed identity and layout; omit profile, name, vendor, product and buttons')
        try:
            args.mapping = load_mapping(args.mapping_file)
            if args.mapping['target'] == 'direct':
                raise ValueError('A direct configuration does not create a relay')
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        args.profile = 'g920'
    defaults = ('Logitech G920 Driving Force Racing Wheel', 0x046d, 0xc262) if args.profile == 'g920' else ('MOZA R25 (mozaproxy)', 0x346e, 0x0002)
    for key, value in zip(('name', 'vendor', 'product'), defaults):
        if getattr(args, key) is None:
            setattr(args, key, value)
    if args.profile == 'g920' and args.buttons not in (None, 11):
        parser.error('G920 profile has a fixed 11-button layout')
    if args.buttons is not None:
        limit = 56 if args.profile == 'compact' else 128
        if not 1 <= args.buttons <= limit:
            parser.error(f'--buttons must be between 1 and {limit} for {args.profile}')
    return args


def diagnose(args):
    dev = find_device(args)
    if dev is None:
        raise ValueError('No matching physical wheel found')
    try:
        caps = dev.capabilities()
        profile = compile_mapping(caps, args.mapping) if args.mapping else make_profile(caps, args.profile, args.buttons)
        print(json.dumps({
            'device': dev.path, 'name': dev.name,
            'vendor': dev.info.vendor, 'product': dev.info.product,
            'effect_slots': dev.ff_effects_count,
            'effects': caps.get(e.EV_FF, []),
            'axes': {str(code): info._asdict() for code, info in caps.get(e.EV_ABS, [])},
            'source_button_count': len(caps.get(e.EV_KEY, [])),
            'profile': profile.name, 'button_mapping': profile.buttons,
            'excluded_buttons': sorted(set(caps.get(e.EV_KEY, [])) - set(profile.buttons)),
            'physical_device_hidden': False,
        }, indent=2))
    finally:
        dev.close()


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    if args.diagnose:
        try:
            diagnose(args)
        except (OSError, ValueError) as exc:
            logging.error('%s', exc)
            return 1
        return 0
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    return supervise(args, stop)
