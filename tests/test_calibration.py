"""Tests for the interactive axis calibrator.

All pure/hardware-free: interactive_calibrate is driven with a duck-typed
FakeDevice, scripted prompt/echo callables, and a monkeypatched _sample that
feeds scripted per-window events instead of select()ing on a real fd.
"""
from __future__ import annotations

import pytest
from evdev import AbsInfo, ecodes

import calibration
from calibration import (
    TravelTracker,
    detect_invert,
    interactive_calibrate,
    source_name,
)

SIGNED = (-32768, 32767)
UNSIGNED = (0, 65535)


# ---------------------------------------------------------------------------
# TravelTracker
# ---------------------------------------------------------------------------
class TestTravelTracker:
    def test_travel_is_observed_span_over_range_width(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100)})
        t.feed(ecodes.ABS_Z, 20)
        t.feed(ecodes.ABS_Z, 70)
        assert t.travel(ecodes.ABS_Z) == pytest.approx(0.5)

    def test_travel_unseen_code_is_zero(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100)})
        assert t.travel(ecodes.ABS_Z) == 0.0

    def test_travel_single_sample_is_zero(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100)})
        t.feed(ecodes.ABS_Z, 50)
        assert t.travel(ecodes.ABS_Z) == 0.0

    def test_travel_code_without_range_is_zero(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100)})
        t.feed(ecodes.ABS_RZ, 0)
        t.feed(ecodes.ABS_RZ, 100)
        assert t.travel(ecodes.ABS_RZ) == 0.0

    def test_travel_zero_width_range_guarded(self):
        t = TravelTracker({ecodes.ABS_Z: (7, 7)})
        t.feed(ecodes.ABS_Z, 7)
        t.feed(ecodes.ABS_Z, 7)
        assert t.travel(ecodes.ABS_Z) == 0.0

    def test_travel_clamped_to_one_on_out_of_range_values(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100)})
        t.feed(ecodes.ABS_Z, -50)
        t.feed(ecodes.ABS_Z, 150)
        assert t.travel(ecodes.ABS_Z) == 1.0

    def test_observed_tracks_extremes(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100)})
        t.feed(ecodes.ABS_Z, 40)
        t.feed(ecodes.ABS_Z, 90)
        t.feed(ecodes.ABS_Z, 10)
        assert t.observed(ecodes.ABS_Z) == (10, 90)
        assert t.observed(ecodes.ABS_RZ) is None

    def test_dominant_picks_largest_travel(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100), ecodes.ABS_RZ: (0, 100)})
        t.feed(ecodes.ABS_Z, 0)
        t.feed(ecodes.ABS_Z, 100)
        t.feed(ecodes.ABS_RZ, 0)
        t.feed(ecodes.ABS_RZ, 40)
        assert t.dominant() == ecodes.ABS_Z

    def test_dominant_none_when_below_min_travel(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100)})
        t.feed(ecodes.ABS_Z, 0)
        t.feed(ecodes.ABS_Z, 20)  # 0.20 < default 0.25
        assert t.dominant() is None

    def test_dominant_min_travel_boundary_inclusive(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100)})
        t.feed(ecodes.ABS_Z, 0)
        t.feed(ecodes.ABS_Z, 25)
        assert t.dominant() == ecodes.ABS_Z
        assert t.dominant(min_travel=0.5) is None

    def test_dominant_respects_exclude_set(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100), ecodes.ABS_RZ: (0, 100)})
        t.feed(ecodes.ABS_Z, 0)
        t.feed(ecodes.ABS_Z, 100)
        t.feed(ecodes.ABS_RZ, 0)
        t.feed(ecodes.ABS_RZ, 60)
        assert t.dominant(exclude={ecodes.ABS_Z}) == ecodes.ABS_RZ

    def test_dominant_always_excludes_hats(self):
        ranges = {code: (-1, 1)
                  for code in range(ecodes.ABS_HAT0X, ecodes.ABS_HAT3Y + 1)}
        ranges[ecodes.ABS_Z] = (0, 100)
        t = TravelTracker(ranges)
        for code in range(ecodes.ABS_HAT0X, ecodes.ABS_HAT3Y + 1):
            t.feed(code, -1)
            t.feed(code, 1)  # 100% travel, still never eligible
        assert t.dominant() is None
        t.feed(ecodes.ABS_Z, 0)
        t.feed(ecodes.ABS_Z, 100)
        assert t.dominant() == ecodes.ABS_Z

    def test_dominant_tie_goes_to_lowest_code(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100), ecodes.ABS_RZ: (0, 100)})
        t.feed(ecodes.ABS_RZ, 0)
        t.feed(ecodes.ABS_RZ, 80)
        t.feed(ecodes.ABS_Z, 0)
        t.feed(ecodes.ABS_Z, 80)
        assert ecodes.ABS_Z < ecodes.ABS_RZ
        assert t.dominant() == ecodes.ABS_Z

    def test_dominant_none_when_nothing_fed(self):
        t = TravelTracker({ecodes.ABS_Z: (0, 100)})
        assert t.dominant() is None


# ---------------------------------------------------------------------------
# detect_invert
# ---------------------------------------------------------------------------
class TestDetectInvert:
    def test_rest_at_min_pressed_toward_max_no_invert(self):
        # Normal pedal: rests at range-min, press increases the value.
        assert detect_invert(-32768, -32768, 32767, SIGNED) is False

    def test_rest_at_max_pressed_toward_min_inverts(self):
        # The problem child: rests at range-max, press decreases the value.
        assert detect_invert(32767, -32768, 32767, SIGNED) is True

    def test_centered_rest_pressed_toward_min_inverts(self):
        assert detect_invert(0, -30000, 500, SIGNED) is True

    def test_centered_rest_pressed_toward_max_no_invert(self):
        assert detect_invert(0, -500, 30000, SIGNED) is False

    def test_partial_travel_near_rest_end_still_detected(self):
        # Rest near max, sweep never reaches the far endpoint: pressed extreme
        # is the observed LO, which sits on the min side.
        assert detect_invert(32000, -20000, 32000, SIGNED) is True


# ---------------------------------------------------------------------------
# source_name
# ---------------------------------------------------------------------------
class TestSourceName:
    def test_known_codes(self):
        assert source_name(ecodes.ABS_X) == "ABS_X"
        assert source_name(ecodes.ABS_Z) == "ABS_Z"
        assert source_name(ecodes.ABS_RZ) == "ABS_RZ"

    def test_unknown_code_raises(self):
        with pytest.raises(ValueError):
            source_name(0x7FFF)


# ---------------------------------------------------------------------------
# interactive_calibrate, driven hardware-free.
# ---------------------------------------------------------------------------
class FakeDevice:
    """Duck-typed stand-in for evdev.InputDevice.

    read()/fd exist only so the object satisfies the real _sample; every test
    monkeypatches _sample, so they are never exercised.
    """

    def __init__(self, ranges: dict[int, tuple[int, int]],
                 rests: dict[int, int]):
        self._ranges = ranges
        self._rests = rests
        self.fd = 42

    def _absinfo(self, code: int) -> AbsInfo:
        lo, hi = self._ranges[code]
        return AbsInfo(value=self._rests.get(code, 0), min=lo, max=hi,
                       fuzz=0, flat=0, resolution=0)

    def capabilities(self, absinfo: bool = False):
        assert absinfo, "calibration must ask for absinfo=True"
        return {ecodes.EV_ABS: [(c, self._absinfo(c)) for c in self._ranges]}

    def absinfo(self, code: int) -> AbsInfo:
        return self._absinfo(code)

    def read(self):
        raise AssertionError("_sample was not monkeypatched")


def scripted_sampler(windows: list[list[tuple[int, int]]]):
    """A _sample replacement feeding one scripted event list per call."""
    remaining = list(windows)

    def fake_sample(dev, tracker, seconds):
        if remaining:
            for code, value in remaining.pop(0):
                tracker.feed(code, value)

    return fake_sample


def sweep(code: int, lo: int, hi: int) -> list[tuple[int, int]]:
    return [(code, lo), (code, hi)]


@pytest.fixture
def device() -> FakeDevice:
    ranges = {
        ecodes.ABS_X: UNSIGNED,    # steering
        ecodes.ABS_Z: SIGNED,      # throttle, rests at min
        ecodes.ABS_RZ: SIGNED,     # brake, rests at MAX (needs invert)
        ecodes.ABS_Y: SIGNED,      # clutch, rests at min
        ecodes.ABS_HAT0X: (-1, 1),
        ecodes.ABS_HAT0Y: (-1, 1),
    }
    rests = {
        ecodes.ABS_X: 32768,
        ecodes.ABS_Z: -32768,
        ecodes.ABS_RZ: 32767,
        ecodes.ABS_Y: -32768,
    }
    return FakeDevice(ranges, rests)


def run(monkeypatch, device, windows, prompts=None, echoes=None):
    monkeypatch.setattr(calibration, "_sample", scripted_sampler(windows))
    prompts = prompts if prompts is not None else []
    echoes = echoes if echoes is not None else []
    return interactive_calibrate(
        device,
        prompt=lambda msg="": (prompts.append(msg), "")[1],
        echo=lambda msg="": echoes.append(msg),
        sample_seconds=0.01,
    )


class TestInteractiveCalibrate:
    def test_happy_path_all_four_axes(self, monkeypatch, device):
        windows = [
            sweep(ecodes.ABS_X, 0, 65535),
            sweep(ecodes.ABS_Z, -32768, 32767),
            sweep(ecodes.ABS_RZ, 32767, -32768),
            sweep(ecodes.ABS_Y, -32768, 32767),
        ]
        result = run(monkeypatch, device, windows)
        assert result == {
            "steering": {"source": "ABS_X"},
            "throttle": {"source": "ABS_Z", "invert": False},
            "brake": {"source": "ABS_RZ", "invert": True},
            "clutch": {"source": "ABS_Y", "invert": False},
        }

    def test_steering_entry_has_no_invert_key(self, monkeypatch, device):
        windows = [
            sweep(ecodes.ABS_X, 0, 65535),
            sweep(ecodes.ABS_Z, -32768, 32767),
            sweep(ecodes.ABS_RZ, 32767, -32768),
            [],
        ]
        result = run(monkeypatch, device, windows)
        assert set(result["steering"]) == {"source"}

    def test_clutch_skipped_silently_when_still(self, monkeypatch, device):
        windows = [
            sweep(ecodes.ABS_X, 0, 65535),
            sweep(ecodes.ABS_Z, -32768, 32767),
            sweep(ecodes.ABS_RZ, 32767, -32768),
            [],  # nothing moves during the clutch window
        ]
        prompts: list[str] = []
        result = run(monkeypatch, device, windows, prompts=prompts)
        assert result is not None
        assert "clutch" not in result
        assert set(result) == {"steering", "throttle", "brake"}
        # One prompt per step: the clutch got exactly one window, no retries.
        assert len(prompts) == 4

    def test_assigned_codes_excluded_from_later_steps(self, monkeypatch, device):
        # During the brake window the throttle axis also sweeps fully (foot
        # slipped); the already-assigned ABS_Z must not win again.
        windows = [
            sweep(ecodes.ABS_X, 0, 65535),
            sweep(ecodes.ABS_Z, -32768, 32767),
            sweep(ecodes.ABS_Z, -32768, 32767) + sweep(ecodes.ABS_RZ, 32767, 0),
            [],
        ]
        result = run(monkeypatch, device, windows)
        assert result["brake"]["source"] == "ABS_RZ"

    def test_hat_chatter_never_wins_a_step(self, monkeypatch, device):
        windows = [
            sweep(ecodes.ABS_HAT0X, -1, 1) + sweep(ecodes.ABS_X, 0, 65535),
            sweep(ecodes.ABS_Z, -32768, 32767),
            sweep(ecodes.ABS_RZ, 32767, -32768),
            [],
        ]
        result = run(monkeypatch, device, windows)
        assert result["steering"]["source"] == "ABS_X"

    def test_retry_then_success(self, monkeypatch, device):
        windows = [
            sweep(ecodes.ABS_X, 0, 65535),
            [(ecodes.ABS_Z, -32768), (ecodes.ABS_Z, -30000)],  # too little travel
            sweep(ecodes.ABS_Z, -32768, 32767),                # retry succeeds
            sweep(ecodes.ABS_RZ, 32767, -32768),
            [],
        ]
        prompts: list[str] = []
        echoes: list[str] = []
        result = run(monkeypatch, device, windows, prompts=prompts, echoes=echoes)
        assert result is not None
        assert result["throttle"] == {"source": "ABS_Z", "invert": False}
        assert len(prompts) == 5  # steering + 2 throttle attempts + brake + clutch
        assert any("try again" in e for e in echoes)

    def test_retries_exhausted_returns_none(self, monkeypatch, device):
        # Steering detected, then the throttle never moves: 1 try + 3 retries
        # all come up empty and the run aborts.
        windows = [sweep(ecodes.ABS_X, 0, 65535)] + [[]] * 4
        prompts: list[str] = []
        result = run(monkeypatch, device, windows, prompts=prompts)
        assert result is None
        assert len(prompts) == 5  # steering + 4 throttle attempts, then abort

    def test_summary_echoed_before_return(self, monkeypatch, device):
        windows = [
            sweep(ecodes.ABS_X, 0, 65535),
            sweep(ecodes.ABS_Z, -32768, 32767),
            sweep(ecodes.ABS_RZ, 32767, -32768),
            [],
        ]
        echoes: list[str] = []
        run(monkeypatch, device, windows, echoes=echoes)
        text = "\n".join(echoes)
        assert "ABS_X" in text and "ABS_Z" in text and "ABS_RZ" in text

    def test_no_imports_from_sibling_layers(self):
        # Locked layering rule: calibration must not import profiledb/mozactl.
        import calibration as mod
        for line in open(mod.__file__):
            stripped = line.strip()
            for forbidden in ("profiledb", "mozactl"):
                assert not stripped.startswith(f"import {forbidden}")
                assert not stripped.startswith(f"from {forbidden}")
