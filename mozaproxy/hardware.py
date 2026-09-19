"""Exclusive, request-driven serial settings. Connecting never changes settings."""

import fcntl
import os
import struct
import termios
import threading
import time
from dataclasses import replace
from pathlib import Path

from .settings import SETTINGS, validate_settings


def encode_packet(group, device, command, payload):
    frame = (
        bytes([0x7E, len(command) + len(payload), group, device]) + command + payload
    )
    return frame + bytes([(sum(frame) + 13) & 255])


def extract_packet(buffer):
    while buffer:
        if buffer[0] != 0x7E:
            del buffer[0]
            continue
        if len(buffer) < 2:
            return None
        size = buffer[1] + 5
        if len(buffer) < size:
            return None
        frame = buffer[:size]
        if (sum(frame[:-1]) + 13) & 255 != frame[-1]:
            del buffer[0]
            continue
        del buffer[:size]
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
        self._io_lock = threading.RLock()
        self._state_lock = threading.RLock()

    def status(self):
        with self._state_lock:
            return dict(
                connected=self._serial is not None,
                port=self._port,
                conflict=self._conflict,
                error=self._error,
                busy=self._busy,
                values=dict(self._values),
            )

    def connect(self):
        with self._io_lock:
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

    def apply(self, settings):
        with self._io_lock:
            validate_settings(settings)
            validate_settings({**self._values, **settings})
            if self._serial is None:
                raise ValueError("Connect the settings device first")
            applied, errors = {}, {}
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
                    if key not in self._values:
                        errors[key] = (
                            "Unavailable: this device has not returned a valid value"
                        )
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
                        self._write_setting(setting, value)
                        if key == "rotation":
                            paired = replace(setting, command=b"\x17")
                            self._write_setting(paired, value)
                            if abs(self._read_setting(paired) - value) > 1:
                                raise ValueError("Maximum angle readback did not match")
                        actual = self._read_setting(setting)
                        validate_settings({key: actual})
                        expected = setting.decode(setting.encode(value))
                        if setting.kind in ("boolean", "select"):
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
                    except (OSError, ValueError) as exc:
                        with self._state_lock:
                            self._values.pop(key, None)
                        errors[key] = str(exc)
            finally:
                self._busy = False
            return dict(applied=applied, errors=errors, values=self.status()["values"])
