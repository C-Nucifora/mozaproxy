"""Saved menu-force protection and an opt-in direct-game launcher."""

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import threading

DESCRIPTION = 'Intended for games whose menus cause a constant force-feedback pull.'
DETAIL = 'Applies on the next game or relay start. Increase the timeout if driving force cuts out; stale menu force will also last longer. Direct games must use the protection launcher. R25 evdev only; not a hardware torque limit.'
DEFAULT_TIMEOUT_MS = 100


def timeout_ms(value):
    if isinstance(value, bool):
        raise ValueError('Force timeout must be a whole number from 50 to 1000 ms')
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise ValueError('Force timeout must be a whole number from 50 to 1000 ms') from None
    if str(number) != str(value) or not 50 <= number <= 1000:
        raise ValueError('Force timeout must be a whole number from 50 to 1000 ms')
    return number


def library_path():
    return Path.home() / '.local/lib/mozaproxy/menu_force_guard.so'


def launcher_options(directory=None):
    command = [sys.executable, str(Path(__file__).resolve())]
    default = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'mozaproxy'
    if directory is not None and Path(directory).resolve() != default.resolve():
        command.extend(['--data-dir', str(Path(directory).resolve())])
    return shlex.join([*command, '--']) + ' %command%'


class ProtectionStore:
    def __init__(self, directory=None):
        directory = Path(directory) if directory is not None else Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'mozaproxy'
        self.path = directory / 'protection.json'
        self.lock = threading.RLock()

    def settings(self):
        with self.lock:
            try:
                with self.path.open() as stream:
                    text = stream.read(4097)
            except FileNotFoundError:
                return {'menu_force_protection': False, 'menu_force_timeout_ms': DEFAULT_TIMEOUT_MS}
            if len(text) > 4096:
                raise ValueError('Protection settings exceed 4 KiB')
            data = json.loads(text)
            if not isinstance(data, dict) or set(data) - {'menu_force_protection', 'menu_force_timeout_ms'} or type(data.get('menu_force_protection')) is not bool:
                raise ValueError('Invalid menu force protection settings')
            value = data.get('menu_force_timeout_ms', DEFAULT_TIMEOUT_MS)
            if type(value) is not int:
                raise ValueError('Force timeout must be an integer')
            return dict(menu_force_protection=data['menu_force_protection'], menu_force_timeout_ms=timeout_ms(value))

    def enabled(self):
        return self.settings()['menu_force_protection']

    def snapshot(self):
        error = None
        try:
            settings = self.settings()
            enabled, timeout = settings['menu_force_protection'], settings['menu_force_timeout_ms']
        except (OSError, ValueError) as exc:
            enabled, timeout, error = False, DEFAULT_TIMEOUT_MS, str(exc)
        return dict(enabled=enabled, timeout_ms=timeout, error=error, description=DESCRIPTION, detail=DETAIL,
                    launch_options=launcher_options(self.path.parent))

    def save(self, enabled, timeout=None):
        if type(enabled) is not bool:
            raise ValueError('Menu force protection must be a boolean')
        with self.lock:
            current = self.settings()  # Preserve malformed documents rather than overwriting them.
            timeout = current['menu_force_timeout_ms'] if timeout is None else timeout_ms(timeout)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.protection-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'menu_force_protection': enabled, 'menu_force_timeout_ms': timeout}, stream)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
        return self.snapshot()


def game_environment(enabled, environment=None, timeout=DEFAULT_TIMEOUT_MS):
    env = dict(os.environ if environment is None else environment)
    # Replace only our own helpers, so switching off cannot leave the LMU guard on.
    own = {str(library_path()), str(library_path().with_name('lmu_ffb_guard.so'))}
    preload = [part for part in env.get('LD_PRELOAD', '').replace(':', ' ').split() if part not in own]
    if enabled:
        timeout = timeout_ms(timeout)
        if env.get('PROTON_ENABLE_HIDRAW'):
            raise ValueError('Menu force protection requires evdev; this launch enables HIDRAW')
        library = library_path()
        if not library.is_file():
            raise ValueError('Menu force guard is not installed. Run install.sh or build tools/menu_force_guard.c as documented.')
        if any(c.isspace() or c == ':' for c in str(library)):
            raise ValueError('The guard library path cannot contain spaces or colons')
        preload.insert(0, str(library))
        env['MOZAPROXY_MENU_FORCE_TIMEOUT_MS'] = str(timeout)
    else:
        env.pop('MOZAPROXY_MENU_FORCE_TIMEOUT_MS', None)
    if preload:
        env['LD_PRELOAD'] = ':'.join(preload)
    else:
        env.pop('LD_PRELOAD', None)
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--menu-force-protection', action=argparse.BooleanOptionalAction,
                        default=None, help='Override the saved toggle for this launch')
    parser.add_argument('--menu-force-timeout-ms', type=timeout_ms, help='Stale-force timeout, 50–1000 ms; default 100')
    parser.add_argument('--data-dir', type=Path, help='Use an alternate app settings directory')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('Supply the game command after --')
    try:
        settings = ProtectionStore(args.data_dir).settings()
        enabled = settings['menu_force_protection'] if args.menu_force_protection is None else args.menu_force_protection
        timeout = settings['menu_force_timeout_ms'] if args.menu_force_timeout_ms is None else args.menu_force_timeout_ms
        env = game_environment(enabled, timeout=timeout)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print('mozaproxy: menu force protection ' + (f'enabled ({timeout} ms)' if enabled else 'disabled'), file=sys.stderr, flush=True)
    os.execvpe(command[0], command, env)


if __name__ == '__main__':
    main()
