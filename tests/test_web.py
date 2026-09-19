import http.client
import io
import json
from pathlib import Path
import shlex
import tempfile
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from mozaproxy.app_state import AppState, PassiveMonitor, ProfileStore, RelayProcess, external_relays
from mozaproxy.web import create_server


SCHEMA = {'groups': [], 'settings': [
    {'id': 'gain', 'type': 'number', 'min': 0, 'max': 100, 'step': 1},
    {'id': 'mode', 'type': 'select', 'choices': [{'value': 0, 'label': 'Off'}, {'value': 1, 'label': 'On'}]},
]}


class Hardware:
    def __init__(self):
        self.calls = []

    def status(self):
        return {'connected': False, 'port': None, 'conflict': None, 'error': None, 'values': {}}

    def connect(self):
        self.calls.append('connect')
        return self.status()

    def disconnect(self):
        self.calls.append('disconnect')
        return self.status()

    def apply(self, settings):
        self.calls.append(settings)
        return {'applied': {}, 'errors': {'device': 'Disconnected'}, 'values': {}}

    def close(self):
        pass


class Monitor:
    def snapshot(self):
        return {'connected': False, 'name': None, 'path': None, 'axes': [], 'buttons': [], 'effects': [], 'slots': 0}

    def close(self):
        pass


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ProfileStore(Path(self.tmp.name), lambda: SCHEMA)

    def test_profile_round_trip_and_activation_do_not_write_hardware(self):
        saved = self.store.save({'name': 'Road', 'game_id': 'fh5', 'settings': {'gain': 40}})
        self.store.activate(saved['id'])
        loaded = ProfileStore(Path(self.tmp.name), lambda: SCHEMA)
        self.assertEqual(loaded.snapshot(), ([saved], saved['id']))
        loaded.delete(saved['id'])
        self.assertEqual(loaded.snapshot(), ([], None))
        self.assertEqual(list(Path(self.tmp.name).glob('*.tmp')), [])

    def test_bad_settings_never_persist(self):
        for settings in [{'gain': 10 ** 400}, {'gain': 101}, {'gain': True}, {'gain': float('nan')}, {'mode': 3}, {'unknown': 2}, []]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.store.save({'name': 'Bad', 'settings': settings})
        self.assertEqual(self.store.snapshot(), ([], None))

    def test_fractional_readback_can_be_saved_without_rounding(self):
        saved = self.store.save({'name': 'Actual', 'settings': {'gain': 49.804}})
        self.assertEqual(saved['settings']['gain'], 49.804)

    def test_failed_replace_preserves_previous_file_and_memory(self):
        saved = self.store.save({'name': 'Old', 'settings': {'gain': 10}})
        with patch('os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.store.save({'name': 'New', 'settings': {'gain': 20}})
        self.assertEqual(self.store.snapshot(), ([saved], None))
        self.assertEqual(ProfileStore(Path(self.tmp.name), lambda: SCHEMA).snapshot(), ([saved], None))

    def test_ids_and_missing_profiles_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save({'id': '../outside', 'name': 'Bad', 'settings': {}})
        with self.assertRaises(KeyError):
            self.store.activate('missing')
        with self.assertRaises(ValueError):
            self.store.save({'name': 'Bad', 'game_id': 'invented', 'settings': {}})


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hardware = Hardware()
        self.app = AppState(data_dir=Path(self.tmp.name), hardware=self.hardware,
                            monitor=Monitor(), schema_provider=lambda: SCHEMA)
        static = Path(self.tmp.name) / 'static'
        static.mkdir()
        (static / 'index.html').write_text('<!doctype html><title>Wheel</title>')
        (Path(self.tmp.name) / 'secret').write_text('private')
        (static / 'escape').symlink_to(Path(self.tmp.name) / 'secret')
        self.server = create_server(self.app, port=0, static_dir=static)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup_server)
        self.token = self.request('GET', '/api/session')[1]['token']

    def cleanup_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
        response = conn.getresponse()
        raw = response.read()
        status = response.status
        conn.close()
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw.decode()

    def auth(self, **extra):
        return {'X-Mozaproxy-Token': self.token, 'Content-Type': 'application/json', **extra}

    def test_mutations_require_token_json_and_local_origin(self):
        for headers in [{}, {'Content-Type': 'application/json'}, self.auth(Origin='https://evil.example'), self.auth(Host='evil.example')]:
            status, result = self.request('POST', '/api/hardware/connect', {}, headers)
            self.assertEqual(status, 403)
            self.assertIn('error', result)
        status, _ = self.request('POST', '/api/hardware/connect', {}, {'X-Mozaproxy-Token': self.token})
        self.assertEqual(status, 415)
        self.assertEqual(self.hardware.calls, [])
        self.assertEqual(self.request('POST', '/api/hardware/connect', {}, self.auth())[0], 200)
        self.assertEqual(self.hardware.calls, ['connect'])

    def test_hostile_host_and_origin_cannot_read_session(self):
        self.assertEqual(self.request('GET', '/api/session', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/api/session', headers={'Origin': 'null'})[0], 403)
        self.assertEqual(self.request('GET', '/api/session', headers={'Origin': 'http://localhost:9999'})[0], 403)

    def test_state_games_and_export_are_truthful_and_do_not_write(self):
        status, state = self.request('GET', '/api/state')
        self.assertEqual(status, 200)
        self.assertFalse(state['relay']['running'])
        self.assertEqual({g['id'] for g in state['games']}, {'fh5','jdm','fs22','fs25','ac','acc','heat','beamng','ets2'})
        games = {g['id']: g for g in state['games']}
        for game_id in ('fh5', 'jdm'):
            for field in ('status', 'input_status', 'ffb_status'):
                self.assertEqual(games[game_id][field], 'confirmed')
            self.assertIn('temporary T3 scanner exclusion', games[game_id]['detail'])
            self.assertIn('2026-09-18', games[game_id]['detail'])
            self.assertIn('manually configured local route', games[game_id]['detail'])
            self.assertIn('built-in game routing remains pending', games[game_id]['detail'])
        for game_id in ('fs22', 'fs25', 'ac', 'acc'):
            for field in ('status', 'input_status', 'ffb_status'):
                self.assertEqual(games[game_id][field], 'untested')
        self.assertIn('346e:0002', games['fh5']['detail'])
        self.assertIn('Proton 11.0', games['fh5']['detail'])
        self.assertIn('GE-Proton11-7', games['jdm']['detail'])
        self.assertEqual(shlex.split(games['jdm']['launch_options']), [
            'DISABLE_LSFGVK=1', 'PROTON_LOG=1', 'WINEDEBUG=-all',
            'PROTON_ENABLE_HIDRAW=0x346e/0x0000',
            'LD_PRELOAD=' + str(Path.home() / '.local/lib/mozaproxy/jdm_hid.so'),
            '%command%',
        ])
        self.assertEqual(games['ac']['launch_options'], '%command%')
        self.assertEqual(self.hardware.calls, [])
        status, report = self.request('GET', '/api/diagnostics/export')
        self.assertEqual(status, 200)
        self.assertIn('state', report)
        self.assertNotIn('token', json.dumps(report))
        self.assertLess(len(json.dumps(report)), 256000)

    def test_state_remains_available_while_hardware_connects(self):
        started = threading.Event()
        finished = threading.Event()
        def slow_connect():
            started.set()
            finished.wait(1.5)
            return self.hardware.status()
        self.hardware.connect = slow_connect
        thread = threading.Thread(target=lambda: self.request('POST', '/api/hardware/connect', {}, self.auth()))
        thread.start()
        try:
            self.assertTrue(started.wait(1))
            before = time.monotonic()
            self.assertEqual(self.request('GET', '/api/state')[0], 200)
            self.assertLess(time.monotonic() - before, 1)
        finally:
            finished.set()
            thread.join()

    def test_profile_api_activation_and_delete(self):
        status, profile = self.request('POST', '/api/profiles', {'name': 'Road', 'settings': {'gain': 50}}, self.auth())
        self.assertEqual(status, 200)
        path = '/api/profiles/' + profile['id']
        self.assertEqual(self.request('POST', path + '/activate', {}, self.auth())[0], 200)
        self.assertEqual(self.request('GET', '/api/state')[1]['active_profile'], profile['id'])
        self.assertEqual(self.hardware.calls, [])
        self.assertEqual(self.request('DELETE', path, {}, self.auth())[0], 200)
        self.assertEqual(self.request('DELETE', path, {}, self.auth())[0], 404)

    def test_invalid_settings_rejected_before_hardware_call(self):
        status, _ = self.request('POST', '/api/hardware/apply', {'settings': {'gain': 200}}, self.auth())
        self.assertEqual(status, 400)
        self.assertEqual(self.hardware.calls, [])
        status, result = self.request('POST', '/api/hardware/apply', {'settings': {'gain': 40}}, self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(result['applied'], {})
        self.assertIn('device', result['errors'])

    def test_default_document_symlink_cannot_escape_static_root(self):
        index = Path(self.tmp.name) / 'static' / 'index.html'
        index.unlink()
        index.symlink_to(Path(self.tmp.name) / 'secret')
        self.assertEqual(self.request('GET', '/')[0], 404)

    def test_traversal_and_symlink_escape_rejected(self):
        for path in ['/../secret', '/%2e%2e/secret', '/escape']:
            self.assertEqual(self.request('GET', path)[0], 404)
        self.assertEqual(self.request('GET', '/')[0], 200)


class MonitorTests(unittest.TestCase):
    def test_reads_real_axis_mapping_without_grabs_or_writes(self):
        from evdev import AbsInfo, ecodes as e
        from types import SimpleNamespace
        class Device:
            name = 'MOZA R25 Ultra Base'
            path = '/dev/input/event-test'
            ff_effects_count = 16
            def capabilities(self):
                return {e.EV_ABS: [(code, None) for code in (0, 2, 5, 6)], e.EV_KEY: [300, 301], e.EV_FF: [e.FF_CONSTANT]}
            def absinfo(self, code):
                return AbsInfo(0, -32768, 32767, 0, 0, 0)
            def active_keys(self):
                return [301]
            def close(self):
                pass
        with patch('mozaproxy.runtime.find_device', return_value=Device()):
            monitor = PassiveMonitor()
            try:
                for _ in range(100):
                    state = monitor.snapshot()
                    if state['connected']:
                        break
                    threading.Event().wait(0.01)
                self.assertTrue(state['connected'])
                self.assertEqual([axis['label'] for axis in state['axes']], ['Steering', 'Throttle', 'Brake', 'Clutch'])
                self.assertAlmostEqual(state['axes'][0]['value'], 0.5, places=4)
                self.assertEqual([button['pressed'] for button in state['buttons']], [False, True])
            finally:
                monitor.close()


class ShutdownTests(unittest.TestCase):
    def test_close_attempts_every_owned_resource_after_cleanup_failure(self):
        calls = []

        class Resource:
            def __init__(self, name, fails):
                self.name, self.fails = name, fails

            def close(self):
                calls.append(self.name)
                if self.fails:
                    raise OSError(self.name + ' cleanup failed')

        with tempfile.TemporaryDirectory() as folder:
            app = AppState(data_dir=folder, schema_provider=lambda: SCHEMA,
                           relay=Resource('relay', True), monitor=Resource('monitor', True),
                           hardware=Resource('hardware', False))
            with self.assertRaises(Exception) as raised:
                app.close()
        self.assertEqual(calls, ['relay', 'monitor', 'hardware'])
        self.assertIn('relay cleanup failed', str(raised.exception))
        self.assertIn('monitor cleanup failed', str(raised.exception))

    def test_sigterm_closes_owned_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'closed'
            code = """
import os, signal
from pathlib import Path
import mozaproxy.web as web
class App:
    def __init__(self, **kwargs): pass
    def close(self): Path(MARKER).write_text('closed')
class Server:
    server_port = 8765
    def serve_forever(self): os.kill(os.getpid(), signal.SIGTERM)
    def server_close(self): pass
web.AppState = App
web.create_server = lambda *args, **kwargs: Server()
web.main([])
""".replace('MARKER', repr(str(marker)))
            result = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(marker.read_text(), 'closed')


class RelayTests(unittest.TestCase):
    def test_external_relay_detection_excludes_web_diagnostics_and_owned_child(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for pid, args in [(101, ['python', '-m', 'mozaproxy', '--profile', 'compact']),
                              (102, ['python', '-m', 'mozaproxy.web']),
                              (103, ['python', 'mozaproxy.py', '--diagnose']),
                              (104, ['python', 'mozaproxy.py'])]:
                directory = root / str(pid)
                directory.mkdir()
                (directory / 'cmdline').write_bytes(('\0'.join(args) + '\0').encode())
            self.assertEqual(external_relays(root, owned_pid=104), [{'pid': 101, 'name': 'mozaproxy relay'}])

    def test_existing_external_relay_blocks_start(self):
        relay = RelayProcess()
        with patch('mozaproxy.app_state.external_relays', return_value=[{'pid': 77, 'name': 'mozaproxy relay'}]), patch('subprocess.Popen') as popen:
            with self.assertRaisesRegex(ValueError, '77'):
                relay.start({'profile': 'compact'})
            popen.assert_not_called()

    def test_stop_without_owned_process_never_signals_external_process(self):
        relay = RelayProcess()
        with patch('os.kill') as kill:
            self.assertFalse(relay.stop()['running'])
            kill.assert_not_called()

    def test_invalid_arguments_never_spawn(self):
        relay = RelayProcess()
        with patch('subprocess.Popen') as popen:
            for params in [{'profile': 'evil'}, {'profile': 'compact', 'product': -1}, {'profile': 'compact', 'name': ''}]:
                with self.assertRaises(ValueError):
                    relay.start(params)
            popen.assert_not_called()

    def test_only_owned_child_is_stopped_and_arguments_are_not_shell(self):
        relay = RelayProcess()
        with patch('mozaproxy.app_state.external_relays', return_value=[]), patch('subprocess.Popen') as popen:
            child = popen.return_value
            child.poll.return_value = None
            child.stdout = io.StringIO('')
            child.pid = 12345
            relay.start({'profile': 'compact', 'name': 'literal;$value', 'product': '0x0002'})
            args, kwargs = popen.call_args
            self.assertIn('literal;$value', args[0])
            self.assertFalse(kwargs.get('shell', False))
            with self.assertRaises(ValueError):
                relay.start({'profile': 'native'})
            relay.stop()
            child.terminate.assert_called_once()
            child.wait.assert_called()


if __name__ == '__main__':
    unittest.main()
