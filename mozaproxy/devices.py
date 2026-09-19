"""Own uinput resources and release pending FF requests before evdev handles."""

import errno
import logging
import os

from evdev import UInput, _uinput


class SafeUInput(UInput):
    def __init__(self, *args, **kwargs):
        self.fd = -1
        self.device = None
        try:
            super().__init__(*args, **kwargs)
        except BaseException:
            try:
                # Some C setup failures already close this descriptor. Other
                # failures leave an unconfigured fd, so no destroy ioctl here.
                self._close_owned(os.close)
            except Exception as exc:
                if not isinstance(exc, OSError) or exc.errno != errno.EBADF:
                    logging.getLogger(__name__).exception('Partial uinput cleanup failed')
            raise

    def _close_owned(self, close_fd):
        fd, device = self.fd, self.device
        # Both close paths release ownership even when a syscall reports an
        # error; retrying a reused descriptor would close someone else's fd.
        self.fd, self.device = -1, None
        try:
            if fd >= 0:
                close_fd(fd)
        finally:
            if device is not None:
                device.close()

    def close(self):
        # UI_DEV_DESTROY cancels pending FF_UPLOAD/FF_ERASE requests before
        # unregistering. Closing the discovery evdev handle first can block on
        # another client's close, which is waiting for one of those requests.
        # python-evdev's C helper also closes fd if the destroy ioctl fails.
        self._close_owned(_uinput.close)
