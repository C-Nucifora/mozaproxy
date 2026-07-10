"""Shared fixtures for the modes test suite.

All fixtures here are pure and hardware-free: they describe the real MOZA R25
Ultra base so the modes can be exercised with nothing plugged in.
"""
from __future__ import annotations

import pytest
from evdev import AbsInfo, ecodes

from modes.base import RealCaps


# Signed axes on the real base: -32768..32767.
_SIGNED_AXES = (
    ecodes.ABS_Y,
    ecodes.ABS_Z,
    ecodes.ABS_RX,
    ecodes.ABS_RY,
    ecodes.ABS_RZ,
    ecodes.ABS_THROTTLE,
    ecodes.ABS_RUDDER,
)


def _abs(lo: int, hi: int) -> AbsInfo:
    return AbsInfo(value=0, min=lo, max=hi, fuzz=0, flat=0, resolution=0)


def make_real_caps() -> RealCaps:
    """Build a RealCaps matching the actual MOZA R25 Ultra base."""
    abs_caps: dict[int, AbsInfo] = {
        ecodes.ABS_X: _abs(0, 65535),  # steering, UNSIGNED
    }
    for code in _SIGNED_AXES:
        abs_caps[code] = _abs(-32768, 32767)
    abs_caps[ecodes.ABS_HAT0X] = _abs(-1, 1)
    abs_caps[ecodes.ABS_HAT0Y] = _abs(-1, 1)

    # 128 contiguous buttons from BTN_JOYSTICK (0x120).
    keys = [ecodes.BTN_JOYSTICK + i for i in range(128)]

    ff = [ecodes.FF_CONSTANT, ecodes.FF_PERIODIC, ecodes.FF_SPRING, ecodes.FF_DAMPER]

    return RealCaps(abs=abs_caps, keys=keys, ff=ff, ff_effects_count=10)


@pytest.fixture
def real_caps() -> RealCaps:
    return make_real_caps()
