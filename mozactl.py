#!/usr/bin/env python3
"""
mozactl - operate and diagnose the mozaproxy compatibility layer.

Phase 1 scope:
  mozactl status            one-glance health of the whole pipeline
  mozactl doctor [--fix]    deeper checks + suggested/automatic fixes
  mozactl start [args...]   start the mozaproxy daemon (Mode A) in the background
  mozactl stop              stop the daemon (wheel disappears from games)

The wheel is intentionally hidden from games at the udev layer, so it exists for
games ONLY while the daemon runs. `status` makes that state obvious; `start`
brings the clean virtual wheel up; `doctor` fixes the common setup gaps.
"""
from __future__ import annotations

import argparse
import glob
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
        line(OK, "Daemon running", f"pid {', '.join(map(str, pids))}")
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


def cmd_start(args) -> int:
    if daemon_pids():
        print("Already running (pid %s)." % ", ".join(map(str, daemon_pids())))
        return 0
    present, _, _ = usb_present()
    if not present:
        print(_c("31", "Base not on USB — power the wheelbase on first."))
        return 1
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    cmd = [py, DAEMON, "--mode", args.mode]
    if args.deadzone:
        cmd += ["--deadzone", str(args.deadzone)]
    cmd += args.daemon_args
    print(f"Starting mode {args.mode.upper()} ...")
    proc = subprocess.Popen(cmd, start_new_session=True)
    try:
        with open(PIDFILE, "w") as f:
            f.write(str(proc.pid))
    except OSError:
        pass
    time.sleep(1.5)
    if virtual_present():
        print(_c("32", "Started.") + f" Virtual wheel up (pid {proc.pid}).")
        return 0
    if proc.poll() is not None:
        print(_c("31", "Daemon exited immediately — run for logs: ")
              + f"{py} {DAEMON} -v")
        return 1
    print(f"Started (pid {proc.pid}); virtual node not seen yet — check: mozactl status")
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
    if not pids:
        print("Not running.")
        return 0
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError as e:
            print(f"Could not stop pid {pid}: {e}")
    print(f"Stopped ({', '.join(map(str, pids))}). Wheel is now hidden from games.")
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
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
