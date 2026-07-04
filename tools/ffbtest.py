#!/usr/bin/env python3
"""
Quick force-feedback relay test.

Finds the mozaproxy *virtual* device, uploads a constant force effect to it, and
plays it. If the relay works, you should feel the real MOZA wheel pull to one
side for a moment. This exercises the full path a game uses:
  upload -> (daemon relays to real base) -> play -> (wheel moves).

Run the daemon first (or the systemd service), then run this.
"""
import sys
import time

import evdev
from evdev import InputDevice, ecodes, ff


def find_virtual(name_sub="mozaproxy"):
    for path in evdev.list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        if name_sub.lower() in dev.name.lower() and ecodes.EV_FF in dev.capabilities():
            return dev
        dev.close()
    return None


def main():
    dev = find_virtual()
    if dev is None:
        print("virtual mozaproxy device not found - is the daemon running?")
        return 1
    print(f"found virtual device: {dev.name} ({dev.path})")

    # A constant force to one side, 1.5s, with a short attack/fade envelope.
    strength = 0x4000  # ~50% of int16 range
    effect = ff.Effect(
        ecodes.FF_CONSTANT, -1, 0x4000,  # type, id (-1 = new), direction (90deg)
        ff.Trigger(0, 0),
        ff.Replay(1500, 0),              # length ms, delay ms
        ff.EffectType(ff_constant_effect=ff.Constant(
            level=strength,
            ff_envelope=ff.Envelope(attack_length=200, attack_level=0,
                                    fade_length=200, fade_level=0),
        )),
    )
    print("uploading effect...")
    effect_id = dev.upload_effect(effect)
    print(f"uploaded, effect id {effect_id}. Playing - the wheel should pull now.")
    dev.write(ecodes.EV_FF, effect_id, 1)
    time.sleep(1.6)
    dev.write(ecodes.EV_FF, effect_id, 0)
    dev.erase_effect(effect_id)
    print("done. Did the wheel move?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
