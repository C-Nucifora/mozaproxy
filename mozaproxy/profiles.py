"""Build explicit source-to-virtual input mappings."""

from dataclasses import dataclass, field

from evdev import AbsInfo, ecodes as e

# Controls exercised on the R25. Keep the first sixteen conventional buttons,
# then include measured auxiliary buttons before filling unused profile slots.
R25_BUTTON_PRIORITY = tuple(range(288, 304)) + (
    626, 627, 628, 629, 630, 639, 640, 641, 642, 643, 653, 655,
)
COMPACT_OUTPUTS = tuple(range(e.BTN_JOYSTICK, e.BTN_DEAD + 1)) + tuple(
    range(e.BTN_TRIGGER_HAPPY1, e.BTN_TRIGGER_HAPPY40 + 1)
)


@dataclass
class Profile:
    name: str
    events: dict
    buttons: dict[int, int]
    axes: tuple[int, ...]
    axis_transforms: dict[int, tuple[int, int, int, bool]] = field(default_factory=dict)

    def axis_event(self, source, value):
        if source not in self.axis_transforms:
            return source, value
        target, low, high, inverted = self.axis_transforms[source]
        value = min(high, max(low, value))
        scaled = round((value - low) * 65535 / (high - low))
        return target, 65535 - scaled if inverted else scaled


def g920_profile(capabilities, buttons):
    if buttons not in (None, 11):
        raise ValueError('G920 profile has a fixed 11-button layout')
    source_axes = dict(capabilities.get(e.EV_ABS, []))
    # Measured R25 pedals; Wine's G920 SDL path expects X/Y/Z/RZ in this order.
    pairs = ((e.ABS_X, e.ABS_X), (e.ABS_Z, e.ABS_Y),
             (e.ABS_RZ, e.ABS_Z), (e.ABS_THROTTLE, e.ABS_RZ))
    if any(source not in source_axes for source, _ in pairs):
        raise ValueError('G920 profile requires measured R25 steering and pedal axes')
    transforms, axes = {}, []
    for source, target in pairs:
        info = source_axes[source]
        if info.max <= info.min:
            raise ValueError('G920 source axes must have a nonzero range')
        transforms[source] = (target, info.min, info.max, source != e.ABS_X)
        initial = round((min(info.max, max(info.min, info.value)) - info.min)
                        * 65535 / (info.max - info.min))
        if source != e.ABS_X:
            initial = 65535 - initial
        axes.append((target, AbsInfo(initial, 0, 65535, 0, 0, 0)))
    source_codes = [source for source, _ in pairs]
    for code in (e.ABS_HAT0X, e.ABS_HAT0Y):
        if code in source_axes:
            axes.append((code, source_axes[code]))
            source_codes.append(code)
    # Right/left paddles are measured R25 codes 301/300, G920 buttons 4/5.
    sources = (288, 289, 296, 297, 301, 300, 298, 299, 290, 291, 292)
    available = set(capabilities.get(e.EV_KEY, []))
    mapping = {source: e.BTN_JOYSTICK + i for i, source in enumerate(sources)
               if source in available}
    events = {e.EV_ABS: axes, e.EV_KEY: list(mapping.values())}
    effects = [code for code in capabilities.get(e.EV_FF, []) if code != e.FF_CUSTOM]
    if effects:
        events[e.EV_FF] = effects
    return Profile('g920', events, mapping, tuple(source_codes), transforms)


def make_profile(capabilities, name='native', buttons=None):
    if name == 'g920':
        return g920_profile(capabilities, buttons)
    if name not in ('native', 'compact'):
        raise ValueError(f'Unknown profile: {name}')
    if buttons is not None and not 1 <= buttons <= 128:
        raise ValueError('Button count must be between 1 and 128')
    source = sorted(set(capabilities.get(e.EV_KEY, [])))
    if name == 'native':
        selected = source if buttons is None else source[:buttons]
        mapping = {code: code for code in selected}
    else:
        limit = 32 if buttons is None else buttons
        if limit > len(COMPACT_OUTPUTS):
            raise ValueError(f'Compact profile supports at most {len(COMPACT_OUTPUTS)} buttons')
        priority = list(dict.fromkeys((*R25_BUTTON_PRIORITY, *source)))
        selected = [code for code in priority if code in source][:limit]
        mapping = dict(zip(selected, COMPACT_OUTPUTS))
    axes = list(capabilities.get(e.EV_ABS, []))
    events = {e.EV_ABS: axes, e.EV_KEY: list(mapping.values())}
    # FF_CUSTOM embeds a process-local pointer. It cannot be relayed by copying
    # the ff_effect structure between the game's and daemon's address spaces.
    effects = [code for code in capabilities.get(e.EV_FF, []) if code != e.FF_CUSTOM]
    if effects:
        events[e.EV_FF] = effects
    return Profile(name, events, mapping, tuple(code for code, _ in axes))
