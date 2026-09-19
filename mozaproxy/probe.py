"""Explicit, finite-duration constant-force hardware probe."""

import argparse
import math
import signal
import time

from evdev import InputDevice, ecodes as e, ff


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True, help='Exact evdev node to test')
    parser.add_argument('--strength', type=float, default=.02, help='Fraction of effect level, 0..0.10')
    parser.add_argument('--duration', type=int, default=250, help='Milliseconds per pulse, 1..1000')
    parser.add_argument('--play', action='store_true', help='Send the pulses; otherwise preview only')
    args = parser.parse_args(argv)
    if not math.isfinite(args.strength) or not 0 < args.strength <= .10:
        parser.error('--strength must be greater than zero and at most 0.10')
    if not 1 <= args.duration <= 1000:
        parser.error('--duration must be between 1 and 1000 milliseconds')
    return args


def play_pulses(dev, strength, duration):
    if not math.isfinite(strength) or not 0 < strength <= .10 or not 1 <= duration <= 1000:
        raise ValueError('Pulse exceeds test limits')
    if e.FF_CONSTANT not in dev.capabilities().get(e.EV_FF, []):
        raise ValueError('Device does not advertise constant force')
    level = round(32767 * strength)
    ramp = min(75, duration // 5)
    for index, direction in enumerate((0x4000, 0xc000), start=1):
        effect = ff.Effect(e.FF_CONSTANT, -1, direction, ff.Trigger(0, 0),
                           ff.Replay(duration, 0), ff.EffectType(ff_constant_effect=ff.Constant(
                               level=level, ff_envelope=ff.Envelope(ramp, 0, ramp, 0))))
        eid = dev.upload_effect(effect)
        try:
            print(f'Pulse {index}: direction={direction:#06x}, level={level}, {duration} ms', flush=True)
            dev.write(e.EV_FF, eid, 1)
            time.sleep(duration / 1000 + .1)
        finally:
            try:
                dev.write(e.EV_FF, eid, 0)
            finally:
                dev.erase_effect(eid)
        print(f'Pulse {index} stopped and erased', flush=True)
        if index == 1:
            time.sleep(3)


def main(argv=None):
    args = parse_args(argv)
    if not args.play:
        print(f'Preview: two {args.strength:.0%} pulses, {args.duration} ms each, on {args.device}.')
        print('Add --play when ready. Global gain will not be changed.')
        return 0

    def interrupted(*_):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    dev = None
    try:
        dev = InputDevice(args.device)
        print(f'Testing {dev.name} at {dev.path}', flush=True)
        play_pulses(dev, args.strength, args.duration)
        return 0
    except KeyboardInterrupt:
        print('Test interrupted; device handle closing.', flush=True)
        return 130
    except (OSError, ValueError) as exc:
        print(f'Test failed: {exc}', flush=True)
        return 1
    finally:
        if dev is not None:
            dev.close()
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())
