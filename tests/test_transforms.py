"""Tests for the pure axis math in modes.base.rescale."""
from __future__ import annotations

from modes.base import rescale


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
