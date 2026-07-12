"""
modes - presentation modes ("faces") the daemon can wear.

A mode decides what the virtual device looks like and how real events map onto
it. Pick one with `--mode` (mozaproxy.py) or `mozactl start --mode ...`:

  A / wheel        direct passthrough wheel (default; fixes FH5 enumeration crash)
  C / normalized   consistent signed axes (fixes games that read axes as binary)
  B / gamepad      Xbox 360 / XInput pad (controller-only + arcade titles)

`get_mode(key, ...)` resolves a selector to a constructed Mode. Overrides that
are left None fall back to the mode's own defaults. The calibration parameters
(steer/throttle/brake/clutch src + invert, steering deadzone in mode B) only
affect the gamepad face; wheel faces mirror the real axis codes 1:1 so there is
nothing to remap and they silently ignore them.
"""
from __future__ import annotations

from .base import Mode
from .gamepad import GamepadMode
from .wheel import NormalizedMode, WheelMode

# Ordered for help/listing: (selector aliases, class, one-line help).
MODES: list[tuple[tuple[str, ...], type[Mode], str]] = [
    (("a", "wheel"), WheelMode,
     "Wheel — direct passthrough (fixes FH5 crash)"),
    (("c", "normalized", "norm"), NormalizedMode,
     "Normalized wheel — consistent signed axes (fixes binary-axis games)"),
    (("b", "gamepad", "xinput", "pad"), GamepadMode,
     "Gamepad — Xbox 360 / XInput (controller-only & arcade titles)"),
]


def _wheel_overrides(buttons, name, vendor, product) -> dict:
    """Only pass overrides the user actually set; None means 'mode default'."""
    o: dict = {}
    if buttons is not None:
        o["buttons"] = buttons
    if name is not None:
        o["name"] = name
    if vendor is not None:
        o["vendor"] = vendor
    if product is not None:
        o["product"] = product
    return o


def get_mode(key: str, *, buttons: int | None = None, name: str | None = None,
             vendor: int | None = None, product: int | None = None,
             steer_deadzone: float = 0.0,
             axis_range: tuple[int, int] | None = None,
             steer_src: int | None = None, throttle_src: int | None = None,
             brake_src: int | None = None, clutch_src: int | None = None,
             steer_invert: bool = False, throttle_invert: bool = False,
             brake_invert: bool = False, clutch_invert: bool = False) -> Mode:
    """Resolve a mode selector (letter or alias) to a constructed Mode.

    The src/invert parameters exist for the gamepad face, which remaps real
    axes onto pad axes. Wheel faces (A/C) mirror the real axis codes 1:1 —
    there is nothing to remap — so they silently ignore src/invert here.

    Raises ValueError on an unknown selector.
    """
    k = str(key).strip().lower()
    if k in ("a", "wheel"):
        return WheelMode(**_wheel_overrides(buttons, name, vendor, product))
    if k in ("c", "normalized", "norm"):
        co: dict = _wheel_overrides(buttons, name, vendor, product)
        if axis_range is not None:
            # Uniform target range for all non-hat axes; (0, 32767) dodges
            # sign-handling bugs in picky HID stacks (see NormalizedMode).
            co["axis_range"] = axis_range
        return NormalizedMode(steer_deadzone=steer_deadzone or 0.0, **co)
    if k in ("b", "gamepad", "xinput", "pad"):
        # Gamepad has its own XInput ids; only name/vendor/product overrides apply.
        go: dict = {}
        if name is not None:
            go["name"] = name
        if vendor is not None:
            go["vendor"] = vendor
        if product is not None:
            go["product"] = product
        # Only pass source overrides that were actually set so GamepadMode's
        # own calibratable defaults hold for the rest.
        if steer_src is not None:
            go["steer_src"] = steer_src
        if throttle_src is not None:
            go["throttle_src"] = throttle_src
        if brake_src is not None:
            go["brake_src"] = brake_src
        if clutch_src is not None:
            go["clutch_src"] = clutch_src
        return GamepadMode(steer_deadzone=steer_deadzone,
                           steer_invert=steer_invert,
                           throttle_invert=throttle_invert,
                           brake_invert=brake_invert,
                           clutch_invert=clutch_invert,
                           **go)
    valid = ", ".join(a[0] for a, _, _ in MODES)
    raise ValueError(f"unknown mode {key!r}; valid selectors: {valid} (or aliases)")


def list_modes() -> list[tuple[str, str]]:
    """(selector, help) pairs for CLI display."""
    return [(aliases[0].upper(), help) for aliases, _, help in MODES]


__all__ = ["Mode", "WheelMode", "NormalizedMode", "GamepadMode",
           "get_mode", "list_modes", "MODES"]
