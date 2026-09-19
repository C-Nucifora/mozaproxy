import ctypes
import errno
import unittest
from types import SimpleNamespace

from evdev import InputEvent, ecodes as e, ff

from mozaproxy.effects import EffectRelay


def effect(vid=0, kind=e.FF_CONSTANT):
    return ff.Effect(kind, vid, 0x4000, ff.Trigger(0, 0), ff.Replay(350, 0),
                     ff.EffectType(ff_constant_effect=ff.Constant(
                         level=1638, ff_envelope=ff.Envelope(75, 0, 75, 0))))


class Physical:
    def __init__(self):
        self.effects = {}
        self.writes = []
        self.upload_error = None
        self.erase_error = None
        self.next_id = 4

    def capabilities(self):
        return {e.EV_FF: [e.FF_CONSTANT, e.FF_PERIODIC, e.FF_SINE, e.FF_GAIN]}

    def upload_effect(self, value):
        if self.upload_error:
            raise self.upload_error
        if value.id == -1:
            value.id = self.next_id
            self.next_id += 1
        self.effects[value.id] = bytes(value)
        return value.id

    def erase_effect(self, eid):
        if self.erase_error:
            raise self.erase_error
        del self.effects[eid]

    def write(self, *event):
        self.writes.append(event)


class Virtual:
    def __init__(self):
        self.upload = SimpleNamespace(effect=effect(), retval=None)
        self.erase = SimpleNamespace(effect_id=0, retval=None)
        self.completed = []

    def begin_upload(self, request):
        return self.upload

    def end_upload(self, upload):
        self.completed.append(('upload', upload.retval))

    def begin_erase(self, request):
        return self.erase

    def end_erase(self, erase):
        self.completed.append(('erase', erase.retval))


class EffectsTests(unittest.TestCase):
    def setUp(self):
        self.real, self.virtual = Physical(), Virtual()
        self.relay = EffectRelay(self.real, self.virtual)

    def upload(self, value):
        self.virtual.upload.effect = value
        self.relay.handle(InputEvent(0, 0, e.EV_UINPUT, e.UI_FF_UPLOAD, 1))

    def erase(self, vid=0):
        self.virtual.erase.effect_id = vid
        self.relay.handle(InputEvent(0, 0, e.EV_UINPUT, e.UI_FF_ERASE, 2))

    def test_update_reuses_own_effect_after_another_upload(self):
        original = effect(0)
        self.upload(original)
        self.upload(effect(1))
        updated = effect(0)
        updated.u.ff_constant_effect.level = -1200
        self.upload(updated)
        self.assertEqual(set(self.real.effects), {4, 5})
        physical = ff.Effect.from_buffer_copy(self.real.effects[4])
        self.assertEqual(physical.u.ff_constant_effect.level, -1200)
        self.assertEqual(updated.id, 0)
        self.assertEqual(original.id, 0)

    def test_upload_failure_returns_kernel_errno_without_mapping(self):
        self.real.upload_error = OSError(errno.ENOSPC, 'full')
        self.upload(effect())
        self.assertEqual(self.virtual.completed, [('upload', -errno.ENOSPC)])
        self.assertEqual(self.relay.effect_map, {})

    def test_unexpected_failure_still_completes_transaction(self):
        self.real.upload_error = RuntimeError('unexpected')
        with self.assertRaises(RuntimeError):
            self.upload(effect())
        self.assertEqual(self.virtual.completed, [('upload', -errno.EIO)])

    def test_erase_failure_keeps_mapping_for_cleanup(self):
        self.upload(effect())
        self.real.erase_error = OSError(errno.EIO, 'failed')
        self.erase()
        self.assertEqual(self.virtual.completed[-1], ('erase', -errno.EIO))
        self.assertEqual(self.relay.effect_map, {0: 4})
        self.real.erase_error = None
        self.relay.close()
        self.assertEqual(self.real.effects, {})

    def test_play_repeat_stop_and_gain_target_correct_physical_codes(self):
        self.upload(effect(0))
        for code, value in [(0, 3), (0, 0), (e.FF_GAIN, 12345)]:
            self.relay.handle(InputEvent(0, 0, e.EV_FF, code, value))
        self.assertEqual(self.real.writes, [(e.EV_FF, 4, 3),
                                          (e.EV_FF, 4, 0),
                                          (e.EV_FF, e.FF_GAIN, 12345)])

    def test_unknown_effect_does_not_play_someone_elses_force(self):
        self.relay.handle(InputEvent(0, 0, e.EV_FF, 7, 1))
        self.assertEqual(self.real.writes, [])

    def test_custom_waveform_rejected_before_pointer_dereference(self):
        custom = effect(kind=e.FF_PERIODIC)
        custom.u.ff_periodic_effect.waveform = e.FF_CUSTOM
        self.upload(custom)
        self.assertEqual(self.virtual.completed[-1], ('upload', -errno.EINVAL))
        self.assertEqual(self.real.effects, {})

    def test_cleanup_stops_all_owned_effects_and_is_idempotent(self):
        self.upload(effect(0))
        self.upload(effect(1))
        self.relay.close()
        self.relay.close()
        self.assertEqual(self.real.effects, {})
        self.assertEqual(self.real.writes, [(e.EV_FF, 4, 0), (e.EV_FF, 5, 0)])


if __name__ == '__main__':
    unittest.main()
