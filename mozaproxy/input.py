"""Forward input frames and recover state after evdev queue overflow."""

import logging

from evdev import ecodes as e

log = logging.getLogger(__name__)


class InputRelay:
    def __init__(self, real, virtual, profile):
        self.real = real
        self.virtual = virtual
        self.profile = profile
        self.dropped = False

    def sync_state(self):
        for code in self.profile.axes:
            target, value = self.profile.axis_event(code, self.real.absinfo(code).value)
            self.virtual.write(e.EV_ABS, target, value)
        held = set(self.real.active_keys())
        for source, target in self.profile.buttons.items():
            self.virtual.write(e.EV_KEY, target, int(source in held))
        self.virtual.syn()

    def replace_profile(self, profile):
        """Release old assignments before taking a snapshot through the new map."""
        for target in self.profile.events.get(e.EV_KEY, []):
            self.virtual.write(e.EV_KEY, target, 0)
        # Disabled hat assignments retain their descriptor but must return neutral.
        for code in (e.ABS_HAT0X, e.ABS_HAT0Y):
            self.virtual.write(e.EV_ABS, code, 0)
        self.virtual.syn()
        self.profile = profile
        self.sync_state()

    def handle(self, event):
        if event.type == e.EV_SYN and event.code == e.SYN_DROPPED:
            self.dropped = True
            log.warning('Input queue overflow; resynchronizing at next frame')
            return
        if self.dropped:
            if event.type == e.EV_SYN and event.code == e.SYN_REPORT:
                self.sync_state()
                self.dropped = False
            return
        if event.type == e.EV_ABS and event.code in self.profile.axes:
            target, value = self.profile.axis_event(event.code, event.value)
            self.virtual.write(event.type, target, value)
        elif event.type == e.EV_KEY:
            target = self.profile.buttons.get(event.code)
            if target is not None:
                self.virtual.write(event.type, target, event.value)
        elif event.type == e.EV_SYN and event.code == e.SYN_REPORT:
            self.virtual.syn()
