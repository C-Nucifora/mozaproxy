"""Opt-in integration tests. These create virtual devices; no motor is opened."""

import os
import select
import multiprocessing
import time
import unittest

from evdev import AbsInfo, InputDevice, UInput, ecodes as e, ff

from mozaproxy.cli import parse_args
from mozaproxy.runtime import Session


def constant(level=100, eid=-1):
    return ff.Effect(e.FF_CONSTANT, eid, 0x4000, ff.Trigger(0, 0), ff.Replay(250, 0),
                     ff.EffectType(ff_constant_effect=ff.Constant(
                         level=level, ff_envelope=ff.Envelope(0, 0, 0, 0))))


@unittest.skipUnless(os.environ.get('MOZAPROXY_TEST_UINPUT') == '1',
                     'Set MOZAPROXY_TEST_UINPUT=1 to test with virtual devices')
class UInputTests(unittest.TestCase):
    def test_kernel_input_and_effect_lifecycle(self):
        source = UInput({
            e.EV_ABS: [(e.ABS_X, AbsInfo(0, 0, 65535, 0, 0, 0))],
            e.EV_KEY: [288, 300, 301, 653, 655],
            e.EV_FF: [e.FF_CONSTANT, e.FF_GAIN],
        }, name='mozaproxy TEST source', vendor=0x1209, product=0xffff,
            phys='mozaproxy/test-source', max_effects=10)
        context = multiprocessing.get_context('fork')
        manager = context.Manager()
        stop = context.Event()
        effects = manager.dict()
        writes = manager.list()
        errors = manager.list()

        def hardware():
            try:
                while not stop.is_set():
                    if not select.select([source.fd], [], [], .05)[0]:
                        continue
                    for event in source.read():
                        if event.type == e.EV_UINPUT and event.code == e.UI_FF_UPLOAD:
                            upload = source.begin_upload(event.value)
                            effects[upload.effect.id] = bytes(upload.effect)
                            upload.retval = 0
                            source.end_upload(upload)
                        elif event.type == e.EV_UINPUT and event.code == e.UI_FF_ERASE:
                            erase = source.begin_erase(event.value)
                            effects.pop(erase.effect_id, None)
                            erase.retval = 0
                            source.end_erase(erase)
                        elif event.type == e.EV_FF:
                            writes.append((event.code, event.value))
            except BaseException as exc:
                errors.append(exc)

        hardware_thread = context.Process(target=hardware, daemon=True)
        hardware_thread.start()
        other = InputDevice(source.device.path)
        reserved = other.upload_effect(constant(77))
        relay_stop = context.Event()
        relay_thread = None
        client = None

        def await_condition(predicate):
            until = time.monotonic() + 3
            while time.monotonic() < until:
                if predicate():
                    return
                if errors:
                    raise errors[0]
                time.sleep(.01)
            self.fail('Timed out waiting for virtual kernel relay')

        try:
            args = parse_args(['--profile', 'compact'])
            with Session(InputDevice(source.device.path), args) as session:
                def run():
                    try:
                        session.run(relay_stop)
                    except BaseException as exc:
                        errors.append(exc)
                relay_thread = context.Process(target=run, daemon=True)
                relay_thread.start()
                client = InputDevice(session.virtual.device.path)
                eid = client.upload_effect(constant(100))
                second = client.upload_effect(constant(200))
                client.upload_effect(constant(-900, eid))
                physical_id = next(key for key, data in effects.items()
                                   if ff.Effect.from_buffer_copy(data)
                                   .u.ff_constant_effect.level == -900)
                self.assertNotEqual(eid, physical_id)  # reserved physical slot
                self.assertEqual(ff.Effect.from_buffer_copy(effects[physical_id])
                                 .u.ff_constant_effect.level, -900)
                self.assertEqual(ff.Effect.from_buffer_copy(effects[reserved])
                                 .u.ff_constant_effect.level, 77)
                client.write(e.EV_FF, eid, 3)
                client.write(e.EV_FF, eid, 0)
                client.write(e.EV_FF, e.FF_GAIN, 12345)
                await_condition(lambda: (e.FF_GAIN, 12345) in writes)
                self.assertIn((physical_id, 3), writes)
                self.assertIn((physical_id, 0), writes)

                source.write(e.EV_ABS, e.ABS_X, 12345)
                source.write(e.EV_KEY, 653, 1)
                source.syn()
                await_condition(lambda: client.absinfo(e.ABS_X).value == 12345)
                mapped = session.inputs.profile.buttons[653]
                await_condition(lambda: mapped in client.active_keys())
                source.write(e.EV_KEY, 653, 0)
                source.syn()
                await_condition(lambda: mapped not in client.active_keys())

                client.erase_effect(second)
                client.close()  # kernel requests erase for the remaining effect
                client = None
                await_condition(lambda: set(effects) == {reserved})
                self.assertEqual(set(effects), {reserved})
                relay_stop.set()
                relay_thread.join(3)
                self.assertFalse(relay_thread.is_alive())
            self.assertFalse(errors)
        finally:
            if client is not None:
                client.close()
            relay_stop.set()
            if relay_thread is not None:
                relay_thread.join(3)
            other.close()
            stop.set()
            hardware_thread.join(3)
            source.close()
            manager.shutdown()


if __name__ == '__main__':
    unittest.main()
