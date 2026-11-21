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
  mozactl watch                  live axis %-travel + button codes (get a signal)
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
import heapq
import json
import os
import shutil
import signal
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
LOGFILE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "mozaproxy.log"
)
WATCHLOG = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "mozaproxy-watch.log"
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
    """The real base's event node (has axes + force feedback).

    usb_backed keeps this from matching the virtual device when a profile
    clones the real identity (identity = "real"): same name/ids, but the
    virtual node's phys is uinput, not usb.
    """
    from evdev import ecodes
    from mozaproxy import usb_backed
    for d in _iter_evdev():
        c = d.capabilities()
        if (d.info.vendor == MOZA_VENDOR and d.info.product == REAL_PRODUCT
                and usb_backed(d.phys)
                and ecodes.EV_ABS in c and ecodes.EV_FF in c):
            return d.path
    return None


def virtual_present() -> str | None:
    """The mozaproxy virtual device name, if the daemon has created it."""
    from mozaproxy import usb_backed
    for d in _iter_evdev():
        if "mozaproxy" in d.name.lower():
            return d.name
        # An identity-cloned virtual wheel: MOZA ids on a non-USB (uinput) node.
        if d.info.vendor == MOZA_VENDOR and not usb_backed(d.phys):
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


# ---- live watch helpers (pure; see cmd_watch) ------------------------------
# `watch` reads a device node and shows axes as %-travel + buttons as they
# fire. Two jobs it settles WITHOUT a game: (1) prove our virtual output is
# smooth analog (so a binary-axis symptom is downstream in Proton/the game,
# not our rescale), and (2) reveal which real button code each paddle/clutch
# sends, so a profile can expose exactly those via button_codes.
def _axis_pct(value: int, lo: int, hi: int) -> float:
    """`value` as a 0..100 percentage of the [lo,hi] axis travel (clamped)."""
    if hi == lo:
        return 0.0
    t = (value - lo) / (hi - lo)
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return t * 100.0


def _bar(pct: float, width: int = 24) -> str:
    """A [####----] text meter for a 0..100 percentage."""
    filled = int(round(pct / 100.0 * width))
    filled = 0 if filled < 0 else width if filled > width else filled
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _code_name(table_name: str, code: int) -> str:
    """Human name for an evdev code via ecodes.<table>, else a bare hex code.

    ecodes maps a code to a str or, for aliased codes, a list of names; take
    the first. table_name is "ABS", "KEY" or "BTN".
    """
    from evdev import ecodes
    table = getattr(ecodes, table_name, {})
    name = table.get(code)
    if isinstance(name, (list, tuple)):
        name = name[0] if name else None
    return name or f"0x{code:x}"


def _axis_name(code: int) -> str:
    return _code_name("ABS", code)


def _key_name(code: int) -> str:
    """Button name preferring the BTN_* table, then KEY_*, then hex — with code."""
    from evdev import ecodes
    name = ecodes.BTN.get(code) or ecodes.KEY.get(code)
    if isinstance(name, (list, tuple)):
        name = name[0] if name else None
    return f"{name} 0x{code:x}" if name else f"0x{code:x}"


_SPARK_LEVELS = " ▁▂▃▄▅▆▇█"  # index 0 (empty bucket) .. 8 (fullest)


def _axis_bucket(value: int, lo: int, hi: int, nbuckets: int) -> int:
    """Which 0..nbuckets-1 histogram bucket `value` lands in over [lo,hi]."""
    if hi == lo or nbuckets <= 0:
        return 0
    t = (value - lo) / (hi - lo)
    idx = int(t * nbuckets)
    return 0 if idx < 0 else nbuckets - 1 if idx >= nbuckets else idx


def _spark(buckets: list[int]) -> str:
    """A unicode sparkline for bucket counts; ONLY empty buckets render as spaces.

    This is the analog-vs-binary tell at a glance: an analog sweep touches
    every bucket, so the bar has no gaps, while a binary/saturated axis piles
    all its mass on the two end buckets with spaces between.
    """
    peak = max(buckets) if buckets else 0
    if peak == 0:
        return " " * len(buckets)
    top = len(_SPARK_LEVELS) - 1
    out = []
    for c in buckets:
        # A populated bucket always gets a visible glyph. Scaling alone rounds
        # small counts to the blank level, and an analog axis that DWELLS (a
        # wheel held at centre, a pedal resting on its stop) then draws exactly
        # like a binary one: tall ends, blanks between.
        lvl = max(1, int(round(c / peak * top))) if c > 0 else 0
        out.append(_SPARK_LEVELS[lvl])
    return "".join(out)


def _new_axis_stats(nbuckets: int) -> dict:
    return {"n": 0, "min": None, "max": None, "distinct": set(),
            "buckets": [0] * nbuckets}


_DISTINCT_CAP = 20000  # bound memory; this many distinct values is plainly analog


def _record_axis(st: dict, value: int, lo: int, hi: int) -> None:
    """Fold one axis sample into its running stats (see _watch_summary)."""
    st["n"] += 1
    st["min"] = value if st["min"] is None else min(st["min"], value)
    st["max"] = value if st["max"] is None else max(st["max"], value)
    if len(st["distinct"]) < _DISTINCT_CAP:
        st["distinct"].add(value)
    st["buckets"][_axis_bucket(value, lo, hi, len(st["buckets"]))] += 1


def _watch_summary(axes: list[tuple[str, dict]], buttons_seen: list[str]) -> list[str]:
    """The end-of-run per-axis table: samples, distinct values, range, histogram.

    `distinct` is the analog-vs-binary verdict in one number: a swept analog
    axis shows hundreds or thousands of distinct values and a filled
    histogram, a binary one shows about two with all its mass at the ends.
    Written to the --log file and printed when the watch ends, so the verdict
    survives a pipe (off a TTY there are no live bars to look at).
    """
    # Column widths keep every row within 78 columns, so the table survives an
    # 80-column terminal without wrapping through the histogram.
    lines = ["SUMMARY — axis travel seen this session",
             f"{'axis':<12} {'samples':>8} {'distinct':>9}  "
             f"{'seen min..max':<16} histogram over range"]
    for name, st in axes:
        dcount = len(st["distinct"])
        dstr = f"{dcount}" + ("+" if dcount >= _DISTINCT_CAP else "")
        seen = f"{st['min']}..{st['max']}" if st["n"] else "(no motion)"
        lines.append(f"{name:<12} {st['n']:>8} {dstr:>9}  "
                     f"{seen:<16} [{_spark(st['buckets'])}]")
    lines.append("~2 distinct, mass only at the ends = BINARY; "
                 "many distinct, no gaps = analog")
    if buttons_seen:
        lines.append("buttons pressed: " + ", ".join(buttons_seen))
    return lines


def _is_moza_node(node: dict) -> bool:
    return node.get("vendor") == MOZA_VENDOR or "mozaproxy" in node.get("name", "").lower()


def _choose_watch_node(nodes: list[dict], want: str | None = None,
                       virtual_name: str | None = None) -> dict | None:
    """Pick which node `watch` should read.

    node dicts carry name/vendor/phys and optional has_abs/has_ff/product. A
    MOZA node is real if usb-backed, virtual otherwise (identity cloning makes
    name/ids identical, so transport is the only reliable discriminator — same
    rule as the daemon's usb_backed). Auto prefers the VIRTUAL node: while the
    daemon runs it holds an exclusive grab on the real node, so only the
    virtual node (what games actually see) still emits — and reading it
    confirms our output. With the daemon down, fall back to the real node (raw
    hardware, e.g. to discover paddle codes).

    `virtual_name` is the running daemon's explicit --name, if it has one: a
    profile's [identity] table can dress the virtual device as anything (an
    Xbox pad, another vendor's wheel), and then neither the MOZA vendor id nor
    "mozaproxy" in the name identifies it — only that recorded name does.
    """
    from mozaproxy import usb_backed

    def named_virtual(n: dict) -> bool:
        return (bool(virtual_name) and n.get("name") == virtual_name
                and not usb_backed(n.get("phys")))

    ours = [n for n in nodes
            if (_is_moza_node(n) or named_virtual(n)) and n.get("has_abs", True)]
    # The base is the node with force feedback and the base's product id; a
    # MOZA accessory on its own USB cable (pedals, shifter) also has axes and
    # must not be mistaken for it.
    real = sorted((n for n in ours if usb_backed(n.get("phys"))),
                  key=lambda n: (not n.get("has_ff", False),
                                 n.get("product", REAL_PRODUCT) != REAL_PRODUCT))
    virt = sorted((n for n in ours if not usb_backed(n.get("phys"))),
                  key=lambda n: not named_virtual(n))
    if want == "real":
        return real[0] if real else None
    if want == "virtual":
        return virt[0] if virt else None
    return (virt or real or [None])[0]


def _fit(text: str, width: int) -> str:
    """Clip plain text to `width` columns, marking a cut with an ellipsis."""
    if width <= 0:
        return ""
    return text if len(text) <= width else text[:width - 1] + "…"


def _watch_frame(axes: list[tuple[str, int, int, int]], pressed: list[str],
                 recent: list[tuple[str, str]], cols: int, rows: int,
                 ) -> list[tuple[str, str]]:
    """The live frame as (SGR colour code or "", plain text) lines.

    Pure so the layout rules are testable: every line is clipped to `cols`,
    and the frame is never taller than `rows - 1` — it is redrawn in place by
    moving the cursor back up over it, which only works while the whole frame
    fits on screen. The recent-events list gives way first; if the axes alone
    do not fit, the tail of the axis list is folded into a one-line note and
    the buttons line is kept (finding which code a paddle sends is half of
    what `watch` is for).

    axes: (name, value, min, max); recent: (colour code, text), newest first.
    """
    budget = max(3, rows - 1)
    barw = max(6, min(24, cols - 54))
    rows_ax = [f"  {name:<14} {val:>7}  {_bar(_axis_pct(val, lo, hi), barw)} "
               f"{_axis_pct(val, lo, hi):5.1f}%   ({lo}..{hi})"
               for name, val, lo, hi in axes]
    room = budget - 2  # the blank line and the buttons line always show
    if len(rows_ax) > room:
        hidden = len(rows_ax) - (room - 1)
        rows_ax = rows_ax[:max(0, room - 1)] + [
            f"  … {hidden} more axes (terminal too short to show them)"]
    lines: list[tuple[str, str]] = [("", ln) for ln in rows_ax]
    lines.append(("", ""))
    if pressed:
        lines.append(("", "  buttons down: " + "  ".join(pressed)))
    else:
        lines.append(("90", "  buttons down: (none)"))
    keep = min(len(recent), 8, budget - len(lines) - 1)
    if keep > 0:
        lines.append(("90", "  recent:"))
        lines += [(code, "    " + text) for code, text in recent[:keep]]
    return [(code, _fit(text, cols)) for code, text in lines]


def _text_rows(lines: list[str], cols: int) -> int:
    """Screen rows `lines` occupy once a `cols`-wide terminal wraps them."""
    cols = max(1, cols)
    return sum(max(1, -(-len(ln) // cols)) for ln in lines)


class _NoEcho:
    """Stop the terminal on `fd` echoing keystrokes, until close().

    watch redraws in place by moving the cursor back up over its last frame.
    An echoed Enter moves the cursor down a row, so every later frame lands
    one row lower and leaves a stale line behind. Keys typed meanwhile are
    discarded on close (TCSAFLUSH) instead of reaching the shell afterwards.
    Ctrl-C still works (ISIG is untouched). A no-op when `fd` is no terminal.
    """

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.saved = None
        try:
            import termios
            if os.isatty(fd):
                self.saved = termios.tcgetattr(fd)
                quiet = termios.tcgetattr(fd)
                quiet[3] &= ~termios.ECHO
                termios.tcsetattr(fd, termios.TCSANOW, quiet)
        except Exception:  # termios.error is not an OSError
            self.saved = None

    def close(self) -> None:
        saved, self.saved = self.saved, None
        if saved is not None:
            try:
                import termios
                termios.tcsetattr(self.fd, termios.TCSAFLUSH, saved)
            except Exception:
                pass


class _WatchLog:
    """The --log file. A failed write (disk full, file-size limit) stops the
    logging and is reported once at the end; it never ends the watch."""

    def __init__(self, f=None) -> None:
        self.f = f
        self.error: str | None = None

    def write(self, text: str) -> None:
        if self.f is None:
            return
        try:
            self.f.write(text)
        except OSError as e:
            self.error = str(e)
            self.close()

    def close(self) -> None:
        f, self.f = self.f, None
        if f is not None:
            try:
                f.close()
            except OSError as e:
                self.error = self.error or str(e)


def _is_daemon_cmdline(parts: list[bytes]) -> bool:
    """True if a /proc cmdline is the daemon: `<python> [opts] .../mozaproxy.py ...`.

    Every launcher runs it that way (_spawn_daemon, run.sh, the systemd unit,
    and a direct ./mozaproxy.py via its env shebang). Matching the script's
    exact name, rather than "mozaproxy.py" anywhere in the command line, keeps
    `stop`/`run` from signalling unrelated processes: an editor on the file, or
    another tool whose script merely ends in it (open-mozaproxy.py).

    The interpreter's options are skipped the way CPython parses them, so the
    script slot is found even when an option takes a value (-X dev, -W error,
    attached as in -Xdev, or inside a cluster as in -uX dev). -c and -m run a
    command or module rather than a script, so they never count.
    """
    if not parts or b"python" not in os.path.basename(parts[0]):
        return False
    args = iter(parts[1:])
    for arg in args:
        if arg == b"--":                        # end of interpreter options
            arg = next(args, b"")
        elif arg.startswith(b"--"):             # long option; just this one takes a value
            if arg == b"--check-hash-based-pycs":
                next(args, None)
            continue
        elif arg.startswith(b"-") and arg != b"-":
            opts = arg[1:]
            for i in range(len(opts)):
                opt = opts[i:i + 1]
                if opt in (b"c", b"m"):
                    return False
                if opt in (b"W", b"X"):         # the rest, or else the next entry, is the value
                    if i + 1 == len(opts):
                        next(args, None)
                    break
            continue
        return os.path.basename(arg) == b"mozaproxy.py"
    return False


def daemon_pids(proc: str = "/proc") -> list[int]:
    pids = []
    for c in glob.glob(os.path.join(proc, "[0-9]*", "cmdline")):
        try:
            with open(c, "rb") as f:
                parts = f.read().split(b"\0")
        except OSError:
            continue
        if parts[-1] == b"":   # each entry ends in NUL; keep empty ones ("-W ''")
            del parts[-1]
        if _is_daemon_cmdline(parts):
            try:
                pids.append(int(os.path.basename(os.path.dirname(c))))
            except ValueError:
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


def _state_virtual_name(pids: list[int]) -> str | None:
    """The explicit --name of the live, state-tracked daemon's virtual device.

    None when no such daemon is running or it uses a mode's default name
    (those contain "mozaproxy", or wear the MOZA vendor id, and are found
    without help). The recorded argv is read with the daemon's own parser, so
    every spelling it accepts (--name X, --name=X) is understood.
    """
    state = _read_state()
    if not state or state.get("pid") not in pids:
        return None
    argv = state.get("argv")
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return None
    try:
        import contextlib
        import io
        from mozaproxy import parse_args
        with contextlib.redirect_stderr(io.StringIO()):
            return parse_args(argv).name or None
    except (SystemExit, Exception):  # argparse exits on argv it rejects
        name = None
        for i, arg in enumerate(argv):
            if arg == "--name" and i + 1 < len(argv):
                name = argv[i + 1]
            elif arg.startswith("--name="):
                name = arg.split("=", 1)[1]
        return name or None


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
    """Start mozaproxy.py with argv_tail; return its pid, or None on failure.

    The daemon's output goes to LOGFILE, not our stdout: inheriting a pipe
    (Steam's launch-option capture, a shell pipeline) would tie the daemon's
    lifetime to it and lose the logs; `mozactl logs` reads the file instead.
    """
    present, _, _ = usb_present()
    if not present:
        print(_c("31", "Base not on USB — power the wheelbase on first."))
        return None
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    try:
        logf = open(LOGFILE, "w")
    except OSError:
        logf = subprocess.DEVNULL
    proc = subprocess.Popen([py, DAEMON] + list(argv_tail), start_new_session=True,
                            stdout=logf, stderr=subprocess.STDOUT)
    if logf is not subprocess.DEVNULL:
        logf.close()  # the child holds its own copy of the fd
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
    # argparse.REMAINDER keeps the "--" that introduces the daemon's own flags.
    # Forwarded as-is it tells the daemon's parser "positionals only from
    # here", which rejects every flag after it — so drop it (as `run` does for
    # the game command).
    extra = list(args.daemon_args)
    if extra[:1] == ["--"]:
        del extra[0]
    argv_tail += extra
    # A --mode among them wins (the daemon takes the last one), so record and
    # report the mode the daemon will really run.
    try:
        import contextlib
        import io
        from mozaproxy import parse_args
        with contextlib.redirect_stderr(io.StringIO()):
            mode = _canonical_mode(parse_args(argv_tail).mode)
    except (SystemExit, Exception):  # rejected argv: the spawn reports it
        pass
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
    while game_cmd and game_cmd[0] in ("--stop-after", "--require-wheel", "--debug"):
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
        if args.debug:
            # Part of the argv on purpose: toggling debug on/off changes the
            # desired argv, so the daemon restarts into/out of FFB tracing.
            desired = desired + ["-v"]
        if profiledb.needs_restart(_read_state(), desired, daemon_pids()):
            _terminate_daemon(wait=3.0)
            print(f"Starting mode {profile.mode} for profile '{profile.name}' ...")
            pid = _spawn_daemon(desired)
            if pid is not None:
                _write_state(pid, profile.mode, desired, profile.name)
                if args.debug:
                    print(f"FFB tracing on — read it with: mozactl logs  ({LOGFILE})")
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


def cmd_logs(args) -> int:
    try:
        with open(LOGFILE) as f:
            lines = f.readlines()
    except OSError:
        print(f"No daemon log at {LOGFILE} — the daemon has not been started "
              "by mozactl since boot.")
        return 1
    for ln in lines[-args.lines:]:
        print(ln, end="")
    return 0


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


def _seconds(s: str) -> float:
    """argparse converter: a finite, non-negative number of seconds."""
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} is not a number of seconds")
    if not 0.0 <= v < float("inf"):  # also rejects nan
        raise argparse.ArgumentTypeError(
            f"seconds must be a finite number >= 0, got {s!r}")
    return v


def cmd_watch(args) -> int:
    """Live-watch a node's axes (%-travel) and buttons (as they fire)."""
    try:
        rc = _watch(args)
        # A reader that left early (`watch | head`) surfaces on this flush;
        # caught here it is a quiet stop, not an "Exception ignored" at exit.
        sys.stdout.flush()
        return rc
    except BrokenPipeError:
        # The reader left. That is a normal way to stop, not an error. _watch
        # has already cleaned up (and finished the log); point stdout at
        # /dev/null so the interpreter's exit-time flush does not raise again.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        return 0


def _watch(args) -> int:
    import collections
    import selectors

    import evdev
    from evdev import ecodes
    from mozaproxy import usb_backed

    want = "real" if args.real else "virtual" if args.virtual else None
    nodes = []
    for d in _iter_evdev():
        try:
            caps = d.capabilities()
            nodes.append({"path": d.path, "name": d.name,
                          "vendor": d.info.vendor, "product": d.info.product,
                          "phys": d.phys or "",
                          "has_abs": ecodes.EV_ABS in caps,
                          "has_ff": ecodes.EV_FF in caps})
        except OSError:
            continue  # unplugged between listing and querying; not ours anyway
        finally:
            d.close()

    pids = daemon_pids()
    node = _choose_watch_node(nodes, want, _state_virtual_name(pids))
    if node is None:
        if want == "virtual" and pids:
            print(_c("31", "The daemon is running but its virtual device was not "
                           "found — check: mozactl status / mozactl logs"))
        elif want == "virtual":
            print(_c("31", "No virtual wheel found — the daemon is not running "
                           "(mozactl start / run)."))
        elif want == "real":
            print(_c("31", "No real MOZA base found — power the wheelbase on."))
        else:
            print(_c("31", "No MOZA (real or virtual) node found — power the "
                           "base on and/or start the daemon."))
        return 1

    is_real = usb_backed(node["phys"])
    if is_real and pids:
        # A grabbed real node delivers events ONLY to the grabber, so we'd read
        # silence. Say so instead of showing a frozen display.
        print(_c("33", "The daemon is running and holds an exclusive grab on the "
                       "real node — it will read as SILENT."))
        print("Watch what games see instead: " + _c("1", "mozactl watch --virtual")
              + "   (or " + _c("1", "mozactl stop") + " to read raw hardware).")
        return 1

    try:
        dev = evdev.InputDevice(node["path"])
    except OSError as e:
        print(_c("31", f"could not open {node['path']}: {e}"))
        return 1

    caps = dev.capabilities(absinfo=True)
    absinfo = {code: info for code, info in caps.get(ecodes.EV_ABS, [])}
    axis_val = {code: info.value for code, info in absinfo.items()}
    pressed: set[int] = set()
    recent: collections.deque = collections.deque(maxlen=8)
    stats: dict = {code: _new_axis_stats(24) for code in absinfo}
    buttons_seen: list[str] = []
    kind = "REAL hardware" if is_real else "VIRTUAL (what games see)"

    # Optional shareable plaintext log: a downsampled event stream plus the
    # end-of-run per-axis summary (see _watch_summary).
    log = _WatchLog()
    if args.log:
        try:
            # Line-buffered: a killed watch still leaves every line it logged.
            log = _WatchLog(open(args.log, "w", buffering=1))
        except OSError as e:
            dev.close()
            print(_c("31", f"could not open log {args.log!r}: {e}"))
            return 1
        log.write(
            f"# mozaproxy watch log\n"
            f"# node: {kind} '{node['name']}' {node['path']} "
            f"vendor=0x{node['vendor']:04x}\n"
            f"# axes: " + ", ".join(f"{_axis_name(c)}[{absinfo[c].min}..{absinfo[c].max}]"
                                    for c in sorted(absinfo)) + "\n"
            f"# columns: +seconds  KIND  name  value  pct\n")

    # The header, as (plain text, rendered) pairs: plain text measures how
    # many rows it wraps to, so the frame below it can be sized to fit.
    head = [
        ("mozaproxy watch  " + kind, _c("1", "mozaproxy watch") + "  " + _c("36", kind)),
        (f"  '{node['name']}'  {node['path']}", f"  '{node['name']}'  {node['path']}"),
        ("  Move each axis / press each button.  Ctrl-C to stop.",
         "  Move each axis / press each button.  Ctrl-C to stop."),
    ]
    note = ("  This is the raw base: note the code each paddle/button sends."
            if is_real else
            "  Analog here = our output is clean; binary in game is downstream.")
    head.append((note, note))
    if args.log:
        head.append((f"  Logging to {args.log} — share this file.",
                     "  Logging to " + _c("1", args.log) + " — share this file."))
    head.append(("", ""))

    # The frame is redrawn IN PLACE below the header: after a draw the cursor
    # sits on the line under the frame, so the next draw first moves back up
    # over it. The frame is sized so header + frame fit the terminal, which
    # keeps the header (which node this is, how to stop) on screen.
    drawn = 0
    size = None  # terminal size at the last draw

    def draw() -> None:
        nonlocal drawn, size
        cols, rows = shutil.get_terminal_size((80, 24))
        out = []
        if size is not None and (cols, rows) != size:
            # Resized: terminals reflow the old lines, so the frame's top is no
            # longer `drawn` rows up. Start over on a clean screen rather than
            # leave fragments of the old frame behind.
            out.append("\033[H\033[2J")
            out += [rendered + "\n" for _, rendered in head]
            drawn = 0
        size = (cols, rows)
        frame = _watch_frame(
            [(_axis_name(c), axis_val.get(c, absinfo[c].value),
              absinfo[c].min, absinfo[c].max) for c in sorted(absinfo)],
            [_key_name(c) for c in sorted(pressed)], list(recent), cols,
            rows - _text_rows([plain for plain, _ in head], cols))
        out.append(f"\033[{drawn}A\r" if drawn else "\r")
        out += [(_c(code, text) if code else text) + "\033[K\n"
                for code, text in frame]
        out.append("\033[J")  # drop leftovers if the frame just got shorter
        sys.stdout.write("".join(out))
        sys.stdout.flush()
        drawn = len(frame)

    # Log stream. Axis lines are thinned to one per axis per 20 ms, and the
    # newest value a thinning skipped is written once that axis's 20 ms is up
    # (or when idle, or at exit), so every axis ends on where it came to rest.
    # Every line carries the time it was READ; held lines pass through a small
    # reorder buffer that releases them in time order once they are 25 ms old
    # (more than the 20 ms window), so the file stays chronological.
    t0 = time.monotonic()  # monotonic: a clock step must not end or extend a run
    last_logged: dict[int, float] = {}       # axis -> read time of its last line
    pending: dict[int, tuple[int, float]] = {}  # axis -> (value, read time) held back
    held: list[tuple[float, int, str]] = []  # (read time, seq, line) awaiting release
    seq = 0

    def emit(when: float, text: str) -> None:
        nonlocal seq
        if log.f is not None:
            seq += 1
            heapq.heappush(held, (when, seq, text))

    def log_axis(code: int, value: int, when: float) -> None:
        info = absinfo[code]
        emit(when, f"+{when - t0:8.3f}  ABS  {_axis_name(code):<12} "
                   f"{value:>7} {_axis_pct(value, info.min, info.max):5.1f}%\n")
        last_logged[code] = when
        pending.pop(code, None)

    def settle_log(now: float, force: bool = False) -> None:
        for code, (value, when) in sorted(pending.items(), key=lambda kv: kv[1][1]):
            if force or now - last_logged.get(code, -1.0) >= 0.02:
                log_axis(code, value, when)
        while held and (force or held[0][0] <= now - 0.025):
            log.write(heapq.heappop(held)[2])

    def on_term(_signum, _frame):
        raise KeyboardInterrupt  # SIGTERM (timeout(1), systemd) ends like Ctrl-C

    try:
        stdin_fd = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):
        stdin_fd = -1
    sel = selectors.DefaultSelector()
    sel.register(dev.fileno(), selectors.EVENT_READ)
    deadline = t0 + args.duration if args.duration else None
    last_draw = 0.0
    dirty = False     # the screen is behind the state
    error = None      # reported AFTER the final frame, so it is not drawn over
    old_term = None
    noecho = None
    rc = 0
    try:
        try:
            old_term = signal.signal(signal.SIGTERM, on_term)
        except ValueError:
            pass  # not the main thread: leave signal handling to the embedder
        if _TTY:
            noecho = _NoEcho(stdin_fd)
        for _, rendered in head:
            print(rendered)
        if _TTY:
            draw()
        else:
            sys.stdout.flush()  # piped: show the header now, not at exit
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break
            timeout = 0.2
            if deadline is not None:
                timeout = max(0.0, min(timeout, deadline - now))
            if not sel.select(timeout=timeout):
                # Quiet: bring the log and the screen up to the final values.
                settle_log(time.monotonic(), force=True)
                if _TTY and dirty:
                    draw()
                    dirty = False
                continue
            try:
                events = list(dev.read())
            except BlockingIOError:
                continue
            except OSError as e:
                error = f"device read error: {e}"
                rc = 1
                break
            now = time.monotonic()
            for ev in events:
                if ev.type == ecodes.EV_ABS and ev.code in absinfo:
                    v = ev.value
                    axis_val[ev.code] = v
                    info = absinfo[ev.code]
                    _record_axis(stats[ev.code], v, info.min, info.max)
                    # The stats above are exact; only the log stream is thinned.
                    if now - last_logged.get(ev.code, -1.0) >= 0.02:
                        log_axis(ev.code, v, now)
                    else:
                        pending[ev.code] = (v, now)
                elif ev.type == ecodes.EV_KEY:
                    name = _key_name(ev.code)
                    if ev.value:
                        pressed.add(ev.code)
                        recent.appendleft(("32", f"press   {name}"))
                        if name not in buttons_seen:
                            buttons_seen.append(name)
                    else:
                        pressed.discard(ev.code)
                        recent.appendleft(("90", f"release {name}"))
                    emit(now, f"+{now - t0:8.3f}  KEY  "
                              f"{'press  ' if ev.value else 'release'} {name}\n")
                    if not _TTY:
                        # No cursor control off a TTY: stream button
                        # transitions, flushed so a pipe sees each one live.
                        print(f"{'press' if ev.value else 'release'} {name}",
                              flush=True)
            settle_log(now)
            if _TTY:
                dirty = True
                if now - last_draw >= 0.03:  # ~30fps cap to avoid flicker
                    draw()
                    last_draw = now
                    dirty = False
    except KeyboardInterrupt:
        pass
    finally:
        # Runs on every way out, including a vanished stdout (BrokenPipeError
        # passes through to cmd_watch): nothing in here may print.
        if noecho is not None:
            noecho.close()
        if old_term is not None:
            signal.signal(signal.SIGTERM, old_term)
        summary = _watch_summary(
            [(_axis_name(code), stats[code]) for code in sorted(absinfo)],
            buttons_seen)
        try:
            settle_log(time.monotonic(), force=True)
            log.write("#\n" + "".join(f"# {ln}\n" for ln in summary))
        finally:
            log.close()
            sel.close()
            dev.close()

    if _TTY:
        draw()
    if error:
        print(_c("31", error))
    # The verdict, on stdout too: off a TTY there were no live bars, and on one
    # the distinct-value count is still the number to read.
    print()
    for ln in summary:
        print("  " + ln)
    if args.log:
        if log.error:
            print("\n" + _c("33", f"Log {args.log} is incomplete — writing it "
                                  f"failed: {log.error}"))
        else:
            print("\nWrote " + _c("1", args.log) + "  — share this file.")
    return rc


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
    s.add_argument("daemon_args", nargs=argparse.REMAINDER, metavar="-- DAEMON_ARGS",
                   help="extra args for mozaproxy.py, after a '--' "
                        "(e.g. -- --button-codes 0x120,0x2c0)")
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
    r.add_argument("--debug", action="store_true",
                   help="run the daemon with -v (traces every FFB upload/play "
                        "to the log; read with 'mozactl logs')")
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
    lg = sub.add_parser("logs", help="show the daemon's log (FFB traces with --debug)")
    lg.add_argument("-n", "--lines", type=int, default=50,
                    help="how many trailing lines to show (default 50)")
    lg.set_defaults(fn=cmd_logs)
    w = sub.add_parser("watch", help="live-watch axes (%%-travel) and button codes")
    wg = w.add_mutually_exclusive_group()
    wg.add_argument("--virtual", action="store_true",
                    help="read the virtual node (what games see; default when "
                         "the daemon is running)")
    wg.add_argument("--real", action="store_true",
                    help="read the raw base node (needs the daemon stopped; "
                         "use it to discover which code each paddle/button sends)")
    w.add_argument("--duration", type=_seconds, default=0.0, metavar="SECONDS",
                   help="stop after this many seconds (default 0: run until "
                        "Ctrl-C)")
    w.add_argument("--log", nargs="?", const=WATCHLOG, default=None, metavar="FILE",
                   # argparse %-formats help text, and WATCHLOG comes from
                   # $XDG_RUNTIME_DIR: escape it or a "%" in that path breaks
                   # every mozactl invocation (see the smoke tests).
                   help="also write a clean, shareable plaintext log (bare --log "
                        f"defaults to {WATCHLOG.replace('%', '%%')}) with an "
                        "end-of-run per-axis analog-vs-binary summary")
    w.set_defaults(fn=cmd_watch)
    sub.add_parser("calibrate",
                   help="interactively map wheel/pedal axes (writes calibration.toml)"
                   ).set_defaults(fn=cmd_calibrate)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
