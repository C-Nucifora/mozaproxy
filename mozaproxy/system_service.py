"""Authenticated local settings and optional relay control for a MOZA wheel.

Each connection carries one JSON line and one response. Only the configured
desktop UID may issue requests; filesystem permissions are a second boundary.
The daemon account must own its private runtime directory.
"""

import argparse
import errno
import json
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import sys
import threading
import time

from .app_state import PassiveMonitor, RelayProcess, UnavailableHardware, validate_settings


DEFAULT_SOCKET = '/run/mozaproxy/control.sock'
MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 1048576
METHODS = frozenset(('status', 'schema', 'relay_start', 'relay_stop',
                     'hardware_connect', 'hardware_disconnect', 'hardware_apply'))
RELAY_IDENTITY = {'profile': 'compact', 'name': 'MOZA R9 Base', 'product': 2}


class ServiceBackend:
    """Small capability surface, independent of the desktop's profile store."""

    def __init__(self, *, hardware, monitor, relay, schema_provider):
        self.hardware = hardware
        self.monitor = monitor
        self.relay = relay
        self.schema_provider = schema_provider
        self.lock = threading.RLock()
        self.closed = False

    @staticmethod
    def relay_status(status):
        # The child PID alone cannot prove a usable virtual device or FFB.
        # Keep the existing running field as process liveness, explicitly separate
        # from readiness until the relay supplies a verified session handshake.
        return dict(status, ready=None if status['running'] else False,
                    readiness='unverified' if status['running'] else 'inactive')

    def dispatch(self, request):
        if not isinstance(request, dict) or set(request) != {'version', 'method', 'params'}:
            raise ValueError('Expected version, method and params')
        if type(request['version']) is not int or request['version'] != 1:
            raise ValueError('Unsupported protocol version')
        method, params = request['method'], request['params']
        if not isinstance(method, str) or method not in METHODS:
            raise ValueError('Unknown method')
        if not isinstance(params, dict):
            raise ValueError('Params must be an object')
        expected = {'settings'} if method == 'hardware_apply' else set()
        if set(params) != expected:
            raise ValueError('Unexpected method parameters')
        if not self.lock.acquire(timeout=1):
            raise ValueError('Service is busy; retry shortly')
        try:
            if self.closed:
                raise ValueError('Service is shutting down')
            if method == 'status':
                return {'device': self.monitor.snapshot(), 'hardware': self.hardware.status(),
                        'relay': self.relay_status(self.relay.status()), 'integration': {
                            'mode': 'system', 'owner': 'mozaproxy',
                            'default_route': 'direct', 'physical_access': 'desktop-and-service',
                            'game_validation': 'experimental',
                            'detail': 'Physical access remains available. The relay starts only on request; virtual game compatibility requires validation.'}}
            if method == 'schema':
                return self.schema_provider()
            if method == 'relay_start':
                # Repeated UI actions must not recreate the virtual device.
                current = self.relay.status()
                return self.relay_status(current if current['running'] else self.relay.start(dict(RELAY_IDENTITY)))
            if method == 'relay_stop':
                return self.relay_status(self.relay.stop())
            if method == 'hardware_connect':
                return self.hardware.connect()
            if method == 'hardware_disconnect':
                return self.hardware.disconnect()
            settings = validate_settings(params['settings'], self.schema_provider())
            return self.hardware.apply(settings)
        finally:
            self.lock.release()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            errors = []
            for component in (self.relay, self.monitor, self.hardware):
                try:
                    component.close()
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                raise RuntimeError('Service cleanup failed: ' + '; '.join(errors))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON member')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('Non-finite JSON numbers are forbidden')


class UnixService:
    """Bounded worker pool with Linux peer credentials and owned-socket cleanup."""

    def __init__(self, path, client_uid, backend, *, request_timeout=3, max_clients=8):
        if type(client_uid) is not int or client_uid < 0:
            raise ValueError('Client UID must be a nonnegative integer')
        if request_timeout <= 0 or max_clients < 1:
            raise ValueError('Timeout and client limit must be positive')
        self.path = Path(path).absolute()
        self.client_uid = client_uid
        self.backend = backend
        self.request_timeout = request_timeout
        self.max_clients = max_clients
        self.listener = None
        self.thread = None
        self.identity = None
        self.stopping = threading.Event()
        self.client_lock = threading.Lock()
        self.clients = set()
        self.workers = set()
        self.slots = threading.BoundedSemaphore(max_clients)
        self.closed = False

    def _prepare_path(self):
        parent = self.path.parent.stat()
        if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
            raise ValueError('Socket directory must be owned by the daemon and not writable by group or others')
        try:
            existing = self.path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(existing.st_mode) or existing.st_uid != os.geteuid():
            raise ValueError('Refusing to replace a foreign socket or non-socket path')
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(0.2)
            try:
                probe.connect(str(self.path))
            except OSError as exc:
                if exc.errno != errno.ECONNREFUSED:
                    raise ValueError('Existing socket cannot safely be replaced') from exc
            else:
                raise ValueError('Service socket is already active')
        current = self.path.lstat()
        if (current.st_dev, current.st_ino) != (existing.st_dev, existing.st_ino):
            raise ValueError('Socket path changed during startup')
        self.path.unlink()

    def start(self):
        if self.listener is not None or self.closed:
            raise ValueError('Service cannot be started twice')
        self._prepare_path()
        listener = socket.socket(socket.AF_UNIX)
        try:
            listener.bind(str(self.path))
            info = self.path.lstat()
            self.identity = info.st_dev, info.st_ino
            os.chmod(self.path, 0o660)
            listener.listen(self.max_clients)
            listener.settimeout(0.2)
        except BaseException:
            listener.close()
            self._unlink_owned_socket()

            raise
        self.listener = listener
        self.thread = threading.Thread(target=self._accept, name='wheel-service', daemon=True)
        self.thread.start()

    @staticmethod
    def _response(client, *, result=None, error=None):
        response = {'version': 1, 'ok': error is None}
        response.update({'result': result} if error is None else {'error': str(error)[:500]})
        try:
            line = json.dumps(response, allow_nan=False, separators=(',', ':')).encode() + b'\n'
        except (ValueError, TypeError, RecursionError):
            line = b'{"version":1,"ok":false,"error":"Invalid response"}\n'
        if len(line) > MAX_RESPONSE_BYTES:
            line = b'{"version":1,"ok":false,"error":"Response exceeds 1 MiB"}\n'
        try:
            client.sendall(line)
        except OSError:
            pass

    def _accept(self):
        while not self.stopping.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client.settimeout(self.request_timeout)
            if not self.slots.acquire(blocking=False):
                self._response(client, error='Too many clients')
                client.close()
                continue
            worker = threading.Thread(target=self._handle, args=(client,),
                                      name='wheel-request', daemon=True)
            with self.client_lock:
                if self.stopping.is_set():
                    client.close()
                    self.slots.release()
                    break
                self.clients.add(client)
                self.workers.add(worker)
                worker.start()

    def _read(self, client):
        deadline = time.monotonic() + self.request_timeout
        content = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('Request timed out')
            client.settimeout(remaining)
            chunk = client.recv(min(4096, MAX_REQUEST_BYTES + 1 - len(content)))
            if not chunk:
                raise ValueError('Request must end with a newline')
            content.extend(chunk)
            newline = content.find(b'\n')
            if len(content) > MAX_REQUEST_BYTES:
                raise ValueError('Request exceeds 64 KiB')
            if newline >= 0:
                if content[newline + 1:]:
                    raise ValueError('Only one request per connection is allowed')
                return json.loads(content[:newline], object_pairs_hook=_unique_object,
                                  parse_constant=_reject_constant)

    def _handle(self, client):
        try:
            credentials = client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
            _, uid, _ = struct.unpack('3i', credentials)
            if uid != self.client_uid:
                raise ValueError('Unauthorized peer UID')
            request = self._read(client)
            result = self.backend.dispatch(request)
            client.settimeout(self.request_timeout)
            self._response(client, result=result)
        except (ValueError, TypeError, UnicodeError, RecursionError, OSError) as exc:
            self._response(client, error=str(exc) or 'Invalid request')
        except Exception:
            self._response(client, error='Service operation failed')
        finally:
            client.close()
            with self.client_lock:
                self.clients.discard(client)
                self.workers.discard(threading.current_thread())
            self.slots.release()

    def _unlink_owned_socket(self):
        if self.identity is None:
            return
        try:
            info = self.path.lstat()
            if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == self.identity:
                self.path.unlink()
        except FileNotFoundError:
            pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stopping.set()
        if self.listener is not None:
            self.listener.close()
        with self.client_lock:
            clients, workers = list(self.clients), list(self.workers)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
        if self.thread is not None:
            self.thread.join(timeout=1)
        deadline = time.monotonic() + 20
        for worker in workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        try:
            self.backend.close()
        finally:
            self._unlink_owned_socket()


class _DisabledMonitor:
    def snapshot(self):
        return {'connected': False, 'name': None, 'path': None, 'axes': [],
                'buttons': [], 'effects': [], 'slots': 0}

    def close(self):
        pass


class _DisabledRelay:
    def status(self):
        return {'running': False, 'pid': None, 'profile': None, 'log': []}

    def start(self, settings):
        raise ValueError('Relay is disabled in --no-relay test mode')

    stop = status
    close = status


def create_backend(*, no_relay=False):
    from .settings import schema
    if no_relay:
        return ServiceBackend(hardware=UnavailableHardware('Hardware is disabled in --no-relay test mode'),
                              monitor=_DisabledMonitor(), relay=_DisabledRelay(), schema_provider=schema)
    from .hardware import HardwareController
    return ServiceBackend(hardware=HardwareController(), monitor=PassiveMonitor(),
                          relay=RelayProcess(), schema_provider=schema)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', default=DEFAULT_SOCKET)
    parser.add_argument('--client-uid', type=int, required=True,
                        help='Only this desktop UID may connect')
    parser.add_argument('--no-relay', action='store_true',
                        help='Test-only mode: disable all physical hardware access and relay processes')
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        print('Run the wheel service as its dedicated unprivileged account, never root.', file=sys.stderr)
        return 1
    if args.client_uid < 0:
        parser.error('--client-uid must be nonnegative')
    stop = threading.Event()
    previous = {}
    service = None
    backend = None
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, lambda _signal, _frame: stop.set())
        backend = create_backend(no_relay=args.no_relay)
        service = UnixService(args.socket, args.client_uid, backend)
        service.start()
        # Startup and restart preserve direct physical input. Relay creation is
        # an explicit authenticated operation, never a side effect of booting.
        stop.wait()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Wheel service: {exc}', file=sys.stderr)
        return 1
    finally:
        try:
            if service is not None:
                service.close()
            elif backend is not None:
                backend.close()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
