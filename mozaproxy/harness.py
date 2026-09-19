"""Test-only virtual compact R9 wheel: scripted inputs and FF capture, no motor output."""

import argparse
from datetime import datetime, timezone
import errno
import json
import math
import os
from pathlib import Path
import select
import signal
import stat
import threading
import time

from evdev import AbsInfo, ecodes as e

from .devices import SafeUInput
from .profiles import make_profile

FAMILY_NAMES = {e.FF_CONSTANT: 'FF_CONSTANT', e.FF_RAMP: 'FF_RAMP',
                e.FF_PERIODIC: 'FF_PERIODIC', e.FF_SPRING: 'FF_SPRING',
                e.FF_DAMPER: 'FF_DAMPER', e.FF_FRICTION: 'FF_FRICTION',
                e.FF_INERTIA: 'FF_INERTIA', e.FF_RUMBLE: 'FF_RUMBLE'}
FAMILIES = tuple(FAMILY_NAMES)
WAVEFORMS = (e.FF_SQUARE, e.FF_TRIANGLE, e.FF_SINE, e.FF_SAW_UP, e.FF_SAW_DOWN)
CONTROLS = {'steer': e.ABS_X, 'throttle': e.ABS_Z,
            'brake': e.ABS_RZ, 'clutch': e.ABS_THROTTLE}
HATS = {'hat_x': e.ABS_HAT0X, 'hat_y': e.ABS_HAT0Y}


def compact_profile():
    """Match the compact relay layout using synthetic, neutral R25 capabilities."""
    axes = [(e.ABS_X, AbsInfo(32768, 0, 65535, 0, 0, 0))]
    for code in range(1, 8):
        axes.append((code, AbsInfo(-32768, -32768, 32767, 8, 0, 0)))
    axes.extend((code, AbsInfo(0, -1, 1, 0, 0, 0)) for code in (e.ABS_HAT0X, e.ABS_HAT0Y))
    return make_profile({e.EV_ABS: axes, e.EV_KEY: list(range(288, 304)) + list(range(624, 656)),
                         e.EV_FF: [*FAMILIES, *WAVEFORMS, e.FF_GAIN]}, 'compact')


def _fields(structure):
    return {name: getattr(structure, name) for name, _ in structure._fields_}


def effect_payload(effect):
    """Copy the active union member; never dereference custom waveform pointers."""
    result = {'id': effect.id, 'type': effect.type,
              'type_name': FAMILY_NAMES.get(effect.type, f'UNKNOWN_{effect.type}'),
              'direction': effect.direction,
              'trigger': _fields(effect.ff_trigger), 'replay': _fields(effect.ff_replay)}
    if effect.type == e.FF_CONSTANT:
        value = effect.u.ff_constant_effect
        result['constant'] = {'level': value.level, 'envelope': _fields(value.ff_envelope)}
    elif effect.type == e.FF_RAMP:
        value = effect.u.ff_ramp_effect
        result['ramp'] = {'start_level': value.start_level, 'end_level': value.end_level,
                          'envelope': _fields(value.ff_envelope)}
    elif effect.type == e.FF_PERIODIC:
        value = effect.u.ff_periodic_effect
        result['periodic'] = {name: getattr(value, name) for name in
                              ('waveform', 'period', 'magnitude', 'offset', 'phase', 'custom_len')}
        result['periodic']['envelope'] = _fields(value.envelope)
    elif effect.type == e.FF_RUMBLE:
        result['rumble'] = _fields(effect.u.ff_rumble_effect)
    elif effect.type in (e.FF_SPRING, e.FF_DAMPER, e.FF_FRICTION, e.FF_INERTIA):
        result['conditions'] = [_fields(value) for value in effect.u.ff_condition_effect]
    return result


def _number(value, lower, upper, name):
    if type(value) not in (int, float) or not lower <= value <= upper or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number from {lower} to {upper}')
    return value


class WheelHarness:
    """Operate only the supplied virtual device; no physical discovery or forwarding."""

    def __init__(self, virtual, record):
        self.virtual = virtual
        self.record = record
        self.effects = {}
        self.buttons = compact_profile().events[e.EV_KEY]

    def command(self, data):
        """Write one validated frame, or return ('wait', seconds)/('stop', None)."""
        if not isinstance(data, dict) or not data:
            raise ValueError('Command must be a nonempty JSON object')
        if set(data) == {'wait'}:
            return 'wait', _number(data['wait'], 0, 86400, 'wait')
        if set(data) == {'stop'} and data['stop'] is True:
            return 'stop', None
        if set(data) - {*CONTROLS, *HATS, 'buttons'}:
            raise ValueError('Unknown or mixed command fields')
        events = []
        for name, code in CONTROLS.items():
            if name in data:
                value = _number(data[name], -1 if name == 'steer' else 0, 1, name)
                raw = round((value + 1) * 65535 / 2) if name == 'steer' else round(value * 65535 - 32768)
                events.append((e.EV_ABS, code, raw))
        for name, code in HATS.items():
            if name in data:
                value = data[name]
                if type(value) is not int or value not in (-1, 0, 1):
                    raise ValueError(f'{name} must be an integer -1, 0, or 1')
                events.append((e.EV_ABS, code, value))
        if 'buttons' in data:
            buttons = data['buttons']
            if not isinstance(buttons, dict) or not buttons:
                raise ValueError('buttons must map button numbers 1..32 to true or false')
            for number, pressed in buttons.items():
                if not isinstance(number, str) or number not in {str(i) for i in range(1, 33)} or type(pressed) is not bool:
                    raise ValueError('buttons must map button numbers 1..32 to true or false')
                events.append((e.EV_KEY, self.buttons[int(number) - 1], int(pressed)))
        for event in events:
            self.virtual.write(*event)
        self.virtual.syn()
        self.record('input', controls=data, events=events)
        return 'input', None

    def handle(self, event):
        if event.type == e.EV_UINPUT and event.code == e.UI_FF_UPLOAD:
            request = self.virtual.begin_upload(event.value)
            request.retval = -errno.EIO
            try:
                effect = request.effect
                payload = effect_payload(effect)
                periodic = payload.get('periodic', {})
                if effect.type not in FAMILIES or (effect.type == e.FF_PERIODIC and
                        (periodic['waveform'] not in WAVEFORMS or periodic['custom_len'])):
                    request.retval = -errno.EINVAL
                    self.record('upload_rejected', effect=payload, errno=errno.EINVAL)
                else:
                    action = 'update' if effect.id in self.effects else 'upload'
                    self.record(action, effect=payload)
                    self.effects[effect.id] = payload
                    request.retval = 0
            finally:
                self.virtual.end_upload(request)
        elif event.type == e.EV_UINPUT and event.code == e.UI_FF_ERASE:
            request = self.virtual.begin_erase(event.value)
            request.retval = -errno.EIO
            try:
                self.record('erase', effect_id=request.effect_id,
                            known=request.effect_id in self.effects)
                self.effects.pop(request.effect_id, None)
                request.retval = 0
            finally:
                self.virtual.end_erase(request)
        elif event.type == e.EV_FF:
            action = ('gain' if event.code == e.FF_GAIN else 'autocenter'
                      if event.code == e.FF_AUTOCENTER else 'start' if event.value else 'stop')
            self.record(action, code=event.code, value=event.value,
                        effect_id=event.code if event.code not in (e.FF_GAIN, e.FF_AUTOCENTER) else None,
                        known=event.code in self.effects)


class CommandReader:
    """Read an append-only JSONL file without acting on incomplete writes."""

    def __init__(self, path):
        if Path(path).exists() and not Path(path).is_file():
            raise ValueError('Commands must be a regular append-only file')
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('Commands must be a regular append-only file')
            self.stream = os.fdopen(fd, 'rb')
        except BaseException:
            os.close(fd)
            raise
        self.pending = b''
        self.discarding = False

    def read_line(self):
        while True:
            chunk = self.stream.readline(8193)
            if not chunk:
                return None
            if self.discarding:
                if chunk.endswith(b'\n'):
                    self.discarding = False
                    continue
                return None
            self.pending += chunk
            if len(self.pending) > 8192:
                self.pending = b''
                self.discarding = not chunk.endswith(b'\n')
                raise ValueError('Command line exceeds 8192 bytes')
            if chunk.endswith(b'\n'):
                line, self.pending = self.pending, b''
                return line.decode('utf-8')
            # Only one bounded chunk per poll if a writer has not finished its line.
            return None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stream.close()


def run(commands, log, duration=None, stop=None):
    """Create a test wheel until duration, stop command, or an external stop event."""
    if duration is not None:
        _number(duration, .001, 86400, 'duration')
    if Path(commands).resolve() == Path(log).resolve():
        raise ValueError('Commands and capture log must use different files')
    stop = stop if stop is not None else threading.Event()
    started = time.monotonic()
    profile = compact_profile()
    virtual = None
    reason = 'error'
    with Path(log).open('x', encoding='utf-8') as output, CommandReader(commands) as reader:
        def record(event, **data):
            row = {'timestamp': datetime.now(timezone.utc).isoformat(),
                   'elapsed': time.monotonic() - started, 'event': event, **data}
            output.write(json.dumps(row, allow_nan=False) + '\n')
            output.flush()

        try:
            virtual = SafeUInput(profile.events, name='MOZA R9 Base', vendor=0x346e,
                                product=0x0002, version=0x0111, bustype=e.BUS_USB,
                                phys='mozaproxy/test-harness', max_effects=10)
            harness = WheelHarness(virtual, record)
            for code, info in profile.events[e.EV_ABS]:
                virtual.write(e.EV_ABS, code, info.value)
            virtual.syn()
            record('session_start', device=virtual.device.path, test_only=True,
                   name='MOZA R9 Base', vendor=0x346e, product=0x0002,
                   commands=str(Path(commands).resolve()), profile='compact',
                   buttons={str(i + 1): code for i, code in enumerate(harness.buttons)},
                   neutral={str(code): info.value for code, info in profile.events[e.EV_ABS]})
            print(f'TEST ONLY: {virtual.device.path}; FF capture: {log}', flush=True)
            ready_at = 0
            while not stop.is_set():
                now = time.monotonic()
                if duration is not None and now - started >= duration:
                    reason = 'duration'
                    break
                if now >= ready_at:
                    for _ in range(32):
                        try:
                            line = reader.read_line()
                            if line is None:
                                break
                            action, value = harness.command(json.loads(line))
                            if action == 'stop':
                                reason = 'command'
                                stop.set()
                                break
                            if action == 'wait':
                                ready_at = time.monotonic() + value
                                record('wait', seconds=value)
                                break
                        except (ValueError, UnicodeError) as exc:
                            record('command_error', message=str(exc))
                if stop.is_set():
                    break
                timeout = .02
                if duration is not None:
                    timeout = min(timeout, max(0, duration - (time.monotonic() - started)))
                if select.select([virtual.fd], [], [], timeout)[0]:
                    try:
                        for event in virtual.read():
                            harness.handle(event)
                    except BlockingIOError:
                        pass
            if reason == 'error':
                reason = 'signal'
        finally:
            if virtual is not None:
                virtual.close()
            record('session_end', reason=reason)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Append JSON objects, one per line, to --commands. Existing lines run on startup.
  {"steer":0.5,"throttle":0.2,"brake":0,"clutch":0}
  {"buttons":{"13":true,"14":false}}
  {"hat_x":0,"hat_y":-1}
  {"wait":1.5}
  {"stop":true}
Steer is -1..1; pedals are 0..1 with 0 released. Buttons are compact slots 1..32.
Hats accept integers only: hat_x/hat_y -1, 0, or 1; 0 releases that direction.
wait delays following commands while FF capture continues. Use fresh command/log
paths per session; the log must not exist. Ctrl+C/SIGTERM also removes the device.
For timing-sensitive tests use /dev/shm for capture and an explicit --duration:
every FF event is serialized and flushed synchronously. Logs have no size cap.
Only a virtual wheel is created. No physical wheel is opened or force forwarded.''')
    parser.add_argument('--commands', type=Path, required=True, help='Append-only local JSONL input file, created if missing')
    parser.add_argument('--log', type=Path, required=True, help='New timestamped JSONL FF capture file')
    parser.add_argument('--duration', type=float, help='Stop after this many seconds, maximum 86400')
    args = parser.parse_args(argv)
    stop = threading.Event()
    previous = {number: signal.signal(number, lambda *_: stop.set()) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        return run(args.commands, args.log, args.duration, stop)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'wheel harness: {exc}\n')
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


if __name__ == '__main__':
    raise SystemExit(main())
