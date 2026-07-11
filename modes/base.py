"""
modes.base - the contract every presentation mode implements.

A *mode* decides what face the virtual device wears and how real events are
translated onto it. `mozaproxy.py` owns the plumbing (grab real device, create
uinput, pump events, relay FFB); it delegates three decisions to the active mode:

  1. build_spec(real)          -> what the virtual device looks like (axes,
                                  buttons, ids, FF caps).
  2. map_input(type, code, v)  -> zero or more virtual events for one real event.
  3. translate_effect(effect)  -> rewrite/relay/drop an FFB effect the game
                                  uploaded to the virtual device before it is
                                  sent to the real base.

Everything here is pure and hardware-free so it can be unit-tested with the base
unplugged. Do not import evdev device I/O here — only the constants/types.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator

from evdev import AbsInfo, ecodes, ff


# ---------------------------------------------------------------------------
# Data the daemon hands a mode about the REAL device.
# ---------------------------------------------------------------------------
@dataclass
class RealCaps:
    """Capabilities read off the real MOZA base."""
    abs: dict[int, AbsInfo]          # ABS code -> AbsInfo(min,max,fuzz,flat,res)
    keys: list[int]                  # EV_KEY button codes present (e.g. 0x120..)
    ff: list[int]                    # EV_FF effect-type codes supported
    ff_effects_count: int = 16

    def axis(self, code: int) -> AbsInfo | None:
        return self.abs.get(code)


# ---------------------------------------------------------------------------
# What the daemon should build for the VIRTUAL device.
# ---------------------------------------------------------------------------
@dataclass
class VirtualSpec:
    """Everything UInput(...) needs, produced by a mode."""
    events: dict                     # {EV_ABS:[(code,AbsInfo)], EV_KEY:[codes], EV_FF:[codes]}
    name: str
    vendor: int
    product: int
    version: int = 0x0111
    max_effects: int = 16


# ---------------------------------------------------------------------------
# Pure axis math. These are the load-bearing transforms; modes compose them.
# ---------------------------------------------------------------------------
def clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def rescale(value: int, smin: int, smax: int, dmin: int, dmax: int,
            invert: bool = False, deadzone: float = 0.0) -> int:
    """Linearly map `value` from [smin,smax] onto [dmin,dmax], clamped, rounded.

    - `invert` flips the source travel (min<->max).
    - `deadzone` (0..1) is a fraction of the *full source travel* removed around
      its CENTER; the surviving travel is re-expanded so the endpoints still hit
      dmin/dmax. Deadzone is centered (right for a steering axis); pass 0 for
      pedals/triggers where you want the raw curve.

    Endpoints are exact: rescale(smin,...)==dmin (or dmax if inverted), and
    rescale(smax,...)==dmax. Reversed source ranges (smin>smax) are supported.
    """
    if smax == smin:
        return int(dmin)
    t = (value - smin) / (smax - smin)          # 0..1 across source travel
    t = clamp(t, 0.0, 1.0)
    if invert:
        t = 1.0 - t
    if deadzone > 0.0:
        dz = clamp(deadzone, 0.0, 0.999)
        c = t - 0.5                              # -0.5..0.5 signed from center
        half = dz / 2.0
        if abs(c) <= half:
            t = 0.5
        else:
            sign = 1.0 if c > 0 else -1.0
            c = sign * (abs(c) - half) / (0.5 - half) * 0.5
            t = 0.5 + c
    return int(round(dmin + t * (dmax - dmin)))


def scale_gain(value: int, percent: int) -> int:
    """Scale an FF_GAIN value by a profile's gain percentage, clamped 0..0xFFFF.

    WHY: per-profile FFB strength. The daemon applies this clamp to every
    FF_GAIN the game writes AND to the initial gain it seeds on the real base
    at attach, so a profile's --ffb-gain caps output whether or not the game
    ever sets gain itself. Kernel gain is unsigned 16-bit, hence the 0..0xFFFF
    clamp; negative inputs clamp to 0.
    """
    scaled = (value * percent) // 100
    if scaled < 0:
        return 0
    return scaled if scaled <= 0xFFFF else 0xFFFF


# Convenience axis specs modes reuse.
SIGNED16 = AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)
TRIGGER8 = AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)
HAT = AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)


# ---------------------------------------------------------------------------
# The mode interface.
# ---------------------------------------------------------------------------
class Mode:
    """Base class. Subclasses set key/label/ffb and implement build_spec+map_input."""
    key: str = "?"                   # short selector, e.g. "A"/"B"/"C"
    aliases: tuple[str, ...] = ()     # e.g. ("wheel",)
    label: str = ""                  # human description
    # FFB policy: "relay" = pass game's effects to the real base (translate_effect
    # may rewrite them); "none" = advertise no FF and ignore game FFB.
    ffb: str = "relay"

    def build_spec(self, real: RealCaps) -> VirtualSpec:
        """Describe the virtual device for this real device."""
        raise NotImplementedError

    def map_input(self, etype: int, code: int, value: int) -> Iterable[tuple[int, int, int]]:
        """Translate one real (etype,code,value) into 0+ virtual events.

        Return an iterable of (etype, code, value). EV_SYN is added by the daemon;
        do not emit it. Return () to drop the event. Only EV_ABS and EV_KEY are
        passed in (the daemon filters the rest).
        """
        raise NotImplementedError

    def translate_effect(self, effect: ff.Effect) -> ff.Effect | None:
        """Rewrite an FFB effect before it is uploaded to the real base.

        Default: identity (relay unchanged). Return None to drop the effect
        (upload will be failed back to the game). Called only when ffb=="relay".
        """
        return effect


__all__ = [
    "RealCaps", "VirtualSpec", "Mode",
    "rescale", "clamp", "scale_gain", "SIGNED16", "TRIGGER8", "HAT",
]
