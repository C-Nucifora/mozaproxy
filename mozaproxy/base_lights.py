"""R25 ambient LED wire facts, independently implemented from AZOM captures.

Reference: https://github.com/giantorth/AZOM/blob/
6f820a8dd373d51764600b42e5c922204f663743/docs/protocol/leds/base-ambient-0x20-0x22.md
Only live colors/masks are written; stored lighting and force settings are untouched.
"""

import re
import time


class BaseLights:
    def __init__(self, encode, extract):
        self._encode = encode
        self._extract = extract
        self.active = False
        self.capabilities = {}
        self._color = None
        self._owned = False

    def _read(self, port, group, command, size):
        port.reset_input_buffer()
        port.write(self._encode(group, 0x12, command, b'\x00' * size))
        deadline = time.monotonic() + 0.3
        buffer = bytearray()
        while time.monotonic() < deadline:
            buffer.extend(port.read(min(256, max(1, port.in_waiting))))
            while (packet := self._extract(buffer)) is not None:
                response_group, device, payload = packet
                if response_group != (group ^ 0x80) or device != 0x21:
                    continue
                if not payload.startswith(command):
                    continue
                value = payload[len(command):]
                if (group == 7 and 0 <= len(value) <= 16) or len(value) == size:
                    return value
        raise ValueError('R25 base lighting probe did not receive a valid reply')

    def begin(self, port):
        if self.active:
            return dict(self.capabilities)
        self.capabilities = {}
        chunks = [self._read(port, 7, bytes([part]), 0) for part in (1, 2)]
        raw = b''.join(chunks).rstrip(b'\x00 ')
        if not raw or any(byte < 32 or byte > 126 for byte in raw):
            raise ValueError('Base model reply is not a valid ASCII model name')
        model = raw.decode('ascii')
        if not re.match(r'^R25(?: |$)', model):
            raise ValueError('Base lighting requires a confirmed R25 model; received ' + model)
        brightness = self._read(port, 0x22, b'\x1f\xff', 1)[0]
        mode = self._read(port, 0x22, b'\x1c', 1)[0]
        if mode != 1:
            raise ValueError('R25 base lighting must already be in external / SimHub mode (1)')
        self.capabilities = dict(model=model, leds_per_strip=9, strips=2,
                                 brightness=brightness, indicator_state=mode)
        self._color = None
        self._owned = False
        self.active = True
        return dict(self.capabilities)

    def frame(self, port, color, mask):
        if type(mask) is not int or not 0 <= mask <= 0x1ff:
            raise ValueError('Invalid nine-light base mask')
        if color is None:
            if mask:
                raise ValueError('A base light color is required for a nonzero mask')
        elif not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('Base light color must be #RRGGBB')
        if not self.active or port is None:
            return False
        if color is None and not self._owned:
            return True
        rgb = bytes.fromhex(color[1:]) if color is not None else None
        # Record ownership before writing so partial failures still get a release.
        self._owned = True
        if rgb is not None and rgb != self._color:
            for strip in (0, 1):
                for start, stop in ((0, 5), (5, 9)):
                    entries = b''.join(bytes([i]) + rgb for i in range(start, stop))
                    port.write(self._encode(0x20, 0x12, bytes([0x1a, strip]), entries))
        for strip in (0, 1):
            port.write(self._encode(0x20, 0x12, bytes([0x1b, strip]), mask.to_bytes(4, 'little')))
        port.flush()
        self._color = rgb
        if color is None:
            self._owned = False
        return True

    def end(self, port):
        try:
            if self.active and self._owned:
                if port is None:
                    raise OSError('Base disconnected before its live lights could be cleared')
                self.frame(port, None, 0)
        finally:
            self.active = False
            self._owned = False
            self._color = None
