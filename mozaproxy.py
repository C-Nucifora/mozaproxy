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

from modes import get_mode
from modes.base import FF_EFFECT_TYPES, RealCaps, canon_ff_type, scale_gain, strip_ff

log = logging.getLogger("mozaproxy")


class SingletonError(Exception):
    """Raised when the base is already grabbed by another mozaproxy instance."""

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


def describe_effect(e: ff.Effect) -> str:
    """Human-readable one-liner for an ff.Effect, for FFB tracing.

    Best-effort only: must NEVER raise, since it runs inside the relay loop.
    (ff.Effect fields are: type, id, direction, ff_trigger, ff_replay, u.)
    """
    try:
        ftype = ecodes.FF.get(e.type, e.type)
        parts = [f"type={ftype}", f"id={e.id}", f"dir=0x{e.direction & 0xffff:04x}"]
        try:
            parts.append(f"len={e.ff_replay.length}ms delay={e.ff_replay.delay}ms")
        except Exception:
            pass
        try:
            if e.type == ecodes.FF_CONSTANT:
                parts.append(f"level={e.u.constant.level}")
            elif e.type == ecodes.FF_PERIODIC:
                p = e.u.periodic
                parts.append(f"mag={p.magnitude} period={p.period} offset={p.offset}")
            elif e.type in (ecodes.FF_SPRING, ecodes.FF_DAMPER, ecodes.FF_FRICTION,
                            ecodes.FF_INERTIA):
                c = e.u.condition[0]
                parts.append(f"satL={c.left_saturation} satR={c.right_saturation} "
                             f"coefL={c.left_coeff} coefR={c.right_coeff} center={c.center}")
            elif e.type == ecodes.FF_RAMP:
                parts.append(f"start={e.u.ramp.start_level} end={e.u.ramp.end_level}")
        except Exception:
            pass
        return " ".join(parts)
    except Exception:
        return "<effect>"


class Proxy:
    def __init__(self, args):
        self.args = args
        self.mode = args._mode           # active presentation mode (see modes/)
        # Per-profile FFB gain clamp (percent); 100 relays the game's gain as-is.
        self.ffb_gain: int = getattr(args, "ffb_gain", 100)
        # Effect types the profile forbids (codes): stripped from the virtual
        # device's advertisement AND refused at upload, for backends that fault
        # on specific PID effects.
        self.ffb_drop: frozenset[int] = getattr(args, "ffb_drop", frozenset())
        # Autocenter percent to seed on attach; None leaves the base untouched.
        self.ffb_autocenter: int | None = getattr(args, "ffb_autocenter", None)
        self.real: InputDevice | None = None
        self.virt: UInput | None = None
        # virtual effect id -> real effect id
        self.effect_map: dict[int, int] = {}
        self.running = True

    # -- lifecycle ---------------------------------------------------------
    def open_real(self) -> bool:
        dev = find_real_device(self.args.vendor_real, self.args.product_real, self.args.name_hint)
        if dev is None:
            return False
        try:
            dev.grab()
        except OSError as exc:
            # An exclusive grab is mandatory: if it fails, another mozaproxy
            # instance already owns the base. Running ungrabbed would create a
            # duplicate, non-relaying virtual wheel that games may bind to
            # instead of the real one. Refuse to start a second copy.
            log.error("could not grab %s (%s) - another instance already running? "
                      "Refusing to start a duplicate.", dev.path, exc)
            dev.close()
            raise SingletonError(str(exc))
        self.real = dev
        log.info("attached to real device: %s (%s)", dev.name, dev.path)
        return True

    def build_virtual(self) -> None:
        assert self.real is not None
        caps = self.real.capabilities(absinfo=True)

        # Hand the mode the real device's capabilities; it decides the virtual
        # device's shape (axes, buttons, ids, FF advertisement).
        real = RealCaps(
            abs={code: info for code, info in caps.get(ecodes.EV_ABS, [])},
            keys=list(caps.get(ecodes.EV_KEY, [])),
            ff=list(caps.get(ecodes.EV_FF, [])),
            ff_effects_count=self.real.ff_effects_count or 16,
        )
        spec = self.mode.build_spec(real)
        if self.ffb_drop:
            # Filter at advertisement time so the kernel refuses forbidden
            # uploads before they reach the relay (see strip_ff).
            spec.events = strip_ff(spec.events, self.ffb_drop)
            names = {code: name for name, code in FF_EFFECT_TYPES.items()}
            log.info("ffb-drop active: not advertising %s",
                     ", ".join(sorted(names.get(c, str(c)) for c in self.ffb_drop)))
        self.virt = UInput(
            spec.events,
            name=spec.name,
            vendor=spec.vendor,
            product=spec.product,
            version=spec.version,
            max_effects=spec.max_effects,
        )
        log.info(
            "mode %s (%s): created virtual device '%s' (vendor=%04x product=%04x, "
            "%d axes, %d buttons, ff=%s, max_effects=%d)",
            self.mode.key, self.mode.label, spec.name, spec.vendor, spec.product,
            len(spec.events.get(ecodes.EV_ABS, [])),
            len(spec.events.get(ecodes.EV_KEY, [])),
            "yes" if spec.events.get(ecodes.EV_FF) else "no", spec.max_effects,
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
        if t == ecodes.EV_ABS or t == ecodes.EV_KEY:
            # The mode translates one real event into zero or more virtual ones
            # (axis rescale/remap, button remap, or drop).
            for et, code, val in self.mode.map_input(t, ev.code, ev.value):
                virt.write(et, code, val)
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
        # end_upload MUST always run, or the uinput FF request is left dangling
        # and every subsequent upload fails. Nothing between here and the finally
        # is allowed to abort that.
        try:
            effect = upload.effect
            vid = effect.id
            try:
                # Forbidden types are already unadvertised (kernel rejects them
                # first); this guard is for kernels/backends that upload anyway.
                if effect.type in self.ffb_drop:
                    log.debug("FF upload vid=%d refused by --ffb-drop", vid)
                    upload.retval = -errno.EINVAL
                    return
                # Let the mode rewrite the effect first (e.g. gamepad mode turns
                # a game's rumble into a periodic effect the wheel understands).
                translated = self.mode.translate_effect(effect)
                if translated is None:
                    log.debug("FF upload vid=%d dropped by mode %s", vid, self.mode.key)
                    upload.retval = -errno.EINVAL
                    return
                real_effect = clone_effect(translated)
                # Re-use the previously mapped real id if the game is updating an
                # existing effect, otherwise ask the kernel for a fresh one.
                real_effect.id = self.effect_map.get(vid, -1)
                real_id = self.real.upload_effect(real_effect)
                self.effect_map[vid] = real_id
                upload.retval = 0
                if log.isEnabledFor(logging.DEBUG):
                    log.debug("FF upload vid=%d->rid=%d  %s",
                              vid, real_id, describe_effect(effect))
            except OSError as exc:
                log.warning("ff upload relay failed (vid=%d): %s", vid, exc)
                upload.retval = -(exc.errno or errno.EINVAL)
        finally:
            self.virt.end_upload(upload)

    def _handle_erase(self, request_id: int) -> None:
        erase = self.virt.begin_erase(request_id)
        try:
            vid = erase.effect_id
            real_id = self.effect_map.pop(vid, None)
            log.debug("FF erase vid=%d->rid=%s", vid, real_id)
            if real_id is not None:
                try:
                    self.real.erase_effect(real_id)
                except OSError as exc:
                    log.debug("ff erase relay failed (vid=%d): %s", vid, exc)
            erase.retval = 0
        finally:
            self.virt.end_erase(erase)

    def apply_initial_ffb(self) -> None:
        """Seed the real base with profile FFB settings right after attach.

        WHY: a game that never writes FF_GAIN would otherwise leave the base at
        whatever gain it last had (typically full), silently bypassing the
        profile's --ffb-gain clamp. Same story for autocenter: --ffb-autocenter
        sets a baseline for games that never touch it (a later game write still
        passes through and wins).
        """
        if self.real is None:
            return
        if self.ffb_gain != 100:
            try:
                self.real.write(ecodes.EV_FF, ecodes.FF_GAIN,
                                scale_gain(0xFFFF, self.ffb_gain))
            except OSError as exc:
                log.debug("initial ffb gain write failed: %s", exc)
        if self.ffb_autocenter is not None:
            try:
                self.real.write(ecodes.EV_FF, ecodes.FF_AUTOCENTER,
                                scale_gain(0xFFFF, self.ffb_autocenter))
            except OSError as exc:
                log.debug("initial autocenter write failed: %s", exc)

    def _handle_ff_write(self, code: int, value: int) -> None:
        if code in FF_CONTROL_CODES:
            # Global gain / autocenter apply directly. Gain is clamped by the
            # profile percentage so it caps FFB strength regardless of what the
            # game asks for; autocenter passes through untouched.
            if code == ecodes.FF_GAIN:
                value = scale_gain(value, self.ffb_gain)
            name = ecodes.FF.get(code, code)
            log.debug("FF control %s=%d", name, value)
            try:
                self.real.write(ecodes.EV_FF, code, value)
            except OSError as exc:
                log.debug("ff control relay failed (code=%d): %s", code, exc)
            return
        real_id = self.effect_map.get(code)
        if real_id is None:
            log.debug("FF %s vid=%d (UNMAPPED - dropped)",
                      "play" if value else "stop", code)
            return
        log.debug("FF %s vid=%d->rid=%d value=%d",
                  "play" if value else "stop", code, real_id, value)
        try:
            self.real.write(ecodes.EV_FF, real_id, value)
        except OSError as exc:
            log.debug("ff play relay failed (vid=%d): %s", code, exc)

    # -- main loop --------------------------------------------------------
    def run(self) -> None:
        sel = selectors.DefaultSelector()
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
            proxy.apply_initial_ffb()
            proxy.run()
        except KeyboardInterrupt:
            proxy.close()
            break
        except SingletonError:
            proxy.close()
            return 3
        except Exception:
            log.exception("proxy error; restarting")
        finally:
            proxy.close()
        if args.once:
            break
        time.sleep(1.0)
    log.info("stopped")
    return 0


def _abs_code(s: str):
    """argparse converter: evdev ABS_* axis name (case-insensitive) or int literal."""
    try:
        return int(s, 0)
    except ValueError:
        pass
    name = s.upper()
    code = ecodes.ecodes.get(name)
    if code is None or not name.startswith("ABS_"):
        raise argparse.ArgumentTypeError(
            f"{s!r} is not an evdev ABS_* axis name (e.g. ABS_Z) or an integer code")
    return code


def _gain_percent(s: str):
    """argparse converter: an FFB percentage (gain/autocenter), 0..100."""
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} is not an integer")
    if not 0 <= v <= 100:
        raise argparse.ArgumentTypeError(f"percent must be 0..100, got {v}")
    return v


def _ff_drop(s: str):
    """argparse converter: comma list of FF effect-type names -> frozenset of codes."""
    codes = set()
    for part in s.split(","):
        if not part.strip():
            continue
        try:
            codes.add(FF_EFFECT_TYPES[canon_ff_type(part)])
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e))
    return frozenset(codes)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="MOZA -> clean virtual wheel proxy with FFB relay")
    p.add_argument("--mode", default="A",
                   help="presentation mode: A/wheel (passthrough), C/normalized "
                        "(consistent signed axes; fixes binary-axis games), "
                        "B/gamepad (Xbox 360 / XInput). Default A.")
    p.add_argument("--deadzone", type=float, default=0.0,
                   help="deadzone fraction 0..1 applied to steering in modes B "
                        "and C (default 0)")
    p.add_argument("--ffb-gain", type=_gain_percent, default=100,
                   help="clamp force-feedback gain to this percent 0..100 "
                        "(default 100 = relay the game's gain untouched)")
    p.add_argument("--ffb-autocenter", type=_gain_percent, default=None,
                   help="seed autocenter at this percent 0..100 on attach "
                        "(default: leave the base's setting alone)")
    p.add_argument("--ffb-drop", type=_ff_drop, default=frozenset(),
                   help="comma list of FF effect types to hide from the game "
                        "(e.g. spring,damper) for backends that fault on them")
    # Calibrated gamepad sources (mode B): which real axis feeds each pad axis.
    p.add_argument("--steer-src", type=_abs_code, default=None,
                   help="real axis feeding steering (ABS_* name or code; mode B)")
    p.add_argument("--throttle-src", type=_abs_code, default=None,
                   help="real axis feeding throttle (ABS_* name or code; mode B)")
    p.add_argument("--brake-src", type=_abs_code, default=None,
                   help="real axis feeding brake (ABS_* name or code; mode B)")
    p.add_argument("--clutch-src", type=_abs_code, default=None,
                   help="real axis feeding clutch (ABS_* name or code; mode B)")
    p.add_argument("--steer-invert", action="store_true",
                   help="invert steering travel (mode B)")
    p.add_argument("--throttle-invert", action="store_true",
                   help="invert throttle travel (mode B)")
    p.add_argument("--brake-invert", action="store_true",
                   help="invert brake travel (mode B)")
    p.add_argument("--clutch-invert", action="store_true",
                   help="invert clutch travel (mode B)")
    # The following override mode defaults; unset (None) means 'use mode default'.
    p.add_argument("--buttons", type=int, default=None,
                   help=f"buttons to expose for wheel modes (mode default {DEFAULT_BUTTONS})")
    p.add_argument("--name", default=None, help="override virtual device name")
    p.add_argument("--vendor", type=lambda x: int(x, 0), default=None,
                   help="override virtual device USB vendor id")
    p.add_argument("--product", type=lambda x: int(x, 0), default=None,
                   help="override virtual device USB product id")
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
    try:
        args._mode = get_mode(
            args.mode,
            buttons=args.buttons, name=args.name,
            vendor=args.vendor, product=args.product,
            steer_deadzone=args.deadzone,
            steer_src=args.steer_src, throttle_src=args.throttle_src,
            brake_src=args.brake_src, clutch_src=args.clutch_src,
            steer_invert=args.steer_invert, throttle_invert=args.throttle_invert,
            brake_invert=args.brake_invert, clutch_invert=args.clutch_invert,
        )
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    return supervise(args)


if __name__ == "__main__":
    sys.exit(main())
