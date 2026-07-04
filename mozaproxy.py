#!/usr/bin/env python3
"""
mozaproxy - present a MOZA wheelbase to games as a clean virtual wheel.

Some titles (notably Forza Horizon 5 under Proton) crash on startup when a MOZA
base is connected. The base advertises a HID profile with 128 buttons plus a
large PID force-feedback block, and the game's DirectInput / Windows.Gaming.Input
enumeration falls over on it. See README for the full diagnosis.

This daemon:
  1. Opens and exclusively grabs the real MOZA evdev device.
  2. Creates a virtual joystick (uinput) that mirrors the real axes and a small,
     game-friendly number of buttons, and advertises the same force-feedback
     effects.
  3. Relays input events real -> virtual, and force-feedback (effect upload,
     erase, play/stop, gain, autocenter) virtual -> real.

Games are steered away from the real node by the accompanying udev rule
(99-mozaproxy.rules), which clears ID_INPUT_JOYSTICK on the real device so input
enumerators skip it while this daemon still opens it directly by path.

Runs as your user (no root at runtime) given access to the real device and
/dev/uinput, both of which the shipped udev rule / MOZA's own rule grant.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import logging
import os
import selectors
import signal
import sys
import time

import evdev
from evdev import AbsInfo, InputDevice, UInput, ecodes, ff

log = logging.getLogger("mozaproxy")

DEFAULT_VENDOR = 0x346E   # keep MOZA vendor id so sims still brand-detect it
DEFAULT_PRODUCT = 0x0002  # distinct product so our udev rule never matches us
DEFAULT_NAME = "MOZA R25 (mozaproxy)"
DEFAULT_BUTTONS = 24      # a normal wheel exposes ~25; well under DInput's 128

# FF control codes that are not per-effect ids.
FF_CONTROL_CODES = {ecodes.FF_GAIN, ecodes.FF_AUTOCENTER}


def find_real_device(vendor: int, product: int, name_hint: str | None) -> InputDevice | None:
    """Locate the real MOZA base evdev node (the one that carries the axes)."""
    for path in evdev.list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        info = dev.info
        caps = dev.capabilities()
        is_moza = info.vendor == vendor and info.product == product
        if name_hint and name_hint.lower() in dev.name.lower():
            is_moza = True
        # The base exposes both axes and force feedback; accessory/HID nodes do not.
        if is_moza and ecodes.EV_ABS in caps and ecodes.EV_FF in caps:
            return dev
        dev.close()
    return None


def clone_effect(src: ff.Effect) -> ff.Effect:
    """Byte-copy an ff.Effect ctypes struct so we can retarget it at the real device."""
    dst = ff.Effect()
    ctypes.memmove(ctypes.addressof(dst), ctypes.addressof(src), ctypes.sizeof(ff.Effect))
    return dst


class Proxy:
    def __init__(self, args):
        self.args = args
        self.real: InputDevice | None = None
        self.virt: UInput | None = None
        # virtual effect id -> real effect id
        self.effect_map: dict[int, int] = {}
        self.button_codes: list[int] = []
        self.running = True

    # -- lifecycle ---------------------------------------------------------
    def open_real(self) -> bool:
        dev = find_real_device(self.args.vendor_real, self.args.product_real, self.args.name_hint)
        if dev is None:
            return False
        try:
            dev.grab()
        except OSError as exc:
            log.warning("could not grab %s (%s); continuing ungrabbed", dev.path, exc)
        self.real = dev
        log.info("attached to real device: %s (%s)", dev.name, dev.path)
        return True

    def build_virtual(self) -> None:
        assert self.real is not None
        caps = self.real.capabilities()

        abs_caps = caps.get(ecodes.EV_ABS, [])
        # Expose the first N buttons contiguously from BTN_JOYSTICK; the real
        # base numbers its buttons from 0x120 upward, so this maps 1:1.
        n = self.args.buttons
        self.button_codes = [ecodes.BTN_JOYSTICK + i for i in range(n)]
        ff_caps = caps.get(ecodes.EV_FF, [])

        events = {
            ecodes.EV_ABS: abs_caps,
            ecodes.EV_KEY: self.button_codes,
        }
        if ff_caps:
            events[ecodes.EV_FF] = ff_caps

        max_effects = self.real.ff_effects_count or 16
        self.virt = UInput(
            events,
            name=self.args.name,
            vendor=self.args.vendor,
            product=self.args.product,
            version=0x0111,
            max_effects=max_effects,
        )
        log.info(
            "created virtual device: %s (vendor=%04x product=%04x, %d axes, %d buttons, "
            "%d ff effects, max_effects=%d)",
            self.args.name, self.args.vendor, self.args.product,
            len(abs_caps), len(self.button_codes), len(ff_caps), max_effects,
        )

    def close(self) -> None:
        if self.virt is not None:
            try:
                self.virt.close()
            except Exception:
                pass
            self.virt = None
        if self.real is not None:
            try:
                self.real.ungrab()
            except Exception:
                pass
            try:
                self.real.close()
            except Exception:
                pass
            self.real = None
        self.effect_map.clear()

    # -- relay: real -> virtual -------------------------------------------
    def on_real_event(self, ev: evdev.InputEvent) -> None:
        virt = self.virt
        if virt is None:
            return
        t = ev.type
        if t == ecodes.EV_ABS:
            virt.write(t, ev.code, ev.value)
        elif t == ecodes.EV_KEY:
            if ev.code in self._button_set:
                virt.write(t, ev.code, ev.value)
        elif t == ecodes.EV_SYN:
            virt.write(t, ev.code, ev.value)
        # EV_MSC (scancodes) and anything else are intentionally dropped.

    # -- relay: virtual -> real (force feedback) --------------------------
    def on_virt_event(self, ev: evdev.InputEvent) -> None:
        real = self.real
        if real is None:
            return
        if ev.type == ecodes.EV_UINPUT:
            if ev.code == ecodes.UI_FF_UPLOAD:
                self._handle_upload(ev.value)
            elif ev.code == ecodes.UI_FF_ERASE:
                self._handle_erase(ev.value)
        elif ev.type == ecodes.EV_FF:
            self._handle_ff_write(ev.code, ev.value)

    def _handle_upload(self, request_id: int) -> None:
        upload = self.virt.begin_upload(request_id)
        effect = upload.effect
        vid = effect.id
        try:
            real_effect = clone_effect(effect)
            # Re-use the previously mapped real id if the game is updating an
            # existing effect, otherwise ask the kernel for a fresh one.
            real_effect.id = self.effect_map.get(vid, -1)
            real_id = self.real.upload_effect(real_effect)
            self.effect_map[vid] = real_id
            upload.retval = 0
        except OSError as exc:
            log.warning("ff upload relay failed (vid=%d): %s", vid, exc)
            upload.retval = -(exc.errno or errno.EINVAL)
        self.virt.end_upload(upload)

    def _handle_erase(self, request_id: int) -> None:
        erase = self.virt.begin_erase(request_id)
        vid = erase.effect_id
        real_id = self.effect_map.pop(vid, None)
        if real_id is not None:
            try:
                self.real.erase_effect(real_id)
            except OSError as exc:
                log.debug("ff erase relay failed (vid=%d): %s", vid, exc)
        erase.retval = 0
        self.virt.end_erase(erase)

    def _handle_ff_write(self, code: int, value: int) -> None:
        if code in FF_CONTROL_CODES:
            # Global gain / autocenter apply directly.
            try:
                self.real.write(ecodes.EV_FF, code, value)
            except OSError as exc:
                log.debug("ff control relay failed (code=%d): %s", code, exc)
            return
        real_id = self.effect_map.get(code)
        if real_id is None:
            return
        try:
            self.real.write(ecodes.EV_FF, real_id, value)
        except OSError as exc:
            log.debug("ff play relay failed (vid=%d): %s", code, exc)

    # -- main loop --------------------------------------------------------
    def run(self) -> None:
        sel = selectors.DefaultSelector()
        self._button_set = set(self.button_codes)
        sel.register(self.real.fileno(), selectors.EVENT_READ, "real")
        sel.register(self.virt.fileno(), selectors.EVENT_READ, "virt")
        log.info("relay running")
        while self.running:
            for key, _ in sel.select(timeout=1.0):
                src = key.data
                dev = self.real if src == "real" else self.virt
                try:
                    for ev in dev.read():
                        if src == "real":
                            self.on_real_event(ev)
                        else:
                            self.on_virt_event(ev)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    if exc.errno in (errno.ENODEV, errno.EBADF):
                        log.warning("device went away (%s); will re-attach", exc)
                        return
                    raise

    def stop(self, *_):
        self.running = False


def supervise(args) -> int:
    """Run the proxy, re-attaching across unplug/replug until told to stop."""
    stop_flag = {"stop": False}

    def handle_signal(signum, _frame):
        log.info("received signal %d, shutting down", signum)
        stop_flag["stop"] = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while not stop_flag["stop"]:
        proxy = Proxy(args)
        try:
            if not proxy.open_real():
                if args.once:
                    log.error("no MOZA base found")
                    return 1
                time.sleep(2.0)
                continue
            proxy.build_virtual()
            proxy.run()
        except KeyboardInterrupt:
            proxy.close()
            break
        except Exception:
            log.exception("proxy error; restarting")
        finally:
            proxy.close()
        if args.once:
            break
        time.sleep(1.0)
    log.info("stopped")
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="MOZA -> clean virtual wheel proxy with FFB relay")
    p.add_argument("--buttons", type=int, default=DEFAULT_BUTTONS,
                   help=f"number of buttons to expose (default {DEFAULT_BUTTONS})")
    p.add_argument("--name", default=DEFAULT_NAME, help="virtual device name")
    p.add_argument("--vendor", type=lambda x: int(x, 0), default=DEFAULT_VENDOR,
                   help="virtual device USB vendor id (default 0x346e)")
    p.add_argument("--product", type=lambda x: int(x, 0), default=DEFAULT_PRODUCT,
                   help="virtual device USB product id (default 0x0002)")
    p.add_argument("--vendor-real", type=lambda x: int(x, 0), default=0x346E,
                   help="real MOZA vendor id to match (default 0x346e)")
    p.add_argument("--product-real", type=lambda x: int(x, 0), default=0x0000,
                   help="real MOZA product id to match (default 0x0000)")
    p.add_argument("--name-hint", default="MOZA",
                   help="substring fallback to match the real device by name")
    p.add_argument("--once", action="store_true",
                   help="do not supervise/re-attach; exit when the device goes away")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return supervise(args)


if __name__ == "__main__":
    sys.exit(main())
