from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from mozaproxy.system_service import ServiceBackend, UnixService


SCHEMA = {'groups': [], 'settings': [
    {'id': 'gain', 'type': 'number', 'min': 0, 'max': 100},
    {'id': 'enabled', 'type': 'boolean'},
]}


class Hardware:
    def __init__(self):
        self.connected = False
        self.values = {}
        self.closed = False

    def status(self):
        return {'connected': self.connected, 'values': self.values.copy(),
                'error': None, 'port': None, 'conflict': None}

    def connect(self):
        self.connected = True
        return self.status()

    def disconnect(self):
        self.connected = False
        return self.status()

    def apply(self, settings):
        self.values.update(settings)
        return {'applied': settings, 'values': self.values.copy(), 'errors': {}}

    def close(self):
        self.closed = True


class Monitor:
    def __init__(self):
        self.closed = False

    def snapshot(self):
        return {'connected': False, 'name': None, 'path': None, 'axes': [],
                'buttons': [], 'effects': [], 'slots': 0}

    def close(self):
        self.closed = True


class Relay:
    def __init__(self):
        self.running = False
        self.identity = None

    def status(self):
        return {'running': self.running, 'pid': 42 if self.running else None,
                'profile': 'compact' if self.identity else None, 'log': []}

    def start(self, settings):
        if self.running:
            raise ValueError('Already running')
        self.identity = settings.copy()
        self.running = True
        return self.status()

    def stop(self):
        self.running = False
        return self.status()

    close = stop


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'control.sock'
        self.hardware, self.monitor, self.relay = Hardware(), Monitor(), Relay()
        self.backend = ServiceBackend(hardware=self.hardware, monitor=self.monitor,
                                      relay=self.relay, schema_provider=lambda: SCHEMA)
        self.service = UnixService(self.path, os.getuid(), self.backend,
                                   request_timeout=0.3, max_clients=2)
        self.service.start()
        self.addCleanup(self.service.close)

    def raw(self, content):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(self.path))
            client.sendall(content)
            with client.makefile('rb') as stream:
                return json.loads(stream.readline(1048577))

    def request(self, method, params=None):
        return self.raw(json.dumps({'version': 1, 'method': method,
                                   'params': {} if params is None else params}).encode() + b'\n')

    def test_status_schema_and_fixed_relay_identity(self):
        state = self.request('status')
        self.assertTrue(state['ok'])
        self.assertEqual(set(state['result']), {'device', 'hardware', 'relay', 'integration'})
        self.assertEqual(state['result']['integration']['mode'], 'system')
        self.assertEqual(self.request('schema')['result'], SCHEMA)
        self.assertTrue(self.request('relay_start')['result']['running'])
        self.assertEqual(self.relay.identity,
                         {'profile': 'compact', 'name': 'MOZA R9 Base', 'product': 2})
        self.assertTrue(self.request('relay_start')['result']['running'])
        self.assertFalse(self.request('relay_stop')['result']['running'])

    def test_direct_default_and_process_liveness_do_not_claim_virtual_readiness(self):
        state = self.request('status')['result']
        self.assertEqual(state['integration'].get('default_route'), 'direct')
        self.assertEqual(state['integration'].get('physical_access'), 'desktop-and-service')
        self.assertIs(state['relay'].get('ready'), False)
        started = self.request('relay_start')['result']
        self.assertTrue(started['running'])
        self.assertIn('ready', started)
        self.assertIsNone(started['ready'])
        self.assertEqual(started['readiness'], 'unverified')
        self.assertIs(self.request('relay_stop')['result']['ready'], False)

    def test_hardware_apply_validates_before_any_write(self):
        self.assertTrue(self.request('hardware_connect')['result']['connected'])
        for settings in ({'gain': 101}, {'gain': True}, {'gain': float('nan')},
                         {'gain': -1}, {'path': '/dev/input/event1'}, {'enabled': 1}):
            with self.subTest(settings=settings):
                self.assertFalse(self.request('hardware_apply', {'settings': settings})['ok'])
                self.assertEqual(self.hardware.values, {})
        result = self.request('hardware_apply', {'settings': {'gain': 25, 'enabled': True}})
        self.assertEqual(result['result']['applied'], {'gain': 25, 'enabled': True})
        self.assertFalse(self.request('hardware_disconnect')['result']['connected'])

    def test_rejects_non_whitelisted_envelopes_and_parameters(self):
        requests = [[], {}, {'version': True, 'method': 'status', 'params': {}},
                    {'version': 2, 'method': 'status', 'params': {}},
                    {'version': 1, 'method': 'status', 'params': {}, 'id': 1},
                    {'version': 1, 'method': 'status', 'params': []}]
        for request in requests:
            self.assertFalse(self.raw(json.dumps(request).encode() + b'\n')['ok'])
        for method, params in [('shutdown', {}), ('relay_start', {'product': 7}),
                               ('relay_start', {'device': '/dev/input/event0'}),
                               ('hardware_connect', {'port': '/dev/ttyUSB0'}),
                               ('status', {'path': '/etc/shadow'}),
                               ('hardware_apply', {}), ('hardware_apply', {'settings': {}, 'raw': []})]:
            with self.subTest(method=method, params=params):
                self.assertFalse(self.request(method, params)['ok'])
        self.assertFalse(self.relay.running)
        self.assertFalse(self.hardware.connected)

    def test_malformed_oversized_and_duplicate_json_are_bounded(self):
        for message in (b'nope\n', b'\xff\n', b'[' * 2000 + b'\n', b' ' * 65536 + b'\n',
                        b'{"version":1,"version":1,"method":"status","params":{}}\n'):
            with self.subTest(size=len(message)):
                self.assertFalse(self.raw(message)['ok'])
        self.assertTrue(self.request('status')['ok'])

    def test_peer_uid_authorization_and_socket_permissions(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o660)
        self.service.client_uid = os.getuid() + 1
        self.assertFalse(self.request('hardware_connect')['ok'])
        self.assertFalse(self.hardware.connected)

    def test_idle_client_times_out_without_blocking_other_clients(self):
        with socket.socket(socket.AF_UNIX) as idle:
            idle.connect(str(self.path))
            idle.settimeout(2)
            idle.sendall(b'{')
            self.assertTrue(self.request('status')['ok'])
            response = json.loads(idle.recv(4096))
            self.assertFalse(response['ok'])

    def test_dribbling_bytes_cannot_extend_request_deadline(self):
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(str(self.path))
            client.settimeout(1)
            started = time.monotonic()
            for _ in range(3):
                client.sendall(b' ')
                time.sleep(0.07)
            reply = json.loads(client.recv(4096))
            self.assertFalse(reply['ok'])
            self.assertLess(time.monotonic() - started, 0.8)

    def test_two_requests_on_one_connection_cannot_write_settings(self):
        self.assertFalse(self.raw(b'{"version":1,"method":"status","params":{}}\n'
                                 b'{"version":1,"method":"hardware_connect","params":{}}\n')['ok'])
        self.assertFalse(self.hardware.connected)

    def test_response_limit_returns_error_and_server_recovers(self):
        with patch.object(self.monitor, 'snapshot', return_value={'axes': 'x' * 1048576}):
            self.assertFalse(self.request('status')['ok'])
        self.assertTrue(self.request('status')['ok'])

    def test_shutdown_closes_clients_components_and_owned_socket(self):
        self.request('relay_start')
        with socket.socket(socket.AF_UNIX) as idle:
            idle.connect(str(self.path))
            idle.settimeout(2)
            self.service.close()
            try:
                self.assertEqual(idle.recv(1), b'')
            except ConnectionResetError:
                pass  # A connection still in the accept backlog may be reset.
        self.assertFalse(self.path.exists())
        self.assertFalse(self.relay.running)
        self.assertTrue(self.hardware.closed)
        self.assertTrue(self.monitor.closed)

    def test_second_server_does_not_replace_live_socket(self):
        other = UnixService(self.path, os.getuid(), self.backend)
        with self.assertRaises((OSError, ValueError)):
            other.start()
        self.assertTrue(self.request('status')['ok'])

    def test_shutdown_does_not_unlink_replacement_path(self):
        self.path.unlink()
        self.path.write_text('preserve')
        self.service.close()
        self.assertEqual(self.path.read_text(), 'preserve')

    def test_refuses_symlink_and_foreign_runtime_directory(self):
        self.service.close()
        target = Path(self.directory.name) / 'target'
        target.write_text('keep')
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            UnixService(self.path, os.getuid(), self.backend).start()
        self.assertEqual(target.read_text(), 'keep')
        self.path.unlink()
        os.chmod(self.path.parent, 0o777)
        with self.assertRaises(ValueError):
            UnixService(self.path, os.getuid(), self.backend).start()
        os.chmod(self.path.parent, 0o700)

    def test_recovers_only_owned_stale_socket(self):
        self.service.close()
        with socket.socket(socket.AF_UNIX) as stale:
            stale.bind(str(self.path))
        replacement_backend = ServiceBackend(hardware=Hardware(), monitor=Monitor(),
                                             relay=Relay(), schema_provider=lambda: SCHEMA)
        replacement = UnixService(self.path, os.getuid(), replacement_backend)
        self.addCleanup(replacement.close)
        replacement.start()
        self.assertTrue(self.request('status')['ok'])

    def test_concurrency_limit_rejects_excess_idle_clients(self):
        idle = []
        try:
            for _ in range(2):
                client = socket.socket(socket.AF_UNIX)
                client.connect(str(self.path))
                client.sendall(b'{')
                idle.append(client)
            deadline = time.monotonic() + 0.2
            while len(self.service.clients) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            reply = self.request('status')
            self.assertFalse(reply['ok'])
            self.assertIn('clients', reply['error'])
        finally:
            for client in idle:
                client.close()


class CliTests(unittest.TestCase):
    def test_normal_startup_leaves_relay_off_until_explicit_request(self):
        from mozaproxy.system_service import main
        backend = ServiceBackend(hardware=Hardware(), monitor=Monitor(),
                                 relay=Relay(), schema_provider=lambda: SCHEMA)
        stopped = Mock()
        observed = []
        stopped.wait.side_effect = lambda: observed.append(backend.relay.status()['running'])
        with patch('mozaproxy.system_service.os.geteuid', return_value=1000), \
             patch('mozaproxy.system_service.create_backend', return_value=backend), \
             patch('mozaproxy.system_service.UnixService'), \
             patch('mozaproxy.system_service.threading.Event', return_value=stopped):
            self.assertEqual(main(['--client-uid', '1000']), 0)
        self.assertEqual(observed, [False])

    def test_disabled_backend_never_discovers_hardware_or_starts_processes(self):
        from mozaproxy.system_service import create_backend
        with patch('mozaproxy.system_service.PassiveMonitor', side_effect=AssertionError('physical discovery')), \
             patch('mozaproxy.system_service.RelayProcess', side_effect=AssertionError('real relay')), \
             patch('mozaproxy.hardware.discover_port', side_effect=AssertionError('serial discovery')):
            backend = create_backend(no_relay=True)
            self.addCleanup(backend.close)
            result = backend.dispatch({'version': 1, 'method': 'hardware_connect', 'params': {}})
            self.assertFalse(result['connected'])
            with self.assertRaises(ValueError):
                backend.dispatch({'version': 1, 'method': 'relay_start', 'params': {}})

    @unittest.skipIf(os.getuid() == 0, 'Service refuses root runtime')
    def test_no_relay_cli_serves_protocol_and_cleans_up_after_sigterm(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'control.sock'
            process = subprocess.Popen([sys.executable, '-m', 'mozaproxy.system_service',
                                        '--socket', str(path), '--client-uid', str(os.getuid()),
                                        '--no-relay'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not path.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(path.exists(), process.communicate(timeout=1) if process.poll() is not None else 'timeout')
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(2)
                    client.connect(str(path))
                    client.sendall(b'{"version":1,"method":"status","params":{}}\n')
                    response = json.loads(client.recv(65536))
                self.assertTrue(response['ok'])
                self.assertFalse(response['result']['relay']['running'])
                process.terminate()
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(stdout, b'')
                self.assertFalse(path.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_cli_refuses_root_before_constructing_components(self):
        from mozaproxy.system_service import main
        with redirect_stderr(io.StringIO()) as errors, \
             patch('mozaproxy.system_service.os.geteuid', return_value=0), \
             patch('mozaproxy.system_service.create_backend', side_effect=AssertionError('must not create')):
            self.assertEqual(main(['--client-uid', '1000', '--no-relay']), 1)
        self.assertIn('unprivileged', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
