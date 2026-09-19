"""Device discovery, exclusive ownership, and reconnect supervision."""

import logging
import selectors
import time
from copy import deepcopy
from pathlib import Path

import evdev
from evdev import InputDevice, UInputError, ecodes as e

from .effects import EffectRelay
from .devices import SafeUInput as UInput
from .input import InputRelay
from .profiles import make_profile
from .game_mappings import compile_mapping, load_mapping, write_mapping_document

log = logging.getLogger(__name__)


def find_device(args):
    matches = []
    paths = [args.device] if args.device else evdev.list_devices()
    try:
        for path in paths:
            try:
                dev = InputDevice(path)
            except OSError:
                if args.device:
                    raise
                continue
            keep = False
            try:
                caps = dev.capabilities()
                keep = (
                    dev.info.vendor == args.vendor_real
                    and dev.info.product == args.product_real
                    and not (dev.phys or '').startswith('mozaproxy/')
                    and 'mozaproxy' not in dev.name.lower()
                    and e.EV_ABS in caps and e.EV_FF in caps
                    and (not args.name_hint or args.name_hint.lower() in dev.name.lower())
                )
                if keep:
                    matches.append(dev)
            finally:
                if not keep:
                    dev.close()
        if len(matches) > 1:
            raise ValueError('Multiple matching wheels; choose one with --device')
        return matches[0] if matches else None
    except BaseException:
        for dev in matches:
            dev.close()
        raise


class Session:
    def __init__(self, real, args):
        self.real = real
        self.args = args
        self.virtual = None
        self.effects = None
        self.inputs = None
        self.grabbed = False
        self.current_mapping = deepcopy(getattr(args, 'mapping', None))
        self.mapping_stamp = None

    def __enter__(self):
        try:
            self.real.grab()
            self.grabbed = True
            mapping = getattr(self.args, 'mapping', None)
            profile = (compile_mapping(self.real.capabilities(), mapping) if mapping else
                       make_profile(self.real.capabilities(), self.args.profile, self.args.buttons))
            capacity = self.real.ff_effects_count
            if capacity < 1:
                raise ValueError('Physical wheel has no force-feedback effect slots')
            self.virtual = UInput(
                profile.events, name=self.args.name,
                vendor=self.args.vendor, product=self.args.product, version=0x0111,
                bustype=e.BUS_USB, phys=f'mozaproxy/{profile.name}',
                max_effects=min(capacity, e.FF_GAIN),
            )
            self.effects = EffectRelay(self.real, self.virtual)
            self.inputs = InputRelay(self.real, self.virtual, profile)
            self.inputs.sync_state()
            if mapping:
                self._mapping_status(None)
            log.info('Relay ready: source=%s virtual=%s profile=%s buttons=%d slots=%d',
                     self.real.path, getattr(self.virtual.device, 'path', 'unavailable'),
                     profile.name, len(profile.buttons), min(capacity, e.FF_GAIN))
            log.info('Physical device is grabbed, not hidden from enumeration')
            log.debug('Button mapping: %s', profile.buttons)
            return self
        except BaseException:
            self.close()
            raise

    def run(self, stop):
        with selectors.DefaultSelector() as selector:
            selector.register(self.real.fd, selectors.EVENT_READ, self.real)
            selector.register(self.virtual.fd, selectors.EVENT_READ, self.virtual)
            next_mapping_check = 0
            while not stop.is_set():
                if time.monotonic() >= next_mapping_check:
                    self.reload_mapping()
                    next_mapping_check = time.monotonic() + 0.25
                for key, _ in selector.select(timeout=0.2):
                    dev = key.data
                    try:
                        events = dev.read()
                        for event in events:
                            if dev is self.real:
                                self.inputs.handle(event)
                            else:
                                self.effects.handle(event)
                    except BlockingIOError:
                        continue

    def _mapping_status(self, error):
        path = getattr(self.args, 'mapping_file', None)
        if path:
            try:
                write_mapping_document(path + '.status', {'mapping': self.current_mapping, 'error': error})
            except OSError:
                log.exception('Cannot report mapping status')

    def reload_mapping(self):
        path = getattr(self.args, 'mapping_file', None)
        if not path:
            return
        try:
            info = Path(path).stat()
            stamp = (info.st_ino, info.st_mtime_ns, info.st_size)
            if stamp == self.mapping_stamp:
                return
            self.mapping_stamp = stamp
            mapping = load_mapping(path)
            if mapping == self.current_mapping:
                self._mapping_status(None)
                return
            if mapping['target'] != 'g920' or mapping['game_id'] != self.current_mapping['game_id']:
                raise ValueError('Live changes must keep the same game and wheel layout')
            profile = compile_mapping(self.real.capabilities(), mapping)
        except (OSError, ValueError) as exc:
            self._mapping_status(str(exc))
            log.warning('Mapping reload rejected: %s', exc)
            return
        # Input writes stay outside the validation catch: a failed device is a
        # failed session, never reported as a successfully retained mapping.
        self.inputs.replace_profile(profile)
        self.current_mapping = mapping
        self._mapping_status(None)
        log.info('Applied input mapping in place for %s; virtual device and FFB retained', mapping['game_id'])

    def close(self):
        try:
            if self.effects is not None:
                self.effects.close()
                log.info('FF session totals: %s', dict(self.effects.counts))
                self.effects = None
        finally:
            try:
                if self.virtual is not None:
                    self.virtual.close()
                    self.virtual = None
            finally:
                if self.real is not None:
                    try:
                        if self.grabbed:
                            self.real.ungrab()
                    except OSError:
                        pass
                    finally:
                        self.real.close()
                        self.real = None
                        self.grabbed = False

    def __exit__(self, *_):
        self.close()


def supervise(args, stop):
    waiting = False
    while not stop.is_set():
        try:
            real = find_device(args)
            if real is None:
                if not waiting:
                    log.warning('No matching physical wheel; waiting for connection')
                waiting = True
                if args.once:
                    return 1
                stop.wait(2)
                continue
            waiting = False
            with Session(real, args) as session:
                session.run(stop)
        except (OSError, ValueError, UInputError):
            log.exception('Wheel session failed')
            if args.once:
                return 1
        if args.once or stop.is_set():
            break
        stop.wait(2)
    return 0
