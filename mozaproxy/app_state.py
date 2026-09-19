"""Local app state, passive input observation, and explicitly owned processes."""

from collections import deque
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import uuid

from .game_mappings import default_mapping, validate_mapping, write_mapping_document

ROOT = Path(__file__).resolve().parent.parent
GAME_IDS = {'fh5', 'jdm', 'fs22', 'fs25', 'ac', 'acc', 'heat', 'beamng', 'ets2'}


def games():
    isolation = shlex.join([sys.executable, str(ROOT / 'tools/run-game.py'), '--']) + ' %command%'
    jdm = shlex.join([
        'DISABLE_LSFGVK=1', 'PROTON_LOG=1', 'WINEDEBUG=-all',
        'PROTON_ENABLE_HIDRAW=0x346e/0x0000',
        'LD_PRELOAD=' + str(Path.home() / '.local/lib/mozaproxy/jdm_hid.so'),
    ]) + ' %command%'
    rows = [
        ('heat', 'Need for Speed Heat', 'Heat', 'partial', 'User confirmed working controls with the G920 relay after installing the Logitech wheel SDK runtime in Heat\'s Proton prefix. The G920 mapping preset includes the tested pedal, paddle and menu assignments. Saved mappings are reused; live editing is optional. SDK setup is separate. Physical FFB quality still needs validation.', isolation, 'confirmed', 'untested'),
        ('beamng', 'BeamNG.drive', 'BeamNG', 'partial', 'User confirmed wheel inputs on the direct route. Physical FFB quality still needs validation. Preserve the working manual configuration.', '%command%', 'confirmed', 'untested'),
        ('ets2', 'Euro Truck Simulator 2', 'ETS2', 'untested', 'Direct physical wheel baseline. Driving retest pending after the Steam scanner fix.', '%command%', 'untested', 'untested'),
        ('fh5', 'Forza Horizon 5', 'FH5', 'confirmed', 'Attended test on 2026-09-18 confirmed steering, pedals, paddles, physical FFB and smooth driving with Proton 11.0, compact MOZA R9 relay 346e:0002 and per-game physical-device isolation. This was a manually configured local route; built-in game routing remains pending. The temporary T3 scanner exclusion was active; its permanent fix remains pending.', isolation, 'confirmed', 'confirmed'),
        ('jdm', 'JDM: Japanese Drift Master', 'JDM', 'confirmed', 'Attended test on 2026-09-18 confirmed steering, pedals, paddles, physical FFB and no freezes with GE-Proton11-7, direct physical R25 HID and jdm_hid.so. Keep the relay stopped. This was a manually configured local route; built-in game routing remains pending. The temporary T3 scanner exclusion was active; its permanent fix remains pending.', jdm, 'confirmed', 'confirmed'),
        ('fs22', 'Farming Simulator 22', 'FS22', 'untested', 'Not tested with the rebuilt relay. Input and physical FFB need a driving test.', '%command%', 'untested', 'untested'),
        ('fs25', 'Farming Simulator 25', 'FS25', 'untested', 'Not tested with the rebuilt relay. Input and physical FFB need a driving test.', '%command%', 'untested', 'untested'),
        ('ac', 'Assetto Corsa', 'AC', 'untested', 'Keep the native device path. Direct-path regression test pending; no relay required by this setup.', '%command%', 'untested', 'untested'),
        ('acc', 'Assetto Corsa Competizione', 'ACC', 'untested', 'Keep the native device path. Direct-path regression test pending; no relay required by this setup.', '%command%', 'untested', 'untested'),
    ]
    fields = ('id', 'name', 'abbr', 'status', 'detail', 'launch_options', 'input_status', 'ffb_status')
    return [dict(zip(fields, row)) for row in rows]


def validate_settings(settings, schema):
    if not isinstance(settings, dict) or len(settings) > 100:
        raise ValueError('Settings must be an object with at most 100 values')
    definitions = {item['id']: item for item in schema['settings']}
    for key, value in settings.items():
        item = definitions.get(key)
        if item is None:
            raise ValueError(f'Unknown setting: {key}')
        if item.get('type') == 'boolean':
            if type(value) is not bool:
                raise ValueError(f'{key} must be a boolean')
        elif item.get('choices'):
            if isinstance(value, bool) or value not in [choice['value'] for choice in item['choices']]:
                raise ValueError(f'Invalid choice for {key}')
        else:
            if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
                raise ValueError(f'{key} must be a finite number')
            if value < item.get('min', -math.inf) or value > item.get('max', math.inf):
                raise ValueError(f'{key} is outside its allowed range')
            # Step is a UI increment; real wire readbacks may fall between steps.
    return deepcopy(settings)


class ProfileStore:
    """One bounded JSON document, replaced atomically after each explicit change."""

    def __init__(self, directory, schema_provider, filename='profiles.json'):
        self.path = Path(directory) / filename
        self.schema_provider = schema_provider
        self.lock = threading.RLock()
        self.profiles = []
        self.active = None
        self.error = None
        if self.path.exists():
            try:
                if self.path.stat().st_size > 262144:
                    raise ValueError('Saved profile file exceeds 256 KiB')
                data = json.loads(self.path.read_text())
                if not isinstance(data, dict) or not isinstance(data.get('profiles'), list) or len(data['profiles']) > 100:
                    raise ValueError('Invalid saved profile document')
                self.profiles = [self._validate(item) for item in data['profiles']]
                ids = [p['id'] for p in self.profiles]
                if len(set(ids)) != len(ids):
                    raise ValueError('Duplicate profile IDs')
                self.active = data.get('active_profile')
                if self.active is not None and self.active not in ids:
                    raise ValueError('Active profile does not exist')
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.profiles = []
                self.active = None
                self.error = f'Could not load profiles: {exc}'

    def _validate(self, data):
        if not isinstance(data, dict):
            raise ValueError('Profile must be an object')
        identifier = data.get('id', uuid.uuid4().hex)
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identifier):
            raise ValueError('Invalid profile ID')
        name = data.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Profile name must contain 1 to 80 printable characters')
        game = data.get('game_id')
        if game is not None and (not isinstance(game, str) or game not in GAME_IDS):
            raise ValueError('Unknown game')
        return {'id': identifier, 'name': name.strip(), 'game_id': game,
                'settings': validate_settings(data.get('settings', {}), self.schema_provider())}

    def _persist(self, profiles, active):
        if self.error:
            raise ValueError(self.error + '; preserve or repair the existing file before saving')
        content = json.dumps({'profiles': profiles, 'active_profile': active}, indent=2, allow_nan=False)
        if len(content.encode()) > 262144:
            raise ValueError('Profile storage exceeds 256 KiB')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.profiles-', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            self.profiles, self.active = profiles, active
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def snapshot(self):
        with self.lock:
            return deepcopy(self.profiles), self.active

    def save(self, data):
        with self.lock:
            profile = self._validate(data)
            profiles = [p for p in self.profiles if p['id'] != profile['id']] + [profile]
            if len(profiles) > 100:
                raise ValueError('At most 100 profiles may be saved')
            self._persist(profiles, self.active)
            return deepcopy(profile)

    def activate(self, identifier):
        with self.lock:
            if not any(p['id'] == identifier for p in self.profiles):
                raise KeyError('Profile not found')
            self._persist(self.profiles, identifier)

    def delete(self, identifier):
        with self.lock:
            if not any(p['id'] == identifier for p in self.profiles):
                raise KeyError('Profile not found')
            self._persist([p for p in self.profiles if p['id'] != identifier], None if self.active == identifier else self.active)


class GameMappingStore(ProfileStore):
    """Reuse atomic storage, keeping input mappings separate from hardware settings."""

    def __init__(self, directory):
        super().__init__(directory, None, filename='game-mappings.json')

    def _validate(self, data):
        if not isinstance(data, dict):
            raise ValueError('Game mapping must be an object')
        mapping = validate_mapping({k: v for k, v in data.items() if k != 'id'})
        if 'id' in data and data['id'] != mapping['game_id']:
            raise ValueError('Game mapping ID does not match its game')
        return dict(mapping, id=mapping['game_id'])

    def get(self, game_id):
        with self.lock:
            if self.error:
                raise ValueError(self.error)
            row = next((p for p in self.profiles if p['game_id'] == game_id), None)
            return {k: deepcopy(v) for k, v in row.items() if k != 'id'} if row else default_mapping(game_id)


class PassiveMonitor:
    """Read current evdev input state without grabbing, uploading or playing effects."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.device = None
        self.error = None
        self.state = self._empty()
        self.thread = threading.Thread(target=self._run, name='wheel-input', daemon=True)
        self.thread.start()

    @staticmethod
    def _empty():
        return {'connected': False, 'name': None, 'path': None, 'axes': [], 'buttons': [], 'effects': [], 'slots': 0}

    def _run(self):
        try:
            from evdev import ecodes as e
            from .runtime import find_device
        except ImportError as exc:
            with self.lock:
                self.error = str(exc)
            return
        labels = {e.ABS_X: 'Steering', e.ABS_Z: 'Throttle', e.ABS_RZ: 'Brake', e.ABS_THROTTLE: 'Clutch'}
        args = SimpleNamespace(device=None, vendor_real=0x346e, product_real=0, name_hint=None)
        while not self.stop_event.is_set():
            try:
                if self.device is None:
                    self.device = find_device(args)
                if self.device is None:
                    with self.lock:
                        self.state = self._empty()
                        self.error = 'No matching physical MOZA wheel found'
                    self.stop_event.wait(2)
                    continue
                dev = self.device
                caps = dev.capabilities()
                axes = []
                for code, _ in caps.get(e.EV_ABS, []):
                    info = dev.absinfo(code)
                    span = info.max - info.min
                    value = (info.value - info.min) / span if span else 0
                    axes.append({'code': code, 'label': labels.get(code, e.ABS.get(code, str(code))), 'raw': info.value,
                                 'min': info.min, 'max': info.max, 'value': max(0, min(1, value))})
                pressed = set(dev.active_keys())
                buttons = [{'code': code, 'label': str(e.BTN.get(code, code)), 'pressed': code in pressed} for code in caps.get(e.EV_KEY, [])]
                state = {'connected': True, 'name': dev.name, 'path': dev.path, 'axes': axes, 'buttons': buttons,
                         'effects': [str(e.FF.get(code, code)) for code in caps.get(e.EV_FF, [])], 'slots': dev.ff_effects_count}
                with self.lock:
                    self.state = state
                    self.error = None
            except (OSError, ValueError) as exc:
                if self.device:
                    self.device.close()
                    self.device = None
                with self.lock:
                    self.state = self._empty()
                    self.error = str(exc)
            self.stop_event.wait(0.1 if self.device else 2)
        if self.device:
            self.device.close()
            self.device = None

    def snapshot(self):
        with self.lock:
            return deepcopy(self.state)

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=3)


def external_relays(proc_root=Path('/proc'), owned_pid=None):
    """Report other relay processes without exposing their full command lines."""
    found = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) in (os.getpid(), owned_pid):
            continue
        try:
            with (entry / 'cmdline').open('rb') as handle:
                args = handle.read(8192).decode(errors='replace').strip('\0').split('\0')
        except OSError:
            continue
        module = any(args[index:index + 2] == ['-m', 'mozaproxy'] for index in range(len(args) - 1))
        script = any(Path(arg).name in ('mozaproxy.py', 'mozaproxy') for arg in args[:2])
        if (module or script) and '--diagnose' not in args:
            found.append({'pid': int(entry.name), 'name': 'mozaproxy relay'})
    return found[:32]


class RelayProcess:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.profile = None
        self.log = deque(maxlen=160)
        self.mapping_file = None
        self.mapping_game = None

    def status(self):
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            result = {'running': running, 'pid': self.process.pid if running else None,
                    'mapping_game': self.mapping_game if running else None,
                    'profile': self.profile, 'log': list(self.log)}
            if running and self.mapping_file:
                try:
                    with open(self.mapping_file + '.status') as stream:
                        result['mapping_status'] = json.loads(stream.read(16385))
                except (OSError, ValueError):
                    result['mapping_status'] = {'mapping': None, 'error': None}
            return result

    def _read_log(self, process):
        if process.stdout is None:
            return
        try:
            while True:
                line = process.stdout.readline(2048)
                if not line:
                    break
                with self.lock:
                    self.log.append(line.rstrip()[:2000])
        except (OSError, ValueError):
            pass
        finally:
            process.stdout.close()

    def start(self, data):
        mapping = validate_mapping(data['mapping']) if 'mapping' in data else None
        if mapping is not None and mapping['target'] == 'direct':
            raise ValueError('A direct configuration does not create a relay')
        profile = data.get('profile')
        if mapping is not None:
            profile = 'g920'
        if profile not in ('native', 'compact', 'g920'):
            raise ValueError('Relay profile must be native or compact')
        name = data.get('name', 'MOZA R9 Base' if profile == 'compact' else 'MOZA R25 (mozaproxy)')
        if not isinstance(name, str) or not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Relay name must contain 1 to 80 printable characters')
        product = data.get('product', 2)
        if isinstance(product, str):
            try:
                product = int(product, 0)
            except ValueError:
                raise ValueError('USB product must be an integer') from None
        if type(product) is not int or not 0 <= product <= 65535:
            raise ValueError('USB product must be between 0 and 65535')
        with self.lock:
            if self.status()['running']:
                raise ValueError('The app already owns a running relay')
            conflicts = external_relays()
            if conflicts:
                raise ValueError('Another relay is already running: PID ' + ', '.join(str(item['pid']) for item in conflicts))
            command = [sys.executable, '-m', 'mozaproxy', '--profile', profile, '--name', name, '--product', str(product)]
            if mapping is not None:
                self._clear_mapping_file()
                fd, self.mapping_file = tempfile.mkstemp(prefix='mozaproxy-mapping-', suffix='.json')
                with os.fdopen(fd, 'w') as stream:
                    json.dump(mapping, stream)
                command = [sys.executable, '-m', 'mozaproxy', '--mapping-file', self.mapping_file]
            elif profile == 'g920':
                command = [sys.executable, '-m', 'mozaproxy', '--profile', 'g920']
            try:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors='replace', bufsize=1, start_new_session=True)
            except Exception:
                self._clear_mapping_file()
                raise
            self.process = process
            self.mapping_game = mapping['game_id'] if mapping else None
            self.profile = profile
            self.log.clear()
            threading.Thread(target=self._read_log, args=(process,), name='relay-log', daemon=True).start()
            return self.status()

    def _clear_mapping_file(self):
        if self.mapping_file is not None:
            Path(self.mapping_file).unlink(missing_ok=True)
            Path(self.mapping_file + '.status').unlink(missing_ok=True)
            self.mapping_file = None

    def apply_mapping(self, mapping):
        mapping = validate_mapping(mapping)
        with self.lock:
            if not self.status()['running'] or not self.mapping_file:
                raise ValueError('Start a saved mapping before applying live changes')
            if mapping['game_id'] != self.mapping_game or mapping['target'] != 'g920':
                raise ValueError('Live changes must keep the same game and wheel layout')
            write_mapping_document(self.mapping_file, mapping)
            return {'queued': True}

    def stop(self):
        with self.lock:
            process = self.process
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            self.process = None
            self._clear_mapping_file()
            return self.status()

    close = stop


class UnavailableHardware:
    def __init__(self, error):
        self.error = str(error)

    def status(self):
        return {'connected': False, 'port': None, 'conflict': None, 'error': self.error, 'values': {}}

    connect = status
    disconnect = status

    def apply(self, settings):
        return {'applied': {}, 'errors': {'device': self.error}, 'values': {}}

    def close(self):
        pass


class AppState:
    def __init__(self, data_dir=None, hardware=None, monitor=None, relay=None, schema_provider=None):
        self.lock = threading.RLock()
        if hardware is None or schema_provider is None:
            try:
                from .hardware import HardwareController
                from .settings import schema
                if hardware is None:
                    hardware = HardwareController()
                if schema_provider is None:
                    schema_provider = schema
            except ImportError as exc:
                if hardware is None:
                    hardware = UnavailableHardware(exc)
                if schema_provider is None:
                    schema_provider = lambda: {'groups': [], 'settings': []}
        self.hardware = hardware
        self.schema_provider = schema_provider
        directory = Path(data_dir) if data_dir is not None else Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'mozaproxy'
        self.profiles = ProfileStore(directory, self.schema_provider)
        self.game_mappings = GameMappingStore(directory)
        self.monitor = monitor if monitor is not None else PassiveMonitor()
        self.relay = relay if relay is not None else RelayProcess()

    def snapshot(self):
        with self.lock:
            device = self.monitor.snapshot()
            hardware = self.hardware.status()
            relay = self.relay.status()
            profiles, active = self.profiles.snapshot()
            diagnostics = [
                {'label': 'Physical input', 'status': 'ok' if device['connected'] else 'warning', 'detail': device['name'] if device['connected'] else getattr(self.monitor, 'error', None) or 'Wheel not connected or input access unavailable'},
                {'label': 'Hardware settings', 'status': 'ok' if hardware['connected'] else 'warning', 'detail': hardware.get('error') or ('Connected; values are device readings' if hardware['connected'] else 'Disconnected. Connect explicitly to read settings')},
                {'label': 'Relay ownership', 'status': 'ok' if relay['running'] else 'info', 'detail': f"App owns relay PID {relay['pid']}" if relay['running'] else 'No relay started by this app'},
                {'label': 'Game validation', 'status': 'warning', 'detail': 'FH5 and JDM controls, physical FFB and smooth driving confirmed on their local routes. FS22, FS25, AC and ACC await attended regression. System wheel mode remains untested.'},
                {'label': 'Steam stalls', 'status': 'warning', 'detail': "T3 preview port scanning caused the stalls. Attended retests used a temporary exclusion of Steam from the scanner's lsof discovery; a permanent T3 fix remains pending."},
            ]
            conflicts = external_relays(owned_pid=relay['pid'])
            if conflicts:
                diagnostics.append({'label': 'Other relay process', 'status': 'warning', 'detail': 'Not owned by this app: PID ' + ', '.join(str(item['pid']) for item in conflicts)})
            if hardware.get('conflict'):
                diagnostics.append({'label': 'Settings owner conflict', 'status': 'error', 'detail': str(hardware['conflict'])})
            if self.profiles.error:
                diagnostics.append({'label': 'Profile storage', 'status': 'error', 'detail': self.profiles.error})
            return {'device': device, 'relay': relay, 'hardware': hardware, 'profiles': profiles,
                    'active_profile': active, 'games': games(),
                    'game_mappings': self.game_mappings.snapshot()[0],
                    'game_mapping_error': self.game_mappings.error,
                    'diagnostics': {'items': diagnostics}}

    def start_game_mapping(self, game_id):
        mapping = self.game_mappings.get(game_id)
        if mapping['target'] == 'direct':
            raise ValueError('This game uses direct physical access; leave the relay stopped')
        return self.relay.start({'mapping': mapping})

    def apply_game_mapping(self, game_id):
        return self.relay.apply_mapping(self.game_mappings.get(game_id))

    def export(self):
        state = self.snapshot()
        # Export only this app's bounded observations, never environment or arbitrary logs.
        state['relay']['log'] = [line[:500] for line in state['relay']['log'][-80:]]
        state['profiles'] = [{key: profile[key] for key in ('id', 'name', 'game_id')} for profile in state['profiles']]
        return {'version': 1, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'state': state}

    def close(self):
        errors = []
        for name, resource in (('relay', self.relay), ('monitor', self.monitor),
                               ('hardware', self.hardware)):
            try:
                resource.close()
            except Exception as exc:
                errors.append((name, exc))
        if errors:
            detail = '; '.join(f'{name}: {exc}' for name, exc in errors)
            raise RuntimeError(f'Could not close all app resources: {detail}') from errors[0][1]
