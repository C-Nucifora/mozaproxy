import os
import errno
import multiprocessing
from multiprocessing.reduction import recv_handle, send_handle
from pathlib import Path
import select
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from evdev import AbsInfo, UInput, ecodes as e
from evdev import _uinput

from mozaproxy.devices import SafeUInput


class DeviceTests(unittest.TestCase):
    def test_close_destroys_before_discovery_handle_and_is_idempotent(self):
        calls = []
        virtual = object.__new__(SafeUInput)
        virtual.fd = 123
        virtual.device = SimpleNamespace(close=lambda: calls.append('discovery'))
        with patch('evdev.uinput._uinput.close', side_effect=lambda fd: calls.append(('destroy', fd))):
            virtual.close()
            virtual.close()
        self.assertEqual(calls, [('destroy', 123), 'discovery'])
        self.assertEqual(virtual.fd, -1)
        self.assertIsNone(virtual.device)

    def test_destroy_failure_still_closes_discovery_and_forgets_both_handles(self):
        calls = []
        virtual = object.__new__(SafeUInput)
        virtual.fd = 123
        virtual.device = SimpleNamespace(close=lambda: calls.append('discovery'))
        with patch('evdev.uinput._uinput.close', side_effect=OSError(errno.EIO, 'destroy failed')) as destroy:
            with self.assertRaisesRegex(OSError, 'destroy failed'):
                virtual.close()
            virtual.close()
            destroy.assert_called_once_with(123)
        self.assertEqual(calls, ['discovery'])
        self.assertEqual(virtual.fd, -1)
        self.assertIsNone(virtual.device)

    def test_discovery_close_failure_still_leaves_device_destroyed(self):
        virtual = object.__new__(SafeUInput)
        virtual.fd = 123
        def fail():
            raise OSError(errno.EIO, 'discovery close failed')
        virtual.device = SimpleNamespace(close=fail)
        with patch('evdev.uinput._uinput.close') as destroy:
            with self.assertRaisesRegex(OSError, 'discovery close failed'):
                virtual.close()
            virtual.close()
            destroy.assert_called_once_with(123)
        self.assertEqual(virtual.fd, -1)
        self.assertIsNone(virtual.device)

    def test_constructor_failure_closes_allocated_descriptor(self):
        fd = os.open('/dev/null', os.O_WRONLY)
        try:
            with patch.object(UInput, '_verify'), \
                 patch('evdev.uinput._uinput.open', return_value=fd), \
                 patch.object(UInput, '_prepare_events', side_effect=OSError('preparation failed')):
                with self.assertRaises(OSError):
                    SafeUInput({1: [288]})
            with self.assertRaises(OSError):
                os.fstat(fd)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


def pending_erase_close_worker(connection, parent_pid):
    """Own the virtual device in a disposable process; parent can rescue teardown."""
    virtual = None
    client = None
    try:
        virtual = SafeUInput({e.EV_ABS: [(e.ABS_X, AbsInfo(0, 0, 65535, 0, 0, 0))],
                              e.EV_KEY: [e.BTN_TRIGGER], e.EV_FF: [e.FF_CONSTANT]},
                             name='mozaproxy TEST pending erase', vendor=0x1209,
                             product=0xffff, phys='mozaproxy/test-pending-erase', max_effects=4)
        connection.send(('ready', virtual.device.path))
        send_handle(connection, virtual.fd, parent_pid)
        # A separate client avoids inheriting the producer's discovery handle.
        code = '''
import sys
from evdev import InputDevice, ecodes as e, ff
device = InputDevice(sys.argv[1])
device.upload_effect(ff.Effect(e.FF_CONSTANT, -1, 0, ff.Trigger(0, 0),
    ff.Replay(100, 0), ff.EffectType(ff_constant_effect=ff.Constant(
        level=100, ff_envelope=ff.Envelope(0, 0, 0, 0)))))
device.close()
'''
        client = subprocess.Popen([sys.executable, '-c', code, virtual.device.path],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 4
        pending = False
        while time.monotonic() < deadline and not pending:
            if not select.select([virtual.fd], [], [], .05)[0]:
                continue
            for event in virtual.read():
                if event.type == e.EV_UINPUT and event.code == e.UI_FF_UPLOAD:
                    upload = virtual.begin_upload(event.value)
                    upload.retval = 0
                    virtual.end_upload(upload)
                elif event.type == e.EV_UINPUT and event.code == e.UI_FF_ERASE:
                    # Stop handling requests at exactly the game-client close race.
                    pending = True
                    break
        if not pending:
            raise AssertionError('Client did not request FF erase')
        connection.send(('erase_pending',))
        started = time.monotonic()
        virtual.close()
        elapsed = time.monotonic() - started
        stdout, stderr = client.communicate(timeout=3)
        if client.returncode:
            raise AssertionError(stderr)
        connection.send(('closed', elapsed))
    except BaseException as exc:
        connection.send(('error', repr(exc)))
        raise
    finally:
        if client is not None and client.poll() is None:
            client.kill()
            client.communicate(timeout=4)
        if virtual is not None:
            virtual.close()
        connection.close()


@unittest.skipUnless(os.environ.get('MOZAPROXY_TEST_UINPUT') == '1',
                     'Set MOZAPROXY_TEST_UINPUT=1 for virtual-only kernel teardown test')
class DeviceKernelTests(unittest.TestCase):
    def test_close_unblocks_pending_client_erase_and_removes_node(self):
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        worker = context.Process(target=pending_erase_close_worker, args=(child, os.getpid()))
        rescue_fd = None
        device_path = None
        worker.start()
        child.close()
        try:
            self.assertTrue(parent.poll(5), 'Virtual producer did not start')
            ready = parent.recv()
            self.assertEqual(ready[0], 'ready', ready)
            device_path = ready[1]
            rescue_fd = recv_handle(parent)
            self.assertTrue(parent.poll(5), 'No pending FF erase observed')
            self.assertEqual(parent.recv(), ('erase_pending',))
            self.assertTrue(parent.poll(2), 'SafeUInput.close blocked on pending FF erase')
            result = parent.recv()
            self.assertEqual(result[0], 'closed', result)
            self.assertLess(result[1], 2)
            worker.join(3)
            self.assertEqual(worker.exitcode, 0)
            self.assertFalse(Path(device_path).exists())
        finally:
            # UI_DEV_DESTROY cancels pending requests even with a duplicated fd.
            # This rescues the old implementation after the two-second failure.
            if rescue_fd is not None:
                _uinput.close(rescue_fd)
            worker.join(4)
            if worker.is_alive():
                worker.kill()
                worker.join(4)
            parent.close()
            if device_path is not None:
                self.assertFalse(Path(device_path).exists(), 'Virtual test node leaked')
