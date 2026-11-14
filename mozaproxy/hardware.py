"""Exclusive, request-driven serial settings. Connecting never changes settings."""

from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import os
import struct
import termios
import threading
import time
from dataclasses import replace
from pathlib import Path

from .settings import SETTINGS, validate_settings
from .base_lights import BaseLights


def encode_packet(group, device, command, payload):
    header = bytes([0x7E, len(command) + len(payload)])
    body = bytes([group, device]) + command + payload
    # MOZA doubles body/checksum 0x7e bytes; the checksum covers stuffed bytes.
    wire = header + body.replace(b'\x7e', b'\x7e\x7e')
    checksum = bytes([(sum(wire) + 13) & 255])
    return wire + checksum.replace(b'\x7e', b'\x7e\x7e')


def extract_packet(buffer):
    while buffer:
        if buffer[0] != 0x7E:
            del buffer[0]
            continue
        if len(buffer) < 2:
            return None
        frame = bytearray(buffer[:2])
        size, offset = buffer[1] + 5, 2
        while len(frame) < size:
            if offset >= len(buffer):
                return None
            value = buffer[offset]
            if value == 0x7E:
                if offset + 1 >= len(buffer):
                    return None
                if buffer[offset + 1] != 0x7E:
                    del buffer[:offset]
                    break
                offset += 1
            frame.append(value)
            offset += 1
        else:
            checksum = (sum(frame[:-1]) + frame[2:-1].count(0x7E) * 0x7E + 13) & 255
            if checksum != frame[-1]:
                del buffer[0]
                continue
            del buffer[:offset]
            return frame[2], frame[3], bytes(frame[4:-1])
    return None


def discover_port():
    matches = sorted(Path("/dev/serial/by-id").glob("*Gudsen*MOZA*Base*"))
    if len(matches) > 1:
        raise OSError(
            "Multiple MOZA bases found; connect only the intended base for settings"
        )
    return str(matches[0]) if matches else None


def serial_owners(port):
    owners = []
    target = os.path.realpath(port)
    for proc in Path("/proc").glob("[0-9]*"):
        if int(proc.name) == os.getpid():
            continue
        try:
            if any(os.path.realpath(fd) == target for fd in (proc / "fd").iterdir()):
                owners.append((int(proc.name), (proc / "comm").read_text().strip()))
        except (OSError, PermissionError):
            continue
    return owners


class HardwareController:
    def __init__(self):
        self._serial = None
        self._port = None
        self._values = {}
        self._error = None
        self._conflict = None
        self._busy = False
        self._last_apply = None
        self._calibration = {}
        self._telemetry_active = False
        self._telemetry_previous = None
        self._telemetry_pending = False
        self._telemetry_restoring = False
        self._telemetry_error = None
        self._calibration_timer = None
        self._calibration_token = None
        self._io_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._base_lights = BaseLights(encode_packet, extract_packet)

    def status(self):
        with self._state_lock:
            return dict(
                connected=self._serial is not None,
                port=self._port,
                conflict=self._conflict,
                error=self._error,
                busy=self._busy,
                values=dict(self._values),
                last_apply=deepcopy(self._last_apply),
                calibration=deepcopy(self._calibration),
                telemetry_active=self._telemetry_active,
                telemetry_restore_pending=self._telemetry_pending,
                telemetry_error=self._telemetry_error,
                base_telemetry_active=self._base_lights.active,
                base_capabilities=dict(self._base_lights.capabilities),
            )

    def connect(self):
        with self._io_lock:
            if self._calibration.get("active"):
                raise ValueError("Calibration stop is unresolved. Retry Stop while connected; if disconnected, recover the pedal with MOZA tools before restarting this app.")
            self._busy = True
            self._error = None
            self._conflict = None
            try:
                if self._serial is None:
                    self._port = discover_port()
                    if not self._port:
                        raise OSError("No MOZA serial device found")
                    owners = serial_owners(self._port)
                    if owners:
                        self._conflict = "Serial connection is in use by " + ", ".join(
                            f"{name} (PID {pid})" for pid, name in owners
                        )
                        return self.status()
                    import serial

                    port = serial.Serial(
                        self._port,
                        baudrate=115200,
                        timeout=0.06,
                        write_timeout=0.3,
                        exclusive=True,
                    )
                    try:
                        fcntl.ioctl(port.fileno(), termios.TIOCEXCL)
                    except BaseException:
                        port.close()
                        raise
                    self._serial = port
                    owners = serial_owners(self._port)
                    if owners:
                        self._conflict = "Serial connection is in use by " + ", ".join(
                            f"{name} (PID {pid})" for pid, name in owners
                        )
                        self._close_port()
                        return self.status()
                confirmed = {}
                read_deadline = time.monotonic() + 12
                for key, setting in SETTINGS.items():
                    if time.monotonic() >= read_deadline:
                        self._error = "Settings read reached its time limit; only confirmed values are available"
                        break
                    try:
                        try:
                            value = self._read_setting(setting)
                        except TimeoutError:
                            value = self._read_setting(setting)
                        validate_settings({key: value})
                        confirmed[key] = value
                    except (TimeoutError, ValueError):
                        pass
                with self._state_lock:
                    self._values = confirmed
                if not confirmed:
                    self._error = (
                        "Serial port opened, but no supported settings replied"
                    )
            except (OSError, ImportError) as exc:
                self._error = str(exc)
                self._close_port()
            finally:
                self._busy = False
            return self.status()

    def _close_port(self):
        with self._state_lock:
            port = self._serial
            self._serial = None
            self._values = {}
        if port is not None:
            try:
                fcntl.ioctl(port.fileno(), termios.TIOCNXCL)
            except OSError:
                pass
            port.close()

    def disconnect(self):
        with self._io_lock:
            self.calibration_stop()
            try:
                self.telemetry_end()
            finally:
                self._close_port()
            self._conflict = None
        return self.status()

    close = disconnect

    def _read_setting(self, setting):
        self._serial.reset_input_buffer()
        sentinel = (
            struct.pack(">f", 1.0)
            if setting.floating
            else (1).to_bytes(setting.size, "big")
        )
        self._serial.write(
            encode_packet(setting.read_group, setting.device, setting.command, sentinel)
        )
        deadline = time.monotonic() + 0.22
        buffer = bytearray()
        expected_device = ((setting.device & 15) << 4) | (setting.device >> 4)
        while time.monotonic() < deadline:
            buffer.extend(self._serial.read(max(1, self._serial.in_waiting)))
            while (packet := extract_packet(buffer)) is not None:
                group, device, payload = packet
                if (
                    group == setting.read_group ^ 0x80
                    and device == expected_device
                    and payload.startswith(setting.command)
                    and len(payload) == len(setting.command) + setting.size
                ):
                    return setting.decode(payload[len(setting.command) :])
        raise TimeoutError("No response from " + setting.label)

    def _write_setting(self, setting, value):
        self._serial.write(
            encode_packet(
                setting.write_group,
                setting.device,
                setting.write_command or setting.command,
                setting.encode(value),
            )
        )
        self._serial.flush()
        time.sleep(0.035)

    def telemetry_begin(self):
        with self._io_lock:
            if self._telemetry_pending:
                raise ValueError("Stop telemetry and restore its previous mode before starting again")
            if self._serial is None or self._calibration.get('active'):
                raise ValueError('Connect settings and finish calibration first')
            keys = ['telemetry_mode'] + [f'rpm_color_{i}' for i in range(1, 11)]
            if any(k not in self._values for k in keys):
                raise ValueError('Wheel has not confirmed the newer RPM color and telemetry-mode protocol')
            previous = self._values['telemetry_mode']
            colors = [bytes([i]) + SETTINGS[f'rpm_color_{i+1}'].encode(self._values[f'rpm_color_{i+1}']) for i in range(10)]
            self._telemetry_previous = previous
            self._telemetry_pending = True
            self._telemetry_error = None
            self._telemetry_restoring = True
            try:
                result = self.apply({'telemetry_mode': 1})
            finally:
                self._telemetry_restoring = False
            if result['errors']:
                self._telemetry_error = 'Telemetry activation was not confirmed. Stop telemetry to retry restoring the previous mode.'
                raise ValueError(self._telemetry_error)
            self._telemetry_active = True
            try:
                for offset in (0, 5):
                    self._serial.write(encode_packet(63, 23, b'\x19\x00', b''.join(colors[offset:offset+5])))
                self._serial.flush()
            except OSError:
                self.telemetry_end()
                raise

    def telemetry_frame(self, mask):
        if type(mask) is not int or not 0 <= mask <= 1023:
            raise ValueError('Invalid ten-light mask')
        if not self._io_lock.acquire(blocking=False):
            return False
        try:
            if not self._telemetry_active or self._serial is None or self._calibration.get('active'):
                return False
            self._serial.write(encode_packet(63, 23, b'\x1a\x00', mask.to_bytes(2, 'little')))
            self._serial.flush()
            return True
        finally:
            self._io_lock.release()

    def telemetry_end(self):
        with self._io_lock:
            base_error = None
            try:
                self.base_telemetry_end()
            except OSError as exc:
                base_error = str(exc)
            if self._telemetry_restoring or not (self._telemetry_active or self._telemetry_pending):
                if base_error:
                    raise OSError(base_error)
                return
            previous = self._telemetry_previous
            clear_error = base_error
            try:
                self.telemetry_frame(0)
            except OSError as exc:
                clear_error = str(exc)
            finally:
                self._telemetry_active = False
            self._telemetry_restoring = True
            try:
                if self._serial is not None and 'telemetry_mode' not in self._values:
                    value = self._read_setting(SETTINGS['telemetry_mode'])
                    validate_settings({'telemetry_mode': value})
                    self._values['telemetry_mode'] = value
                result = self.apply({'telemetry_mode': previous})
                if result['errors']:
                    raise ValueError('Previous telemetry mode could not be confirmed; reread wheel settings')
                self._telemetry_pending = False
                self._telemetry_error = clear_error
            except (OSError, ValueError) as exc:
                self._telemetry_error = str(exc)
                raise
            finally:
                self._telemetry_restoring = False
            if clear_error:
                raise OSError('Mode restored, but clearing LEDs failed: ' + clear_error)

    def base_telemetry_begin(self):
        with self._io_lock:
            if self._serial is None or self._calibration.get('active'):
                raise ValueError('Connect settings and finish calibration first')
            return self._base_lights.begin(self._serial)

    def base_telemetry_frame(self, color, mask):
        if not self._io_lock.acquire(blocking=False):
            return False
        try:
            if self._calibration.get('active'):
                return False
            return self._base_lights.frame(self._serial, color, mask)
        finally:
            self._io_lock.release()

    def base_telemetry_end(self):
        with self._io_lock:
            self._base_lights.end(self._serial)

    def calibration_start(self, pedal, idle_confirmed=False):
        """Address-25 base-connected pedal procedure, never a profile setting."""
        if pedal not in ('throttle', 'brake', 'clutch') or idle_confirmed is not True:
            raise ValueError('Select a pedal and confirm the game is stopped')
        with self._io_lock:
            if self._serial is None or self._calibration.get('active'):
                raise ValueError('Connect settings and finish any existing calibration first')
            if not all(pedal + suffix in self._values for suffix in ('_min', '_max', '_reverse')):
                raise ValueError('This pedal has not replied to the supported address-25 protocol')
            self.telemetry_end()
            token = object()
            self._calibration_token = token
            self._calibration = dict(active=True, pedal=pedal, outcome='start_unconfirmed', error=None)
            try:
                command = 12 + ('throttle', 'brake', 'clutch').index(pedal)
                self._serial.write(encode_packet(38, 25, bytes([command]), b'\x00\x01'))
                self._serial.flush()
                self._calibration['outcome'] = 'calibrating'
                self._calibration_timer = threading.Timer(7, self._calibration_expired, (token,))
                self._calibration_timer.daemon = True
                self._calibration_timer.start()
            except OSError:
                self.calibration_stop()
                raise
            return self.status()

    def _calibration_expired(self, token):
        with self._io_lock:
            if self._calibration_token is token:
                self.calibration_stop()

    def calibration_stop(self):
        with self._io_lock:
            if not self._calibration.get('active'):
                return self.status()
            pedal = self._calibration['pedal']
            self._calibration_token = None
            if self._calibration_timer:
                self._calibration_timer.cancel()
                self._calibration_timer = None
            stop_sent = False
            try:
                if self._serial is None:
                    raise OSError('Device disconnected before calibration could stop')
                command = 16 + ('throttle', 'brake', 'clutch').index(pedal)
                self._serial.write(encode_packet(38, 25, bytes([command]), b'\x00\x00'))
                self._serial.flush()
                stop_sent = True
                self._calibration.update(active=False, outcome='stop_sent')
                for suffix in ('_min', '_max'):
                    key = pedal + suffix
                    self._values.pop(key, None)
                    value = self._read_setting(SETTINGS[key])
                    validate_settings({key: value})
                    self._values[key] = value
                self._calibration['outcome'] = 'stop_sent_ranges_read'
            except (OSError, ValueError) as exc:
                self._calibration.update(active=not stop_sent, outcome='ranges_unconfirmed' if stop_sent else 'stop_unconfirmed', error=str(exc))
            return self.status()

    def apply(self, settings):
        with self._io_lock:
            if self._calibration.get("active"):
                raise ValueError("Finish calibration before applying settings")
            validate_settings(settings)
            validate_settings({**self._values, **settings})
            self.telemetry_end()
            if self._serial is None:
                raise ValueError("Connect the settings device first")
            applied, errors = {}, {}
            report = dict(time=datetime.now(timezone.utc).isoformat(), port=self._port, settings={})
            with self._state_lock:
                self._last_apply = report
            self._busy = True
            try:

                def write_order(item):
                    key, value = item
                    old = self._values.get(key)
                    # Widen a pedal's valid interval before narrowing its other edge.
                    widening = old is not None and (
                        (key.endswith("_min") and value < old)
                        or (key.endswith("_max") and value > old)
                    )
                    return 0 if widening else 1

                for key, value in sorted(settings.items(), key=write_order):
                    evidence = dict(previous=self._values.get(key), requested=value, actual=None,
                                    outcome='not_written', error=None)
                    report['settings'][key] = evidence
                    if key not in self._values:
                        errors[key] = (
                            "Unavailable: this device has not returned a valid value"
                        )
                        evidence["error"] = errors[key]
                        continue
                    setting = SETTINGS[key]
                    try:
                        if key.endswith(("_min", "_max")):
                            pedal = key.rsplit("_", 1)[0]
                            if any(
                                pedal + suffix not in self._values
                                for suffix in ("_min", "_max")
                            ):
                                raise ValueError(
                                    "Read both pedal boundaries before changing its range"
                                )
                        validate_settings({**self._values, key: value})
                        evidence["outcome"] = "written_unconfirmed"
                        self._write_setting(setting, value)
                        if key == "rotation":
                            paired = replace(setting, command=b"\x17")
                            self._write_setting(paired, value)
                            if abs(self._read_setting(paired) - value) > 1:
                                raise ValueError("Maximum angle readback did not match")
                        actual = self._read_setting(setting)
                        evidence["actual"] = actual
                        evidence["outcome"] = "confirmed_mismatch"
                        validate_settings({key: actual})
                        expected = setting.decode(setting.encode(value))
                        if setting.kind in ("boolean", "select", "color"):
                            matches = actual == expected
                        else:
                            matches = abs(actual - expected) <= 0.001
                        if not matches:
                            raise ValueError(
                                "Readback did not match the requested value"
                            )
                        with self._state_lock:
                            self._values[key] = actual
                        applied[key] = actual
                        evidence["outcome"] = "confirmed_match"
                    except (OSError, ValueError) as exc:
                        with self._state_lock:
                            self._values.pop(key, None)
                        errors[key] = str(exc)
                        evidence["error"] = str(exc)
            finally:
                self._busy = False
            return dict(applied=applied, errors=errors, values=self.status()["values"], report=deepcopy(report))
