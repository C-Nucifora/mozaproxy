"""Optional per-user game watcher. Does not change launch options or start relays."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time

from .app_state import ProfileStore
from .game_setup import GameSetupStore, GameSession
from .hardware import HardwareController
from .settings import schema


@contextmanager
def owner_lock(directory):
    Path(directory).mkdir(parents=True, exist_ok=True)
    with (Path(directory) / 'game-watcher.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def write_status(path, data):
    fd, name = tempfile.mkstemp(prefix='.watcher-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, allow_nan=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def watcher_status(directory):
    try:
        with (Path(directory)/'game-watcher-status.json').open() as stream:
            data = json.loads(stream.read(16385))
        if not isinstance(data, dict) or time.time() - data.get('updated', 0) > 10:
            return {}
        return data
    except (OSError, ValueError, TypeError):
        return {}


def desktop_open(directory):
    try:
        with (Path(directory)/'desktop-presence.json').open() as stream:
            data = json.loads(stream.read(512))
        return isinstance(data, dict) and 0 <= time.time() - data.get('updated', 0) < 10
    except (OSError, ValueError, TypeError):
        return False


class GameWatcher:
    def __init__(self, directory, hardware=None, scan=None):
        self.directory = Path(directory)
        self.setup = GameSetupStore(directory)
        self.profiles = ProfileStore(directory, schema)
        self.hardware = hardware if hardware is not None else HardwareController()
        self.session = GameSession() if scan is None else GameSession(scan)
        self.event = {}

    def tick(self):
        settings = self.setup.settings()
        # Reload profiles: another app can edit their atomic document.
        self.profiles = ProfileStore(self.directory, schema)
        if self.profiles.error:
            raise ValueError(self.profiles.error)
        result = self.session.poll(settings, self.profiles.snapshot()[0])
        if result:
            self.event = dict(game_id=result['game_id'], action=result['action'], time=time.time(), message=result.get('message', ''))
            if 'profile' in result:
                profile = result['profile']
                self.event['profile_id'] = profile['id']
                self.event['message'] = 'Linked profile selected; manual Apply is available.'
                if result['action'] == 'apply':
                    # A visible desktop may have unsaved edits. Never race its user.
                    if desktop_open(self.directory):
                        self.event['message'] = 'Automatic Apply skipped while the desktop is open. Apply the selected profile manually.'
                    else:
                        try:
                            status = self.hardware.connect()
                            if not status.get('connected') or status.get('busy') or status.get('conflict') or status.get('error'):
                                raise ValueError(status.get('error') or status.get('conflict') or 'Settings unavailable')
                            latest = self.setup.settings()
                            latest_profiles = ProfileStore(self.directory, schema)
                            live = self.session.scan()
                            same_launch = set(live) == {result['game_id']} and bool(live[result['game_id']] & self.session.previous[result['game_id']])
                            same_policy = all(latest[k] == settings[k] for k in ('detection', 'automatic', 'links'))
                            same_profile = not latest_profiles.error and profile in latest_profiles.snapshot()[0]
                            if desktop_open(self.directory) or not same_launch or not same_policy or not same_profile:
                                raise ValueError('Game, profile or automation eligibility changed while reading settings')
                            report = self.hardware.apply(profile['settings'])
                            self.event['message'] = 'Automatic Apply had errors; inspect settings.' if report.get('errors') else 'Linked profile applied and read back.'
                            # Full report remains local and exportable, never contains process environment.
                            write_status(self.directory/'game-watcher-apply.json', report)
                        except (OSError, ValueError) as exc:
                            self.event['message'] = 'Automatic Apply skipped or failed: ' + str(exc)
                        finally:
                            self.hardware.close()
        status = dict(pid=os.getpid(), updated=time.time(), detection=settings['detection'], event=self.event)
        write_status(self.directory/'game-watcher-status.json', status)
        return status

    def close(self):
        self.hardware.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'mozaproxy')
    args = parser.parse_args(argv)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    while not stop.is_set():
        with owner_lock(args.data_dir) as owner:
            if not owner:
                stop.wait(2)
                continue
            watcher = GameWatcher(args.data_dir)
            try:
                while not stop.is_set():
                    try:
                        watcher.tick()
                    except (OSError, ValueError) as exc:
                        write_status(args.data_dir/'game-watcher-status.json', dict(pid=os.getpid(), updated=time.time(), error=str(exc)))
                        watcher.session.previous = None
                    stop.wait(2)
            finally:
                watcher.close()
                (args.data_dir/'game-watcher-status.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
