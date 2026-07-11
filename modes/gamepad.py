"""
modes.gamepad - present the MOZA base as an Xbox 360 / XInput gamepad.

WHY this mode exists:
  Some games refuse to bind a wheel at all, only accepting a controller, and
  some misread a wheel's high-resolution axes as binary 0%/100% inputs. Wearing
  an Xbox-360 face gives those games proper analog steering, throttle and brake
  on the axes an XInput pad is expected to expose.

WHY the Microsoft vendor/product ids:
  SDL, Steam Input and most engines recognise a controller as "XInput" by its
  USB vid/pid. Defaulting to Microsoft's Xbox 360 pad (0x045e:0x028e) makes the
  virtual device light up as a real controller. Our udev hide-rule only matches
  the real MOZA vendor (0x346e), so this synthetic 0x045e device is never hidden
  from games.

WHY rumble is translated:
  A gamepad advertises FF_RUMBLE (games probe it), but the real MOZA base does
  NOT implement FF_RUMBLE - only FF_CONSTANT / FF_PERIODIC / spring / damper.
  So a rumble effect uploaded by a game is rewritten into an equivalent sine
  FF_PERIODIC effect that the base can actually play (see translate_effect).

WHY the pedal source axes are configurable:
  Without hardware attached we cannot be certain which real ABS code carries the
  throttle vs. brake vs. clutch on a given base. The source axes are therefore
  constructor arguments with sensible defaults and are meant to be calibrated
  (Phase 3 will add `mozactl calibrate` to persist per-user assignments).
"""
from __future__ import annotations

from evdev import AbsInfo, ecodes, ff

from modes.base import (
    HAT,
    Mode,
    RealCaps,
    SIGNED16,
    TRIGGER8,
    VirtualSpec,
    rescale,
)


class GamepadMode(Mode):
    """Expose the wheelbase as a standard Xbox 360 (XInput) controller.

    Steering drives the left stick X, throttle the right trigger, brake the left
    trigger, and an optional clutch the left stick Y. Wheel buttons map in order
    onto the 11 face/shoulder/system buttons of a 360 pad. Game rumble is relayed
    to the real base as a sine periodic effect.
    """

    key = "B"
    aliases = ("gamepad", "xinput", "pad")
    label = "Gamepad (Xbox 360 / XInput)"
    ffb = "relay"

    def __init__(
        self,
        *,
        steer_src: int = ecodes.ABS_X,
        throttle_src: int = ecodes.ABS_Z,
        brake_src: int = ecodes.ABS_RZ,
        clutch_src: int | None = None,
        name: str = "MOZA R25 Pad (mozaproxy)",
        vendor: int = 0x045E,
        product: int = 0x028E,
        rumble_gain: float = 1.0,
        steer_deadzone: float = 0.0,
        steer_invert: bool = False,
        throttle_invert: bool = False,
        brake_invert: bool = False,
        clutch_invert: bool = False,
    ) -> None:
        # Real ABS codes we read from. Calibratable: defaults are best-guesses
        # until `mozactl calibrate` records the real per-device assignment.
        self.steer_src = steer_src
        self.throttle_src = throttle_src
        self.brake_src = brake_src
        self.clutch_src = clutch_src

        # Calibration outputs: some rigs report a pedal at rest at its range
        # MAX (press = decreasing) while virtual triggers expect press =
        # increasing; the per-axis inverts flip that. The deadzone applies to
        # steering only — pedals must keep their raw curve.
        self.steer_deadzone = steer_deadzone
        self.steer_invert = steer_invert
        self.throttle_invert = throttle_invert
        self.brake_invert = brake_invert
        self.clutch_invert = clutch_invert

        self.name = name
        self.vendor = vendor
        self.product = product
        self.rumble_gain = rumble_gain

        # Populated by build_spec(): source ABS ranges and real->virtual button map.
        self._steer_range: tuple[int, int] = (0, 65535)
        self._throttle_range: tuple[int, int] = (-32768, 32767)
        self._brake_range: tuple[int, int] = (-32768, 32767)
        self._clutch_range: tuple[int, int] = (-32768, 32767)
        self._btn_map: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Virtual device description.
    # ------------------------------------------------------------------
    #: Face/shoulder/system buttons of a 360 pad, in the order wheel buttons
    #: (BTN_JOYSTICK+0, +1, ...) are assigned onto them.
    _PAD_BUTTONS: tuple[int, ...] = (
        ecodes.BTN_A,
        ecodes.BTN_B,
        ecodes.BTN_X,
        ecodes.BTN_Y,
        ecodes.BTN_TL,
        ecodes.BTN_TR,
        ecodes.BTN_SELECT,
        ecodes.BTN_START,
        ecodes.BTN_MODE,
        ecodes.BTN_THUMBL,
        ecodes.BTN_THUMBR,
    )

    def build_spec(self, real: RealCaps) -> VirtualSpec:
        """Build the standard 360 layout and capture real source ranges/buttons."""

        def rng(code: int, default: tuple[int, int]) -> tuple[int, int]:
            info = real.abs.get(code)
            if info is None:
                return default
            return (info.min, info.max)

        # Capture the real source axis ranges so map_input can rescale exactly.
        self._steer_range = rng(self.steer_src, (0, 65535))
        self._throttle_range = rng(self.throttle_src, (-32768, 32767))
        self._brake_range = rng(self.brake_src, (-32768, 32767))
        if self.clutch_src is not None:
            self._clutch_range = rng(self.clutch_src, (-32768, 32767))

        # Map real buttons (BTN_JOYSTICK+0, +1, ...) in order onto the 11 pad
        # buttons; any extra real buttons beyond the 11th are dropped.
        self._btn_map = {}
        for real_code, pad_code in zip(sorted(real.keys), self._PAD_BUTTONS):
            self._btn_map[real_code] = pad_code

        events = {
            ecodes.EV_ABS: [
                (ecodes.ABS_X, SIGNED16),      # left stick X  <- steering
                (ecodes.ABS_Y, SIGNED16),      # left stick Y  <- clutch (opt)
                (ecodes.ABS_RX, SIGNED16),     # right stick X
                (ecodes.ABS_RY, SIGNED16),     # right stick Y
                (ecodes.ABS_Z, TRIGGER8),      # left trigger  <- brake
                (ecodes.ABS_RZ, TRIGGER8),     # right trigger <- throttle
                (ecodes.ABS_HAT0X, HAT),       # dpad X
                (ecodes.ABS_HAT0Y, HAT),       # dpad Y
            ],
            ecodes.EV_KEY: list(self._PAD_BUTTONS),
            # Games probe a pad for rumble; advertise it and translate on upload.
            ecodes.EV_FF: [ecodes.FF_RUMBLE],
        }

        return VirtualSpec(
            events=events,
            name=self.name,
            vendor=self.vendor,
            product=self.product,
            max_effects=real.ff_effects_count or 16,
        )

    # ------------------------------------------------------------------
    # Event translation.
    # ------------------------------------------------------------------
    def map_input(self, etype: int, code: int, value: int):
        """Translate one real (etype,code,value) into 0+ virtual events."""
        if etype == ecodes.EV_ABS:
            if code == self.steer_src:
                smin, smax = self._steer_range
                return ((ecodes.EV_ABS, ecodes.ABS_X,
                         rescale(value, smin, smax, -32768, 32767,
                                 invert=self.steer_invert,
                                 deadzone=self.steer_deadzone)),)
            if code == self.throttle_src:
                smin, smax = self._throttle_range
                return ((ecodes.EV_ABS, ecodes.ABS_RZ,
                         rescale(value, smin, smax, 0, 255,
                                 invert=self.throttle_invert)),)
            if code == self.brake_src:
                smin, smax = self._brake_range
                return ((ecodes.EV_ABS, ecodes.ABS_Z,
                         rescale(value, smin, smax, 0, 255,
                                 invert=self.brake_invert)),)
            if self.clutch_src is not None and code == self.clutch_src:
                smin, smax = self._clutch_range
                return ((ecodes.EV_ABS, ecodes.ABS_Y,
                         rescale(value, smin, smax, -32768, 32767,
                                 invert=self.clutch_invert)),)
            if code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                # Dpad passes straight through (both are -1..1 HAT axes).
                return ((ecodes.EV_ABS, code, value),)
            return ()

        if etype == ecodes.EV_KEY:
            mapped = self._btn_map.get(code)
            if mapped is None:
                return ()
            return ((ecodes.EV_KEY, mapped, value),)

        return ()

    # ------------------------------------------------------------------
    # FFB translation.
    # ------------------------------------------------------------------
    def translate_effect(self, effect: ff.Effect) -> ff.Effect | None:
        """Relay an effect to the real base, rewriting rumble into periodic.

        The real base cannot play FF_RUMBLE, so a rumble effect is converted into
        a sine FF_PERIODIC effect whose magnitude derives from the strong/weak
        rumble magnitudes. All other effect types (CONSTANT/PERIODIC/spring/...)
        are already playable and relayed unchanged.

        Preserves effect.id so the daemon's virtual->real id remapping still
        works. Never raises: on any AttributeError reading the union we drop the
        effect (return None) rather than crash the relay.
        """
        try:
            if effect.type != ecodes.FF_RUMBLE:
                # Already a base-playable effect; relay as-is.
                return effect

            rumble = effect.u.ff_rumble_effect
            strong = int(rumble.strong_magnitude)
            weak = int(rumble.weak_magnitude)
            # Halve so a full 0xffff rumble maps to ~half-scale periodic drive.
            mag = int(min(0x7FFF, self.rumble_gain * max(strong, weak) // 2))

            periodic = ff.Periodic(
                waveform=ecodes.FF_SINE,
                period=100,          # ms; a gentle ~10 Hz buzz
                magnitude=mag,
                offset=0,
                phase=0,
                envelope=ff.Envelope(0, 0, 0, 0),
            )
            return ff.Effect(
                ecodes.FF_PERIODIC,
                effect.id,
                effect.direction,
                ff.Trigger(effect.ff_trigger.button, effect.ff_trigger.interval),
                ff.Replay(effect.ff_replay.length, effect.ff_replay.delay),
                ff.EffectType(ff_periodic_effect=periodic),
            )
        except AttributeError:
            # Malformed/unexpected union shape: drop rather than crash the relay.
            return None


__all__ = ["GamepadMode"]
