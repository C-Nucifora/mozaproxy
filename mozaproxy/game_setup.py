"""Local game evidence and opt-in launch decisions; no hardware access on reads."""

from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading

# Exact application IDs and executable basenames, not substring process matches.
GAMES = {
    'fh5': ('1551360', {'forzahorizon5.exe'}),
    'jdm': ('1153410', {'jdm-win64-shipping.exe'}),
    'fs22': ('1248130', {'farmingsimulator2022game.exe'}),
    'fs25': ('2300320', {'farmingsimulator2025game.exe'}),
    'ac': ('244210', {'acs.exe', 'acs_x86.exe'}),
    'acc': ('805550', {'acc-win64-shipping.exe'}),
    'lmu': ('2399420', {'le mans ultimate.exe'}),
    'heat': ('1222680', {'needforspeedheat.exe'}),
    'beamng': ('284160', {'beamng.drive.x64.exe', 'beamng.drive.x64'}),
    'ets2': ('227300', {'eurotrucks2.exe', 'eurotrucks2'}),
}
RESULTS = ('untested', 'pass', 'fail')
CHECKS = ('launch', 'input', 'ffb', 'pause_resume')


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def short_text(value, limit=200):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c != '\n' for c in value):
        raise ValueError(f'Text must contain at most {limit} printable characters')
    return value.strip()


class GameSetupStore:
    def __init__(self, directory):
        self.path = Path(directory) / 'game-setup.json'
        self.lock = threading.RLock()

    def settings(self):
        try:
            with self.path.open() as stream:
                text = stream.read(262145)
        except FileNotFoundError:
            return dict(detection=False, automatic=False, links={}, records=[])
        if len(text) > 262144:
            raise ValueError('Game setup exceeds 256 KiB')
        data = json.loads(text)
        self.validate(data)
        return data

    @staticmethod
    def validate(data):
        if not isinstance(data, dict) or set(data) != {'detection', 'automatic', 'links', 'records'}:
            raise ValueError('Invalid game setup document')
        if any(type(data[k]) is not bool for k in ('detection', 'automatic')):
            raise ValueError('Automation options must be boolean')
        if not isinstance(data['links'], dict) or set(data['links']) - GAMES.keys():
            raise ValueError('Unknown linked game')
        for link in data['links'].values():
            if not isinstance(link, dict) or set(link) != {'profile_id', 'automatic'} or type(link['automatic']) is not bool:
                raise ValueError('Invalid profile link')
            if not short_text(link['profile_id'], 64):
                raise ValueError('Select a saved profile')
        if not isinstance(data['records'], list) or len(data['records']) > 200:
            raise ValueError('At most 200 game test records are retained')
        for record in data['records']:
            if not isinstance(record, dict) or set(record) != {'game_id', 'time', 'route', 'runtime', 'wheel', 'notes', *CHECKS}:
                raise ValueError('Invalid game test record')
            if not isinstance(record['game_id'], str) or record['game_id'] not in GAMES or any(record[k] not in RESULTS for k in CHECKS):
                raise ValueError('Unknown game or test result')
            for key in ('time', 'route', 'runtime', 'wheel', 'notes'):
                short_text(record[key], 2000 if key == 'notes' else 200)

    def _change(self, edit):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix('.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                data = self.settings()  # Never replace a malformed document.
                edit(data)
                self.validate(data)
                content = json.dumps(data, ensure_ascii=True, allow_nan=False)
                if len(content) > 262144:
                    raise ValueError('Game setup exceeds 256 KiB')
                fd, name = tempfile.mkstemp(prefix='.game-setup-', dir=self.path.parent)
                try:
                    with os.fdopen(fd, 'w') as stream:
                        stream.write(content + '\n')
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(name, self.path)
                finally:
                    Path(name).unlink(missing_ok=True)
        return self.snapshot()

    def save(self, patch, profiles):
        if not isinstance(patch, dict) or set(patch) - {'detection', 'automatic', 'game_id', 'profile_id', 'game_automatic'}:
            raise ValueError('Invalid game setup options')
        for flag in ('detection', 'automatic', 'game_automatic'):
            if flag in patch and type(patch[flag]) is not bool:
                raise ValueError('Automation options must be boolean')
        if 'game_id' not in patch and {'profile_id', 'game_automatic'} & patch.keys():
            raise ValueError('Select a game')
        def edit(data):
            for key in ('detection', 'automatic'):
                if key in patch:
                    data[key] = patch[key]
            if 'game_id' in patch:
                game = patch['game_id']
                if not isinstance(game, str) or game not in GAMES:
                    raise ValueError('Unknown game')
                profile = patch.get('profile_id')
                if profile is None:
                    data['links'].pop(game, None)
                elif not any(p['id'] == profile for p in profiles):
                    raise ValueError('Linked profile no longer exists')
                else:
                    data['links'][game] = dict(profile_id=profile, automatic=patch.get('game_automatic', False))
        return self._change(edit)

    def record(self, record):
        if not isinstance(record, dict) or 'time' in record:
            raise ValueError('Supply a game result without a timestamp')
        value = dict(record, time=stamp())
        return self._change(lambda data: data.update(records=[*data['records'][-199:], value]))

    def snapshot(self):
        try:
            from .game_service import watcher_status
            return dict(self.settings(), error=None, watcher=watcher_status(self.path.parent))
        except (ValueError, OSError) as exc:
            return dict(detection=False, automatic=False, links={}, records=[], error=str(exc))


def preflight(game_id, protection=False):
    """Only inspect prerequisites. No process launch, port scan or device open."""
    if game_id not in GAMES:
        raise ValueError('Unknown game')
    items = []
    if game_id in ('fh5', 'heat'):
        items.append(dict(name='bubblewrap', available=bool(shutil.which('bwrap'))))
        items.append(dict(name='Relay setup', available=None, detail='Start the tested relay mapping explicitly before this game.'))
    if game_id == 'jdm':
        items.append(dict(name='JDM HID helper', available=(Path.home()/'.local/lib/mozaproxy/jdm_hid.so').is_file()))
    if protection and game_id in ('acc', 'lmu'):
        from .protection import library_path
        items.append(dict(name='Menu force helper', available=library_path().is_file()))
    items.append(dict(name='Attended validation', available=None, detail='Launch/input/physical force are separate checks; prerequisites do not prove compatibility.'))
    return items


def running_games(proc_root=Path('/proc')):
    found = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            with (entry/'environ').open('rb') as stream:
                environment = stream.read(65537)
            if len(environment) > 65536:
                continue
            ids = {v.split(b'=', 1)[1].decode('ascii', 'ignore') for v in environment.split(b'\0')
                   if v.startswith((b'SteamAppId=', b'SteamGameId='))}
            if len(ids) != 1:
                continue
            matches = [g for g, (app, _) in GAMES.items() if app in ids]
            if len(matches) != 1:
                continue
            game = matches[0]
            with (entry/'cmdline').open('rb') as stream:
                command = stream.read(32769)
            if len(command) > 32768:
                continue
            names = {arg.decode('utf-8', 'replace').replace('\\', '/').rsplit('/', 1)[-1].casefold()
                     for arg in command.split(b'\0')}
            if not names & GAMES[game][1]:
                continue
            stat = (entry/'stat').read_text()[:4096]
            start = stat.rsplit(')', 1)[1].split()[19]
            found.setdefault(game, set()).add((int(entry.name), int(start)))
        except (OSError, ValueError, IndexError):
            continue
    return found


class GameSession:
    """Consume launch transitions once. The caller owns the automation lock."""
    def __init__(self, scan=running_games):
        self.scan = scan
        self.previous = None
        self.policy = None

    def poll(self, settings, profiles, blocked=False):
        policy = json.dumps({k: settings[k] for k in ('detection', 'automatic', 'links')}, sort_keys=True)
        current = self.scan() if settings['detection'] else {}
        previous = self.previous
        self.previous, old_policy, self.policy = current, self.policy, policy
        if previous is None or policy != old_policy or len(current) != 1:
            return None
        game, tokens = next(iter(current.items()))
        if game in previous:
            # Require an observed exit before rearming; wrapper PID churn is not a new launch.
            return None
        link = settings['links'].get(game)
        if not link:
            return dict(game_id=game, action='notice', message='No profile linked to this game.')
        profile = next((p for p in profiles if p['id'] == link['profile_id']), None)
        if profile is None:
            return dict(game_id=game, action='notice', message='Linked profile no longer exists.')
        if blocked:
            return dict(game_id=game, action='notice', message='Game detected; profile selection and automatic Apply skipped because the app has pending edits or is busy.')
        automatic = settings['automatic'] and link['automatic']
        return dict(game_id=game, action='apply' if automatic else 'select', profile=deepcopy(profile), policy=policy, launch_tokens=tuple(tokens))
