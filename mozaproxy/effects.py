"""Own physical effects on behalf of uinput clients."""

import errno
import logging
from collections import Counter

from evdev import ecodes as e, ff
from .protection import DEFAULT_TIMEOUT_MS, timeout_ms

log = logging.getLogger(__name__)
CONTROLS = {e.FF_GAIN, e.FF_AUTOCENTER}


class EffectRelay:
    def __init__(self, real, virtual, menu_force_protection=False, menu_force_timeout_ms=DEFAULT_TIMEOUT_MS):
        self.real = real
        self.virtual = virtual
        self.effect_map = {}
        self.supported = set(real.capabilities().get(e.EV_FF, []))
        self.counts = Counter()
        self.menu_force_protection = menu_force_protection
        self.menu_force_timeout_ms = timeout_ms(menu_force_timeout_ms)
        self.guarded = set()
        self.playing = set()

    def handle(self, event):
        if event.type == e.EV_UINPUT:
            if event.code == e.UI_FF_UPLOAD:
                self.upload(event.value)
            elif event.code == e.UI_FF_ERASE:
                self.erase(event.value)
        elif event.type == e.EV_FF:
            code = event.code
            if code in CONTROLS:
                if code not in self.supported:
                    return
                target = code
            else:
                target = self.effect_map.get(code)
                if target is None:
                    log.warning('Ignoring playback for unknown virtual effect %d', code)
                    return
            value = 1 if code in self.guarded and event.value > 0 else event.value
            self.real.write(e.EV_FF, target, value)
            if code not in CONTROLS:
                if event.value > 0:
                    self.playing.add(code)
                elif event.value == 0:
                    self.playing.discard(code)
            self.counts['control' if code in CONTROLS else 'play_stop'] += 1
            log.debug('FF write virtual=%d physical=%d value=%d', code, target, event.value)

    def upload(self, request_id):
        request = self.virtual.begin_upload(request_id)
        request.retval = -errno.EIO
        try:
            original = request.effect
            if original.type == e.FF_PERIODIC and (
                original.u.ff_periodic_effect.waveform == e.FF_CUSTOM
                or original.u.ff_periodic_effect.custom_len
            ):
                raise OSError(errno.EINVAL, 'Custom waveform pointers cannot cross the relay')
            effect = ff.Effect.from_buffer_copy(bytes(original))
            effect.id = self.effect_map.get(original.id, -1)
            guarded = (self.menu_force_protection and effect.type == e.FF_CONSTANT
                       and not effect.ff_replay.length and not effect.ff_replay.delay
                       and not effect.ff_trigger.button
                       and not effect.u.ff_constant_effect.ff_envelope.attack_length
                       and not effect.u.ff_constant_effect.ff_envelope.fade_length)
            if guarded:
                effect.ff_replay.length = self.menu_force_timeout_ms
            physical_id = self.real.upload_effect(effect)
            self.effect_map[original.id] = physical_id
            if guarded:
                self.guarded.add(original.id)
                if original.id in self.playing:
                    self.real.write(e.EV_FF, physical_id, 1)
            else:
                self.guarded.discard(original.id)
            request.retval = 0
            self.counts[f'upload_type_{original.type}'] += 1
            log.debug('FF upload type=%d virtual=%d physical=%d',
                      original.type, original.id, physical_id)
        except OSError as exc:
            request.retval = -(exc.errno or errno.EIO)
            self.counts['upload_error'] += 1
            log.warning('FF upload failed: %s', exc)
            if exc.errno in (errno.ENODEV, errno.EBADF):
                raise
        finally:
            self.virtual.end_upload(request)

    def erase(self, request_id):
        request = self.virtual.begin_erase(request_id)
        request.retval = -errno.EIO
        try:
            physical_id = self.effect_map.get(request.effect_id)
            if physical_id is None:
                raise OSError(errno.EINVAL, 'Unknown virtual effect')
            self.real.erase_effect(physical_id)
            del self.effect_map[request.effect_id]
            self.guarded.discard(request.effect_id)
            self.playing.discard(request.effect_id)
            request.retval = 0
            self.counts['erase'] += 1
            log.debug('FF erase virtual=%d physical=%d', request.effect_id, physical_id)
        except OSError as exc:
            request.retval = -(exc.errno or errno.EIO)
            self.counts['erase_error'] += 1
            log.warning('FF erase failed: %s', exc)
            if exc.errno in (errno.ENODEV, errno.EBADF):
                raise
        finally:
            self.virtual.end_erase(request)

    def close(self):
        for physical_id in list(self.effect_map.values()):
            try:
                self.real.write(e.EV_FF, physical_id, 0)
            except OSError as exc:
                log.debug('Effect stop during cleanup: %s', exc)
            try:
                self.real.erase_effect(physical_id)
            except OSError as exc:
                # Closing the owning evdev fd is the final kernel cleanup path.
                log.debug('Effect erase during cleanup: %s', exc)
        self.effect_map.clear()
        self.guarded.clear()
        self.playing.clear()
