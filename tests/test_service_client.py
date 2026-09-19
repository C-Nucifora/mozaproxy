"""System backend clients use fake sockets and never open input devices."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mozaproxy.service_client import ServiceClient, ServiceError, SystemAppState, select_backend
from mozaproxy.system_service import ServiceBackend, UnixService
from test_system_service import Hardware, Monitor, Relay, SCHEMA


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail = False

    def call(self, method, params=None):
        self.calls.append((method, params or {}))
        if self.fail:
            raise ServiceError('service unavailable')
        if method == 'status':
            return {'device': {'connected': True, 'name': 'MOZA', 'axes': [], 'buttons': []},
                    'hardware': {'connected': False, 'values': {}, 'error': None},
                    'relay': {'running': True, 'pid': 987, 'profile': 'compact', 'log': []},
                    'integration': {'mode': 'system'}}
        return {'connected': True, 'values': {}}

    def close(self):
        pass


class ServiceClientTests(unittest.TestCase):
    def exchange(self, reply, expected_uid=None):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'socket')
            server = socket.socket(socket.AF_UNIX)
            server.bind(path)
            server.listen(1)
            requests = []
            def serve():
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(1)
                    try:
                        data = conn.recv(65536)
                        if data:
                            requests.append(json.loads(data))
                            conn.sendall(reply)
                    except (OSError, ValueError):
                        pass
            thread = threading.Thread(target=serve)
            thread.start()
            try:
                result = ServiceClient(path, expected_uid=os.getuid() if expected_uid is None else expected_uid).call('status')
                return result, requests
            finally:
                thread.join(2)
                server.close()

    def test_versioned_exchange(self):
        result, requests = self.exchange(b'{"version":1,"ok":true,"result":{"connected":true}}\n')
        self.assertEqual(result, {'connected': True})
        self.assertEqual(requests, [{'version': 1, 'method': 'status', 'params': {}}])

    def test_untrusted_server_receives_no_request(self):
        with self.assertRaisesRegex(ServiceError, 'identity'):
            self.exchange(b'{}\n', expected_uid=os.getuid() + 1)

    def test_protocol_error_and_oversized_reply(self):
        for reply in (b'{"version":2,"ok":true,"result":{}}\n', b'not json\n',
                      b'{"version":1,"ok":false,"error":"denied"}\n',
                      b'x' * (1024 * 1024 + 1)):
            with self.subTest(reply=reply[:60]), self.assertRaises(ServiceError):
                self.exchange(reply)

    def test_duplicate_nonfinite_and_deeply_nested_responses_are_service_errors(self):
        for reply in (
            b'{"version":1,"version":1,"ok":true,"result":{}}\n',
            b'{"version":1,"ok":true,"result":{"value":NaN}}\n',
            b'{"version":1,"ok":true,"result":' + b'[' * 100000 + b'0' + b']' * 100000 + b'}\n',
        ):
            with self.subTest(reply=reply[:60]), self.assertRaises(ServiceError):
                self.exchange(reply)

    def test_dribbling_response_cannot_extend_client_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'dribble.sock')
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(path)
                server.listen(1)
                server.settimeout(1)

                def dribble():
                    try:
                        conn, _ = server.accept()
                    except OSError:
                        return
                    with conn:
                        conn.settimeout(1)
                        try:
                            conn.recv(65536)
                            for _ in range(30):
                                conn.sendall(b' ')
                                time.sleep(0.01)
                        except OSError:
                            pass

                thread = threading.Thread(target=dribble, daemon=True)
                thread.start()
                started = time.monotonic()
                try:
                    with self.assertRaises(ServiceError):
                        ServiceClient(path, expected_uid=os.getuid(), io_timeout=0.05).call('status')
                    self.assertLess(time.monotonic() - started, 0.2)
                finally:
                    thread.join(1)

    def test_disconnected_socket_is_actionable_error(self):
        with self.assertRaisesRegex(ServiceError, 'system service'):
            ServiceClient('/nonexistent/mozaproxy.sock', expected_uid=os.getuid()).call('status')

    def test_system_state_retains_local_profiles_and_close_never_stops_service(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient()
            backend = SystemAppState(client, data_dir=directory)
            state = backend.snapshot()
            self.assertEqual(state['integration']['mode'], 'system')
            self.assertTrue(state['relay']['running'])
            self.assertTrue(all(g['launch_options'] == '' for g in state['games']))
            for game in state['games']:
                for field in ('status', 'input_status', 'ffb_status'):
                    self.assertEqual(game[field], 'untested')
                self.assertIn('direct physical wheel, relay off', game['detail'])
                self.assertIn('still need validation', game['detail'])
            backend.profiles.save({'name': 'My setup', 'settings': {}, 'game_id': 'fh5'})
            self.assertEqual(len(backend.snapshot()['profiles']), 1)
            backend.close()
            self.assertEqual({c[0] for c in client.calls}, {'status'})

    def test_service_loss_clears_stale_readings_without_local_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient()
            backend = SystemAppState(client, data_dir=directory)
            self.assertTrue(backend.snapshot()['device']['connected'])
            client.fail = True
            state = backend.snapshot()
            self.assertFalse(state['device']['connected'])
            self.assertFalse(state['relay']['running'])
            self.assertFalse(state['integration']['available'])
            self.assertIn('service unavailable', state['hardware']['error'])

    def test_relay_identity_cannot_be_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient()
            backend = SystemAppState(client, data_dir=directory)
            with self.assertRaises(ValueError):
                backend.relay.start({'profile': 'native'})
            backend.relay.start({'profile': 'compact'})
            self.assertEqual(client.calls, [('relay_start', {})])

    def test_auto_mode_does_not_probe_or_connect_when_not_installed(self):
        with tempfile.TemporaryDirectory() as directory, patch('mozaproxy.service_client.AppState') as local:
            backend = select_backend(config_path=Path(directory) / 'absent')
            self.assertIs(backend, local.return_value)

    def test_installed_configuration_never_falls_back_to_local(self):
        with tempfile.TemporaryDirectory() as directory, patch('mozaproxy.service_client.AppState') as local:
            path = Path(directory) / 'system.json'
            path.write_text(json.dumps({'version': 1, 'client_uid': os.getuid(), 'socket': '/missing/service'}))
            with patch('mozaproxy.service_client.read_system_config', return_value=json.loads(path.read_text())), \
                 patch('mozaproxy.service_client.daemon_uid', return_value=os.getuid()):
                backend = select_backend(config_path=path, data_dir=directory)
            self.assertIsInstance(backend, SystemAppState)
            self.assertFalse(backend.snapshot()['integration']['available'])
            local.assert_not_called()

    def test_dangling_installed_config_fails_closed_without_local_hardware(self):
        with tempfile.TemporaryDirectory() as directory, patch('mozaproxy.service_client.AppState') as local:
            marker = Path(directory) / 'system.json'
            marker.symlink_to(Path(directory) / 'missing-config.json')
            with self.assertRaises(ServiceError):
                select_backend(config_path=marker)
            local.assert_not_called()


class LiveProtocolTests(unittest.TestCase):
    """Real client and daemon transport with hardware/processes replaced by fakes."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'service.sock'
        self.hardware, self.monitor, self.relay = Hardware(), Monitor(), Relay()
        daemon = ServiceBackend(hardware=self.hardware, monitor=self.monitor,
                                relay=self.relay, schema_provider=lambda: SCHEMA)
        self.service = UnixService(self.path, os.getuid(), daemon)
        self.service.start()
        self.addCleanup(self.service.close)
        self.client = ServiceClient(self.path, expected_uid=os.getuid())
        self.state = SystemAppState(self.client, data_dir=Path(self.directory.name) / 'profiles',
                                    schema_provider=lambda: SCHEMA)

    def test_real_round_trip_settings_profiles_and_fixed_relay(self):
        self.assertEqual(self.client.call('schema'), SCHEMA)
        self.assertTrue(self.state.hardware.connect()['connected'])
        self.assertEqual(self.state.hardware.apply({'gain': 28})['applied'], {'gain': 28})
        self.assertTrue(self.state.relay.start({'profile': 'compact'})['running'])
        self.assertTrue(self.state.relay.start({'profile': 'compact'})['running'])
        self.assertEqual(self.relay.identity,
                         {'profile': 'compact', 'name': 'MOZA R9 Base', 'product': 2})
        profile = self.state.profiles.save({'name': 'System setup', 'game_id': 'fh5',
                                          'settings': {'gain': 28}})
        state = self.state.snapshot()
        self.assertTrue(state['integration']['available'])
        self.assertEqual(state['hardware']['values'], {'gain': 28})
        self.assertEqual(state['profiles'], [profile])
        self.assertTrue(all(game['ffb_status'] == 'untested' for game in state['games']))
        self.assertFalse(self.state.relay.stop()['running'])
        self.assertFalse(self.state.hardware.disconnect()['connected'])

    def test_closing_system_app_preserves_running_daemon_and_hardware(self):
        self.state.hardware.connect()
        self.state.relay.start({'profile': 'compact'})
        self.state.close()
        another_window = ServiceClient(self.path, expected_uid=os.getuid())
        state = another_window.call('status')
        self.assertTrue(state['relay']['running'])
        self.assertTrue(state['hardware']['connected'])
        self.assertFalse(self.hardware.closed)
        self.assertFalse(self.monitor.closed)

    def test_daemon_loss_is_visible_and_local_profiles_survive_without_fallback(self):
        self.state.relay.start({'profile': 'compact'})
        profile = self.state.profiles.save({'name': 'Keep me', 'settings': {'gain': 41}})
        self.assertTrue(self.state.snapshot()['relay']['running'])
        self.service.close()
        with patch('mozaproxy.service_client.AppState', side_effect=AssertionError('local fallback')), \
             patch('mozaproxy.app_state.PassiveMonitor', side_effect=AssertionError('physical discovery')), \
             patch('mozaproxy.hardware.HardwareController', side_effect=AssertionError('physical settings')):
            state = self.state.snapshot()
        self.assertFalse(state['integration']['available'])
        self.assertFalse(state['device']['connected'])
        self.assertFalse(state['relay']['running'])
        self.assertEqual(state['profiles'], [profile])
        self.assertIn('system service', state['hardware']['error'])

    def test_real_authentication_and_validation_fail_before_mutations(self):
        self.service.client_uid = os.getuid() + 1
        with self.assertRaisesRegex(ServiceError, 'Unauthorized'):
            self.state.hardware.connect()
        self.assertFalse(self.hardware.connected)
        self.service.client_uid = os.getuid()
        with self.assertRaises(ServiceError):
            self.client.call('relay_start', {'product': 123})
        self.assertFalse(self.relay.running)
        with self.assertRaises(ServiceError):
            self.state.hardware.apply({'gain': 101})
        self.assertEqual(self.hardware.values, {})
