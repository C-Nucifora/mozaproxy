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


def boost_effect(effect: "ff.Effect", percent: int) -> None:
    """Amplify an effect's drive levels in place by `percent` (150 = +50%).

    WHY: some games send timid FFB no matter what (FH5's output on a
    direct-drive base reads as "super light"), and FF_GAIN cannot help once
    the game already runs gain at max. Boosting rewrites the effect payloads
    the daemon relays to the real base.

    Only the drive-level payloads are scaled — constant level, periodic
    magnitude, ramp start/end, rumble magnitudes. Condition effects
    (spring/damper/friction/inertia) are left untouched: scaling their
    coefficients stiffens centering nonlinearly and can oscillate a
    direct-drive wheel. Values clamp to their kernel field ranges.
    """
    k = percent / 100.0

    def s16(v: float) -> int:
        return int(clamp(v, -32768, 32767))

    def u16(v: float) -> int:
        return int(clamp(v, 0, 0xFFFF))

    if effect.type == ecodes.FF_CONSTANT:
        c = effect.u.ff_constant_effect
        c.level = s16(c.level * k)
    elif effect.type == ecodes.FF_PERIODIC:
        p = effect.u.ff_periodic_effect
        p.magnitude = s16(p.magnitude * k)
    elif effect.type == ecodes.FF_RAMP:
        r = effect.u.ff_ramp_effect
        r.start_level = s16(r.start_level * k)
        r.end_level = s16(r.end_level * k)
    elif effect.type == ecodes.FF_RUMBLE:
        r = effect.u.ff_rumble_effect
        r.strong_magnitude = u16(r.strong_magnitude * k)
        r.weak_magnitude = u16(r.weak_magnitude * k)


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


# ---------------------------------------------------------------------------
# FF effect-type names. One source of truth for profile validation (profiledb),
# the daemon's --ffb-drop converter, and the advertisement filter below —
# so "spring" in a profile, FF_SPRING on the CLI and the ecode all agree.
# ---------------------------------------------------------------------------
FF_EFFECT_TYPES: dict[str, int] = {
    "FF_CONSTANT": ecodes.FF_CONSTANT,
    "FF_PERIODIC": ecodes.FF_PERIODIC,
    "FF_RAMP": ecodes.FF_RAMP,
    "FF_SPRING": ecodes.FF_SPRING,
    "FF_DAMPER": ecodes.FF_DAMPER,
    "FF_FRICTION": ecodes.FF_FRICTION,
    "FF_INERTIA": ecodes.FF_INERTIA,
    "FF_RUMBLE": ecodes.FF_RUMBLE,
}


def canon_ff_type(name: str) -> str:
    """Canonical FF_* name for an effect-type name ("spring" or "FF_SPRING").

    Raises ValueError naming the valid choices on anything else.
    """
    n = str(name).strip().upper()
    if not n.startswith("FF_"):
        n = "FF_" + n
    if n not in FF_EFFECT_TYPES:
        valid = ", ".join(k[3:].lower() for k in FF_EFFECT_TYPES)
        raise ValueError(f"unknown FF effect type {name!r}; expected one of {valid}")
    return n


def strip_ff(events: dict, drop: frozenset[int] | set[int]) -> dict:
    """Remove dropped effect-type codes from a VirtualSpec events dict.

    WHY: some game backends fault on specific PID effect types (the same class
    of bug as the 128-button crash). Not advertising a type means the kernel
    rejects the game's upload before it ever reaches the relay, so the filter
    must happen at advertisement time, not just upload time. Removing the last
    type removes EV_FF entirely (a device advertising EV_FF with no effects
    confuses enumerators).
    """
    if not drop or ecodes.EV_FF not in events:
        return events
    kept = [c for c in events[ecodes.EV_FF] if c not in drop]
    out = {k: v for k, v in events.items() if k != ecodes.EV_FF}
    if kept:
        out[ecodes.EV_FF] = kept
    return out


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
    "rescale", "clamp", "scale_gain", "boost_effect", "SIGNED16", "TRIGGER8", "HAT",
    "FF_EFFECT_TYPES", "canon_ff_type", "strip_ff",
]
