"""
modes.wheel - the two "wheel" presentation modes.

  WheelMode       ("A") - direct passthrough; replicates the original daemon.
  NormalizedMode  ("C") - presents every non-hat axis on a consistent SIGNED16
                          range so games that choke on the MOZA's unsigned
                          steering axis behave.

Both are pure/hardware-free: they only describe the virtual device and translate
events. All device I/O stays in mozaproxy.py.
"""
from __future__ import annotations

from typing import Iterable

from evdev import ecodes, AbsInfo, ff  # noqa: F401  (ff/AbsInfo kept for parity/type use)

from modes.base import Mode, RealCaps, VirtualSpec, rescale, SIGNED16, TRIGGER8, HAT  # noqa: F401


# Hat axes are already a tiny signed -1..1 range; normalizing them would destroy
# their discrete D-pad semantics, so both modes leave them untouched.
_HAT_AXES = (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y)


class WheelMode(Mode):
    """Mode "A": mirror the real base verbatim (the original daemon's behavior).

    Every real ABS axis is exposed with its exact AbsInfo, a small game-friendly
    block of buttons is presented contiguously from BTN_JOYSTICK, and the real
    FF effects are advertised so the FFB relay works unchanged.
    """

    key: str = "A"
    aliases: tuple[str, ...] = ("wheel",)
    label: str = "Wheel (direct passthrough)"
    ffb: str = "relay"

    def __init__(self, buttons: int = 24,
                 name: str = "MOZA R25 (mozaproxy)",
                 vendor: int = 0x346E, product: int = 0x0002) -> None:
        self.buttons = buttons
        self.name = name
        self.vendor = vendor
        self.product = product
        # Populated by build_spec: the set of button codes we actually expose,
        # used by map_input to drop real buttons above our advertised count.
        self.button_set: set[int] = set()

    def build_spec(self, real: RealCaps) -> VirtualSpec:
        """Describe a virtual device that mirrors the real axes 1:1."""
        # Mirror every real ABS axis verbatim (same AbsInfo objects/ranges).
        abs_caps = [(code, info) for code, info in real.abs.items()]
        # Expose the first N buttons contiguously from BTN_JOYSTICK; the real
        # base numbers its buttons from 0x120 upward, so this maps 1:1.
        button_codes = [ecodes.BTN_JOYSTICK + i for i in range(self.buttons)]
        self.button_set = set(button_codes)

        events: dict = {
            ecodes.EV_ABS: abs_caps,
            ecodes.EV_KEY: button_codes,
        }
        if real.ff:
            events[ecodes.EV_FF] = list(real.ff)

        return VirtualSpec(
            events=events,
            name=self.name,
            vendor=self.vendor,
            product=self.product,
            max_effects=real.ff_effects_count or 16,
        )

    def map_input(self, etype: int, code: int, value: int) -> Iterable[tuple[int, int, int]]:
        """Pass axes through unchanged; pass only exposed buttons through."""
        if etype == ecodes.EV_ABS:
            return [(etype, code, value)]
        if etype == ecodes.EV_KEY:
            # Drop buttons above the exposed count (they have no virtual code).
            if code in self.button_set:
                return [(etype, code, value)]
            return ()
        return ()


class NormalizedMode(WheelMode):
    """Mode "C": present every non-hat axis on a consistent signed range.

    The real MOZA base reports steering (ABS_X) as UNSIGNED 0..65535 while the
    pedals and other axes are SIGNED -32768..32767. Some games/enumerators
    assume a single axis convention and misread the base as a result (e.g. a
    steering axis stuck at one extreme, or a phantom center offset). This mode
    rescales every non-hat axis onto SIGNED16 so all axes share one convention.
    Hat axes keep their discrete -1..1 range.
    """

    key: str = "C"
    aliases: tuple[str, ...] = ("normalized", "norm")
    label: str = "Normalized wheel (consistent signed axes)"

    def __init__(self, buttons: int = 24,
                 name: str = "MOZA R25 (mozaproxy)",
                 vendor: int = 0x346E, product: int = 0x0002,
                 steer_deadzone: float = 0.0,
                 axis_range: tuple[int, int] = (-32768, 32767)) -> None:
        super().__init__(buttons=buttons, name=name, vendor=vendor, product=product)
        self.steer_deadzone = steer_deadzone
        # The uniform target range every non-hat axis is presented on. The
        # SIGNED16 default suits most backends, but ranges with a negative
        # minimum trip sign-handling bugs in some HID stacks (UE RawInput under
        # Proton reads them as pegged min-or-max). axis_range=(0, 32767) is the
        # bulletproof alternative: the top bit is never set, so signed and
        # unsigned parsers read identical values.
        self.axis_range = axis_range
        # ABS code -> (src_min, src_max) captured from the real device, so
        # map_input can rescale each incoming value onto axis_range.
        self.src_ranges: dict[int, tuple[int, int]] = {}

    def build_spec(self, real: RealCaps) -> VirtualSpec:
        """Like WheelMode, but re-type every non-hat axis onto axis_range."""
        lo, hi = self.axis_range
        target = AbsInfo(value=0, min=lo, max=hi, fuzz=0, flat=0, resolution=0)
        abs_caps: list[tuple[int, AbsInfo]] = []
        self.src_ranges = {}
        for code, info in real.abs.items():
            if code in _HAT_AXES:
                # Leave hats alone (discrete D-pad axis).
                abs_caps.append((code, info))
            else:
                # Capture the real source range for rescaling, and advertise a
                # uniform target range to the game.
                self.src_ranges[code] = (info.min, info.max)
                abs_caps.append((code, target))

        # Reuse WheelMode's button + FF logic by building the same button block.
        button_codes = [ecodes.BTN_JOYSTICK + i for i in range(self.buttons)]
        self.button_set = set(button_codes)

        events: dict = {
            ecodes.EV_ABS: abs_caps,
            ecodes.EV_KEY: button_codes,
        }
        if real.ff:
            events[ecodes.EV_FF] = list(real.ff)

        return VirtualSpec(
            events=events,
            name=self.name,
            vendor=self.vendor,
            product=self.product,
            max_effects=real.ff_effects_count or 16,
        )

    def map_input(self, etype: int, code: int, value: int) -> Iterable[tuple[int, int, int]]:
        """Rescale non-hat axes onto axis_range; defer everything else to WheelMode."""
        if etype == ecodes.EV_ABS and code not in _HAT_AXES:
            src = self.src_ranges.get(code)
            if src is None:
                # No captured range (shouldn't happen): pass through unchanged.
                return [(etype, code, value)]
            smin, smax = src
            lo, hi = self.axis_range
            # Only the steering axis gets a (centered) deadzone; pedals/triggers
            # keep their raw curve.
            dz = self.steer_deadzone if code == ecodes.ABS_X else 0.0
            return [(etype, code, rescale(value, smin, smax, lo, hi, deadzone=dz))]
        # Hat axes and buttons are handled exactly as WheelMode does.
        return super().map_input(etype, code, value)


__all__ = ["WheelMode", "NormalizedMode"]
