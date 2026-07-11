#!/usr/bin/env python3
"""
mozactl - operate and diagnose the mozaproxy compatibility layer.

  mozactl status                 one-glance health of the whole pipeline
  mozactl doctor [--fix]         deeper checks + suggested/automatic fixes
  mozactl start [args...]        start the mozaproxy daemon in a chosen mode
  mozactl stop                   stop the daemon (wheel disappears from games)
  mozactl modes                  list the presentation modes (faces)
  mozactl list                   list game profiles (shipped seeds + your own)
  mozactl run PROFILE -- CMD...  apply PROFILE's mode/env, then exec the game
  mozactl calibrate              interactive axis mapper -> calibration.toml

The wheel is intentionally hidden from games at the udev layer, so it exists for
games ONLY while the daemon runs. `status` makes that state obvious; `start`
brings the clean virtual wheel up; `doctor` fixes the common setup gaps.

`run` is the Steam glue: put `mozactl run <profile> -- %command%` in a game's
launch options and the right mode, FFB gain, calibrated axes and Proton env are
applied per game. It errs on the side of launching: a broken profile or a
powered-off base must never brick the game start Steam asked for.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(REPO_DIR, ".venv", "bin", "python")
DAEMON = os.path.join(REPO_DIR, "mozaproxy.py")
PIDFILE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "mozaproxy.pid"
)
STATEFILE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "mozaproxy.state.json"
)

MOZA_VENDOR = 0x346E
REAL_PRODUCT = 0x0000
VIRT_PRODUCT = 0x0002  # mozaproxy's virtual device (see mozaproxy.py DEFAULT_PRODUCT)
GOOD_DRIVER = "hid-universal-pidff"

# ---- pretty output ---------------------------------------------------------
_TTY = sys.stdout.isatty()
def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _TTY else s
OK = _c("32", "OK  ")
WARN = _c("33", "WARN")
FAIL = _c("31", "FAIL")
NA = _c("90", "----")


def line(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status}] {label}" + (f"  {_c('90', detail)}" if detail else ""))


# ---- detection (no external deps beyond evdev + udevadm) -------------------
def usb_present() -> tuple[bool, str, str]:
    """Return (present, product_hex, product_name) for the MOZA base on USB."""
    for idv in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        try:
            if open(idv).read().strip().lower() != "346e":
                continue
            base = os.path.dirname(idv)
            pid = open(os.path.join(base, "idProduct")).read().strip()
            name = ""
            pf = os.path.join(base, "product")
            if os.path.exists(pf):
                name = open(pf).read().strip()
            return True, pid, name
        except OSError:
            continue
    return False, "", ""


def hid_driver() -> str | None:
    """Which HID driver bound the base (want hid-universal-pidff)."""
    for d in glob.glob("/sys/bus/hid/devices/*"):
        b = os.path.basename(d).upper()
        if f":{MOZA_VENDOR:04X}:" in b:
            drv = os.path.join(d, "driver")
            if os.path.islink(drv):
                return os.path.basename(os.readlink(drv))
            return None
    return None


def _iter_evdev():
    import evdev
    for p in evdev.list_devices():
        try:
            yield evdev.InputDevice(p)
        except OSError:
            continue


def real_evdev_path() -> str | None:
    """The real base's event node (has axes + force feedback)."""
    from evdev import ecodes
    for d in _iter_evdev():
        c = d.capabilities()
        if (d.info.vendor == MOZA_VENDOR and d.info.product == REAL_PRODUCT
                and ecodes.EV_ABS in c and ecodes.EV_FF in c):
            return d.path
    return None


def virtual_present() -> str | None:
    """The mozaproxy virtual device name, if the daemon has created it."""
    for d in _iter_evdev():
        if d.info.vendor == MOZA_VENDOR and d.info.product == VIRT_PRODUCT:
            return d.name
        if "mozaproxy" in d.name.lower():
            return d.name
    return None


def real_hidden(path: str) -> bool | None:
    """True if the real node is NOT tagged ID_INPUT_JOYSTICK (games skip it)."""
    try:
        out = subprocess.run(["udevadm", "info", path], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return "ID_INPUT_JOYSTICK=1" not in out


def daemon_pids() -> list[int]:
    pids = []
    for c in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            parts = open(c, "rb").read().split(b"\0")
        except OSError:
            continue
        joined = b" ".join(parts)
        if b"mozaproxy.py" in joined and b"mozactl" not in joined:
            try:
                pids.append(int(c.split("/")[2]))
            except (IndexError, ValueError):
                pass
    return pids


# ---- runtime state ----------------------------------------------------------
# `run` decides whether the daemon needs a restart by comparing the argv it
# WANTS with the argv the daemon was STARTED with; the state file records the
# latter (pid guards against a stale file surviving a crash or reboot).
def _write_state(pid: int, mode: str, argv: list[str],
                 profile: str | None = None) -> None:
    state = {"pid": pid, "mode": mode, "argv": list(argv), "profile": profile}
    try:
        with open(STATEFILE, "w") as f:
            json.dump(state, f)
    except OSError:
        pass


def _read_state() -> dict | None:
    """The recorded daemon state, or None if missing/corrupt."""
    try:
        with open(STATEFILE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def _clear_state() -> None:
    try:
        os.unlink(STATEFILE)
    except OSError:
        pass


def _terminate_daemon(wait: float = 0.0) -> list[int]:
    """SIGTERM every running daemon; optionally wait for them to exit.

    The wait matters before a respawn: the dying daemon must release its
    exclusive grab on the real base or the new one cannot take it.
    """
    pids = daemon_pids()
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError as e:
            print(f"Could not stop pid {pid}: {e}")
    if pids and wait > 0:
        deadline = time.time() + wait
        while daemon_pids() and time.time() < deadline:
            time.sleep(0.1)
    return pids


def _spawn_daemon(argv_tail: list[str]) -> int | None:
    """Start mozaproxy.py with argv_tail; return its pid, or None on failure."""
    present, _, _ = usb_present()
    if not present:
        print(_c("31", "Base not on USB — power the wheelbase on first."))
        return None
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    proc = subprocess.Popen([py, DAEMON] + list(argv_tail), start_new_session=True)
    try:
        with open(PIDFILE, "w") as f:
            f.write(str(proc.pid))
    except OSError:
        pass
    time.sleep(1.5)
    if proc.poll() is not None:
        print(_c("31", "Daemon exited immediately — run for logs: ")
              + f"{py} {DAEMON} {' '.join(argv_tail)} -v")
        return None
    if virtual_present():
        print(_c("32", "Started.") + f" Virtual wheel up (pid {proc.pid}).")
    else:
        print(f"Started (pid {proc.pid}); virtual node not seen yet — check: mozactl status")
    return proc.pid


# ---- commands --------------------------------------------------------------
def cmd_status(_args) -> int:
    present, pid, name = usb_present()
    print(_c("1", "mozaproxy status"))
    if present:
        line(OK, "Base on USB", f"346e:{pid} {name}")
    else:
        line(FAIL, "Base on USB", "not found — power the wheelbase on / check cable")

    drv = hid_driver() if present else None
    if not present:
        line(NA, "Kernel driver")
    elif drv == GOOD_DRIVER:
        line(OK, "Kernel driver", drv)
    elif drv:
        line(WARN, "Kernel driver", f"{drv} (expected {GOOD_DRIVER}; FFB may be limited)")
    else:
        line(WARN, "Kernel driver", "no HID driver bound")

    real = real_evdev_path() if present else None
    if not present:
        line(NA, "Real node hidden from games")
    elif real is None:
        line(WARN, "Real node hidden from games", "real event node not found")
    else:
        h = real_hidden(real)
        if h is True:
            line(OK, "Real node hidden from games", f"{real} (ID_INPUT_JOYSTICK cleared)")
        elif h is False:
            line(FAIL, "Real node hidden from games",
                 f"{real} still visible — run: mozactl doctor --fix")
        else:
            line(WARN, "Real node hidden from games", "could not query udev")

    pids = daemon_pids()
    if pids:
        detail = f"pid {', '.join(map(str, pids))}"
        state = _read_state()
        # Only trust the state file if it describes a daemon that is alive.
        if state and state.get("pid") in pids:
            detail += f", mode {state.get('mode', '?')}"
            if state.get("profile"):
                detail += f" (profile {state['profile']})"
        line(OK, "Daemon running", detail)
    else:
        line(WARN, "Daemon running", "not running — start with: mozactl start")

    virt = virtual_present()
    if virt:
        line(OK, "Virtual wheel present", f"'{virt}' — bind games to this")
    elif pids:
        line(WARN, "Virtual wheel present", "daemon up but no virtual node yet")
    else:
        line(WARN, "Virtual wheel present", "none (start the daemon)")

    print()
    if present and pids and virt:
        print("  " + _c("32", "Ready.") + " Games should see the clean virtual wheel.")
        return 0
    if present and not pids:
        print("  " + _c("33", "Base is ready but the daemon is down —")
              + " games currently see NO wheel (real node is hidden).")
        print("  Start it:  " + _c("1", "mozactl start"))
        return 1
    if not present:
        print("  Power the base on, then re-run " + _c("1", "mozactl status") + ".")
        return 1
    return 1


def cmd_doctor(args) -> int:
    print(_c("1", "mozaproxy doctor"))
    problems = []

    rules = "/etc/udev/rules.d/99-mozaproxy.rules"
    if os.path.exists(rules):
        line(OK, "udev hide-rule installed", rules)
    else:
        line(FAIL, "udev hide-rule installed", "missing — run ./install.sh")
        problems.append("install")

    present, pid, _ = usb_present()
    if not present:
        line(WARN, "Base powered on", "not on USB — power it on to finish diagnosis")
    else:
        real = real_evdev_path()
        h = real_hidden(real) if real else None
        if h is True:
            line(OK, "Real node hidden", real)
        elif h is False:
            line(FAIL, "Real node hidden", "still tagged joystick")
            problems.append("retrigger")
        else:
            line(WARN, "Real node hidden", "real node not found / udev unqueryable")

    in_input = _user_in_input()
    line(OK if in_input else WARN, "User in 'input' group",
         "yes" if in_input else "no (fallback access) — run ./install.sh")

    if not problems:
        print("\n  " + _c("32", "No problems found."))
        return 0

    print("\n  Suggested fixes:")
    if "install" in problems:
        print("    ./install.sh")
    if "retrigger" in problems:
        print("    sudo udevadm control --reload-rules && "
              "sudo udevadm trigger --subsystem-match=input --attr-match=idVendor=346e")

    if args.fix and "retrigger" in problems:
        print("\n  Applying udev reload + trigger (needs sudo)...")
        subprocess.run(["sudo", "udevadm", "control", "--reload-rules"])
        subprocess.run(["sudo", "udevadm", "trigger", "--subsystem-match=input",
                        "--attr-match=idVendor=346e"])
        time.sleep(1.0)
        real = real_evdev_path()
        if real and real_hidden(real):
            print("  " + _c("32", "Fixed:") + " real node now hidden.")
            return 0
        print("  " + _c("33", "Still visible — replug the base or reboot."))
    return 1


def _user_in_input() -> bool:
    try:
        return "input" in subprocess.run(["id", "-nG"], capture_output=True,
                                         text=True).stdout.split()
    except OSError:
        return False


def _canonical_mode(selector: str) -> str:
    """Canonical mode letter for the state file; plain `start` must never break
    on a missing/unhappy profiledb, so fall back to the raw selector uppercased."""
    try:
        from profiledb import ProfileError, canon_mode
        try:
            return canon_mode(selector)
        except ProfileError:
            return selector.upper()
    except ImportError:
        return selector.upper()


def cmd_start(args) -> int:
    if daemon_pids():
        print("Already running (pid %s)." % ", ".join(map(str, daemon_pids())))
        return 0
    # The canonical letter goes into argv so the state file compares equal to
    # what a profile would render — otherwise `run` restarts a matching daemon
    # just because `start --mode wheel` spelled the same mode differently.
    mode = _canonical_mode(args.mode)
    argv_tail = ["--mode", mode]
    if args.deadzone:
        argv_tail += ["--deadzone", str(args.deadzone)]
    argv_tail += args.daemon_args
    print(f"Starting mode {mode} ...")
    pid = _spawn_daemon(argv_tail)
    if pid is None:
        return 1
    _write_state(pid, mode, argv_tail, None)
    return 0


def cmd_modes(_args) -> int:
    from modes import list_modes
    print(_c("1", "presentation modes") + "  (mozactl start --mode <sel>)")
    for sel, desc in list_modes():
        print(f"  {_c('36', sel):>6}  {desc}")
    print("\n  Triage a broken game: try A, then C, then B.")
    return 0


def cmd_stop(_args) -> int:
    pids = daemon_pids()
    _clear_state()
    if not pids:
        print("Not running.")
        return 0
    _terminate_daemon()
    print(f"Stopped ({', '.join(map(str, pids))}). Wheel is now hidden from games.")
    return 0


def cmd_list(_args) -> int:
    try:
        import profiledb
    except ImportError as e:
        print(_c("31", f"profile support unavailable: {e}"))
        return 1
    profiles = profiledb.list_profiles()
    print(_c("1", "game profiles"))
    if not profiles:
        print("  (none found)")
    else:
        width = max(len(p.name) for p in profiles)
        for prof in profiles:
            src = "seed" if prof.path.startswith(profiledb.SEED_DIR + os.sep) else "user"
            note = prof.notes.splitlines()[0] if prof.notes else ""
            tail = f"  {_c('90', note)}" if note else ""
            print(f"  {_c('36', prof.name.ljust(width))}  {prof.mode}  [{src}]{tail}")
    print()
    print("  Steam launch options:  " + _c("1", "mozactl run NAME -- %command%"))
    print(f"  Your profiles (shadow seeds by name): {profiledb.USER_DIR}")
    return 0


def _exec_game(cmd: list[str], env: dict[str, str]) -> int:
    """Replace this process with the game so Steam keeps tracking the real pid.

    Only returns if exec itself fails.
    """
    # exec replaces the process image without flushing stdio; without this the
    # warnings we just printed are silently lost when stdout is a pipe (Steam).
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        os.execvpe(cmd[0], cmd, env)
    except OSError as e:
        print(_c("31", f"could not exec {cmd[0]!r}: {e}"))
        return 127


def cmd_run(args) -> int:
    game_cmd = list(args.game_cmd)
    # argparse's REMAINDER swallows our own flags when they follow PROFILE;
    # hoist them back out. Anything after the '--' separator is the game's.
    while game_cmd and game_cmd[0] in ("--stop-after", "--require-wheel"):
        setattr(args, game_cmd.pop(0).lstrip("-").replace("-", "_"), True)
    if game_cmd and game_cmd[0] == "--":
        del game_cmd[0]

    try:
        import profiledb
    except ImportError as e:
        print(_c("31", f"profile support unavailable: {e}"))
        if game_cmd:
            return _exec_game(game_cmd, dict(os.environ))
        return 2
    try:
        profile = profiledb.load_profile(args.profile)
    except profiledb.ProfileError as e:
        # A broken profile must never brick the game launch Steam asked for.
        print(_c("31", f"profile {args.profile!r}: {e}"))
        if game_cmd:
            print(_c("33", "Launching the game anyway, without mozaproxy."))
            return _exec_game(game_cmd, dict(os.environ))
        return 2

    env = profiledb.launch_env(profile)
    if profile.hook_pre:
        # The Boxflat/base-tuning hook point: runs before the daemon comes up
        # (Boxflat talks over the serial channel, independent of our grab).
        print(f"Running pre hook: {profile.hook_pre}")
        sys.stdout.flush()  # keep our line ahead of the hook's output in logs
        try:
            hrc = subprocess.call(profile.hook_pre, shell=True, env=env)
        except OSError as e:
            hrc = -1
            print(_c("33", f"WARNING: pre hook failed to start: {e}"))
        if hrc != 0:
            print(_c("33", f"WARNING: pre hook exited {hrc}; continuing."))

    if profile.mode == "D":
        if daemon_pids():
            cmd_stop(None)
        print(_c("33", "Mode D is passthrough: the udev rule still HIDES the real "
                       "wheel from games — this only helps if the hide rule was removed."))
    else:
        try:
            calib = profiledb.load_calibration()
        except profiledb.ProfileError as e:
            # A corrupt calibration overlay must not brick the launch either;
            # run uncalibrated (mode defaults) and tell the user.
            print(_c("33", f"WARNING: ignoring unreadable calibration: {e}"))
            print(_c("33", "Re-run 'mozactl calibrate' to rewrite it."))
            calib = {}
        desired = profiledb.daemon_args(profile, calib)
        if profiledb.needs_restart(_read_state(), desired, daemon_pids()):
            _terminate_daemon(wait=3.0)
            print(f"Starting mode {profile.mode} for profile '{profile.name}' ...")
            pid = _spawn_daemon(desired)
            if pid is not None:
                _write_state(pid, profile.mode, desired, profile.name)
            elif args.require_wheel:
                return 1
            else:
                print(_c("31", "WARNING: no wheel daemon — the game will see NO wheel. "
                               "Launching anyway (is the base powered on?)."))
        else:
            print(f"Daemon already in the right mode ({profile.mode}); leaving it running.")

    if profile.steam_input == "off":
        print("Reminder: disable Steam Input for this title "
              "(game Properties -> Controller) — it cannot be set from here.")

    if not game_cmd:
        print(_c("32", "Ready.") + f" Profile '{profile.name}' applied; no game command given.")
        return 0

    # A post hook needs someone alive after the game exits, so its presence
    # forces wait-mode (child process) instead of exec-replacement. Steam still
    # tracks the game fine as our child.
    if args.stop_after or profile.hook_post:
        sys.stdout.flush()
        try:
            rc = subprocess.call(game_cmd, env=env)
        except OSError as e:
            # A missing/unrunnable game binary must still stop the daemon.
            print(_c("31", f"could not run {game_cmd[0]!r}: {e}"))
            rc = 127
        if profile.hook_post:
            print(f"Running post hook: {profile.hook_post}")
            sys.stdout.flush()
            try:
                subprocess.call(profile.hook_post, shell=True, env=env)
            except OSError as e:
                print(_c("33", f"WARNING: post hook failed to start: {e}"))
        if args.stop_after:
            _terminate_daemon(wait=3.0)
            _clear_state()
        return rc
    return _exec_game(game_cmd, env)


def cmd_new(args) -> int:
    try:
        import profiledb
    except ImportError as e:
        print(_c("31", f"profile support unavailable: {e}"))
        return 1
    try:
        if args.copy_from:
            profile = profiledb.load_profile(args.copy_from)
            profile.name = args.name
            if args.mode is not None:
                profile.mode = profiledb.canon_mode(args.mode)
        else:
            profile = profiledb.Profile(
                name=args.name,
                mode=profiledb.canon_mode(args.mode or "A"),
                notes="created by mozactl new; triage a broken game: A, then C, then B",
            )
        path = profiledb.save_profile(profile, force=args.force)
    except profiledb.ProfileError as e:
        print(_c("31", str(e)))
        return 1
    print(_c("32", "Created: ") + path)
    print(f"Edit it, then use:  mozactl run {profile.name} -- %command%")
    return 0


def cmd_calibrate(_args) -> int:
    if daemon_pids():
        # The daemon's exclusive grab starves other readers; we would sample
        # nothing but silence.
        print(_c("31", "The daemon is running and holds an exclusive grab on the base."))
        print("Run " + _c("1", "mozactl stop") + " first, then retry.")
        return 1
    try:
        import calibration
        import profiledb
        from mozaproxy import find_real_device
    except ImportError as e:
        print(_c("31", f"calibration support unavailable: {e}"))
        return 1
    dev = find_real_device(MOZA_VENDOR, REAL_PRODUCT, "MOZA")
    if dev is None:
        print(_c("31", "Base not found — power the wheelbase on, then retry."))
        return 1
    try:
        mapping = calibration.interactive_calibrate(dev)
    finally:
        dev.close()
    if mapping is None:
        print("Calibration aborted; nothing saved.")
        return 1
    path = profiledb.save_calibration(mapping)
    print(_c("32", "Saved: ") + path)
    print("Gamepad/normalized profiles now pick these axes up automatically.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mozactl", description=__doc__.strip().splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show pipeline health").set_defaults(fn=cmd_status)
    d = sub.add_parser("doctor", help="diagnose + fix setup")
    d.add_argument("--fix", action="store_true", help="apply safe fixes (udev reload/trigger)")
    d.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("start", help="start the daemon in a chosen mode")
    s.add_argument("--mode", default="A",
                   help="A/wheel (default), C/normalized (binary-axis fix), "
                        "B/gamepad (XInput). See 'mozactl modes'.")
    s.add_argument("--deadzone", type=float, default=0.0,
                   help="steering deadzone 0..1 (mode C)")
    s.add_argument("daemon_args", nargs=argparse.REMAINDER,
                   help="extra args passed through to mozaproxy.py")
    s.set_defaults(fn=cmd_start)
    sub.add_parser("stop", help="stop the daemon").set_defaults(fn=cmd_stop)
    sub.add_parser("modes", help="list presentation modes").set_defaults(fn=cmd_modes)
    sub.add_parser("list", help="list game profiles").set_defaults(fn=cmd_list)
    r = sub.add_parser("run", help="apply a game profile, then exec the game "
                                   "(Steam launch option)")
    r.add_argument("profile", help="profile name from 'mozactl list' (or a .toml path)")
    r.add_argument("--stop-after", action="store_true",
                   help="wait for the game and stop the daemon when it exits "
                        "(default: exec the game so Steam tracks it)")
    r.add_argument("--require-wheel", action="store_true",
                   help="refuse to launch the game if the daemon cannot start")
    r.add_argument("game_cmd", nargs=argparse.REMAINDER, metavar="-- CMD",
                   help="game command to launch; in Steam: -- %%command%%")
    r.set_defaults(fn=cmd_run)
    n = sub.add_parser("new", help="create a user profile skeleton in "
                                   "~/.config/mozaproxy/profiles")
    n.add_argument("name", help="profile name (becomes <name>.toml)")
    n.add_argument("--mode", default=None,
                   help="mode for the new profile (default A, or --from's mode)")
    n.add_argument("--from", dest="copy_from", default=None, metavar="PROFILE",
                   help="copy settings from an existing profile")
    n.add_argument("--force", action="store_true",
                   help="overwrite an existing user profile of the same name")
    n.set_defaults(fn=cmd_new)
    sub.add_parser("calibrate",
                   help="interactively map wheel/pedal axes (writes calibration.toml)"
                   ).set_defaults(fn=cmd_calibrate)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
