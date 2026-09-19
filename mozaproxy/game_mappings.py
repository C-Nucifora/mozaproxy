"""Versioned per-game source assignments for immutable target wheel layouts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
from evdev import AbsInfo, ecodes as e
from .profiles import Profile

G920_IDENTITY = ('Logitech G920 Driving Force Racing Wheel', 0x046d, 0xc262)
AXIS_ROLES = {'steering': e.ABS_X, 'throttle': e.ABS_Y,
              'brake': e.ABS_Z, 'clutch': e.ABS_RZ}
SOURCE_AXES = {0: 'Steering', 1: 'Axis 1', 2: 'Throttle', 3: 'Axis 3',
               4: 'Axis 4', 5: 'Brake', 6: 'Clutch', 7: 'Axis 7'}
SOURCE_BUTTONS = {300: 'Left paddle', 301: 'Right paddle'}


def write_mapping_document(path, data):
    """Replace a private JSON control/status document without partial readers."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.mapping-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def default_mapping(game_id, target='direct'):
    mapping = {'version': 1, 'game_id': game_id, 'target': target}
    if target == 'g920':
        mapping.update(axes={role: {'source': source, 'inverted': role != 'steering'}
                             for role, source in zip(AXIS_ROLES, (0, 2, 5, 6))},
                       buttons=[None] * 11, hat=False)
        mapping['buttons'][4:6] = [301, 300]
        # Attended Heat mapping after installing its Logitech wheel SDK runtime.
        # These are measured inputs on this R25 setup, not guessed rim labels.
        if game_id == 'heat':
            mapping['buttons'][0:2] = [639, 640]
            mapping['buttons'][6] = 627
            mapping['hat'] = True
    return validate_mapping(mapping)


def validate_mapping(data):
    if not isinstance(data, dict):
        raise ValueError('Game mapping must be an object')
    if type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('Unsupported game mapping version')
    if not isinstance(data.get('game_id'), str) or not re.fullmatch(r'[a-z0-9_-]{1,64}', data['game_id']):
        raise ValueError('Invalid game ID')
    target = data.get('target')
    if target not in ('direct', 'g920'):
        raise ValueError('Choose direct physical access or the fixed G920 layout')
    keys = {'version', 'game_id', 'target'}
    if target == 'g920':
        keys |= {'axes', 'buttons', 'hat'}
        axes = data.get('axes')
        if not isinstance(axes, dict) or set(axes) != set(AXIS_ROLES):
            raise ValueError('Assign steering, throttle, brake and clutch')
        sources = []
        for role, item in axes.items():
            if not isinstance(item, dict) or set(item) != {'source', 'inverted'}:
                raise ValueError(f'Invalid {role} assignment')
            if type(item['source']) is not int or item['source'] not in SOURCE_AXES:
                raise ValueError(f'Invalid R25 axis for {role}')
            if type(item['inverted']) is not bool:
                raise ValueError(f'{role} reversal must be a boolean')
            sources.append(item['source'])
        if len(set(sources)) != 4:
            raise ValueError('Assign each R25 axis only once')
        buttons = data.get('buttons')
        if not isinstance(buttons, list) or len(buttons) != 11:
            raise ValueError('The G920 layout has exactly eleven button slots')
        assigned = [code for code in buttons if code is not None]
        if any(type(code) is not int or not e.BTN_MISC <= code <= e.KEY_MAX for code in assigned):
            raise ValueError('Invalid R25 button')
        if len(set(assigned)) != len(assigned):
            raise ValueError('Assign each R25 button only once')
        if type(data.get('hat')) is not bool:
            raise ValueError('Hat passthrough must be a boolean')
    if set(data) != keys:
        raise ValueError('Unexpected game mapping fields')
    return deepcopy(data)


def load_mapping(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError('Game mapping exceeds 16 KiB')
    return validate_mapping(json.loads(raw))


def compile_mapping(capabilities, data):
    data = validate_mapping(data)
    if data['target'] == 'direct':
        raise ValueError('A direct configuration does not create a relay')
    available = dict(capabilities.get(e.EV_ABS, []))
    transforms, axes, sources = {}, [], []
    for role, target in AXIS_ROLES.items():
        item = data['axes'][role]
        source = item['source']
        info = available.get(source)
        if info is None or info.max <= info.min:
            raise ValueError(f'{role}: assigned R25 axis {source} is missing or has no range')
        transforms[source] = (target, info.min, info.max, item['inverted'])
        initial = round((min(info.max, max(info.min, info.value)) - info.min) * 65535 / (info.max-info.min))
        axes.append((target, AbsInfo(65535-initial if item['inverted'] else initial, 0, 65535, 0, 0, 0)))
        sources.append(source)
    if data['hat']:
        for code in (e.ABS_HAT0X, e.ABS_HAT0Y):
            if code not in available:
                raise ValueError('Assigned R25 hat is unavailable')
            axes.append((code, available[code])); sources.append(code)
    else:
        # Preserve the fixed POV descriptor even when no source is assigned.
        for code in (e.ABS_HAT0X, e.ABS_HAT0Y):
            axes.append((code, AbsInfo(0, -1, 1, 0, 0, 0)))
    buttons = {code: e.BTN_JOYSTICK + i for i, code in enumerate(data['buttons']) if code is not None}
    missing = set(buttons) - set(capabilities.get(e.EV_KEY, []))
    if missing:
        raise ValueError(f'Assigned R25 buttons are unavailable: {sorted(missing)}')
    # Keep disabled slots advertised so DirectInput never renumbers later buttons.
    events = {e.EV_ABS: axes, e.EV_KEY: list(range(e.BTN_JOYSTICK, e.BTN_JOYSTICK + 11))}
    effects = [code for code in capabilities.get(e.EV_FF, []) if code != e.FF_CUSTOM]
    if effects:
        events[e.EV_FF] = effects
    return Profile('g920', events, buttons, tuple(sources), transforms)
