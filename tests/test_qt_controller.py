import os
import threading
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from mozaproxy.qt_controller import Controller


class Backend:
    def __init__(self):
        self.calls = []
        self.value = 0
        self.snapshot_error = None
        self.close_error = None

    def snapshot(self):
        self.calls.append(('snapshot', threading.get_ident()))
        if self.snapshot_error:
            raise self.snapshot_error
        return {'value': self.value}

    def close(self):
        self.calls.append(('close', threading.get_ident()))
        if self.close_error:
            raise self.close_error


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend = Backend()
        self.controller = Controller(self.backend)
        self.snapshots = []
        self.results = []
        self.errors = []
        self.closed = []
        self.signal_threads = []
        self.controller.snapshot_ready.connect(self.on_snapshot)
        self.controller.operation_done.connect(self.on_result)
        self.controller.failed.connect(self.on_error)
        self.controller.closed.connect(self.on_closed)

    def on_snapshot(self, snapshot):
        self.signal_threads.append(threading.get_ident())
        self.snapshots.append(snapshot)

    def on_result(self, name, result):
        self.signal_threads.append(threading.get_ident())
        self.results.append((name, result))

    def on_error(self, name, error):
        self.signal_threads.append(threading.get_ident())
        self.errors.append((name, error))

    def on_closed(self):
        self.signal_threads.append(threading.get_ident())
        self.closed.append(True)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertTrue(predicate(), 'Qt callback did not arrive')

    def tearDown(self):
        self.controller.shutdown()
        self.wait_for(lambda: bool(self.closed))

    def test_creation_is_passive_and_refresh_delivers_on_gui_thread(self):
        self.assertEqual(self.backend.calls, [])
        self.assertTrue(self.controller.refresh())
        self.wait_for(lambda: bool(self.snapshots))
        self.assertEqual(self.snapshots, [{'value': 0}])
        self.assertFalse(self.controller.busy)
        self.assertNotEqual(self.backend.calls[0][1], threading.get_ident())
        self.assertEqual(self.signal_threads, [threading.get_ident()])

    def test_operation_and_following_snapshot_share_worker(self):
        def change():
            self.backend.calls.append(('change', threading.get_ident()))
            self.backend.value = 42
            return {'saved': True}

        self.assertTrue(self.controller.submit('change', change))
        self.wait_for(lambda: bool(self.snapshots))
        self.assertEqual(self.results, [('change', {'saved': True})])
        self.assertEqual(self.snapshots, [{'value': 42}])
        self.assertEqual([name for name, _ in self.backend.calls], ['change', 'snapshot'])
        self.assertEqual(len({ident for _, ident in self.backend.calls}), 1)
        self.assertNotEqual(self.backend.calls[0][1], threading.get_ident())
        self.assertEqual(set(self.signal_threads), {threading.get_ident()})

    def test_busy_rejects_operations_and_drops_repeated_refreshes(self):
        release = threading.Event()
        started = threading.Event()

        def slow():
            started.set()
            release.wait(3)

        try:
            self.assertTrue(self.controller.submit('slow', slow))
            self.assertTrue(started.wait(1))
            self.assertTrue(self.controller.busy)
            for _ in range(20):
                self.assertFalse(self.controller.refresh())
                self.assertFalse(self.controller.submit('duplicate', lambda: self.fail('Executed duplicate')))
            self.app.processEvents()
            self.assertEqual(self.results, [])
        finally:
            release.set()
        self.wait_for(lambda: not self.controller.busy)
        self.assertEqual([name for name, _ in self.backend.calls], ['snapshot'])
        self.assertEqual(self.results, [('slow', None)])

    def test_refreshes_do_not_accumulate_while_snapshot_is_pending(self):
        self.assertTrue(self.controller.refresh())
        for _ in range(20):
            self.assertFalse(self.controller.refresh())
        self.wait_for(lambda: not self.controller.busy)
        self.assertEqual(len(self.snapshots), 1)
        self.assertEqual(len(self.backend.calls), 1)

    def test_operation_error_is_reported_and_next_operation_can_run(self):
        def fail():
            raise ValueError('invalid value')

        self.controller.submit('apply', fail)
        self.wait_for(lambda: not self.controller.busy)
        self.assertEqual(self.errors, [('apply', 'invalid value')])
        self.assertEqual(self.results, [])
        self.assertTrue(self.controller.submit('retry', lambda: 5))
        self.wait_for(lambda: bool(self.results))
        self.assertEqual(self.results, [('retry', 5)])

    def test_snapshot_error_preserves_successful_operation_result(self):
        self.backend.snapshot_error = OSError('snapshot unavailable')
        self.controller.submit('save', lambda: 7)
        self.wait_for(lambda: not self.controller.busy)
        self.assertEqual(self.results, [('save', 7)])
        self.assertEqual(self.errors, [('refresh', 'snapshot unavailable')])
        self.assertEqual(self.snapshots, [])

    def test_shutdown_is_nonblocking_and_closes_once_after_active_operation(self):
        release = threading.Event()
        started = threading.Event()

        def slow():
            self.backend.calls.append(('start', threading.get_ident()))
            started.set()
            release.wait(3)
            self.backend.calls.append(('finish', threading.get_ident()))

        try:
            self.controller.submit('slow', slow)
            self.assertTrue(started.wait(1))
            self.controller.shutdown()
            self.controller.shutdown()
            self.assertTrue(self.controller.closing)
            self.assertFalse(self.controller.refresh())
            self.assertFalse(self.controller.submit('late', lambda: None))
            self.app.processEvents()
            self.assertEqual(self.closed, [])
            self.assertEqual([name for name, _ in self.backend.calls], ['start'])
        finally:
            release.set()
        self.wait_for(lambda: bool(self.closed))
        names = [name for name, _ in self.backend.calls]
        self.assertEqual(names[-1], 'close')
        self.assertLess(names.index('finish'), names.index('close'))
        self.assertEqual(names.count('close'), 1)
        self.assertEqual(len({ident for _, ident in self.backend.calls}), 1)
        self.assertEqual(self.closed, [True])
        self.assertFalse(self.controller.busy)
        self.assertEqual(set(self.signal_threads), {threading.get_ident()})

    def test_close_error_still_signals_shutdown_completion(self):
        self.backend.close_error = OSError('close failed')
        self.controller.shutdown()
        self.wait_for(lambda: bool(self.closed))
        self.assertEqual(self.errors, [('close', 'close failed')])
        self.assertFalse(self.controller.busy)


if __name__ == '__main__':
    unittest.main()
