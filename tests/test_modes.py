"""Tests for the three presentation modes and the registry.

All pure/hardware-free: they use the RealCaps fixture (see conftest.py).
"""
from __future__ import annotations

import types

import pytest
from evdev import ecodes, ff

from modes import get_mode, list_modes
from modes.base import scale_gain
from modes.gamepad import GamepadMode
from modes.wheel import NormalizedMode, WheelMode
from mozaproxy import Proxy

from conftest import make_real_caps


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
        # The first 24 of the base's OWN codes: the 16-button 0x120 block plus
        # the first 8 of the upper 0x270 block — NOT a synthetic contiguous run.
        assert keys == list(range(0x120, 0x130)) + list(range(0x270, 0x278))

    def test_build_spec_exposes_all_real_buttons_when_uncapped(self, real_caps):
        mode = WheelMode(buttons=128)
        spec = mode.build_spec(real_caps)
        # Every real button code is exposed, none invented, none from the
        # 0x130 gamepad block the hardware skips.
        assert spec.events[ecodes.EV_KEY] == sorted(real_caps.keys)
        assert all(0x130 <= c <= 0x13f for c in spec.events[ecodes.EV_KEY]) is False

    def test_map_input_upper_block_button_passes_when_exposed(self, real_caps):
        # A paddle/wheel button in the upper 0x270 block must pass through once
        # exposed — the exact regression that broke JDM's paddles/clutch.
        mode = WheelMode(buttons=128)
        mode.build_spec(real_caps)
        code = 0x275
        assert list(mode.map_input(ecodes.EV_KEY, code, 1)) == [
            (ecodes.EV_KEY, code, 1)
        ]

    def test_map_input_upper_block_button_dropped_when_capped(self, real_caps):
        mode = WheelMode(buttons=24)
        mode.build_spec(real_caps)
        # 0x2df is a real button but beyond the 24-cap, so it is dropped.
        assert list(mode.map_input(ecodes.EV_KEY, 0x2DF, 1)) == []

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


# ---------------------------------------------------------------------------
# GamepadMode calibration parameters (Phase 3): per-axis inverts + steering
# deadzone applied on top of the source->pad rescale.
# ---------------------------------------------------------------------------
class TestGamepadCalibration:
    def test_steer_invert_flips_endpoints(self, real_caps):
        mode = GamepadMode(steer_invert=True)
        mode.build_spec(real_caps)
        (_, _, lo), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 0)
        (_, _, hi), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 65535)
        assert lo == 32767
        assert hi == -32768

    def test_throttle_invert(self, real_caps):
        mode = GamepadMode(throttle_invert=True)
        mode.build_spec(real_caps)
        # Inverted pedal: rest at source MAX reads released, source MIN = full.
        (_, code, released), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_Z, 32767)
        (_, _, pressed), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_Z, -32768)
        assert code == ecodes.ABS_RZ
        assert released == 0
        assert pressed == 255

    def test_brake_invert(self, real_caps):
        mode = GamepadMode(brake_invert=True)
        mode.build_spec(real_caps)
        (_, code, released), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_RZ, 32767)
        (_, _, pressed), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_RZ, -32768)
        assert code == ecodes.ABS_Z
        assert released == 0
        assert pressed == 255

    def test_clutch_invert(self, real_caps):
        mode = GamepadMode(clutch_src=ecodes.ABS_RX, clutch_invert=True)
        mode.build_spec(real_caps)
        (_, code, lo), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_RX, -32768)
        (_, _, hi), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_RX, 32767)
        assert code == ecodes.ABS_Y
        assert lo == 32767
        assert hi == -32768

    def test_steer_deadzone_centers_and_keeps_endpoints(self, real_caps):
        mode = GamepadMode(steer_deadzone=0.1)
        mode.build_spec(real_caps)
        (_, _, mid), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 32768)
        assert mid == 0
        (_, _, lo), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 0)
        (_, _, hi), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 65535)
        assert lo == -32768
        assert hi == 32767

    def test_steer_deadzone_does_not_affect_pedals(self, real_caps):
        dz = GamepadMode(steer_deadzone=0.2)
        dz.build_spec(real_caps)
        plain = GamepadMode()
        plain.build_spec(real_caps)
        # A pedal near its source center would be flattened by a centered
        # deadzone; it must match the deadzone-free mapping exactly.
        for code in (ecodes.ABS_Z, ecodes.ABS_RZ):
            assert (tuple(dz.map_input(ecodes.EV_ABS, code, 1000))
                    == tuple(plain.map_input(ecodes.EV_ABS, code, 1000)))

    def test_defaults_leave_mapping_unchanged(self, real_caps):
        # All new params at defaults reproduce the pre-Phase-3 behavior.
        mode = GamepadMode()
        mode.build_spec(real_caps)
        (_, _, val), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 65535)
        assert val == 32767


# ---------------------------------------------------------------------------
# get_mode wiring of the Phase 3 calibration parameters.
# ---------------------------------------------------------------------------
class TestGetModeCalibrationWiring:
    def test_gamepad_receives_srcs_inverts_deadzone(self):
        mode = get_mode(
            "B",
            steer_src=ecodes.ABS_RX, throttle_src=ecodes.ABS_RY,
            brake_src=ecodes.ABS_THROTTLE, clutch_src=ecodes.ABS_RUDDER,
            steer_invert=True, throttle_invert=True,
            brake_invert=True, clutch_invert=True,
            steer_deadzone=0.05,
        )
        assert type(mode) is GamepadMode
        assert mode.steer_src == ecodes.ABS_RX
        assert mode.throttle_src == ecodes.ABS_RY
        assert mode.brake_src == ecodes.ABS_THROTTLE
        assert mode.clutch_src == ecodes.ABS_RUDDER
        assert mode.steer_invert and mode.throttle_invert
        assert mode.brake_invert and mode.clutch_invert
        assert mode.steer_deadzone == 0.05

    def test_gamepad_none_srcs_keep_mode_defaults(self):
        mode = get_mode("B")
        assert mode.steer_src == ecodes.ABS_X
        assert mode.throttle_src == ecodes.ABS_Z
        assert mode.brake_src == ecodes.ABS_RZ
        assert mode.clutch_src is None
        assert not mode.steer_invert
        assert mode.steer_deadzone == 0.0

    def test_wheel_mode_ignores_calibration_params(self, real_caps):
        mode = get_mode("A", steer_src=ecodes.ABS_RX, steer_invert=True,
                        throttle_invert=True)
        assert type(mode) is WheelMode
        mode.build_spec(real_caps)
        # Passthrough is untouched: same code, same value.
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 12345)) == [
            (ecodes.EV_ABS, ecodes.ABS_X, 12345)
        ]

    def test_normalized_mode_ignores_calibration_params(self, real_caps):
        mode = get_mode("C", brake_src=ecodes.ABS_RX, brake_invert=True,
                        clutch_invert=True)
        assert type(mode) is NormalizedMode
        mode.build_spec(real_caps)
        # Not inverted: source max still maps to destination max.
        (_, _, hi), = mode.map_input(ecodes.EV_ABS, ecodes.ABS_RX, 32767)
        assert hi == 32767


# ---------------------------------------------------------------------------
# Daemon FF_GAIN clamp: _handle_ff_write/apply_initial_gain only need a
# .write()-able real device, so the scaling path is testable without hardware.
# ---------------------------------------------------------------------------
class _FakeReal:
    def __init__(self):
        self.writes: list[tuple[int, int, int]] = []

    def write(self, etype, code, value):
        self.writes.append((etype, code, value))


def _gain_proxy(pct: int) -> Proxy:
    proxy = Proxy(types.SimpleNamespace(_mode=None, ffb_gain=pct))
    proxy.real = _FakeReal()
    return proxy


class TestProxyFfbGain:
    def test_gain_write_scaled(self):
        proxy = _gain_proxy(50)
        proxy._handle_ff_write(ecodes.FF_GAIN, 0xFFFF)
        assert proxy.real.writes == [(ecodes.EV_FF, ecodes.FF_GAIN, 0x7FFF)]

    def test_gain_write_untouched_at_100(self):
        proxy = _gain_proxy(100)
        proxy._handle_ff_write(ecodes.FF_GAIN, 0xC000)
        assert proxy.real.writes == [(ecodes.EV_FF, ecodes.FF_GAIN, 0xC000)]

    def test_autocenter_untouched(self):
        proxy = _gain_proxy(25)
        proxy._handle_ff_write(ecodes.FF_AUTOCENTER, 0x8000)
        assert proxy.real.writes == [(ecodes.EV_FF, ecodes.FF_AUTOCENTER, 0x8000)]

    def test_initial_gain_seeded_when_clamped(self):
        proxy = _gain_proxy(40)
        proxy.apply_initial_ffb()
        assert proxy.real.writes == [
            (ecodes.EV_FF, ecodes.FF_GAIN, scale_gain(0xFFFF, 40))
        ]

    def test_initial_gain_skipped_at_100(self):
        proxy = _gain_proxy(100)
        proxy.apply_initial_ffb()
        assert proxy.real.writes == []

    def test_initial_gain_write_failure_swallowed(self):
        proxy = _gain_proxy(40)

        def boom(*_a):
            raise OSError(19, "device gone")

        proxy.real.write = boom
        proxy.apply_initial_ffb()  # must not raise


class TestProxyFfbAutocenterAndDrop:
    """Phase 4: autocenter seeding and effect-type drop, via the same fake real."""

    def _proxy(self, **over):
        defaults = dict(_mode=None, ffb_gain=100, ffb_autocenter=None,
                        ffb_drop=frozenset())
        defaults.update(over)
        proxy = Proxy(types.SimpleNamespace(**defaults))
        proxy.real = _FakeReal()
        return proxy

    def test_autocenter_seeded(self):
        proxy = self._proxy(ffb_autocenter=25)
        proxy.apply_initial_ffb()
        assert proxy.real.writes == [
            (ecodes.EV_FF, ecodes.FF_AUTOCENTER, scale_gain(0xFFFF, 25))
        ]

    def test_autocenter_zero_still_seeded(self):
        # 0 means "force autocenter OFF", which is a real setting, not unset.
        proxy = self._proxy(ffb_autocenter=0)
        proxy.apply_initial_ffb()
        assert proxy.real.writes == [(ecodes.EV_FF, ecodes.FF_AUTOCENTER, 0)]

    def test_autocenter_unset_writes_nothing(self):
        proxy = self._proxy()
        proxy.apply_initial_ffb()
        assert proxy.real.writes == []

    def test_gain_and_autocenter_both_seed(self):
        proxy = self._proxy(ffb_gain=40, ffb_autocenter=10)
        proxy.apply_initial_ffb()
        assert proxy.real.writes == [
            (ecodes.EV_FF, ecodes.FF_GAIN, scale_gain(0xFFFF, 40)),
            (ecodes.EV_FF, ecodes.FF_AUTOCENTER, scale_gain(0xFFFF, 10)),
        ]

    def test_legacy_namespace_without_new_fields(self):
        # mozactl-spawned daemons always have the attrs, but Proxy must not
        # require them (tests/other embedders build minimal namespaces).
        proxy = Proxy(types.SimpleNamespace(_mode=None, ffb_gain=100))
        proxy.real = _FakeReal()
        proxy.apply_initial_ffb()
        assert proxy.real.writes == []
        assert proxy.ffb_drop == frozenset()


class TestFfDropConverter:
    def test_parses_comma_list_any_spelling(self):
        from mozaproxy import _ff_drop
        assert _ff_drop("spring,FF_DAMPER") == frozenset(
            {ecodes.FF_SPRING, ecodes.FF_DAMPER})

    def test_rejects_unknown_type(self):
        import argparse
        import pytest
        from mozaproxy import _ff_drop
        with pytest.raises(argparse.ArgumentTypeError):
            _ff_drop("spring,wobble")

    def test_via_parse_args(self):
        from mozaproxy import parse_args
        args = parse_args(["--ffb-drop", "spring,damper", "--ffb-autocenter", "30"])
        assert args.ffb_drop == frozenset({ecodes.FF_SPRING, ecodes.FF_DAMPER})
        assert args.ffb_autocenter == 30

    def test_defaults(self):
        from mozaproxy import parse_args
        args = parse_args([])
        assert args.ffb_drop == frozenset()
        assert args.ffb_autocenter is None


class TestUsbBacked:
    """Transport-based real/virtual discrimination (identity cloning)."""

    def test_real_base_phys(self):
        from mozaproxy import usb_backed
        assert usb_backed("usb-0000:00:14.0-5.1.2/input2") is True

    def test_uinput_phys(self):
        from mozaproxy import usb_backed
        assert usb_backed("py-evdev-uinput") is False

    def test_missing_phys(self):
        from mozaproxy import usb_backed
        assert usb_backed("") is False
        assert usb_backed(None) is False


class TestNormalizedAxisRange:
    """Mode C axis_range override (one uniform range for direct evdev readers)."""

    def test_default_stays_signed16(self, real_caps):
        mode = NormalizedMode()
        spec = mode.build_spec(real_caps)
        ax = dict(spec.events[ecodes.EV_ABS])[ecodes.ABS_X]
        assert (ax.min, ax.max) == (-32768, 32767)

    def test_custom_range_advertised_on_all_non_hat_axes(self, real_caps):
        mode = NormalizedMode(axis_range=(0, 32767))
        spec = mode.build_spec(real_caps)
        for code, info in spec.events[ecodes.EV_ABS]:
            if code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                assert (info.min, info.max) == (-1, 1)
            else:
                assert (info.min, info.max) == (0, 32767)

    def test_values_rescaled_into_range(self, real_caps):
        mode = NormalizedMode(axis_range=(0, 32767))
        mode.build_spec(real_caps)
        # Steering: unsigned 0..65535 source.
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 0)) == \
            [(ecodes.EV_ABS, ecodes.ABS_X, 0)]
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 65535)) == \
            [(ecodes.EV_ABS, ecodes.ABS_X, 32767)]
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 32768)) == \
            [(ecodes.EV_ABS, ecodes.ABS_X, 16384)]
        # Pedal: signed source, rest at min -> 0.
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_Z, -32768)) == \
            [(ecodes.EV_ABS, ecodes.ABS_Z, 0)]
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_Z, 32767)) == \
            [(ecodes.EV_ABS, ecodes.ABS_Z, 32767)]

    def test_get_mode_wires_axis_range(self, real_caps):
        mode = get_mode("C", axis_range=(0, 32767))
        assert mode.axis_range == (0, 32767)
        # Unset keeps the mode default.
        assert get_mode("C").axis_range == (-32768, 32767)

    def test_axis_range_converter(self):
        import argparse
        import pytest
        from mozaproxy import _axis_range, parse_args
        assert _axis_range("0:32767") == (0, 32767)
        assert _axis_range("-32768:32767") == (-32768, 32767)
        for bad in ("32767:0", "0:70000", "abc", "5"):
            with pytest.raises(argparse.ArgumentTypeError):
                _axis_range(bad)
        assert parse_args(["--axis-range", "0:32767"]).axis_range == (0, 32767)
        assert parse_args([]).axis_range is None


class TestExplicitButtonCodes:
    """Wheel modes: expose an explicit set of real button codes.

    Decouples WHICH buttons appear from HOW MANY, so buttons high in the
    0x270+ block can stay exposed while the total count stays small. That
    turns "does this game mind a large button set?" into a one-variable
    experiment instead of an all-or-nothing choice.
    """

    def test_wheel_exposes_only_listed_codes(self, real_caps):
        # Low block + two specific upper-block paddle codes: 18 buttons total,
        # yet including codes a plain count of 18 would never reach.
        codes = list(range(0x120, 0x130)) + [0x2C0, 0x2C1]
        mode = WheelMode(button_codes=codes)
        spec = mode.build_spec(real_caps)
        assert spec.events[ecodes.EV_KEY] == sorted(codes)

    def test_explicit_codes_win_over_count(self, real_caps):
        mode = WheelMode(buttons=128, button_codes=[0x120, 0x2C0])
        spec = mode.build_spec(real_caps)
        assert spec.events[ecodes.EV_KEY] == [0x120, 0x2C0]

    def test_unknown_codes_dropped_not_invented(self, real_caps):
        # 0x131 is in the gamepad block the base skips; 0x400 is out of range.
        # Neither is on the real device, so both are dropped rather than faked
        # — and remembered, so the daemon can say so instead of staying silent.
        mode = WheelMode(button_codes=[0x120, 0x131, 0x2C0, 0x400])
        spec = mode.build_spec(real_caps)
        assert spec.events[ecodes.EV_KEY] == [0x120, 0x2C0]
        assert mode.unknown_button_codes == [0x131, 0x400]
        assert mode.button_codes_ignored is False

    def test_all_known_codes_report_nothing_unknown(self, real_caps):
        mode = WheelMode(button_codes=[0x120, 0x2C0])
        mode.build_spec(real_caps)
        assert mode.unknown_button_codes == []
        assert mode.button_codes_ignored is False

    def test_no_listed_code_on_device_falls_back_to_count(self, real_caps):
        # A list written for a different wheel (or all typos) must not produce
        # a button-less virtual wheel: ignore it and use the count instead.
        for cls in (WheelMode, NormalizedMode):
            mode = cls(buttons=24, button_codes=[0x130, 0x131])
            spec = mode.build_spec(real_caps)
            assert spec.events[ecodes.EV_KEY] == sorted(real_caps.keys)[:24]
            assert mode.button_codes_ignored is True
            assert mode.unknown_button_codes == [0x130, 0x131]
            # The fallback set is what map_input honours too.
            assert list(mode.map_input(ecodes.EV_KEY, 0x120, 1)) == [
                (ecodes.EV_KEY, 0x120, 1)]

    def test_duplicate_codes_collapsed(self, real_caps):
        # The CLI and profile layers dedupe, but a mode built directly must not
        # advertise the same code twice.
        mode = WheelMode(button_codes=[0x2C0, 0x120, 0x2C0, 0x120])
        spec = mode.build_spec(real_caps)
        assert spec.events[ecodes.EV_KEY] == [0x120, 0x2C0]

    def test_resolution_state_resets_between_builds(self, real_caps):
        # build_spec runs again on every re-attach; stale "unknown" state from
        # a previous device must not leak into the next report.
        mode = WheelMode(button_codes=[0x120, 0x131])
        mode.build_spec(real_caps)
        assert mode.unknown_button_codes == [0x131]
        other = make_real_caps()
        other.keys = other.keys + [0x131]
        mode.build_spec(other)
        assert mode.unknown_button_codes == []
        assert mode.button_set == {0x120, 0x131}

    def test_ignored_state_resets_after_a_fallback_build(self, real_caps, caplog):
        # Attach to a device with none of the codes (fallback), then re-attach
        # to the base: the second build honours the list, so neither the flag
        # nor the daemon's log may still claim it was ignored.
        import logging
        mode = WheelMode(buttons=4, button_codes=[0x120, 0x131])
        bare = make_real_caps()
        bare.keys = [0x2C0, 0x2C1]
        mode.build_spec(bare)
        assert mode.button_codes_ignored is True
        spec = mode.build_spec(real_caps)
        assert mode.button_codes_ignored is False
        assert spec.events[ecodes.EV_KEY] == [0x120]
        proxy = Proxy(types.SimpleNamespace(_mode=mode, ffb_gain=100))
        with caplog.at_level(logging.WARNING, logger="mozaproxy"):
            proxy._report_button_codes(spec)
        (msg,) = [r.getMessage() for r in caplog.records]
        assert "does not report 0x131" in msg and "none of" not in msg

    def test_codes_sorted_regardless_of_input_order(self, real_caps):
        mode = WheelMode(button_codes=[0x2C0, 0x120, 0x271])
        spec = mode.build_spec(real_caps)
        assert spec.events[ecodes.EV_KEY] == [0x120, 0x271, 0x2C0]

    def test_map_input_passes_listed_drops_unlisted(self, real_caps):
        mode = WheelMode(button_codes=[0x120, 0x2C0])
        mode.build_spec(real_caps)
        assert list(mode.map_input(ecodes.EV_KEY, 0x2C0, 1)) == [
            (ecodes.EV_KEY, 0x2C0, 1)]
        # 0x271 is a real button but not in the exposed set -> dropped.
        assert list(mode.map_input(ecodes.EV_KEY, 0x271, 1)) == []

    def test_normalized_mode_honors_button_codes(self, real_caps):
        mode = NormalizedMode(button_codes=[0x120, 0x2DF])
        spec = mode.build_spec(real_caps)
        assert spec.events[ecodes.EV_KEY] == [0x120, 0x2DF]
        # Axes still rescaled: the button change must not touch axis handling.
        assert list(mode.map_input(ecodes.EV_ABS, ecodes.ABS_X, 65535)) == [
            (ecodes.EV_ABS, ecodes.ABS_X, 32767)]

    def test_none_falls_back_to_count(self, real_caps):
        mode = WheelMode(buttons=24, button_codes=None)
        spec = mode.build_spec(real_caps)
        assert len(spec.events[ecodes.EV_KEY]) == 24

    def test_get_mode_wires_button_codes(self, real_caps):
        for sel in ("A", "C"):
            mode = get_mode(sel, button_codes=[0x120, 0x2C0])
            assert mode.button_codes == [0x120, 0x2C0]
            spec = mode.build_spec(real_caps)
            assert spec.events[ecodes.EV_KEY] == [0x120, 0x2C0]
        # Unset stays None (mode falls back to the count).
        assert get_mode("A").button_codes is None


class TestButtonCodesConverter:
    def test_parses_hex_and_decimal_sorted_deduped(self):
        from mozaproxy import _button_codes
        assert _button_codes("0x120, 0x2c0, 288, 0x120") == [0x120, 0x2C0]

    def test_rejects_non_integer(self):
        import argparse
        import pytest
        from mozaproxy import _button_codes
        with pytest.raises(argparse.ArgumentTypeError):
            _button_codes("0x120,paddle")

    def test_rejects_out_of_range(self):
        import argparse
        import pytest
        from mozaproxy import _button_codes
        for bad in ("0xff", "0x300", "-1"):
            with pytest.raises(argparse.ArgumentTypeError):
                _button_codes(bad)

    def test_rejects_empty_list(self):
        # "" used to parse to [] — i.e. "expose zero buttons". The profile
        # schema already rejects an empty button_codes list; match it.
        import argparse
        import pytest
        from mozaproxy import _button_codes
        for bad in ("", " ", ",", " , ,"):
            with pytest.raises(argparse.ArgumentTypeError):
                _button_codes(bad)

    def test_empty_list_is_a_usage_error_via_parse_args(self, capsys):
        import pytest
        from mozaproxy import parse_args
        with pytest.raises(SystemExit) as exc:
            parse_args(["--button-codes", ""])
        assert exc.value.code == 2
        assert "at least one button code" in capsys.readouterr().err

    def test_via_parse_args(self):
        from mozaproxy import parse_args
        args = parse_args(["--button-codes", "0x120,0x2c0"])
        assert args.button_codes == [0x120, 0x2C0]
        assert parse_args([]).button_codes is None


class TestDaemonWiring:
    """The daemon's own path: argv -> main() -> mode -> virtual device."""

    def test_main_hands_button_codes_to_the_mode(self, monkeypatch):
        import mozaproxy
        seen = {}
        monkeypatch.setattr(mozaproxy, "supervise",
                            lambda args: seen.setdefault("args", args) and 0)
        assert mozaproxy.main(["--mode", "C", "--button-codes", "0x2c0,0x120"]) == 0
        mode = seen["args"]._mode
        assert isinstance(mode, NormalizedMode)
        assert mode.button_codes == [0x120, 0x2C0]

    def test_build_virtual_creates_the_listed_buttons_and_logs_the_rest(
            self, real_caps, monkeypatch, caplog):
        import logging
        import mozaproxy
        created = {}

        class FakeUInput:
            def __init__(self, events, **kw):
                created["keys"] = list(events[ecodes.EV_KEY])
                created.update(kw)

        class FakeReal:
            name = "Gudsen MOZA R25 Ultra Base"
            info = types.SimpleNamespace(vendor=0x346E, product=0, version=0x111)
            ff_effects_count = 10

            def capabilities(self, absinfo=False):
                return {ecodes.EV_ABS: list(real_caps.abs.items()),
                        ecodes.EV_KEY: list(real_caps.keys),
                        ecodes.EV_FF: list(real_caps.ff)}

        monkeypatch.setattr(mozaproxy, "UInput", FakeUInput)
        args = mozaproxy.parse_args(["--mode", "A", "--button-codes", "0x120,0x131,0x2c0"])
        args._mode = get_mode(args.mode, button_codes=args.button_codes)
        proxy = Proxy(args)
        proxy.real = FakeReal()
        with caplog.at_level(logging.WARNING, logger="mozaproxy"):
            proxy.build_virtual()
        assert created["keys"] == [0x120, 0x2C0]
        assert any("does not report 0x131" in r.getMessage() for r in caplog.records)


class TestProxyReportsButtonCodes:
    """The daemon says what an explicit code list resolved to (mozactl logs)."""

    def _report(self, mode, real_caps, caplog):
        import logging
        proxy = Proxy(types.SimpleNamespace(_mode=mode, ffb_gain=100))
        spec = mode.build_spec(real_caps)
        with caplog.at_level(logging.WARNING, logger="mozaproxy"):
            proxy._report_button_codes(spec)
        return [r.getMessage() for r in caplog.records]

    def test_silent_when_every_code_exists(self, real_caps, caplog):
        mode = WheelMode(button_codes=[0x120, 0x2C0])
        assert self._report(mode, real_caps, caplog) == []

    def test_silent_without_an_explicit_list(self, real_caps, caplog):
        assert self._report(WheelMode(buttons=24), real_caps, caplog) == []

    def test_warns_naming_the_dropped_codes(self, real_caps, caplog):
        mode = NormalizedMode(button_codes=[0x120, 0x131, 0x2C0])
        (msg,) = self._report(mode, real_caps, caplog)
        assert "0x131" in msg and "does not report" in msg
        assert "0x120" not in msg

    def test_warns_when_the_whole_list_is_ignored(self, real_caps, caplog):
        mode = WheelMode(buttons=24, button_codes=[0x130, 0x131])
        (msg,) = self._report(mode, real_caps, caplog)
        assert "none of the requested codes" in msg
        assert "0x130,0x131" in msg and "lowest 24 buttons" in msg

    def test_modes_without_the_feature_are_ignored(self, real_caps, caplog):
        # GamepadMode has no button_codes machinery; the report must not care.
        assert self._report(GamepadMode(), real_caps, caplog) == []
