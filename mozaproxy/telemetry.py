"""Loopback game telemetry preview and optional supported-wheel RPM LEDs."""
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


SOURCES = {'lmu': 'Le Mans Ultimate', 'acc': 'Assetto Corsa Competizione',
           'ac': 'Assetto Corsa', 'beamng': 'BeamNG.drive',
           'ets2': 'Euro Truck Simulator 2', 'fh5': 'Forza Horizon 5'}
BRIDGE_IDS = {'lmu': 1, 'acc': 2, 'ac': 3, 'ets2': 4}


def rpm_sample(rpm, maximum, racing, timestamp=None, stream=None):
    if not all(math.isfinite(v) for v in (rpm, maximum)) or not 0 <= rpm <= 100000 or not 0 < maximum <= 100000:
        raise ValueError('Invalid telemetry RPM range')
    count = min(10, max(0, math.ceil((rpm / maximum - 0.5) * 20))) if racing else 0
    return dict(rpm=rpm, maximum=maximum, racing=bool(racing), timestamp=timestamp,
                stream=stream, leds=count, mask=(1 << count) - 1)


def decode_packet(packet, source, maximum_rpm=None):
    if source == 'fh5':
        return decode_fh5(packet)
    if source == 'beamng':
        # BeamNG OutGauge has neither max RPM nor a useful clock (time is always 0).
        if len(packet) not in (92, 96) or packet[4:8] != b'beam':
            raise ValueError('Expected a BeamNG OutGauge packet')
        if maximum_rpm is None:
            raise ValueError('Set the BeamNG RPM scale for the current vehicle')
        return rpm_sample(struct.unpack_from('<f', packet, 16)[0], maximum_rpm, True)
    if source not in BRIDGE_IDS or len(packet) != 24:
        raise ValueError('Expected a Mozaproxy telemetry bridge packet')
    magic, version, game, flags, session, sequence, rpm, maximum = struct.unpack('<4sBBHIIff', packet)
    if magic != b'MZTP' or version != 1 or game != BRIDGE_IDS[source] or flags & ~1:
        raise ValueError('Telemetry bridge source or version does not match')
    return rpm_sample(rpm, maximum, flags & 1, sequence, session)


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

    def start(self, port=20777, output=False, source='fh5', maximum_rpm=None):
        if type(port) is not int or not 1024 <= port <= 65535 or type(output) is not bool:
            raise ValueError('Choose a UDP port from 1024 to 65535 and a boolean output option')
        if not isinstance(source, str) or source not in SOURCES:
            raise ValueError('Choose a supported telemetry source')
        if source == 'beamng' and (type(maximum_rpm) not in (int, float) or
                                   not math.isfinite(maximum_rpm) or not 100 <= maximum_rpm <= 100000):
            raise ValueError('Set the BeamNG RPM scale between 100 and 100000 for this vehicle')
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
            self.state = dict(running=True, output=output, port=port, source=source, maximum_rpm=maximum_rpm if source == 'beamng' else None, sample=None, error=None, stale=True)
            self.thread = threading.Thread(target=self._receive, args=(sock, output, source, maximum_rpm), daemon=True, name='game-telemetry')
            self.thread.start()
        return self.status()

    def _receive(self, sock, output, source, maximum_rpm):
        last_valid, last_send, last_timestamp = 0, 0, None
        cleared = False
        last_stream = None
        try:
            while not self.stop_event.is_set():
                if output and not self.hardware.status().get('telemetry_active'):
                    break
                sample = None
                try:
                    packet, address = sock.recvfrom(325)
                    if address[0] != '127.0.0.1':
                        continue
                    sample = decode_packet(packet, source, maximum_rpm)
                    timestamp = sample['timestamp']
                    stream = (address[1], sample.get('stream'))
                    if stream != last_stream:
                        if last_stream is not None and time.monotonic() - last_valid <= 0.5:
                            raise ValueError('Another telemetry sender is already active')
                        last_timestamp = None
                    if timestamp is not None and last_timestamp is not None and not 0 < (timestamp - last_timestamp) % 2**32 < 2**31:
                        sample = None
                    else:
                        last_stream = stream
                        last_timestamp = timestamp
                        last_valid = time.monotonic()
                        cleared = False
                        with self.lock:
                            self.state.update(sample=sample, stale=False)
                except (socket.timeout, ValueError):
                    sample = None
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
