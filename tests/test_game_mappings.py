"""Saved mappings compile into fixed wheel layouts without changing other routes."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from evdev import ecodes as e
from mozaproxy.game_mappings import default_mapping, validate_mapping, compile_mapping, load_mapping
from mozaproxy.app_state import GameMappingStore, AppState
from mozaproxy.cli import parse_args
from tests.test_g920_profile import source_caps
from tests.test_web import Hardware, Monitor, SCHEMA


class MappingTests(unittest.TestCase):
    def test_unknown_game_defaults_direct_and_heat_is_explicit_experiment(self):
        self.assertEqual(default_mapping('new-game')['target'], 'direct')
        self.assertEqual(default_mapping('heat')['target'], 'direct')
        draft = default_mapping('heat', 'g920')
        self.assertEqual(draft['buttons'], [639, 640, None, None, 301, 300,
                                           627, None, None, None, None])
        self.assertTrue(draft['hat'])

    def test_remap_pedals_and_buttons_preserves_fixed_descriptor(self):
        draft = default_mapping('heat', 'g920')
        draft['axes']['throttle']['source'], draft['axes']['brake']['source'] = 5, 2
        draft['axes']['throttle']['inverted'] = False
        draft['buttons'][0] = 296
        profile = compile_mapping(source_caps(), draft)
        self.assertEqual(profile.axis_event(5, 32767), (e.ABS_Y, 65535))
        self.assertEqual(profile.axis_event(2, 32767), (e.ABS_Z, 0))
        self.assertEqual(profile.buttons, {296: 288, 640: 289, 301: 292,
                                          300: 293, 627: 294})
        self.assertEqual(profile.events[e.EV_KEY], list(range(288,299)))
        self.assertEqual(set(dict(profile.events[e.EV_ABS])), {0,1,2,5,16,17})
        self.assertEqual(profile.events[e.EV_FF], source_caps()[e.EV_FF])

    def test_invalid_or_ambiguous_mapping_rejected(self):
        changes = [lambda d: d.update(target='made-up'),
                   lambda d: d['axes']['brake'].update(source=2),
                   lambda d: d['axes']['brake'].update(inverted='false'),
                   lambda d: d['buttons'].__setitem__(0, 300),
                   lambda d: d.update(game_id='../outside'),
                   lambda d: d.update(version=True),
                   lambda d: d.update(vendor=123)]
        for change in changes:
            draft = default_mapping('heat', 'g920'); change(draft)
            with self.subTest(draft=draft), self.assertRaises(ValueError): validate_mapping(draft)
        caps = source_caps(); caps[e.EV_ABS] = [(c,a) for c,a in caps[e.EV_ABS] if c != 5]
        with self.assertRaises(ValueError): compile_mapping(caps, default_mapping('heat', 'g920'))

    def test_store_roundtrip_and_failed_write_preserves_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GameMappingStore(directory)
            draft = default_mapping('heat', 'g920'); store.save(draft)
            self.assertEqual(GameMappingStore(directory).get('heat'), draft)
            self.assertEqual(store.get('ac')['target'], 'direct')
            with patch('os.replace', side_effect=OSError('full')):
                with self.assertRaises(OSError): store.save(default_mapping('heat'))
            self.assertEqual(store.get('heat'), draft)
            self.assertFalse((Path(directory) / 'profiles.json').exists())

    def test_cli_fixed_identity_and_configuration_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mapping.json'
            path.write_text(json.dumps(default_mapping('heat','g920')))
            args = parse_args(['--mapping-file', str(path)])
            self.assertEqual((args.profile,args.vendor,args.product), ('g920',0x046d,0xc262))
            self.assertEqual(args.mapping, load_mapping(path))
            with self.assertRaises(SystemExit): parse_args(['--mapping-file',str(path),'--vendor','2'])
            path.write_text(json.dumps(default_mapping('heat')))
            with self.assertRaises(SystemExit): parse_args(['--mapping-file', str(path)])

    def test_save_never_starts_relay_and_start_uses_saved_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = Mock(); relay.status.return_value = {'running':False,'pid':None,'log':[]}
            state = AppState(directory, Hardware(), Monitor(), relay, lambda: SCHEMA)
            self.addCleanup(state.close)
            state.game_mappings.save(default_mapping('heat','g920'))
            relay.start.assert_not_called()
            state.start_game_mapping('heat')
            self.assertEqual(relay.start.call_args.args[0]['mapping'], default_mapping('heat','g920'))
            with self.assertRaisesRegex(ValueError,'direct'): state.start_game_mapping('ac')

class LiveMappingTests(unittest.TestCase):
    def test_live_switch_releases_old_buttons_and_keeps_virtual_device(self):
        from mozaproxy.input import InputRelay
        from tests.test_input import Sink
        from types import SimpleNamespace
        old=default_mapping('heat','g920'); old['buttons'][0]=296
        new=deepcopy(old); new['buttons'][0]=None; new['buttons'][1]=296
        caps=source_caps(); values=dict(caps[e.EV_ABS])
        real=SimpleNamespace(active_keys=lambda:[296], absinfo=lambda code:values[code])
        sink=Sink(); relay=InputRelay(real,sink,compile_mapping(caps,old))
        relay.replace_profile(compile_mapping(caps,new))
        self.assertIs(relay.virtual,sink)
        self.assertIn((e.EV_KEY,288,0),sink.events)
        self.assertIn((e.EV_KEY,289,1),sink.events)
        self.assertLess(sink.events.index((e.EV_KEY,288,0)),sink.events.index((e.EV_KEY,289,1)))

    def test_session_reload_rejects_invalid_and_preserves_effects(self):
        from mozaproxy.runtime import Session
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'mapping.json'; draft=default_mapping('heat','g920')
            path.write_text(json.dumps(draft))
            session=Session(Mock(),SimpleNamespace(mapping_file=str(path),mapping=draft))
            session.real.capabilities.return_value=source_caps()
            session.inputs=Mock(); session.effects=Mock(); effects=session.effects
            session.reload_mapping()
            session.inputs.replace_profile.assert_not_called()
            draft['buttons'][4:6]=[300,301]
            path.write_text(json.dumps(draft)); session.reload_mapping()
            session.inputs.replace_profile.assert_called_once()
            self.assertIs(session.effects,effects)
            self.assertEqual(json.loads(Path(str(path)+'.status').read_text())['mapping'],draft)
            path.write_text('{broken'); session.reload_mapping()
            session.inputs.replace_profile.assert_called_once()
            self.assertIn('error',json.loads(Path(str(path)+'.status').read_text()))

@unittest.skipUnless(__import__('os').environ.get('MOZAPROXY_TEST_UINPUT') == '1', 'Opt-in virtual device test')
class LiveKernelMappingTests(unittest.TestCase):
    def test_existing_client_keeps_device_and_observes_reassigned_held_input(self):
        import threading
        import time
        from evdev import UInput, InputDevice
        from mozaproxy.runtime import Session
        from mozaproxy.game_mappings import write_mapping_document
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'mapping.json'; draft=default_mapping('heat','g920')
            draft['buttons'][0]=296
            write_mapping_document(path,draft)
            args=parse_args(['--mapping-file',str(path)])
            # Identify both synthetic devices as test hardware while a game is open.
            args.name='mozaproxy TEST live mapping'; args.vendor=0x1209; args.product=0xfffd
            with UInput(source_caps(),name='mozaproxy TEST mapping source',vendor=0x1209,
                        product=0xfffe,phys='mozaproxy/test-mapping',max_effects=10) as source:
                with Session(InputDevice(source.device.path),args) as session:
                    stop=threading.Event(); errors=[]
                    def run():
                        try: session.run(stop)
                        except Exception as exc: errors.append(exc)
                    worker=threading.Thread(target=run,daemon=True);worker.start()
                    def await_condition(predicate):
                        until=time.monotonic()+3
                        while time.monotonic()<until:
                            if errors: raise errors[0]
                            if predicate(): return
                            time.sleep(.01)
                        self.fail('Timed out waiting for live mapping')
                    try:
                        with closing(InputDevice(session.virtual.device.path)) as client:
                            original=(client.path,client.fd,session.virtual,session.effects)
                            source.write(e.EV_KEY,296,1);source.syn()
                            await_condition(lambda: 288 in client.active_keys())
                            draft['buttons'][0]=None;draft['buttons'][1]=296
                            draft['axes']['steering']['inverted']=True
                            write_mapping_document(path,draft)
                            await_condition(lambda: 289 in client.active_keys() and 288 not in client.active_keys())
                            source.write(e.EV_ABS,e.ABS_X,10000);source.syn()
                            await_condition(lambda: client.absinfo(e.ABS_X).value==55535)
                            self.assertEqual((client.path,client.fd,session.virtual,session.effects),original)
                            await_condition(lambda: json.loads(Path(str(path)+'.status').read_text())['mapping']==draft)
                    finally:
                        stop.set();worker.join(3)
                        self.assertFalse(worker.is_alive())
                        self.assertEqual(errors,[])
