"""Unprivileged Qt backend for the installed system wheel service."""
from copy import deepcopy
import json
import os
from pathlib import Path
import pwd
import socket
import stat
import struct
import time

from .app_state import AppState, ProfileStore, games
from .settings import schema

DEFAULT_SOCKET = '/run/mozaproxy/control.sock'
SYSTEM_CONFIG = Path('/etc/mozaproxy/system.json')
MAX_REQUEST = 65536
MAX_RESPONSE = 1048576


class ServiceError(RuntimeError):
    pass


def _unique_members(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate response member')
        value[key] = item
    return value


def _invalid_number(value):
    raise ValueError('Non-finite JSON value')


def daemon_uid():
    try:
        return pwd.getpwnam('mozaproxy').pw_uid
    except KeyError:
        raise ServiceError('System service account is missing. Repair the system installation.') from None


class ServiceClient:
    def __init__(self, path=DEFAULT_SOCKET, expected_uid=None, io_timeout=2.0, operation_timeout=20.0):
        self.path = str(path)
        self.expected_uid = daemon_uid() if expected_uid is None else expected_uid
        self.io_timeout = io_timeout
        self.operation_timeout = operation_timeout

    def call(self, method, params=None):
        request = json.dumps({'version': 1, 'method': method, 'params': params or {}},
                             allow_nan=False).encode() + b'\n'
        if len(request) > MAX_REQUEST:
            raise ServiceError('Request exceeds the system service limit')
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                timeout = self.io_timeout if method in ('status', 'schema') else self.operation_timeout
                deadline = time.monotonic() + timeout
                conn.settimeout(timeout)
                conn.connect(self.path)
                _, uid, _ = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != self.expected_uid:
                    raise ServiceError('Unexpected system service identity; request was not sent')
                conn.sendall(request)
                data = bytearray()
                while b'\n' not in data:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ServiceError('System service response timed out')
                    conn.settimeout(remaining)
                    chunk = conn.recv(min(65536, MAX_RESPONSE + 1 - len(data)))
                    if not chunk:
                        raise ServiceError('System service closed an incomplete response')
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        raise ServiceError('System service response exceeds its limit')
                line, extra = data.split(b'\n', 1)
                if extra.strip():
                    raise ServiceError('Unexpected extra system service response')
                result = json.loads(line, object_pairs_hook=_unique_members, parse_constant=_invalid_number)
                if not isinstance(result, dict) or type(result.get('version')) is not int or result['version'] != 1:
                    raise ServiceError('Incompatible system service protocol')
                if result.get('ok') is not True:
                    raise ServiceError(str(result.get('error', 'System service rejected the request'))[:2000])
                if 'result' not in result:
                    raise ServiceError('System service response has no result')
                return result['result']
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            raise ServiceError(f'Cannot reach the mozaproxy system service: {exc}') from exc

    def close(self):
        # Connections are request-scoped. Closing Qt must not stop the wheel.
        pass


class RemoteHardware:
    def __init__(self, client):
        self.client = client

    def connect(self):
        return self.client.call('hardware_connect')

    def disconnect(self):
        return self.client.call('hardware_disconnect')

    def apply(self, settings):
        return self.client.call('hardware_apply', {'settings': settings})


class RemoteRelay:
    def __init__(self, client):
        self.client = client

    def start(self, data):
        if data != {'profile': 'compact'}:
            raise ValueError('The system service uses a fixed compact R9 identity')
        return self.client.call('relay_start')

    def stop(self):
        return self.client.call('relay_stop')


class SystemAppState:
    """Keep profiles local and delegate this app's device operations to the service."""
    def __init__(self, client, data_dir=None, schema_provider=schema):
        self.client = client
        self.schema_provider = schema_provider
        directory = Path(data_dir) if data_dir is not None else Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'mozaproxy'
        self.profiles = ProfileStore(directory, schema_provider)
        from .app_state import GameMappingStore
        self.game_mappings = GameMappingStore(directory)
        self.hardware = RemoteHardware(client)
        self.relay = RemoteRelay(client)

    def snapshot(self):
        error = None
        try:
            state = self.client.call('status')
            if not isinstance(state, dict) or not all(isinstance(state.get(k), dict) for k in ('device', 'hardware', 'relay', 'integration')):
                raise ServiceError('Invalid system service status')
            state = deepcopy(state)
            state['integration'].update(mode='system', available=True)
        except ServiceError as exc:
            error = str(exc)
            state = {'device': {'connected': False, 'name': None, 'axes': [], 'buttons': [], 'effects': [], 'slots': 0},
                     'hardware': {'connected': False, 'values': {}, 'error': error, 'conflict': None},
                     'relay': {'running': False, 'pid': None, 'profile': 'compact', 'log': []},
                     'integration': {'mode': 'system', 'available': False, 'error': error}}
        profiles, active = self.profiles.snapshot()
        state.update(profiles=profiles, active_profile=active)
        state.update(game_mappings=self.game_mappings.snapshot()[0], game_mapping_error=self.game_mappings.error)
        # Historical local-mode results do not validate a newly installed route.
        state['games'] = [dict(game, launch_options='', status='untested', input_status='untested',
                               ffb_status='untested', detail='Default route: direct physical wheel, relay off. Built-in game routing and this service setup still need validation; preserve any working manual game configuration.')
                          for game in games()]
        state['diagnostics'] = {'items': [
            {'label': 'Wheel service', 'status': 'error' if error else 'ok',
             'detail': error or 'Connected to the system service. Closing this window leaves the service running; the relay starts only when requested.'},
            {'label': 'Device presentation', 'status': 'warning',
             'detail': 'Physical wheel access is the default. The optional compact R9 relay does not hide the physical wheel. Installed permissions and game compatibility still need validation.'},
        ]}
        if self.profiles.error:
            state['diagnostics']['items'].append({'label': 'Profile storage', 'status': 'error', 'detail': self.profiles.error})
        return state

    def export(self):
        return AppState.export(self)

    def start_game_mapping(self, game_id):
        raise ValueError('Custom mappings can be saved here, but activation currently requires local app mode')

    def close(self):
        self.client.close()


def read_system_config(path):
    """Only a root-owned installation marker may select automatic system mode."""
    try:
        with open(path, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ServiceError('System integration configuration must be root-owned and not writable by other users')
            data = stream.read(16385)
        if len(data) > 16384:
            raise ValueError('configuration is too large')
        value = json.loads(data)
        if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1
                or type(value.get('client_uid')) is not int or value['client_uid'] != os.getuid()
                or value.get('socket') != DEFAULT_SOCKET):
            raise ValueError('configuration does not match this user or protocol')
        return value
    except (OSError, ValueError) as exc:
        raise ServiceError(f'Invalid mozaproxy system configuration: {exc}') from exc


def select_backend(mode='auto', data_dir=None, socket_path=None, config_path=SYSTEM_CONFIG):
    if mode not in ('auto', 'local', 'system'):
        raise ValueError('Backend must be auto, local or system')
    installed = os.path.lexists(config_path)
    if socket_path is not None and mode != 'system':
        raise ValueError('--service-socket requires --backend system')
    if mode == 'system' or (mode == 'auto' and installed):
        if installed:
            read_system_config(config_path)
        return SystemAppState(ServiceClient(socket_path or DEFAULT_SOCKET), data_dir=data_dir)
    if mode == 'local' and installed:
        raise ServiceError('System integration is installed. Roll it back before using local hardware mode.')
    return AppState(data_dir=data_dir)
