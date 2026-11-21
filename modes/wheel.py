"""
modes.wheel - the two "wheel" presentation modes.

  WheelMode       ("A") - direct passthrough of the real axes and button codes.
  NormalizedMode  ("C") - presents every non-hat axis on one uniform range
                          (SIGNED16, or axis_range) for software that reads the
                          evdev values directly; no effect on how Proton games
                          decode the axes (docs/PROTON-AXES.md).

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
    """Mode "A": mirror the real base's axes and FF verbatim.

    Every real ABS axis is exposed with its exact AbsInfo, the real device's
    own button codes are passed through (the lowest `buttons` of them, or
    exactly `button_codes`; see _button_codes), and the real FF effects are
    advertised so the FFB relay works unchanged.
    """

    key: str = "A"
    aliases: tuple[str, ...] = ("wheel",)
    label: str = "Wheel (direct passthrough)"
    ffb: str = "relay"

    def __init__(self, buttons: int = 24,
                 name: str = "MOZA R25 (mozaproxy)",
                 vendor: int = 0x346E, product: int = 0x0002,
                 button_codes: list[int] | None = None) -> None:
        self.buttons = buttons
        self.name = name
        self.vendor = vendor
        self.product = product
        # An explicit set of real button codes to expose. When given it wins
        # over the `buttons` count: it decouples WHICH buttons appear from HOW
        # MANY, so you can expose the 16-button low block plus only the specific
        # upper-block codes a wheel's paddles/clutch use — keeping the total
        # count low WITHOUT dropping the high-numbered paddles. None = fall back
        # to the sorted-and-capped count (see _button_codes).
        self.button_codes = button_codes
        # Populated by build_spec: the set of button codes we actually expose,
        # used by map_input to drop real buttons we did not advertise.
        self.button_set: set[int] = set()
        # Populated by build_spec when button_codes is given: the requested
        # codes the real device does not report, and whether that was ALL of
        # them (in which case we fell back to the count). The daemon logs both
        # so a list written for another wheel, or a typo, is not silent.
        self.unknown_button_codes: list[int] = []
        self.button_codes_ignored: bool = False

    def _button_codes(self, real: RealCaps) -> list[int]:
        """The real button codes to expose, sorted.

        If an explicit `button_codes` list was given, expose exactly those that
        the real device actually reports. Codes the device does not report are
        dropped (a profile written for one wheel can't invent phantom buttons
        on another) and recorded in `unknown_button_codes` for the daemon to
        log. If NONE of the listed codes exist on this device the list is
        ignored and we fall back to the count: a wheel with no buttons at all
        is never what anyone wants, and a device with X/Y/Z axes but no EV_KEY
        is tagged by udev as an accelerometer, not a joystick. With no explicit
        list, expose the real device's own codes, sorted and capped to
        `self.buttons`.

        WHY not a synthetic BTN_JOYSTICK+i block: the MOZA base does NOT number
        its buttons contiguously from 0x120. It uses 0x120..0x12f (16) then
        jumps to 0x270..0x2df (112) — deliberately skipping the 0x130 gamepad
        block so it reads as a wheel, not a pad. A synthetic contiguous range
        therefore misses every button in the upper block (paddles, clutch,
        wheel buttons) and invents phantom codes the device never sends.
        Passing the real codes through preserves the exact button set (and the
        pad-block gap) the hardware advertises.

        WHY the explicit list matters: capping by count takes the LOWEST codes,
        so a button living high in the 0x270+ block only appears once the count
        is raised enough to drag in everything below it. Listing codes
        decouples WHICH buttons a game sees from HOW MANY, which makes "does
        this game mind a large button set?" a one-variable experiment instead
        of an all-or-nothing choice. (It was built while bisecting a game that
        read every axis as binary. Button count was never shown to be the
        cause there, so treat this as a general lever, not a known fix.)
        """
        self.unknown_button_codes = []
        self.button_codes_ignored = False
        if self.button_codes is not None:
            real_keys = set(real.keys)
            wanted = set(self.button_codes)
            self.unknown_button_codes = sorted(wanted - real_keys)
            chosen = sorted(wanted & real_keys)
            if chosen:
                return chosen
            self.button_codes_ignored = True
        return sorted(real.keys)[:self.buttons]

    def build_spec(self, real: RealCaps) -> VirtualSpec:
        """Describe a virtual device that mirrors the real axes 1:1."""
        # Mirror every real ABS axis verbatim (same AbsInfo objects/ranges).
        abs_caps = [(code, info) for code, info in real.abs.items()]
        button_codes = self._button_codes(real)
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
    pedals and other axes are SIGNED -32768..32767. Software that reads the
    evdev values directly may assume a single convention and misread the base
    (e.g. a steering axis stuck at one extreme, or a phantom center offset).
    This mode rescales every non-hat axis onto SIGNED16 so all axes share one
    convention. Hat axes keep their discrete -1..1 range.

    It does NOT change what a Proton game receives: Proton reads the virtual
    wheel through SDL, which rescales every axis onto -32768..32767 whatever
    range is advertised here, and presents it as a signed 32-bit HID field. A
    game that misreads those fields (JDM) reads binary in modes A and C alike;
    mode B may reach it through XInput instead (not yet tried in JDM). See
    docs/PROTON-AXES.md.
    """

    key: str = "C"
    aliases: tuple[str, ...] = ("normalized", "norm")
    label: str = "Normalized wheel (consistent signed axes)"

    def __init__(self, buttons: int = 24,
                 name: str = "MOZA R25 (mozaproxy)",
                 vendor: int = 0x346E, product: int = 0x0002,
                 steer_deadzone: float = 0.0,
                 axis_range: tuple[int, int] = (-32768, 32767),
                 button_codes: list[int] | None = None) -> None:
        super().__init__(buttons=buttons, name=name, vendor=vendor,
                         product=product, button_codes=button_codes)
        self.steer_deadzone = steer_deadzone
        # The uniform target range every non-hat axis is presented on.
        # axis_range=(0, 32767) keeps the top bit clear, so a direct evdev
        # reader that confuses signed and unsigned values reads the same
        # numbers either way. It does not help Proton games: SDL rescales any
        # range onto -32768..32767. JDM tried it in July and stayed binary,
        # except when SDL mapped the wheel as a gamepad; see
        # docs/PROTON-AXES.md.
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

        # Reuse WheelMode's real-button selection (see _button_codes).
        button_codes = self._button_codes(real)
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
