#!/usr/bin/env python3
"""Stage, explicitly activate, or roll back the unprivileged system wheel service.

This administrative program does not import or execute checkout code as root.
Dependency builds run under the desktop account; the daemon runs as mozaproxy.
Activation requires unplugging and reconnecting, so no existing device ACL is
modified in place. The rollback journal survives interrupted activation.
"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid


UNIT = 'mozaproxy-system.service'
STATE = '/var/lib/mozaproxy-system'
RULE = '/etc/udev/rules.d/71-mozaproxy-system.rules'
UNIT_PATH = '/etc/systemd/system/' + UNIT
CONFIG = '/etc/mozaproxy/system.json'
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}


@contextmanager
def read_as(client):
    """Source reads use the client credentials, including supplementary groups."""
    if client is None:
        yield
        return
    uid, gid, groups = os.geteuid(), os.getegid(), os.getgroups()
    try:
        os.setgroups(os.getgrouplist(client['name'], client['gid']))
        os.setegid(client['gid'])
        os.seteuid(client['uid'])
        yield
    finally:
        os.seteuid(uid)
        os.setgroups(groups)
        os.setegid(gid)


def copy_regular_tree(source, destination, *, venv=False, client=None):
    """Copy readable regular files through no-follow descriptors into new files.

    Directory descriptors prevent rename/symlink races in the client-writable
    build tree. Dropped read credentials prevent copying root-only content.
    """
    with read_as(client):
        source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _copy_directory(source_fd, destination, venv, client)
    finally:
        os.close(source_fd)


def _copy_directory(source_fd, destination, venv, client):
    destination.mkdir(mode=0o755, parents=True, exist_ok=True)
    with os.scandir(source_fd) as entries:
        for entry in entries:
            if entry.name in ('__pycache__', '.git') or entry.name.endswith('.pyc'):
                continue
            target = destination / entry.name
            if entry.is_symlink():
                if venv and entry.name == 'lib64' and os.readlink(entry.name, dir_fd=source_fd) == 'lib':
                    continue
                raise RuntimeError(f'Symlink rejected in runtime source: {entry.name}')
            with read_as(client):
                fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_fd)
            try:
                info = os.fstat(fd)
                if stat.S_ISDIR(info.st_mode):
                    _copy_directory(fd, target, venv, client)
                elif stat.S_ISREG(info.st_mode):
                    output_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                    with os.fdopen(os.dup(fd), 'rb') as reader, os.fdopen(output_fd, 'wb') as writer:
                        shutil.copyfileobj(reader, writer)
                    target.chmod(0o755 if info.st_mode & 0o111 else 0o644)
                else:
                    raise RuntimeError(f'Non-regular runtime source: {entry.name}')
            finally:
                os.close(fd)


class System:
    def run(self, *args, check=True):
        return subprocess.run(args, check=check, text=True, capture_output=True, env=ENV)

    def client(self, name):
        entry = pwd.getpwnam(name)
        group = grp.getgrgid(entry.pw_gid)
        if entry.pw_uid == 0 or name == 'mozaproxy':
            raise RuntimeError('Choose a non-root desktop client account')
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.-]*', name + ''):
            raise RuntimeError('Unsupported client account name')
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.-]*', group.gr_name):
            raise RuntimeError('Unsupported client primary group name')
        return {'name': name, 'uid': entry.pw_uid, 'gid': entry.pw_gid, 'group': group.gr_name}

    def ensure_account(self, client):
        created = []
        try:
            try:
                group = grp.getgrnam('mozaproxy-hardware')
            except KeyError:
                self.run('groupadd', '--system', 'mozaproxy-hardware')
                created.append('group')
                group = grp.getgrnam('mozaproxy-hardware')
            if set(group.gr_mem) - {'mozaproxy'} or any(
                user.pw_gid == group.gr_gid and user.pw_name != 'mozaproxy'
                for user in pwd.getpwall()
            ):
                raise RuntimeError('mozaproxy-hardware must contain only the service account')
            try:
                service = pwd.getpwnam('mozaproxy')
            except KeyError:
                self.run('useradd', '--system', '--no-create-home', '--home-dir', '/nonexistent',
                         '--shell', '/usr/sbin/nologin', '--gid', str(client['gid']),
                         '--groups', 'mozaproxy-hardware', 'mozaproxy')
                created.append('user')
                service = pwd.getpwnam('mozaproxy')
            groups = set(os.getgrouplist('mozaproxy', service.pw_gid))
            if (service.pw_uid in (0, client['uid']) or service.pw_gid != client['gid']
                    or groups != {client['gid'], group.gr_gid}
                    or service.pw_shell not in ('/usr/sbin/nologin', '/sbin/nologin', '/bin/false')):
                raise RuntimeError('Existing mozaproxy account has unsafe UID, groups, or login shell')
            return created
        except BaseException:
            self.undo_account(created)
            raise

    def undo_account(self, created):
        if 'user' in created:
            self.run('userdel', 'mozaproxy')
        if 'group' in created:
            self.run('groupdel', 'mozaproxy-hardware')

    def read_templates(self, source, client):
        with read_as(client):
            return ((source / 'systemd/mozaproxy-system.service').read_bytes(),
                    (source / 'udev/71-mozaproxy-system.rules').read_bytes())

    def build_runtime(self, source, destination, client):
        # A user-writable build is never executed by a root Python interpreter.
        build = Path(tempfile.mkdtemp(prefix='mozaproxy-build-', dir='/var/tmp'))
        os.chown(build, client['uid'], client['gid'])
        try:
            venv = build / 'venv'
            self.run('runuser', '--user', client['name'], '--', '/usr/bin/python3', '-I',
                     '-m', 'venv', '--copies', str(venv))
            self.run('runuser', '--user', client['name'], '--', str(venv / 'bin/python'),
                     '-I', '-m', 'pip', '--isolated', 'install', 'evdev>=1.9.0', 'pyserial>=3.5')
            copy_regular_tree(venv, destination / 'venv', venv=True, client=client)
            copy_regular_tree(source / 'mozaproxy', destination / 'app/mozaproxy', client=client)
            sites = list((destination / 'venv/lib').glob('python*/site-packages'))
            if len(sites) != 1:
                raise RuntimeError('Cannot identify private Python site-packages')
            pth_fd = os.open(sites[0] / 'mozaproxy-runtime.pth', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(pth_fd, 'w') as stream:
                stream.write(str(destination / 'app') + '\n')
            # Validate imports under the service identity, never as root.
            self.run('runuser', '--user', 'mozaproxy', '--', str(destination / 'venv/bin/python'),
                     '-I', '-c', 'import evdev, serial, mozaproxy.system_service')
        finally:
            shutil.rmtree(build)

    def busy_processes(self):
        busy = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdecimal() or int(entry.name) == os.getpid():
                continue
            try:
                command = (entry / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
                comm = (entry / 'comm').read_text().strip().lower()
            except (FileNotFoundError, ProcessLookupError):
                continue
            lower = command.lower()
            if (comm.startswith(('wine', 'wineserver')) or comm.endswith('.exe')
                    or re.search(r'(?:^|[/ ])(?:wine(?:64)?|wineserver)(?: |$)', lower)
                    or 'mozaproxy.py' in lower or re.search(r'(?:^| )-m +mozaproxy(?: |\.|$)', lower)
                    or 'open-desktop.py' in lower or 'mozaproxy-app' in lower
                    or 'wheel-harness.py' in lower):
                busy.append(f'{entry.name} {command.strip()}')
        return busy

    def physical_devices(self):
        bases = []
        for entry in Path('/sys/bus/usb/devices').iterdir():
            try:
                if ((entry / 'idVendor').read_text().strip() == '346e'
                        and (entry / 'idProduct').read_text().strip() == '0000'):
                    bases.append(entry.resolve())
            except FileNotFoundError:
                continue
        if not bases:
            return []
        candidates = list(bases)
        for subsystem in ('input', 'hidraw', 'tty'):
            candidates.extend(Path('/sys/class', subsystem).glob('*'))
        nodes = set()
        for entry in candidates:
            resolved = entry.resolve()
            if not any(resolved == base or base in resolved.parents for base in bases):
                continue
            try:
                properties = dict(line.split('=', 1) for line in (entry / 'uevent').read_text().splitlines()
                                  if '=' in line)
            except FileNotFoundError:
                continue
            if 'DEVNAME' in properties:
                nodes.add('/dev/' + properties['DEVNAME'])
        if not nodes:
            raise RuntimeError('Physical MOZA USB device exists but device nodes are unavailable')
        return sorted(nodes)

    def service_state(self):
        result = self.run('systemctl', 'show', '--property=LoadState', '--property=UnitFileState',
                          '--property=ActiveState', UNIT)
        properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        enabled = properties.get('UnitFileState', '')
        if properties.get('LoadState') == 'not-found':
            enabled = 'not-found'
        if enabled not in ('enabled', 'enabled-runtime', 'disabled', 'static', 'indirect', 'not-found'):
            raise RuntimeError(f'Unsupported previous service enablement: {enabled!r}')
        active = properties.get('ActiveState')
        if active not in ('active', 'inactive', 'failed'):
            raise RuntimeError(f'Service is transitioning or state is unavailable: {active!r}')
        return {'enabled': enabled, 'active': active == 'active'}

    def snapshot_uinput(self):
        self.run('modprobe', 'uinput')
        return self.run('getfacl', '--absolute-names', '--numeric', '--', '/dev/uinput').stdout

    def restore_uinput(self, acl):
        # getfacl headers include the exact numeric owner and group for restore.
        if '# file: /dev/uinput\n' not in acl or acl.count('# file:') != 1:
            raise RuntimeError('Invalid uinput ACL recovery data')
        subprocess.run(('setfacl', '--restore=-'), input=acl, text=True,
                       capture_output=True, check=True, env=ENV)

    def wait_for_reconnect(self, timeout):
        print('Reconnect the physical MOZA wheel now. Waiting for fresh device permissions.', flush=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            devices = self.physical_devices()
            if devices:
                self.run('udevadm', 'settle', '--timeout=15')
                return self.physical_devices()
            time.sleep(0.25)
        raise RuntimeError('Timed out waiting for physical wheel reconnect')

    def verify_access(self, client, devices):
        hardware_gid = grp.getgrnam('mozaproxy-hardware').gr_gid
        for name in devices:
            info = Path(name).stat()
            if (not stat.S_ISCHR(info.st_mode) or info.st_uid != 0
                    or info.st_gid != hardware_gid or stat.S_IMODE(info.st_mode) != 0o660):
                raise RuntimeError(f'Physical ownership verification failed for {name}')
            for flag in ('-r', '-w'):
                if self.run('runuser', '--user', client['name'], '--', 'test', flag, name, check=False).returncode != 0:
                    raise RuntimeError(f'Desktop physical access is unavailable: {name}')
                self.run('runuser', '--user', 'mozaproxy', '--', 'test', flag, name)
        for flag in ('-r', '-w'):
            self.run('runuser', '--user', 'mozaproxy', '--', 'test', flag, '/dev/uinput')
        self.run('systemctl', 'is-active', '--quiet', UNIT)
        socket = Path('/run/mozaproxy/control.sock').stat()
        if (not stat.S_ISSOCK(socket.st_mode) or socket.st_uid != pwd.getpwnam('mozaproxy').pw_uid
                or socket.st_gid != client['gid'] or stat.S_IMODE(socket.st_mode) != 0o660):
            raise RuntimeError('Control socket owner or permissions are incorrect')


class Installer:
    def __init__(self, root=Path('/'), system=None):
        self.root = Path(root)
        self.system = system or System()

    def path(self, name):
        return self.root / name.lstrip('/')

    def trusted(self, path):
        """Reject symlinks and any administrative path writable by other users."""
        current = self.root
        parts = path.relative_to(self.root).parts
        for part in parts:
            current /= part
            if current.is_symlink():
                raise RuntimeError(f'Untrusted symlink: {current}')
            if current.exists():
                info = current.stat()
                if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                    raise RuntimeError(f'Untrusted owner or writable administrative path: {current}')

    def atomic(self, target, data, mode=0o644):
        self.trusted(target)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        fd, name = tempfile.mkstemp(prefix='.' + target.name + '-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), mode)
            os.replace(name, target)
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def write_json(self, target, data):
        self.atomic(target, (json.dumps(data, indent=2) + '\n').encode())

    def read_json(self, target):
        self.trusted(target)
        return json.loads(target.read_text())

    def install(self, source, client_name):
        if self.path(STATE + '/activation.json').exists():
            raise RuntimeError('Activation exists; rollback before replacing the runtime')
        state_dir = self.path(STATE)
        releases = self.path('/opt/mozaproxy/releases')
        self.trusted(state_dir)
        self.trusted(releases)
        client = self.system.client(client_name)
        # Read inert templates. No source Python is imported by the installer.
        unit, rules = self.system.read_templates(source, client)
        release_name = '/opt/mozaproxy/releases/' + uuid.uuid4().hex
        release = self.path(release_name)
        releases.mkdir(parents=True, exist_ok=True, mode=0o755)
        created = self.system.ensure_account(client)
        try:
            release.mkdir(mode=0o755)
            self.system.build_runtime(source, release, client)
            # Keep everything needed for activation in the immutable release.
            self.atomic(release / 'service.template', unit)
            self.atomic(release / 'ownership.rules', rules)
            self.write_json(state_dir / 'staged.json', {'version': 1, 'client': client, 'runtime': release_name})
        except BaseException:
            shutil.rmtree(release, ignore_errors=True)
            self.system.undo_account(created)
            raise
        print('Runtime staged. Permissions, service, and desktop integration are not activated.')

    def preflight(self):
        busy = self.system.busy_processes()
        if busy:
            raise RuntimeError('Close running Wine, games, and mozaproxy relays before switching:\n' + '\n'.join(busy))
        if self.system.physical_devices():
            raise RuntimeError('Unplug the physical MOZA wheel before activation or rollback; reconnect when instructed')

    def snapshots(self):
        saved = {}
        for name in (RULE, UNIT_PATH, CONFIG):
            target = self.path(name)
            self.trusted(target)
            saved[name] = ({'data': base64.b64encode(target.read_bytes()).decode(),
                            'mode': stat.S_IMODE(target.stat().st_mode)} if target.exists() else None)
        return saved

    def restore(self, journal):
        errors = []
        try:
            stopped = self.system.run('systemctl', 'stop', UNIT, check=False)
            if stopped.returncode and self.system.run('systemctl', 'is-active', '--quiet', UNIT, check=False).returncode == 0:
                raise RuntimeError('Service is still running')
        except Exception as error:
            errors.append(f'service stop: {error}')
        try:
            disabled = self.system.run('systemctl', 'disable', UNIT, check=False)
            if disabled.returncode and self.system.service_state()['enabled'] in ('enabled', 'enabled-runtime'):
                raise RuntimeError('Service remains enabled')
        except Exception as error:
            errors.append(f'service disable: {error}')
        for name, saved in journal['files'].items():
            try:
                if name not in (RULE, UNIT_PATH, CONFIG):
                    raise RuntimeError('Unknown rollback target')
                target = self.path(name)
                self.trusted(target)
                if saved is None:
                    target.unlink(missing_ok=True)
                else:
                    self.atomic(target, base64.b64decode(saved['data']), saved['mode'])
            except Exception as error:
                errors.append(f'{name}: {error}')
        for command in (('systemctl', 'daemon-reload'), ('udevadm', 'control', '--reload-rules')):
            try:
                self.system.run(*command)
            except Exception as error:
                errors.append(str(error))
        try:
            self.system.restore_uinput(journal['uinput_acl'])
        except Exception as error:
            errors.append(f'uinput ACL restore: {error}')
        try:
            previous = journal['service']
            if previous['enabled'] == 'enabled':
                self.system.run('systemctl', 'enable', UNIT)
            elif previous['enabled'] == 'enabled-runtime':
                self.system.run('systemctl', 'enable', '--runtime', UNIT)
            if previous['active'] and not errors:
                self.system.run('systemctl', 'start', UNIT)
        except Exception as error:
            errors.append(f'previous service state restore: {error}')
        if errors:
            raise RuntimeError('Rollback incomplete; journal retained: ' + '; '.join(errors))
        self.path(STATE + '/activation.json').unlink()

    def activate(self, timeout=120):
        journal_path = self.path(STATE + '/activation.json')
        if journal_path.exists():
            raise RuntimeError('Activation already exists; run rollback first')
        staged = self.read_json(self.path(STATE + '/staged.json'))
        release = self.path(staged['runtime'])
        self.trusted(release)
        self.preflight()
        client = staged['client']
        if self.system.client(client['name']) != client:
            raise RuntimeError('Desktop account changed since installation; stage again')
        self.system.ensure_account(client)
        journal = {'version': 1, 'files': self.snapshots(), 'uinput_acl': self.system.snapshot_uinput(),
                   'service': self.system.service_state()}
        self.write_json(journal_path, journal)
        try:
            self.atomic(self.path(RULE), (release / 'ownership.rules').read_bytes())
            unit = (release / 'service.template').read_text()
            unit = unit.replace('@RUNTIME@', staged['runtime']).replace('@CLIENT_UID@', str(client['uid']))
            unit = unit.replace('@CLIENT_GROUP@', client['group'])
            self.atomic(self.path(UNIT_PATH), unit.encode())
            self.system.run('udevadm', 'control', '--reload-rules')
            self.system.run('udevadm', 'trigger', '--subsystem-match=misc', '--sysname-match=uinput')
            self.system.run('udevadm', 'settle', '--timeout=15')
            self.system.run('systemctl', 'daemon-reload')
            self.system.run('systemctl', 'enable', UNIT)
            self.system.run('systemctl', 'start', UNIT)
            devices = self.system.wait_for_reconnect(timeout)
            self.system.verify_access(client, devices)
            self.write_json(self.path(CONFIG), {'version': 1, 'client_uid': client['uid'],
                                               'socket': '/run/mozaproxy/control.sock'})
        except BaseException as error:
            try:
                self.restore(journal)
            except Exception as rollback_error:
                raise RuntimeError(f'Activation failed: {error}. {rollback_error}. Unplug and reconnect after repair.') from error
            raise RuntimeError(f'Activation failed: {error}. Previous rules restored. Unplug and reconnect the wheel to restore direct access.') from error
        print('Activated with desktop physical access verified and relay off by default. Virtual game and physical force-feedback validation remain pending.')

    def rollback(self):
        # The service can own the wheel until it is unplugged. Never modify live ACLs.
        if self.system.physical_devices():
            raise RuntimeError('Unplug the physical MOZA wheel before rollback')
        journal = self.read_json(self.path(STATE + '/activation.json'))
        self.restore(journal)
        print('Previous rules and integration restored. Reconnect the wheel to restore direct access.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    install = commands.add_parser('install', help='stage runtime and account without activation')
    install.add_argument('--client-user', required=True)
    install.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    activate = commands.add_parser('activate', help='explicit permission switch, requiring unplug/reconnect')
    activate.add_argument('--reconnect-timeout', type=int, default=120)
    commands.add_parser('rollback', help='restore prior configuration after unplugging the wheel')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error('Administrative changes require root; read docs/system-service.md first')
    manager = Installer()
    try:
        lock_path = manager.path(STATE + '/installer.lock')
        manager.trusted(lock_path)
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, 'a') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == 'install':
                manager.install(args.source, args.client_user)
            elif args.command == 'activate':
                if not 1 <= args.reconnect_timeout <= 600:
                    raise RuntimeError('Reconnect timeout must be between 1 and 600 seconds')
                manager.activate(args.reconnect_timeout)
            else:
                manager.rollback()
    except (RuntimeError, OSError, KeyError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
