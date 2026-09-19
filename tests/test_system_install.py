"""Installer tests use a temporary root and never invoke host administration."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'tools/install-system-service.py'


def installer_module():
    spec = importlib.util.spec_from_file_location('system_install', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSystem:
    def __init__(self):
        self.calls = []
        self.busy = []
        self.connected = False
        self.failure = None
        self.account_removed = False
        self.reconnected = False
        self.enabled = 'disabled'
        self.active = False

    def client(self, name):
        return {'name': name, 'uid': 1000, 'gid': 1000, 'group': 'desktop'}

    def ensure_account(self, client):
        self.calls.append('account')
        return ['user', 'group']

    def undo_account(self, created):
        self.account_removed = True

    def read_templates(self, source, client):
        return ((source / 'systemd/mozaproxy-system.service').read_bytes(),
                (source / 'udev/71-mozaproxy-system.rules').read_bytes())

    def build_runtime(self, source, destination, client):
        self.calls.append('build')
        (destination / 'venv/bin').mkdir(parents=True)
        (destination / 'venv/bin/python').write_text('fake interpreter')
        (destination / 'app/mozaproxy').mkdir(parents=True)
        (destination / 'app/mozaproxy/__init__.py').write_text('')
        if self.failure == 'build':
            raise RuntimeError('build failed')

    def busy_processes(self):
        return self.busy

    def physical_devices(self):
        return ['/dev/input/event99'] if self.connected else []

    def service_state(self):
        return {'enabled': self.enabled, 'active': self.active}

    def run(self, *args, check=True):
        self.calls.append(args)
        if self.failure and self.failure in args:
            raise RuntimeError('command failed')
        if args[:2] == ('systemctl', 'enable'):
            self.enabled = 'enabled-runtime' if '--runtime' in args else 'enabled'
        if args[:2] == ('systemctl', 'disable'):
            self.enabled = 'disabled'
        if args[:2] == ('systemctl', 'start'):
            self.active = True
        if args[:2] == ('systemctl', 'stop'):
            self.active = False
        return type('Result', (), {'returncode': 0, 'stdout': ''})()

    def snapshot_uinput(self):
        return 'original uinput ACL'

    def restore_uinput(self, acl):
        self.calls.append(('restore_uinput', acl))

    def wait_for_reconnect(self, timeout):
        self.calls.append('reconnect')
        if self.failure == 'reconnect':
            raise RuntimeError('reconnect timed out')
        self.reconnected = True
        return ['/dev/input/event99']

    def verify_access(self, client, devices):
        self.calls.append('verify')
        if self.failure == 'verify':
            raise RuntimeError('desktop user lost physical access')


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'the separate system-service installer is missing')
        self.module = installer_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = FakeSystem()
        self.installer = self.module.Installer(self.root, self.system)
        self.source = SCRIPT.parent.parent

    def stage(self):
        self.installer.install(self.source, 'desktop')

    def test_install_stages_runtime_without_activating_permissions_or_integration(self):
        self.stage()
        state = json.loads((self.root / 'var/lib/mozaproxy-system/staged.json').read_text())
        self.assertEqual(state['client']['uid'], 1000)
        release = self.root / state['runtime'].lstrip('/')
        self.assertTrue((release / 'venv/bin/python').is_file())
        self.assertFalse((self.root / 'etc/udev/rules.d/71-mozaproxy-system.rules').exists())
        self.assertFalse((self.root / 'etc/mozaproxy/system.json').exists())
        self.assertFalse(any(isinstance(c, tuple) for c in self.system.calls))

    def test_build_failure_removes_partial_runtime_and_new_account(self):
        self.system.failure = 'build'
        with self.assertRaisesRegex(RuntimeError, 'build failed'):
            self.stage()
        self.assertFalse((self.root / 'var/lib/mozaproxy-system/staged.json').exists())
        self.assertEqual(list((self.root / 'opt/mozaproxy/releases').iterdir()), [])
        self.assertTrue(self.system.account_removed)

    def test_install_rejects_writable_destination(self):
        target = self.root / 'opt/mozaproxy'
        target.mkdir(parents=True)
        target.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, 'writable|trusted'):
            self.stage()
        self.assertNotIn('build', self.system.calls)

    def test_install_rejects_symlink_destination(self):
        target = self.root / 'opt'
        target.mkdir()
        (target / 'mozaproxy').symlink_to(self.root / 'elsewhere')
        with self.assertRaisesRegex(RuntimeError, 'symlink|trusted'):
            self.stage()

    def test_activation_refuses_live_wine_before_rules_change(self):
        self.stage()
        self.system.busy = ['2330555 /usr/bin/wine64 game.exe']
        with self.assertRaisesRegex(RuntimeError, 'running|Wine|process'):
            self.installer.activate(1)
        self.assertFalse((self.root / 'etc/udev/rules.d/71-mozaproxy-system.rules').exists())
        self.assertNotIn(('systemctl', 'start', 'mozaproxy-system.service'), self.system.calls)

    def test_activation_requires_unplugging_before_any_permission_changes(self):
        self.stage()
        self.system.connected = True
        with self.assertRaisesRegex(RuntimeError, '[Uu]nplug|disconnect'):
            self.installer.activate(1)
        self.assertFalse((self.root / 'etc/udev/rules.d/71-mozaproxy-system.rules').exists())

    def test_activation_waits_for_replug_and_verifies_before_config_is_published(self):
        self.stage()
        self.installer.activate(1)
        self.assertTrue(self.system.reconnected)
        self.assertIn('verify', self.system.calls)
        config = json.loads((self.root / 'etc/mozaproxy/system.json').read_text())
        self.assertEqual(config, {'version': 1, 'client_uid': 1000, 'socket': '/run/mozaproxy/control.sock'})
        unit = (self.root / 'etc/systemd/system/mozaproxy-system.service').read_text()
        self.assertIn('User=mozaproxy\n', unit)
        self.assertIn('Group=desktop\n', unit)
        self.assertNotIn('@', unit)

    def test_access_verification_accepts_desktop_seat_access_and_rejects_its_loss(self):
        system = self.module.System()
        client = self.system.client('desktop')
        device = SimpleNamespace(st_mode=stat.S_IFCHR | 0o660, st_uid=0, st_gid=777)
        control = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=991, st_gid=1000)
        denied = set()

        def run(*args, check=True):
            if args[0] == 'getfacl':
                return SimpleNamespace(returncode=0, stdout='user::rw-\nuser:1000:rw-\ngroup::rw-\nmask::rw-\nother::---\n')
            account = args[2] if args[0] == 'runuser' else None
            result = SimpleNamespace(returncode=int(account in denied), stdout='')
            if check and result.returncode:
                raise RuntimeError('Access denied for ' + account)
            return result

        with patch.object(self.module.Path, 'stat', side_effect=lambda: None) as path_stat, \
             patch.object(self.module.grp, 'getgrnam', return_value=SimpleNamespace(gr_gid=777)), \
             patch.object(self.module.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=991)), \
             patch.object(system, 'run', side_effect=run):
            path_stat.side_effect = [device, control]
            system.verify_access(client, ['/dev/input/event99'])
            denied.add('desktop')
            path_stat.side_effect = [device]
            with self.assertRaisesRegex(RuntimeError, '[Dd]esktop|desktop'):
                system.verify_access(client, ['/dev/input/event99'])
            denied.clear()
            denied.add('mozaproxy')
            path_stat.side_effect = [device]
            with self.assertRaisesRegex(RuntimeError, 'mozaproxy'):
                system.verify_access(client, ['/dev/input/event99'])

    def test_failed_access_verification_restores_previous_rule_and_unit(self):
        self.stage()
        rules = self.root / 'etc/udev/rules.d/71-mozaproxy-system.rules'
        unit = self.root / 'etc/systemd/system/mozaproxy-system.service'
        for target, data in ((rules, b'previous rule\n'), (unit, b'previous unit\n')):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.system.failure = 'verify'
        with self.assertRaisesRegex(RuntimeError, 'replug|reconnect'):
            self.installer.activate(1)
        self.assertEqual(rules.read_bytes(), b'previous rule\n')
        self.assertEqual(unit.read_bytes(), b'previous unit\n')
        self.assertFalse((self.root / 'etc/mozaproxy/system.json').exists())
        self.assertIn(('systemctl', 'stop', 'mozaproxy-system.service'), self.system.calls)

    def test_explicit_rollback_restores_original_permissions_configuration(self):
        self.stage()
        rules = self.root / 'etc/udev/rules.d/71-mozaproxy-system.rules'
        rules.parent.mkdir(parents=True)
        rules.write_bytes(b'original\n')
        self.installer.activate(1)
        self.installer.rollback()
        self.assertEqual(rules.read_bytes(), b'original\n')
        self.assertIn(('restore_uinput', 'original uinput ACL'), self.system.calls)
        self.assertFalse((self.root / 'etc/mozaproxy/system.json').exists())

    def test_runtime_copy_rejects_symlinks_without_reading_the_target(self):
        source = self.root / 'source'
        source.mkdir()
        secret = self.root / 'secret'
        secret.write_text('do not copy')
        (source / 'escape').symlink_to(secret)
        with self.assertRaisesRegex(RuntimeError, 'Symlink'):
            self.module.copy_regular_tree(source, self.root / 'destination')
        self.assertFalse((self.root / 'destination/escape').exists())

    def test_failed_reload_keeps_recovery_journal_and_removes_integration(self):
        self.stage()
        self.system.failure = '--reload-rules'
        with self.assertRaisesRegex(RuntimeError, 'journal retained'):
            self.installer.activate(1)
        self.assertTrue((self.root / 'var/lib/mozaproxy-system/activation.json').exists())
        self.assertFalse((self.root / 'etc/mozaproxy/system.json').exists())

    def test_runtime_copy_strips_source_write_permissions(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'module.py').write_text('pass')
        (source / 'module.py').chmod(0o666)
        self.module.copy_regular_tree(source, self.root / 'destination')
        self.assertEqual((self.root / 'destination/module.py').stat().st_mode & 0o777, 0o644)

    def test_runtime_files_are_never_world_writable_even_with_permissive_umask(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'module.py').write_text('pass')
        copy = self.module.shutil.copyfileobj

        def check_permissions(reader, writer):
            self.assertEqual(os.fstat(writer.fileno()).st_mode & 0o022, 0)
            return copy(reader, writer)

        previous = os.umask(0)
        try:
            with patch.object(self.module.shutil, 'copyfileobj', side_effect=check_permissions):
                self.module.copy_regular_tree(source, self.root / 'destination')
        finally:
            os.umask(previous)

    def test_existing_hardware_group_with_desktop_member_is_rejected(self):
        system = self.module.System()
        unsafe = SimpleNamespace(gr_gid=777, gr_mem=['desktop'])
        with patch.object(self.module.grp, 'getgrnam', return_value=unsafe):
            with self.assertRaisesRegex(RuntimeError, 'only the service account'):
                system.ensure_account(self.system.client('desktop'))

    def test_existing_service_account_with_extra_groups_is_rejected(self):
        system = self.module.System()
        group = SimpleNamespace(gr_gid=777, gr_mem=['mozaproxy'])
        service = SimpleNamespace(pw_name='mozaproxy', pw_uid=991, pw_gid=1000,
                                  pw_shell='/usr/sbin/nologin')
        with patch.object(self.module.grp, 'getgrnam', return_value=group), \
                patch.object(self.module.pwd, 'getpwall', return_value=[service]), \
                patch.object(self.module.pwd, 'getpwnam', return_value=service), \
                patch.object(self.module.os, 'getgrouplist', return_value=[1000, 777, 0]):
            with self.assertRaisesRegex(RuntimeError, 'unsafe UID, groups'):
                system.ensure_account(self.system.client('desktop'))

    def test_rollback_requires_unplugging_and_preserves_recovery_data(self):
        self.stage()
        self.installer.activate(1)
        self.system.connected = True
        with self.assertRaisesRegex(RuntimeError, '[Uu]nplug'):
            self.installer.rollback()
        self.assertTrue((self.root / 'var/lib/mozaproxy-system/activation.json').exists())

    def test_module_relay_is_detected_during_process_preflight(self):
        proc = self.root / 'proc'
        entry = proc / '99999'
        entry.mkdir(parents=True)
        (entry / 'cmdline').write_bytes(b'python\0-m\0mozaproxy\0--profile\0compact\0')
        (entry / 'comm').write_text('python')
        original_path = self.module.Path
        with patch.object(self.module, 'Path', side_effect=lambda name: proc if name == '/proc' else original_path(name)):
            self.assertEqual(len(self.module.System().busy_processes()), 1)

    def test_activation_enables_service_for_reboot_before_reporting_success(self):
        self.stage()
        self.installer.activate(1)
        self.assertEqual(self.system.enabled, 'enabled')
        self.assertTrue(self.system.active)
        journal = json.loads((self.root / 'var/lib/mozaproxy-system/activation.json').read_text())
        self.assertEqual(journal['service'], {'enabled': 'disabled', 'active': False})
        self.assertLess(self.system.calls.index(('systemctl', 'enable', 'mozaproxy-system.service')),
                        self.system.calls.index(('systemctl', 'start', 'mozaproxy-system.service')))

    def test_rollback_restores_previously_disabled_service(self):
        self.stage()
        self.installer.activate(1)
        self.installer.rollback()
        self.assertEqual(self.system.enabled, 'disabled')
        self.assertFalse(self.system.active)

    def test_rollback_restores_previous_enabled_and_active_service(self):
        self.stage()
        self.system.enabled = 'enabled'
        self.system.active = True
        self.installer.activate(1)
        self.installer.rollback()
        self.assertEqual(self.system.enabled, 'enabled')
        self.assertTrue(self.system.active)

    def test_failed_activation_restores_previous_runtime_enablement(self):
        self.stage()
        self.system.enabled = 'enabled-runtime'
        self.system.failure = 'verify'
        with self.assertRaisesRegex(RuntimeError, 'reconnect'):
            self.installer.activate(1)
        self.assertEqual(self.system.enabled, 'enabled-runtime')
        self.assertFalse(self.system.active)

    def test_activation_will_not_overwrite_an_existing_active_transaction(self):
        self.stage()
        self.installer.activate(1)
        with self.assertRaisesRegex(RuntimeError, 'already|rollback'):
            self.installer.activate(1)


if __name__ == '__main__':
    unittest.main()
