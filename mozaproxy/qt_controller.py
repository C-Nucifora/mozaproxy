"""Serialize backend access without blocking the Qt event loop."""

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot

if TYPE_CHECKING:
    from mozaproxy.app_state import AppState


class Controller(QObject):
    """Own an injected AppState and deliver worker results on the GUI thread.

    Call the public methods from the GUI thread. A busy controller drops
    refresh requests and rejects new operations instead of building a queue.
    Keep the controller alive until ``closed`` arrives during shutdown.
    """

    snapshot_ready = Signal(dict)
    operation_done = Signal(str, object)
    failed = Signal(str, str)
    closed = Signal()
    _completed = Signal(object)

    def __init__(self, appstate: 'AppState', parent: QObject | None = None):
        super().__init__(parent)
        self._state = appstate
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mozaproxy-ui')
        self._busy = False
        self._closing = False
        self._completed.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def closing(self) -> bool:
        return self._closing

    def refresh(self) -> bool:
        """Read one snapshot when idle; return whether work was accepted."""
        if self._busy or self._closing:
            return False
        self._busy = True
        self._executor.submit(self._run, 'refresh', None)
        return True

    def submit(self, name: str, callback: Callable[[], object]) -> bool:
        """Run an explicit operation, then read its updated snapshot."""
        if self._busy or self._closing:
            return False
        self._busy = True
        self._executor.submit(self._run, name, callback)
        return True

    def shutdown(self) -> None:
        """Close AppState after pending work and report completion asynchronously."""
        if self._closing:
            return
        self._closing = True
        self._busy = True
        self._executor.submit(self._close)
        self._executor.shutdown(wait=False)

    def _run(self, name: str, callback: Callable[[], object] | None) -> None:
        result = None
        operation_error = None
        snapshot = None
        snapshot_error = None
        if callback is not None:
            try:
                result = callback()
            except Exception as exc:
                operation_error = str(exc)
        try:
            snapshot = self._state.snapshot()
        except Exception as exc:
            snapshot_error = str(exc)
        self._completed.emit((False, name, callback is not None, result,
                              operation_error, snapshot, snapshot_error))

    def _close(self) -> None:
        error = None
        try:
            self._state.close()
        except Exception as exc:
            error = str(exc)
        self._completed.emit((True, 'close', False, None, error, None, None))

    @Slot(object)
    def _deliver(self, completion: tuple) -> None:
        is_close, name, operation, result, error, snapshot, snapshot_error = completion
        if is_close:
            self._busy = False
            if error is not None:
                self.failed.emit(name, error)
            self.closed.emit()
            return
        if not self._closing:
            self._busy = False
        if error is not None:
            self.failed.emit(name, error)
        elif operation:
            self.operation_done.emit(name, result)
        if snapshot_error is not None:
            self.failed.emit('refresh', snapshot_error)
        elif snapshot is not None and not self._closing:
            self.snapshot_ready.emit(snapshot)
