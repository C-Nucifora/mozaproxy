"""Virtual wheel capture tests. The opt-in test opens only its own uinput device."""

import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from evdev import InputDevice, InputEvent, ecodes as e, ff

from mozaproxy.harness import CommandReader, WheelHarness, compact_profile, run


def effect(kind=e.FF_CONSTANT, eid=0):
    return ff.Effect(kind, eid, 0x4000, ff.Trigger(3, 11), ff.Replay(700, 9),
                     ff.EffectType(ff_constant_effect=ff.Constant(
                         level=-1200, ff_envelope=ff.Envelope(12, 34, 56, 78))))


class Virtual:
    def __init__(self):
        self.writes = []
        self.completed = []
        self.upload = SimpleNamespace(effect=effect(), retval=None)
        self.erase = SimpleNamespace(effect_id=0, retval=None)

    def write(self, *args):
        self.writes.append(args)

    def syn(self):
        self.writes.append((e.EV_SYN, e.SYN_REPORT, 0))

    def begin_upload(self, request_id):
        return self.upload

    def end_upload(self, request):
        self.completed.append(('upload', request.retval))

    def begin_erase(self, request_id):
        return self.erase

    def end_erase(self, request):
        self.completed.append(('erase', request.retval))


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.virtual = Virtual()
        self.records = []
        self.harness = WheelHarness(self.virtual, lambda event, **data: self.records.append({'event': event, **data}))

    def upload(self, value):
        self.virtual.upload.effect = value
        self.harness.handle(InputEvent(0, 0, e.EV_UINPUT, e.UI_FF_UPLOAD, 1))

    def test_compact_neutral_axes_and_numbered_buttons(self):
        profile = compact_profile()
        axes = dict(profile.events[e.EV_ABS])
        self.assertEqual((axes[e.ABS_X].value, axes[e.ABS_X].min, axes[e.ABS_X].max), (32768, 0, 65535))
        for code in (e.ABS_Z, e.ABS_RZ, e.ABS_THROTTLE):
            self.assertEqual((axes[code].value, axes[code].min, axes[code].max), (-32768, -32768, 32767))
        for code in range(1, 8):
            self.assertEqual((axes[code].value, axes[code].fuzz), (-32768, 8))
        self.assertEqual(len(profile.events[e.EV_KEY]), 32)
        self.assertNotIn(e.FF_CUSTOM, profile.events[e.EV_FF])
        self.assertNotIn(e.FF_AUTOCENTER, profile.events[e.EV_FF])
        self.harness.command({'steer': -1, 'throttle': 1, 'brake': 0, 'clutch': .5, 'buttons': {'13': True}})
        self.assertEqual(self.virtual.writes, [
            (e.EV_ABS, e.ABS_X, 0), (e.EV_ABS, e.ABS_Z, 32767),
            (e.EV_ABS, e.ABS_RZ, -32768), (e.EV_ABS, e.ABS_THROTTLE, 0),
            (e.EV_KEY, 300, 1), (e.EV_SYN, e.SYN_REPORT, 0)])

    def test_bad_input_rejected_before_any_part_of_frame_is_written(self):
        for command in [[], {}, {'steer': 2}, {'throttle': -1}, {'brake': float('nan')},
                        {'clutch': True}, {'steer': 0, 'buttons': {'33': True}},
                        {'buttons': {'1': 1}}, {'steer': .5, 'unknown': 0},
                        {'stop': True, 'throttle': 1}, {'wait': -1}, {'stop': False}]:
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.harness.command(command)
        self.assertEqual(self.virtual.writes, [])

    def test_hat_directions_and_release_share_frames_with_other_controls(self):
        self.harness.command({'hat_x': -1, 'hat_y': 1, 'steer': 0})
        self.harness.command({'hat_x': 0, 'hat_y': 0})
        self.harness.command({'hat_x': 1, 'hat_y': -1, 'buttons': {'13': True}})
        self.assertEqual(self.virtual.writes, [
            (e.EV_ABS, e.ABS_X, 32768),
            (e.EV_ABS, e.ABS_HAT0X, -1), (e.EV_ABS, e.ABS_HAT0Y, 1),
            (e.EV_SYN, e.SYN_REPORT, 0),
            (e.EV_ABS, e.ABS_HAT0X, 0), (e.EV_ABS, e.ABS_HAT0Y, 0),
            (e.EV_SYN, e.SYN_REPORT, 0),
            (e.EV_ABS, e.ABS_HAT0X, 1), (e.EV_ABS, e.ABS_HAT0Y, -1),
            (e.EV_KEY, 300, 1), (e.EV_SYN, e.SYN_REPORT, 0)])
        self.assertEqual(self.records[1]['controls'], {'hat_x': 0, 'hat_y': 0})

    def test_invalid_hat_rejects_entire_frame_including_valid_steering(self):
        for name in ('hat_x', 'hat_y'):
            for value in (True, False, 1.0, 0.0, -.5, -2, 2, '1', None):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.harness.command({'steer': .5, name: value})
        with self.assertRaises(ValueError):
            self.harness.command({'hat_x': 1, 'buttons': {'13': 'pressed'}})
        self.assertEqual(self.virtual.writes, [])
        self.assertEqual(self.records, [])

    def test_upload_update_play_stop_controls_and_erase_capture(self):
        self.upload(effect())
        changed = effect()
        changed.u.ff_constant_effect.level = 456
        self.upload(changed)
        for code, value in [(0, 2), (0, 0), (e.FF_GAIN, 12345), (e.FF_AUTOCENTER, 900)]:
            self.harness.handle(InputEvent(0, 0, e.EV_FF, code, value))
        self.harness.handle(InputEvent(0, 0, e.EV_UINPUT, e.UI_FF_ERASE, 2))
        self.assertEqual([r['event'] for r in self.records], ['upload', 'update', 'start', 'stop', 'gain', 'autocenter', 'erase'])
        first = self.records[0]['effect']
        self.assertEqual(first['constant']['level'], -1200)
        self.assertEqual(first['constant']['envelope'], {'attack_length': 12, 'attack_level': 34, 'fade_length': 56, 'fade_level': 78})
        self.assertEqual(first['replay'], {'length': 700, 'delay': 9})
        self.assertEqual(self.records[1]['effect']['constant']['level'], 456)
        self.assertEqual(self.records[2]['value'], 2)
        self.assertEqual(self.virtual.completed, [('upload', 0), ('upload', 0), ('erase', 0)])
        self.assertEqual(self.virtual.writes, [])

    def test_periodic_ramp_rumble_and_two_axis_conditions_are_serialized(self):
        periodic = effect(e.FF_PERIODIC)
        periodic.u.ff_periodic_effect = ff.Periodic(e.FF_SINE, 90, -456, 12, 1024, ff.Envelope(1, 2, 3, 4), 0, None)
        self.upload(periodic)
        self.assertEqual(self.records[-1]['effect']['periodic']['magnitude'], -456)
        self.assertEqual(self.records[-1]['effect']['periodic']['waveform'], e.FF_SINE)
        ramp = effect(e.FF_RAMP)
        ramp.u.ff_ramp_effect = ff.Ramp(-200, 400, ff.Envelope(1, 2, 3, 4))
        self.upload(ramp)
        self.assertEqual(self.records[-1]['effect']['ramp']['start_level'], -200)
        self.assertEqual(self.records[-1]['effect']['type_name'], 'FF_RAMP')
        rumble = effect(e.FF_RUMBLE)
        rumble.u.ff_rumble_effect = ff.Rumble(1000, 2000)
        self.upload(rumble)
        self.assertEqual(self.records[-1]['effect']['rumble'], {'strong_magnitude': 1000, 'weak_magnitude': 2000})
        for kind in (e.FF_SPRING, e.FF_DAMPER, e.FF_FRICTION, e.FF_INERTIA):
            condition = effect(kind)
            condition.u.ff_condition_effect[0] = ff.Condition(1, 2, -3, 4, 5, -6)
            condition.u.ff_condition_effect[1] = ff.Condition(7, 8, 9, -10, 11, 12)
            self.upload(condition)
            values = self.records[-1]['effect']['conditions']
            self.assertEqual(values[0]['center'], -6)
            self.assertEqual(values[1]['left_coeff'], -10)
        json.dumps(self.records, allow_nan=False)

    def test_custom_waveform_is_rejected_without_dereferencing_pointer(self):
        value = effect(e.FF_PERIODIC)
        value.u.ff_periodic_effect = ff.Periodic(e.FF_CUSTOM, 100, 30, 0, 0, ff.Envelope(0, 0, 0, 0), 1, None)
        self.upload(value)
        self.assertEqual(self.virtual.completed, [('upload', -errno.EINVAL)])
        self.assertEqual(self.records[-1]['event'], 'upload_rejected')
        self.assertNotIn(0, self.harness.effects)

    def test_logging_failure_still_releases_kernel_upload_transaction(self):
        self.harness.record = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('disk full'))
        with self.assertRaisesRegex(OSError, 'disk full'):
            self.upload(effect())
        self.assertEqual(len(self.virtual.completed), 1)

    def test_command_reader_waits_for_complete_lines_and_bounds_bad_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'commands.jsonl'
            path.write_bytes(b'{"steer":')
            with CommandReader(path) as reader:
                self.assertIsNone(reader.read_line())
                with path.open('ab') as writer:
                    writer.write(b'0}\n' + b'x' * 9000 + b'\n{"stop":true}\n')
                self.assertEqual(json.loads(reader.read_line()), {'steer': 0})
                with self.assertRaises(ValueError):
                    reader.read_line()
                self.assertEqual(json.loads(reader.read_line()), {'stop': True})

    def test_run_releases_device_after_duration_and_logs_valid_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            commands, log = Path(folder) / 'commands', Path(folder) / 'capture'
            commands.write_text('{"wait":10}\n{"throttle":1}\n')
            read_fd, write_fd = os.pipe()
            fake = Virtual()
            fake.fd = read_fd
            fake.device = SimpleNamespace(path='/dev/input/test-only')
            fake.close = lambda: os.close(read_fd)
            try:
                with patch('mozaproxy.harness.SafeUInput', return_value=fake) as factory:
                    self.assertEqual(run(commands, log, duration=.02), 0)
                with self.assertRaises(OSError):
                    os.fstat(read_fd)
                rows = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertEqual(rows[0]['event'], 'session_start')
                self.assertEqual(rows[0]['device'], '/dev/input/test-only')
                self.assertEqual(rows[-1]['event'], 'session_end')
                self.assertEqual(rows[-1]['reason'], 'duration')
                self.assertTrue(all('timestamp' in row and 'elapsed' in row for row in rows))
                self.assertEqual(factory.call_args.kwargs['phys'], 'mozaproxy/test-harness')
                self.assertEqual(factory.call_args.kwargs['max_effects'], 10)
                self.assertNotIn((e.EV_ABS, e.ABS_Z, 32767), fake.writes)
            finally:
                os.close(write_fd)


@unittest.skipUnless(os.environ.get('MOZAPROXY_TEST_UINPUT') == '1',
                     'Set MOZAPROXY_TEST_UINPUT=1 for virtual-only kernel smoke test')
class KernelHarnessTests(unittest.TestCase):
    def test_created_virtual_wheel_captures_effects_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as folder:
            commands, log = Path(folder) / 'commands', Path(folder) / 'capture'
            process = subprocess.Popen([sys.executable, '-m', 'mozaproxy.harness',
                '--commands', str(commands), '--log', str(log), '--duration', '10'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            client = None
            def rows():
                return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            def wait_for(predicate):
                until = time.monotonic() + 4
                while time.monotonic() < until:
                    if predicate():
                        return
                    time.sleep(.01)
                self.fail('Timed out waiting for virtual harness')
            try:
                wait_for(lambda: any(row['event'] == 'session_start' for row in rows()))
                device = rows()[0]['device']
                client = InputDevice(device)
                self.assertEqual(client.phys, 'mozaproxy/test-harness')
                eid = client.upload_effect(effect(eid=-1))
                client.upload_effect(effect(eid=eid))
                client.write(e.EV_FF, eid, 2)
                client.write(e.EV_FF, eid, 0)
                client.write(e.EV_FF, e.FF_GAIN, 1234)
                client.erase_effect(eid)
                with commands.open('a') as writer:
                    writer.write('{"steer":0.5,"throttle":1,"buttons":{"13":true}}\n')
                wait_for(lambda: client.absinfo(e.ABS_X).value == 49151)
                self.assertEqual(client.absinfo(e.ABS_Z).value, 32767)
                self.assertIn(300, client.active_keys())
                wait_for(lambda: 'erase' in [r['event'] for r in rows()])
                client.close(); client = None
                with commands.open('a') as writer:
                    writer.write('{"stop":true}\n')
                stdout, stderr = process.communicate(timeout=4)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertFalse(Path(device).exists())
                events = [r['event'] for r in rows()]
                for event in ['upload', 'update', 'start', 'stop', 'gain', 'erase', 'input', 'session_end']:
                    self.assertIn(event, events)
            finally:
                if client is not None:
                    client.close()
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=4)


if __name__ == '__main__':
    unittest.main()
