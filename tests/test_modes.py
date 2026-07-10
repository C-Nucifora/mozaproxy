"""Tests for the three presentation modes and the registry.

All pure/hardware-free: they use the RealCaps fixture (see conftest.py).
"""
from __future__ import annotations

import pytest
from evdev import ecodes, ff

from modes import get_mode, list_modes
from modes.gamepad import GamepadMode
from modes.wheel import NormalizedMode, WheelMode


# ---------------------------------------------------------------------------
# WheelMode / Mode A
# ---------------------------------------------------------------------------
class TestWheelMode:
    def test_build_spec_mirrors_axes(self, real_caps):
        mode = WheelMode(buttons=24)
        spec = mode.build_spec(real_caps)

        abs_events = dict(spec.events[ecodes.EV_ABS])
        # All 10 real axes mirrored with identical ranges.
        assert len(abs_events) == len(real_caps.abs)
        for code, info in real_caps.abs.items():
            assert code in abs_events
            assert (abs_events[code].min, abs_events[code].max) == (info.min, info.max)
        # ABS_X stays unsigned 0..65535.
        assert (abs_events[ecodes.ABS_X].min, abs_events[ecodes.ABS_X].max) == (0, 65535)

    def test_build_spec_buttons(self, real_caps):
        mode = WheelMode(buttons=24)
        spec = mode.build_spec(real_caps)
        keys = spec.events[ecodes.EV_KEY]
        assert len(keys) == 24
        assert keys == [ecodes.BTN_JOYSTICK + i for i in range(24)]

    def test_build_spec_ff_and_ids(self, real_caps):
        mode = WheelMode()
        spec = mode.build_spec(real_caps)
        assert ecodes.EV_FF in spec.events
        assert spec.events[ecodes.EV_FF] == list(real_caps.ff)
        assert spec.product == 0x0002
        assert spec.vendor == 0x346E

    def test_map_input_abs_passthrough(self, real_caps):
        mode = WheelMode(buttons=24)
        mode.build_spec(real_caps)
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 12345)) == [
            (ecodes.EV_ABS, ecodes.ABS_X, 12345)
        ]

    def test_map_input_button_within_count_passes(self, real_caps):
        mode = WheelMode(buttons=24)
        mode.build_spec(real_caps)
        code = ecodes.BTN_JOYSTICK + 3
        assert list(mode.map_input(ecodes.EV_KEY, code, 1)) == [
            (ecodes.EV_KEY, code, 1)
        ]

    def test_map_input_button_above_count_dropped(self, real_caps):
        mode = WheelMode(buttons=24)
        mode.build_spec(real_caps)
        code = ecodes.BTN_JOYSTICK + 50
        assert list(mode.map_input(ecodes.EV_KEY, code, 1)) == []


# ---------------------------------------------------------------------------
# NormalizedMode / Mode C
# ---------------------------------------------------------------------------
class TestNormalizedMode:
    def test_build_spec_signed_axes_hats_untouched(self, real_caps):
        mode = NormalizedMode()
        spec = mode.build_spec(real_caps)
        abs_events = dict(spec.events[ecodes.EV_ABS])
        hats = (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y)
        for code, info in abs_events.items():
            if code in hats:
                assert (info.min, info.max) == (-1, 1)
            else:
                assert (info.min, info.max) == (-32768, 32767)

    def test_map_input_steering_rescaled(self, real_caps):
        mode = NormalizedMode()
        mode.build_spec(real_caps)
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 0)) == [
            (ecodes.EV_ABS, ecodes.ABS_X, -32768)
        ]
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 65535)) == [
            (ecodes.EV_ABS, ecodes.ABS_X, 32767)
        ]
        (_, _, mid), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 32768)
        assert abs(mid) <= 1

    def test_map_input_signed_pedal_passes_at_endpoints(self, real_caps):
        mode = NormalizedMode()
        mode.build_spec(real_caps)
        # ABS_Z is already signed -32768..32767 -> unchanged at endpoints.
        (_, _, lo), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_Z, -32768)
        (_, _, hi), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_Z, 32767)
        assert lo == -32768
        assert hi == 32767

    def test_map_input_hat_passthrough(self, real_caps):
        mode = NormalizedMode()
        mode.build_spec(real_caps)
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_HAT0X, 1)) == [
            (ecodes.EV_ABS, ecodes.ABS_HAT0X, 1)
        ]

    def test_map_input_buttons_filtered(self, real_caps):
        mode = NormalizedMode(buttons=24)
        mode.build_spec(real_caps)
        ok = ecodes.BTN_JOYSTICK + 2
        assert list(mode.map_input(ecodes.EV_KEY, ok, 1)) == [(ecodes.EV_KEY, ok, 1)]
        bad = ecodes.BTN_JOYSTICK + 50
        assert list(mode.map_input(ecodes.EV_KEY, bad, 1)) == []

    def test_steer_deadzone_center_zero_endpoints_full(self, real_caps):
        mode = NormalizedMode(steer_deadzone=0.1)
        mode.build_spec(real_caps)
        (_, _, mid), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 32768)
        assert mid == 0
        (_, _, lo), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 0)
        (_, _, hi), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 65535)
        assert lo == -32768
        assert hi == 32767

    def test_steer_deadzone_does_not_affect_pedal(self, real_caps):
        mode = NormalizedMode(steer_deadzone=0.1)
        mode.build_spec(real_caps)
        # A pedal near its center is NOT zeroed by the steering deadzone.
        (_, _, val), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_Z, 0)
        # 0 in -32768..32767 -> ~0 anyway, so probe a clearly off-center value
        # that a deadzone would have flattened.
        (_, _, off), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_Z, 1000)
        assert off != 0


# ---------------------------------------------------------------------------
# GamepadMode / Mode B
# ---------------------------------------------------------------------------
class TestGamepadMode:
    def test_build_spec_ids_and_axes(self, real_caps):
        mode = GamepadMode()
        spec = mode.build_spec(real_caps)
        assert spec.vendor == 0x045E
        assert spec.product == 0x028E
        abs_events = dict(spec.events[ecodes.EV_ABS])
        for code in (ecodes.ABS_X, ecodes.ABS_Z, ecodes.ABS_RZ,
                     ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
            assert code in abs_events
        assert (abs_events[ecodes.ABS_Z].min, abs_events[ecodes.ABS_Z].max) == (0, 255)
        assert (abs_events[ecodes.ABS_RZ].min, abs_events[ecodes.ABS_RZ].max) == (0, 255)

    def test_build_spec_buttons_and_ff(self, real_caps):
        mode = GamepadMode()
        spec = mode.build_spec(real_caps)
        keys = spec.events[ecodes.EV_KEY]
        assert len(keys) == 11
        assert ecodes.BTN_A in keys
        assert spec.events[ecodes.EV_FF] == [ecodes.FF_RUMBLE]

    def test_map_input_steering(self, real_caps):
        mode = GamepadMode()
        mode.build_spec(real_caps)
        (etype, code, val), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 65535)
        assert (etype, code) == (ecodes.EV_ABS, ecodes.ABS_X)
        assert val == 32767

    def test_map_input_throttle_to_rz(self, real_caps):
        mode = GamepadMode()
        mode.build_spec(real_caps)
        # default throttle_src = ABS_Z -> ABS_RZ in 0..255.
        (etype, code, val), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_Z, 32767)
        assert (etype, code) == (ecodes.EV_ABS, ecodes.ABS_RZ)
        assert val == 255

    def test_map_input_brake_to_z(self, real_caps):
        mode = GamepadMode()
        mode.build_spec(real_caps)
        # default brake_src = ABS_RZ -> ABS_Z in 0..255.
        (etype, code, val), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_RZ, 32767)
        assert (etype, code) == (ecodes.EV_ABS, ecodes.ABS_Z)
        assert val == 255

    def test_map_input_unmapped_axis_dropped(self, real_caps):
        mode = GamepadMode()
        mode.build_spec(real_caps)
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_RUDDER, 100)) == []

    def test_map_input_button_maps_to_first_pad_button(self, real_caps):
        mode = GamepadMode()
        mode.build_spec(real_caps)
        (etype, code, val), = mode.map_input(ecodes.EV_KEY, ecodes.BTN_JOYSTICK, 1)
        assert (etype, code, val) == (ecodes.EV_KEY, ecodes.BTN_A, 1)

    def test_map_input_hat_passthrough(self, real_caps):
        mode = GamepadMode()
        mode.build_spec(real_caps)
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_HAT0X, -1)) == [
            (ecodes.EV_ABS, ecodes.ABS_HAT0X, -1)
        ]

    def test_translate_rumble_to_periodic(self):
        mode = GamepadMode()
        eff = ff.Effect(
            ecodes.FF_RUMBLE, 7, 0,
            ff.Trigger(0, 0),
            ff.Replay(200, 0),
            ff.EffectType(ff_rumble_effect=ff.Rumble(0xC000, 0x8000)),
        )
        out = mode.translate_effect(eff)
        assert out is not None
        assert out.type == ecodes.FF_PERIODIC
        assert out.id == 7
        assert out.u.ff_periodic_effect.magnitude > 0

    def test_translate_non_rumble_unchanged(self):
        mode = GamepadMode()
        eff = ff.Effect(
            ecodes.FF_CONSTANT, 3, 0,
            ff.Trigger(0, 0),
            ff.Replay(100, 0),
            ff.EffectType(ff_constant_effect=ff.Constant(0x4000, ff.Envelope(0, 0, 0, 0))),
        )
        out = mode.translate_effect(eff)
        assert out is eff


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class TestRegistry:
    @pytest.mark.parametrize("sel", ["A", "a", "wheel"])
    def test_wheel_selectors(self, sel):
        assert type(get_mode(sel)) is WheelMode

    @pytest.mark.parametrize("sel", ["C", "normalized", "norm"])
    def test_normalized_selectors(self, sel):
        assert type(get_mode(sel)) is NormalizedMode

    @pytest.mark.parametrize("sel", ["B", "gamepad", "xinput", "pad"])
    def test_gamepad_selectors(self, sel):
        assert type(get_mode(sel)) is GamepadMode

    def test_unknown_selector_raises(self):
        with pytest.raises(ValueError):
            get_mode("zzz")

    def test_buttons_override(self, real_caps):
        mode = get_mode("A", buttons=32)
        spec = mode.build_spec(real_caps)
        assert len(spec.events[ecodes.EV_KEY]) == 32

    def test_list_modes(self):
        pairs = list_modes()
        selectors = [s for s, _ in pairs]
        assert "A" in selectors and "B" in selectors and "C" in selectors
