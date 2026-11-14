"""Opt-in lighting watcher, separate from Steam's runtime and profile automation."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid

from .game_setup import running_games

DEFAULTS = dict(enabled=False, base_alerts=False, activity_alerts=False,
                rpm_start_percent=50, rpm_end_percent=100)
UNIT = 'mozaproxy-lighting.service'


def config_directory():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'mozaproxy'


def helper_path():
    return Path.home() / '.local/lib/mozaproxy/telemetry/mozaproxy-shared-memory.exe'


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.lighting-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _validate(data):
    if not isinstance(data, dict) or set(data) - DEFAULTS.keys():
        raise ValueError('Invalid lighting settings')
    result = {**DEFAULTS, **data}
    if any(type(result[key]) is not bool for key in ('enabled', 'base_alerts', 'activity_alerts')):
        raise ValueError('Lighting toggles must be booleans')
    start, end = result['rpm_start_percent'], result['rpm_end_percent']
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= 100:
        raise ValueError('RPM percentages must be integers with 0 <= start < end <= 100')
    return result


class LightingStore:
    def __init__(self, directory=None):
        self.path = (Path(directory) if directory is not None else config_directory()) / 'lighting.json'
        self.lock = threading.RLock()

    def settings(self):
        with self.lock:
            try:
                with self.path.open() as stream:
                    text = stream.read(4097)
            except FileNotFoundError:
                return dict(DEFAULTS)
            if len(text) > 4096:
                raise ValueError('Lighting settings exceed 4 KiB')
            return _validate(json.loads(text))

    def save(self, patch):
        if not isinstance(patch, dict) or set(patch) - DEFAULTS.keys():
            raise ValueError('Invalid lighting settings')
        with self.lock:
            settings = _validate({**self.settings(), **patch})
            _write_json(self.path, settings)
        return self.snapshot()

    def snapshot(self):
        error = None
        try:
            settings = self.settings()
        except (OSError, ValueError) as exc:
            settings, error = dict(DEFAULTS), str(exc)
        status = {}
        try:
            with self.path.with_name('lighting-status.json').open() as stream:
                raw = stream.read(16385)
            status = json.loads(raw) if len(raw) <= 16384 else {}
            if not isinstance(status, dict) or not 0 <= time.time() - status.get('updated', 0) < 30:
                status = {}
        except (OSError, ValueError, TypeError):
            status = {}
        return dict(**settings, error=error, status=status,
                    helper_available=helper_path().is_file(),
                    launcher_available=bool(shutil.which('protontricks-launch')),
                    service_installed=(config_directory().parent / 'systemd/user' / UNIT).is_file())


def start_if_enabled(directory=None):
    """Best effort only: never prevent or modify a game launch."""
    try:
        store = LightingStore(directory)
        if not store.settings()['enabled']:
            return
        if store.path.parent.resolve() != config_directory().resolve():
            raise ValueError('Managed lighting service uses the default settings directory')
        result = subprocess.run(['systemctl', '--user', '--no-block', 'start', UNIT],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=2, check=False)
        if result.returncode:
            raise OSError('Could not start managed lighting; install its user service')
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        import sys
        print(f'mozaproxy: lighting unavailable: {exc}', file=sys.stderr, flush=True)


class LightingWatcher:
    def __init__(self, directory, hardware=None, monitor=None, scan=running_games):
        from .hardware import HardwareController
        from .telemetry import TelemetryMonitor
        self.store = LightingStore(directory)
        self.hardware = hardware if hardware is not None else HardwareController()
        self.monitor = monitor if monitor is not None else TelemetryMonitor(self.hardware)
        self.scan = scan
        self.launch = set()
        self.policy = None
        self.helper = None
        self.lease = None
        self.deadline = 0
        self.retry_at = 0
        self.failed = False
        self.output = False
        self.message = 'Waiting for Le Mans Ultimate'
        self.error = None

    def _stop_helper(self):
        if self.lease is not None:
            self.lease.unlink(missing_ok=True)
            self.lease = None
        helper, self.helper = self.helper, None
        if helper is not None and helper.poll() is None:
            try:
                helper.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Only our launcher PID. Never signal Wine's process group or server.
                helper.terminate()
                try:
                    helper.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    helper.kill()
                    helper.wait(timeout=2)

    def close(self):
        try:
            self.monitor.stop()
        finally:
            try:
                self.hardware.close()
            finally:
                self._stop_helper()
                self.output = False

    def _fail(self, error):
        self.failed = True
        self.error = str(error)
        self.message = 'Lighting stopped; toggle lighting or restart the game to retry'
        try:
            self.close()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.error += '; cleanup: ' + str(exc)

    def _launch_helper(self):
        launcher = shutil.which('protontricks-launch')
        path = helper_path()
        if launcher is None or not path.is_file():
            raise ValueError('Install protontricks-launch and the LMU telemetry helper first')
        self.lease = self.store.path.parent / ('lighting-lease-' + uuid.uuid4().hex)
        self.lease.touch(mode=0o600)
        windows_lease = 'Z:' + str(self.lease.resolve()).replace('/', '\\')
        self.helper = subprocess.Popen([launcher, '--appid', '2399420', str(path),
                                        'lmu', '20777', windows_lease],
                                       stdin=subprocess.DEVNULL, start_new_session=True)

    def tick(self):
        try:
            settings = self.store.settings()
            games = self.scan()
            launch = games.get('lmu', set()) if set(games) == {'lmu'} else set()
            changed = settings != self.policy or bool(launch) != bool(self.launch) or (
                launch and not launch.intersection(self.launch))
            if changed:
                self.close()
                self.policy = settings
                self.failed, self.error = False, None
                self.deadline, self.retry_at = time.monotonic() + 180, 0
            self.launch = launch
            if not settings['enabled']:
                self.message = 'Managed lighting is disabled'
            elif not launch:
                self.message = ('Only one running LMU game is supported for managed lighting'
                                if games else 'Waiting for Le Mans Ultimate')
            elif not self.failed:
                if self.lease is not None:
                    os.utime(self.lease, None)
                state = self.monitor.status()
                if self.output:
                    if self.helper is None or self.helper.poll() is not None:
                        raise ValueError('LMU telemetry helper exited; toggle lighting to retry')
                    if not state.get('running') or state.get('error'):
                        raise ValueError(state.get('error') or 'Telemetry output stopped')
                    self.message = 'Lighting active' if not state.get('stale') else 'Waiting for fresh LMU telemetry'
                else:
                    now = time.monotonic()
                    if now > self.deadline:
                        raise ValueError('No valid LMU telemetry within 180 seconds; enter a session and retry')
                    if not state.get('running'):
                        self.monitor.start(source='lmu', output=False)
                    if self.helper is not None and self.helper.poll() is not None:
                        self._stop_helper()
                        self.retry_at = now + 5
                    if self.helper is None and now >= self.retry_at:
                        self._launch_helper()
                    state = self.monitor.status()
                    self.message = 'Waiting for valid LMU telemetry before connecting the wheel'
                    if self.helper is not None and state.get('sample') and not state.get('stale'):
                        status = self.hardware.connect()
                        if not status.get('connected') or any(status.get(k) for k in ('busy', 'conflict', 'error')):
                            raise ValueError(status.get('error') or status.get('conflict') or 'Wheel settings connection unavailable')
                        # Connecting can take seconds. Recheck permission and game before any lighting writes.
                        latest = self.scan()
                        if self.store.settings() != settings or set(latest) != {'lmu'} or not launch.intersection(latest['lmu']):
                            raise ValueError('Game or lighting settings changed while connecting')
                        if self.lease is not None:
                            os.utime(self.lease, None)
                        self.monitor.stop()
                        self.monitor.start(source='lmu', output=True,
                                           base_alerts=settings['base_alerts'], activity_alerts=settings['activity_alerts'],
                                           rpm_start_percent=settings['rpm_start_percent'], rpm_end_percent=settings['rpm_end_percent'])
                        self.output = True
                        self.message = 'Lighting active'
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self._fail(exc)
        status = dict(pid=os.getpid(), updated=time.time(), message=self.message,
                      error=self.error, output=self.output, telemetry=self.monitor.status())
        _write_json(self.store.path.with_name('lighting-status.json'), status)
        return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=config_directory())
    args = parser.parse_args(argv)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    with (args.data_dir / 'lighting.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        watcher = LightingWatcher(args.data_dir)
        def heartbeat():
            while not stop.wait(1):
                lease = watcher.lease
                if lease is not None:
                    try:
                        os.utime(lease, None)
                    except OSError:
                        pass  # A removed lease must stay removed while the helper exits.
        pulse = threading.Thread(target=heartbeat, daemon=True, name='lighting-lease')
        pulse.start()
        try:
            while not stop.is_set():
                watcher.tick()
                stop.wait(1)
        finally:
            stop.set()
            pulse.join(timeout=2)
            watcher.close()
            (args.data_dir / 'lighting-status.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
