"""Base alerts from explicit game telemetry, never inferred from wheel forces."""
import math


class AlertLights:
    def __init__(self, activity=False):
        self.activity = activity
        self.reset()

    def reset(self):
        self.stream = None
        self.yellow = None
        self.green_until = 0
        self.activity_until = 0

    def frame(self, sample, now, stale=False):
        if stale or not sample or not sample.get('racing'):
            self.reset()
            return None, 0
        stream = sample.get('stream')
        if stream != self.stream:
            self.reset()
            self.stream = stream
        yellow, blue = sample.get('yellow'), sample.get('blue')
        if yellow is None or blue is None:
            self.yellow = None
            self.green_until = 0
        else:
            if self.yellow is True and not yellow and not blue:
                self.green_until = now + 1
            self.yellow = yellow
        blink = 0x1ff if int(now * 4) % 2 == 0 else 0
        if yellow:
            return '#FFFF00', blink
        if blue:
            return '#0000FF', blink
        if now < self.green_until:
            return '#00FF00', 0x1ff
        if sample.get('limiter'):
            level = round(50 + 205 * (1 + math.sin(now * math.tau)) / 2)
            return f'#00{level:02X}{level:02X}', 0x1ff
        if self.activity:
            if sample.get('abs_active') or sample.get('tc_active'):
                self.activity_until = now + 0.15
            elif sample.get('abs_active') is None or sample.get('tc_active') is None:
                self.activity_until = 0
            if now < self.activity_until:
                return '#FF8000', 0x1ff
        return None, 0
