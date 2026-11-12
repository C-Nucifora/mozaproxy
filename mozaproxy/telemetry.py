"""Explicit loopback FH5 Data Out preview and optional supported-wheel LEDs."""
import math
import socket
import struct
import threading
import time


def decode_fh5(packet):
    # First 20 bytes of FH5's 324-byte Dash packet. Other game formats are not inferred.
    if len(packet) != 324:
        raise ValueError('Expected a 324-byte FH5 Dash packet')
    racing, timestamp, maximum, idle, rpm = struct.unpack_from('<iIfff', packet)
    if racing not in (0, 1) or not all(math.isfinite(v) for v in (maximum, idle, rpm)):
        raise ValueError('Invalid FH5 telemetry values')
    if not 0 <= idle < maximum <= 100000 or not 0 <= rpm <= 100000:
        raise ValueError('Invalid FH5 RPM range')
    # Start the bar at 50% of reported maximum. This is not the car's shift point.
    count = min(10, max(0, math.ceil((rpm / maximum - 0.5) * 20))) if racing else 0
    return dict(rpm=rpm, maximum=maximum, racing=bool(racing), timestamp=timestamp,
                leds=count, mask=(1 << count) - 1)


class TelemetryMonitor:
    def __init__(self, hardware=None):
        self.hardware = hardware
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.socket = None
        self.state = dict(running=False, output=False, sample=None, error=None, stale=True)

    def status(self):
        with self.lock:
            return dict(self.state)

    def start(self, port=20777, output=False):
        if type(port) is not int or not 1024 <= port <= 65535 or type(output) is not bool:
            raise ValueError('Choose a UDP port from 1024 to 65535 and a boolean output option')
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Stop the existing telemetry listener first')
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind(('127.0.0.1', port))
                sock.settimeout(0.05)
                if output:
                    if self.hardware is None or not hasattr(self.hardware, 'telemetry_begin'):
                        raise ValueError('LED output requires the local settings connection')
                    self.hardware.telemetry_begin()
            except Exception:
                sock.close()
                raise
            self.socket = sock
            self.stop_event.clear()
            self.state = dict(running=True, output=output, port=port, sample=None, error=None, stale=True)
            self.thread = threading.Thread(target=self._receive, args=(sock, output), daemon=True, name='fh5-telemetry')
            self.thread.start()
        return self.status()

    def _receive(self, sock, output):
        last_valid, last_send, last_timestamp = 0, 0, None
        cleared = False
        try:
            while not self.stop_event.is_set():
                if output and not self.hardware.status().get('telemetry_active'):
                    break
                sample = None
                try:
                    packet, address = sock.recvfrom(325)
                    if address[0] != '127.0.0.1':
                        continue
                    sample = decode_fh5(packet)
                    timestamp = sample['timestamp']
                    if last_timestamp is not None and not 0 < (timestamp - last_timestamp) % 2**32 < 2**31:
                        sample = None
                    else:
                        last_timestamp = timestamp
                        last_valid = time.monotonic()
                        cleared = False
                        with self.lock:
                            self.state.update(sample=sample, stale=False)
                except (socket.timeout, ValueError):
                    pass
                now = time.monotonic()
                if now - last_valid > 0.5:
                    with self.lock:
                        self.state['stale'] = True
                    if output and not cleared:
                        if self.hardware.telemetry_frame(0):
                            cleared = True
                elif output and sample and now - last_send >= 0.05:
                    self.hardware.telemetry_frame(sample['mask'])
                    last_send = now
        except (OSError, ValueError) as exc:
            with self.lock:
                self.state['error'] = str(exc)
        finally:
            if output:
                try:
                    self.hardware.telemetry_end()
                except (OSError, ValueError) as exc:
                    with self.lock:
                        self.state['error'] = str(exc)
            sock.close()
            with self.lock:
                self.state.update(running=False, output=False, stale=True)

    def stop(self):
        self.stop_event.set()
        thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
            if thread.is_alive():
                raise ValueError('Telemetry is still stopping; settings connection may be busy')
        if self.hardware is not None and hasattr(self.hardware, 'telemetry_end'):
            self.hardware.telemetry_end()
        return self.status()

    close = stop
