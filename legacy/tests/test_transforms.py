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


# ---------------------------------------------------------------------------
# Effect boosting (ffb_gain > 100).
# ---------------------------------------------------------------------------
from evdev import ff

from modes.base import boost_effect


def _effect(etype, union):
    return ff.Effect(etype, -1, 0x4000, ff.Trigger(0, 0), ff.Replay(1000, 0), union)


class TestBoostEffect:
    def test_constant_boosted_and_clamped(self):
        e = _effect(ecodes.FF_CONSTANT,
                    ff.EffectType(ff_constant_effect=ff.Constant(level=10000)))
        boost_effect(e, 150)
        assert e.u.ff_constant_effect.level == 15000
        boost_effect(e, 200)   # 30000 -> ok; boost again to prove clamping
        boost_effect(e, 200)
        assert e.u.ff_constant_effect.level == 32767

    def test_negative_constant_clamps_low(self):
        e = _effect(ecodes.FF_CONSTANT,
                    ff.EffectType(ff_constant_effect=ff.Constant(level=-30000)))
        boost_effect(e, 200)
        assert e.u.ff_constant_effect.level == -32768

    def test_periodic_magnitude(self):
        p = ff.Periodic(waveform=ecodes.FF_SINE, period=100, magnitude=8000,
                        offset=0, phase=0, envelope=ff.Envelope(0, 0, 0, 0))
        e = _effect(ecodes.FF_PERIODIC, ff.EffectType(ff_periodic_effect=p))
        boost_effect(e, 150)
        assert e.u.ff_periodic_effect.magnitude == 12000

    def test_ramp_levels(self):
        r = ff.Ramp(start_level=-1000, end_level=2000)
        e = _effect(ecodes.FF_RAMP, ff.EffectType(ff_ramp_effect=r))
        boost_effect(e, 150)
        assert e.u.ff_ramp_effect.start_level == -1500
        assert e.u.ff_ramp_effect.end_level == 3000

    def test_rumble_magnitudes_u16_clamped(self):
        r = ff.Rumble(strong_magnitude=0xC000, weak_magnitude=100)
        e = _effect(ecodes.FF_RUMBLE, ff.EffectType(ff_rumble_effect=r))
        boost_effect(e, 200)
        assert e.u.ff_rumble_effect.strong_magnitude == 0xFFFF
        assert e.u.ff_rumble_effect.weak_magnitude == 200

    def test_condition_effects_untouched(self):
        c = ff.Condition(right_saturation=1000, left_saturation=1000,
                         right_coeff=500, left_coeff=500,
                         deadband=0, center=0)
        e = _effect(ecodes.FF_SPRING, ff.EffectType(ff_condition_effect=(c, c)))
        boost_effect(e, 200)
        got = e.u.ff_condition_effect[0]
        assert got.right_saturation == 1000
        assert got.right_coeff == 500


class TestDescribeEffect:
    def test_constant_magnitude_traced(self):
        from mozaproxy import describe_effect
        e = _effect(ecodes.FF_CONSTANT,
                    ff.EffectType(ff_constant_effect=ff.Constant(level=12345)))
        out = describe_effect(e)
        assert "level=12345" in out

    def test_rumble_traced(self):
        from mozaproxy import describe_effect
        e = _effect(ecodes.FF_RUMBLE,
                    ff.EffectType(ff_rumble_effect=ff.Rumble(
                        strong_magnitude=1000, weak_magnitude=2000)))
        out = describe_effect(e)
        assert "strong=1000" in out and "weak=2000" in out
