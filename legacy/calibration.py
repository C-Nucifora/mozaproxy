"""
calibration - interactive discovery of which real ABS axis is which.

WHY this exists:
  The MOZA base exposes a pile of anonymous ABS axes and nothing in the
  descriptor says which one carries the throttle vs. the brake. Worse, some
  pedal sets rest at range MAX and press toward MIN — mapped naively onto a
  virtual gamepad trigger they read fully pressed at rest. The only reliable
  oracle is the person holding the hardware: ask them to move one control at
  a time, watch which axis actually travels (TravelTracker), and compare its
  rest value against the travelled extreme to decide whether the daemon must
  invert it (detect_invert).

WHY it is structured this way:
  Everything except the tiny _sample() helper is pure. TravelTracker is fed
  (code, value) pairs, detect_invert is arithmetic, and interactive_calibrate
  takes injectable prompt/echo callables plus a duck-typed device — so the
  whole flow unit-tests with no hardware and no evdev device I/O. Only
  _sample() touches select() and the clock; tests monkeypatch it.

This module imports nothing from profiledb or mozactl: it sits below both
(mozactl drives it; profiledb persists what it returns) and is built in
parallel with them.
"""
from __future__ import annotations

import select
import time
from dataclasses import dataclass

from evdev import ecodes

# Hats are digital dpads (-1..1); a stray dpad tap would otherwise register as
# 100% travel and outshine every analog axis, so dominant() always drops them.
_HAT_CODES = frozenset(range(ecodes.ABS_HAT0X, ecodes.ABS_HAT3Y + 1))

# Required steps get the first try plus this many retries before we abort.
_REQUIRED_RETRIES = 3


class TravelTracker:
    """Track observed min/max per ABS code and rank axes by normalized travel.

    Travel is (observed_hi - observed_lo) / (range_max - range_min): the
    fraction of an axis's full range the user actually swept during a sampling
    window. The axis being calibrated sweeps ~1.0 while everything else sits
    near 0, which is what makes "move only the throttle" detectable.
    """

    def __init__(self, ranges: dict[int, tuple[int, int]]) -> None:
        self._ranges = dict(ranges)
        self._seen: dict[int, tuple[int, int]] = {}  # code -> (lo, hi) observed

    def feed(self, code: int, value: int) -> None:
        seen = self._seen.get(code)
        if seen is None:
            self._seen[code] = (value, value)
        else:
            lo, hi = seen
            self._seen[code] = (min(lo, value), max(hi, value))

    def observed(self, code: int) -> tuple[int, int] | None:
        """(lo, hi) actually seen for `code`, or None if never fed."""
        return self._seen.get(code)

    def travel(self, code: int) -> float:
        seen = self._seen.get(code)
        rng = self._ranges.get(code)
        if seen is None or rng is None:
            return 0.0
        width = rng[1] - rng[0]
        if width == 0:
            return 0.0
        lo, hi = seen
        t = (hi - lo) / width
        return 0.0 if t < 0.0 else 1.0 if t > 1.0 else t

    def dominant(self, exclude: set[int] = frozenset(),
                 min_travel: float = 0.25) -> int | None:
        """The ABS code with the largest travel, or None if nothing moved enough.

        Hats are always excluded on top of the caller's set. Ties go to the
        lowest code (sorted iteration + strict >) so results are deterministic.
        """
        best_code = None
        best_travel = 0.0
        for code in sorted(self._seen):
            if code in exclude or code in _HAT_CODES:
                continue
            t = self.travel(code)
            if t >= min_travel and t > best_travel:
                best_code, best_travel = code, t
        return best_code


def source_name(code: int) -> str:
    """Canonical evdev name for an ABS code, e.g. ecodes.ABS_Z -> "ABS_Z"."""
    name = ecodes.ABS.get(code)
    if name is None:
        raise ValueError(f"not an ABS code: {code}")
    # ecodes tables may alias one code to several names; the first is canonical.
    return name if isinstance(name, str) else name[0]


def detect_invert(rest: int, lo: int, hi: int, rng: tuple[int, int]) -> bool:
    """True if a pedal presses toward range-min (virtual trigger needs invert).

    The pressed extreme is whichever observed endpoint lies farther from the
    rest value — a pedal rests at one end and is pressed toward the other.
    Virtual triggers expect press = increasing value, so a pedal whose pressed
    extreme sits on the range-min side must be inverted (it RESTS at max, and
    without invert the trigger would read fully pressed with feet off).
    """
    pressed = lo if abs(lo - rest) >= abs(hi - rest) else hi
    rmin, rmax = rng
    return abs(pressed - rmin) < abs(pressed - rmax)


def _sample(dev, tracker: TravelTracker, seconds: float) -> None:
    """Feed EV_ABS events from `dev` into `tracker` for `seconds` of wall time.

    The single impure spot in the flow: select() on dev.fd with short timeouts
    so the window ends on schedule even if the user never touches anything.
    Tests monkeypatch this whole function to inject scripted events.
    """
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        ready, _, _ = select.select([dev.fd], [], [], min(0.1, remaining))
        if not ready:
            continue
        try:
            for event in dev.read():
                if event.type == ecodes.EV_ABS:
                    tracker.feed(event.code, event.value)
        except BlockingIOError:
            # Non-blocking node drained between select() and read(); just poll on.
            pass


@dataclass(frozen=True)
class _Step:
    axis: str
    instruction: str
    pedal: bool     # pedals get invert detection; steering does not
    required: bool  # abort the whole run if undetected; else skip silently


_STEPS: tuple[_Step, ...] = (
    _Step("steering",
          "Turn the wheel fully left, then fully right, then centre it.",
          pedal=False, required=True),
    _Step("throttle",
          "Press the throttle pedal all the way down, then release it.",
          pedal=True, required=True),
    _Step("brake",
          "Press the brake pedal all the way down, then release it.",
          pedal=True, required=True),
    _Step("clutch",
          "Press the clutch pedal all the way down, then release it "
          "(no clutch? just press Enter and leave everything still to skip).",
          pedal=True, required=False),
)


def interactive_calibrate(dev, *, prompt=input, echo=print,
                          sample_seconds: float = 4.0) -> dict[str, dict] | None:
    """Walk the user through assigning steering/throttle/brake/clutch.

    `dev` is an (ungrabbed) evdev.InputDevice-like object; the daemon must be
    stopped so its events reach us. Returns a mapping shaped for the
    calibration TOML, e.g.::

        {"steering": {"source": "ABS_X"},
         "throttle": {"source": "ABS_Z", "invert": False},
         "brake":    {"source": "ABS_RZ", "invert": True}}

    or None if a required axis could not be detected after retries.
    """
    ranges: dict[int, tuple[int, int]] = {}
    for code, info in dev.capabilities(absinfo=True).get(ecodes.EV_ABS, []):
        ranges[code] = (info.min, info.max)

    assigned: dict[str, dict] = {}
    used: set[int] = set()

    for step in _STEPS:
        attempts = 1 + (_REQUIRED_RETRIES if step.required else 0)
        code = None
        tracker = TravelTracker(ranges)
        rests: dict[int, int] = {}
        for attempt in range(attempts):
            echo(f"[{step.axis}] {step.instruction}")
            prompt(f"Press Enter, then move the {step.axis} within "
                   f"{sample_seconds:g}s... ")
            # Rest values must be captured now — after Enter, before movement —
            # so detect_invert compares the sweep against a true hands-off value.
            rests = {c: dev.absinfo(c).value for c in ranges}
            tracker = TravelTracker(ranges)
            _sample(dev, tracker, sample_seconds)
            code = tracker.dominant(exclude=used)
            if code is not None:
                break
            if step.required and attempt < attempts - 1:
                echo(f"No axis moved enough — try again "
                     f"({attempts - 1 - attempt} retries left).")

        if code is None:
            if not step.required:
                continue  # clutch is optional: nothing moved, nothing assigned
            echo(f"Could not detect the {step.axis} axis; aborting.")
            return None

        used.add(code)
        entry: dict = {"source": source_name(code)}
        if step.pedal:
            lo, hi = tracker.observed(code)  # type: ignore[misc]  # code was fed
            entry["invert"] = detect_invert(rests[code], lo, hi, ranges[code])
        assigned[step.axis] = entry
        echo(f"  -> {step.axis}: {entry['source']}"
             + ("  (inverted)" if entry.get("invert") else ""))

    echo("Detected mapping:")
    for axis, entry in assigned.items():
        echo(f"  {axis:<9} {entry['source']}"
             + ("  (inverted)" if entry.get("invert") else ""))
    return assigned


__all__ = ["TravelTracker", "source_name", "detect_invert", "interactive_calibrate"]
