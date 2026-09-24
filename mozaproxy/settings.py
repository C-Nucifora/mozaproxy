"""Typed MOZA settings and wire conversions. Protocol reference: Boxflat serial.yml."""

import math
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class Setting:
    id: str
    label: str
    group: str
    command: bytes
    minimum: float = 0
    maximum: float = 100
    scale: float = 1
    offset: float = 0
    size: int = 2
    device: int = 19
    read_group: int = 40
    write_group: int = 41
    write_command: bytes | None = None
    kind: str = "number"
    unit: str = "%"
    step: float = 1
    choices: tuple = ()
    floating: bool = False
    description: str = ""

    def encode(self, value):
        raw = float(value) * self.scale + self.offset
        return (
            struct.pack(">f", raw)
            if self.floating
            else round(raw).to_bytes(self.size, "big")
        )

    def decode(self, payload):
        raw = (
            struct.unpack(">f", payload)[0]
            if self.floating
            else int.from_bytes(payload, "big")
        )
        value = (raw - self.offset) / self.scale
        if self.kind == "boolean":
            if value not in (0, 1):
                raise ValueError("Invalid boolean reply")
            return bool(value)
        return round(value, 3)

    def schema(self):
        return dict(
            id=self.id,
            label=self.label,
            group=self.group,
            description=self.description,
            type=self.kind,
            min=self.minimum,
            max=self.maximum,
            step=self.step,
            unit=self.unit,
            choices=[dict(value=v, label=l) for v, l in self.choices],
        )


SETTINGS = {}


def add(id, label, group, command, **kwargs):
    command = bytes([command]) if isinstance(command, int) else bytes(command)
    SETTINGS[id] = Setting(id, label, group, command, **kwargs)


add(
    "rotation",
    "Steering rotation",
    "base",
    1,
    minimum=90,
    maximum=2700,
    scale=0.5,
    unit="°",
    step=2,
    description="Total steering travel from left to right. Apply sets both the steering range and maximum angle; match the game's steering range when needed.",
)
add("ffb_strength", "Game force strength", "base", 2, scale=10,
    description="Scales force feedback requested by the game. Base torque output separately controls the base's available force.")
add("torque", "Maximum torque limit", "base", 18, minimum=50,
    description="Limits maximum motor torque as a percentage of the base rating. Firmware accepts 50–100%. Game force strength is separate; reducing it does not establish a lower hardware torque cap.")
add("speed", "Maximum wheel speed", "base", 10, maximum=200, scale=10,
    description="Controls how fast the motor can turn the steering wheel. The percentage is a device setting, not vehicle speed.")
add(
    "protection", "Hands-off protection", "base", 13, kind="boolean", maximum=1, unit="",
    description="Enables the base's hands-off protection. Protection mode and steering wheel inertia configure this feature for the fitted steering wheel.",
)
add(
    "protection_mode",
    "Protection mode",
    "base",
    45,
    kind="select",
    minimum=1,
    maximum=2,
    unit="",
    choices=((1, "Mode 1"), (2, "Mode 2")),
    description="Selects a firmware protection mode when hands-off protection is enabled. The behavior of Mode 1 versus Mode 2 is not documented in the available reference.",
)
add(
    "wheel_inertia",
    "Steering wheel inertia",
    "base",
    19,
    minimum=100,
    maximum=4000,
    unit="",
    step=50,
    description="Wheel inertia value used by hands-off protection for the fitted steering wheel. This is separate from the Natural inertia effect; no physical unit is specified here.",
)
add(
    "soft_limit",
    "Soft limit strength",
    "base",
    27,
    kind="select",
    minimum=56,
    maximum=100,
    unit="",
    choices=((56, "Soft"), (78, "Medium"), (100, "Hard")),
    description="Chooses the strength of the steering stop at the configured rotation limit. Soft limit stiffness adjusts the stop's stiffness separately.",
)
add(
    "soft_limit_stiffness",
    "Soft limit stiffness",
    "base",
    31,
    minimum=1,
    maximum=10,
    scale=400 / 9,
    offset=100 - 400 / 9,
    unit="",
    description="Adjusts how stiff the steering stop feels at the rotation limit. Higher values make the stop stiffer; they do not change the steering range.",
)
add(
    "soft_limit_retain",
    "Retain game force at limit",
    "base",
    28,
    kind="boolean",
    maximum=1,
    unit="",
    description="Keeps game force feedback active at the steering limit, alongside the soft stop.",
)
add(
    "temperature_strategy",
    "Temperature control",
    "base",
    30,
    kind="select",
    maximum=1,
    unit="",
    choices=((0, "Conservative · 50°C"), (1, "Radical · 60°C")),
    description="Selects the base's temperature-control strategy. The reference labels Conservative as 50°C and Radical as 60°C; this is not a live temperature reading.",
)
for id, label, cmd, description in [
    ("damper", "Wheel damping", 7, "Adds resistance that depends on how fast you turn the wheel. This base effect is separate from damping requested by the game."),
    ("friction", "Wheel friction", 8, "Adds friction-like resistance to wheel movement. This base effect is separate from friction requested by the game."),
    ("spring", "Wheel spring", 9, "Adds a centering spring force from the base. Game spring separately controls spring effects requested by the game."),
]:
    add(id, label, "effects", cmd, scale=10, description=description)
add(
    "inertia",
    "Natural inertia",
    "effects",
    4,
    minimum=100,
    maximum=500,
    scale=10,
    unit="",
    description="Adds an inertia effect that resists changes in wheel movement. This adjusts the wheel's feel; Steering wheel inertia separately configures hands-off protection.",
)
add("speed_damping", "High speed damping", "effects", 25,
    description="Sets the damping level for the base's high-speed damping feature. Damping trigger speed sets its vehicle-speed threshold; availability depends on game and device support.")
add(
    "speed_damping_point",
    "Damping trigger speed",
    "effects",
    26,
    maximum=400,
    unit="km/h",
    description="Vehicle-speed threshold for high-speed damping. This requires the base to receive the relevant speed information; Mozaproxy does not supply game telemetry.",
)
add(
    "ffb_reverse",
    "Reverse force direction",
    "effects",
    24,
    kind="boolean",
    maximum=1,
    unit="",
    description="Reverses the direction of force feedback. Changes force direction without reversing the steering input reported to the game.",
)
for name, idx in [("spring", 8), ("damper", 9), ("inertia", 10), ("friction", 11)]:
    add(
        "game_" + name,
        "Game " + name,
        "effects",
        [79, idx],
        write_command=bytes([78, idx]),
        device=18,
        read_group=31,
        write_group=31,
        size=1,
        scale=2.55,
        description=f"Scales {name} effects requested by the game. It has no effect if the game does not send this effect type; it does not add a base effect.",
    )
for hz, cmd in [(10, 14), (15, 15), (25, 16), (40, 17), (60, 20), (100, 44)]:
    add("eq_" + str(hz), str(hz) + " Hz", "filters", cmd, maximum=400,
        description=f"Adjusts force feedback strength in the {hz} Hz equalizer band. This shapes the force signal rather than the steering input.")
add(
    "interpolation",
    "FFB interpolation",
    "filters",
    77,
    write_command=b"\x4c",
    device=18,
    read_group=31,
    write_group=31,
    size=1,
    maximum=10,
    scale=10,
    unit="",
    description="Adjusts the base's interpolation of incoming force feedback. Interpolation smooths changes between force updates; the firmware's exact filter behavior is not documented here.",
)
for i in range(1, 6):
    add(
        "ffb_curve_" + str(i),
        "Force curve point " + str(i),
        "filters",
        [34, i + 4],
        size=1,
        description=f"Force output at curve point {i}. The device's existing input breakpoint is preserved; this control changes only the output level.",
    )
for pedal, cmd, curve in [
    ("throttle", 1, [14, 15, 16, 17, 27]),
    ("brake", 4, [18, 19, 20, 21, 28]),
    ("clutch", 7, [22, 23, 24, 25, 29]),
]:
    common = dict(device=25, read_group=35, write_group=36)
    add(
        pedal + "_reverse",
        pedal.title() + " reversed",
        "pedals",
        cmd,
        kind="boolean",
        maximum=1,
        unit="",
        description=f"Reverses the direction of the {pedal} input, exchanging its released and pressed ends.",
        **common,
    )
    add(pedal + "_min", pedal.title() + " minimum", "pedals", cmd + 1,
        description=f"Lower boundary of the {pedal}'s active range. Raise it to leave more input travel before the pedal begins responding; keep it below maximum.", **common)
    add(pedal + "_max", pedal.title() + " maximum", "pedals", cmd + 2,
        description=f"Upper boundary of the {pedal}'s active range. Lower it to reach full output sooner; keep it above minimum.", **common)
    for i, point in enumerate(curve, 1):
        add(
            pedal + "_curve_" + str(i),
            pedal.title() + " output at " + str(i * 20) + "%",
            "pedals",
            point,
            size=4,
            floating=True,
            description=f"Reported {pedal} output when its curve input is {i * 20}%. Matching the two percentages gives a linear point; higher output makes this part of the response stronger.",
            **common,
        )
add(
    "brake_sensor_ratio",
    "Brake pressure sensor mix",
    "pedals",
    26,
    device=25,
    read_group=35,
    write_group=36,
    size=4,
    floating=True,
    description="Blends the brake's angle and pressure sensors. 0% uses only the angle sensor; 100% uses only the load cell, on pedals that support both.",
)
wheel = dict(device=23, read_group=64, write_group=63, size=1)
add(
    "paddles_mode",
    "Clutch paddle mode",
    "wheel",
    3,
    kind="select",
    minimum=1,
    maximum=3,
    unit="",
    choices=((1, "Buttons"), (2, "Combined"), (3, "Split")),
    description="Chooses whether clutch paddles act as buttons, a combined clutch input, or separate paddle inputs. The clutch bite point applies in Combined mode.",
    **wheel,
)
add("clutch_point", "Clutch bite point", "wheel", 9, minimum=5, maximum=95,
    description="Sets the left clutch paddle's cutoff in Combined mode. It changes the combined paddle response, not the clutch pedal.", **wheel)
add("rpm_brightness", "RPM light brightness", "wheel", [27, 0, 255],
    description="Sets the brightness of the steering wheel's RPM indicator lights. It does not configure RPM timing, colors or game telemetry.", **wheel)
add("button_brightness", "Button brightness", "wheel", [27, 1, 255],
    description="Sets the brightness of supported steering wheel button lights. It does not change their colors or button assignments.", **wheel)
add(
    "knob_mode",
    "Rotary control mode",
    "wheel",
    10,
    kind="select",
    maximum=1,
    unit="",
    choices=((0, "Buttons"), (1, "Knob")),
    description="Selects the wheel firmware's Buttons or Knob behavior for rotary controls. Check the live inputs and game bindings after changing it; behavior depends on the wheel.",
    **wheel,
)


def schema():
    return {
        "groups": [
            {"id": i, "label": l}
            for i, l in [
                ("base", "Wheelbase"),
                ("effects", "Force feedback"),
                ("filters", "Equalizer & curves"),
                ("pedals", "Pedals"),
                ("wheel", "Wheel controls"),
            ]
        ],
        "settings": [s.schema() for s in SETTINGS.values()],
    }


def validate_settings(values):
    if not isinstance(values, dict):
        raise ValueError("Settings must be an object")
    for key, value in values.items():
        if key not in SETTINGS:
            raise ValueError("Unknown setting: " + str(key))
        s = SETTINGS[key]
        if s.kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError(s.label + " must be true or false")
        else:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(s.label + " must be a finite number")
            if not s.minimum <= value <= s.maximum:
                raise ValueError(s.label + " is out of range")
            if s.choices and value not in [c[0] for c in s.choices]:
                raise ValueError(s.label + " has an invalid choice")
    for pedal in ("throttle", "brake", "clutch"):
        if (
            pedal + "_min" in values
            and pedal + "_max" in values
            and values[pedal + "_min"] >= values[pedal + "_max"]
        ):
            raise ValueError(pedal.title() + " minimum must be below maximum")
    return dict(values)
