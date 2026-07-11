"""Tests for the pure axis math in modes.base (rescale, scale_gain)."""
from __future__ import annotations

from modes.base import rescale, scale_gain


def test_endpoints_exact():
    # Unsigned steering -> signed16.
    assert rescale(0, 0, 65535, -32768, 32767) == -32768
    assert rescale(65535, 0, 65535, -32768, 32767) == 32767
    # Midpoint maps to ~0 (allow +/-1).
    assert abs(rescale(32768, 0, 65535, -32768, 32767)) <= 1


def test_pedal_signed_to_trigger():
    assert rescale(-32768, -32768, 32767, 0, 255) == 0
    assert rescale(32767, -32768, 32767, 0, 255) == 255


def test_clamping():
    # Below smin clamps to dmin.
    assert rescale(-100, 0, 65535, -32768, 32767) == -32768
    # Above smax clamps to dmax.
    assert rescale(70000, 0, 65535, -32768, 32767) == 32767


def test_invert_swaps_endpoints():
    assert rescale(0, 0, 65535, -32768, 32767, invert=True) == 32767
    assert rescale(65535, 0, 65535, -32768, 32767, invert=True) == -32768


def test_deadzone_center_maps_to_center():
    # Exact center with a deadzone lands on the destination center.
    assert rescale(32768, 0, 65535, -32768, 32767, deadzone=0.1) == 0


def test_deadzone_does_not_shrink_output_range():
    # Endpoints STILL reach dmin/dmax despite the deadzone.
    assert rescale(0, 0, 65535, -32768, 32767, deadzone=0.1) == -32768
    assert rescale(65535, 0, 65535, -32768, 32767, deadzone=0.1) == 32767


def test_value_just_outside_deadzone_is_nonzero():
    # A value clearly past the deadzone edge produces a non-zero output.
    # deadzone 0.1 removes 10% of travel centered; 70% travel is well outside.
    out = rescale(int(0.70 * 65535), 0, 65535, -32768, 32767, deadzone=0.1)
    assert out != 0


def test_degenerate_range_returns_dmin():
    # smin == smax must not raise; returns dmin.
    assert rescale(500, 100, 100, -32768, 32767) == -32768


# ---------------------------------------------------------------------------
# scale_gain — the per-profile FFB gain clamp.
# ---------------------------------------------------------------------------
class TestScaleGain:
    def test_identity_at_100_percent(self):
        assert scale_gain(0, 100) == 0
        assert scale_gain(12345, 100) == 12345
        assert scale_gain(0xFFFF, 100) == 0xFFFF

    def test_zero_percent_silences(self):
        assert scale_gain(0xFFFF, 0) == 0
        assert scale_gain(1, 0) == 0
        assert scale_gain(0, 0) == 0

    def test_half_gain(self):
        assert scale_gain(0xFFFF, 50) == 0x7FFF
        assert scale_gain(40000, 50) == 20000

    def test_floor_division(self):
        assert scale_gain(99, 50) == 49
        assert scale_gain(1, 99) == 0

    def test_negative_value_clamps_to_zero(self):
        assert scale_gain(-1, 100) == 0
        assert scale_gain(-0xFFFF, 50) == 0

    def test_overflow_clamps_to_16bit_max(self):
        assert scale_gain(0xFFFF + 1000, 100) == 0xFFFF
        assert scale_gain(0x20000, 75) == 0xFFFF


# ---------------------------------------------------------------------------
# FF effect-type helpers (Phase 4: per-profile effect filtering).
# ---------------------------------------------------------------------------
from evdev import ecodes

from modes.base import FF_EFFECT_TYPES, canon_ff_type, strip_ff


class TestCanonFfType:
    def test_shorthand_and_canonical_and_case(self):
        assert canon_ff_type("spring") == "FF_SPRING"
        assert canon_ff_type("FF_SPRING") == "FF_SPRING"
        assert canon_ff_type("Rumble") == "FF_RUMBLE"
        assert canon_ff_type(" ff_damper ") == "FF_DAMPER"

    def test_unknown_raises_with_choices(self):
        import pytest
        with pytest.raises(ValueError, match="spring"):
            canon_ff_type("wobble")

    def test_every_name_maps_to_its_ecode(self):
        for name, code in FF_EFFECT_TYPES.items():
            assert getattr(ecodes, name) == code
            assert canon_ff_type(name) == name


class TestStripFf:
    def _events(self):
        return {
            ecodes.EV_ABS: [(ecodes.ABS_X, None)],
            ecodes.EV_KEY: [ecodes.BTN_JOYSTICK],
            ecodes.EV_FF: [ecodes.FF_CONSTANT, ecodes.FF_SPRING, ecodes.FF_DAMPER],
        }

    def test_drops_only_listed_types(self):
        out = strip_ff(self._events(), {ecodes.FF_SPRING})
        assert out[ecodes.EV_FF] == [ecodes.FF_CONSTANT, ecodes.FF_DAMPER]
        # Non-FF sections are untouched.
        assert out[ecodes.EV_ABS] == [(ecodes.ABS_X, None)]
        assert out[ecodes.EV_KEY] == [ecodes.BTN_JOYSTICK]

    def test_dropping_everything_removes_ev_ff_entirely(self):
        out = strip_ff(self._events(), {ecodes.FF_CONSTANT, ecodes.FF_SPRING,
                                        ecodes.FF_DAMPER})
        assert ecodes.EV_FF not in out

    def test_empty_drop_is_identity(self):
        ev = self._events()
        assert strip_ff(ev, frozenset()) is ev

    def test_no_ff_section_is_identity(self):
        ev = {ecodes.EV_ABS: []}
        assert strip_ff(ev, {ecodes.FF_SPRING}) is ev
