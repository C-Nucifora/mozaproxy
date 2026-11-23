"""Tests for the pure helpers behind `mozactl watch`.

All hardware-free: they exercise the axis/percent/label maths and the
node-selection logic with synthetic node dicts, so nothing is opened.
"""
from __future__ import annotations

import pytest
from evdev import ecodes

import mozactl


# ---------------------------------------------------------------------------
# Axis percentage + bar rendering
# ---------------------------------------------------------------------------
class TestAxisPct:
    def test_endpoints_and_midpoint(self):
        assert mozactl._axis_pct(0, 0, 65535) == 0.0
        assert mozactl._axis_pct(65535, 0, 65535) == 100.0
        assert mozactl._axis_pct(32768, 0, 65535) == pytest.approx(50.0, abs=0.01)

    def test_signed_axis(self):
        assert mozactl._axis_pct(-32768, -32768, 32767) == 0.0
        assert mozactl._axis_pct(32767, -32768, 32767) == 100.0

    def test_clamped_out_of_range(self):
        assert mozactl._axis_pct(-100, 0, 100) == 0.0
        assert mozactl._axis_pct(999, 0, 100) == 100.0

    def test_degenerate_range_is_zero(self):
        assert mozactl._axis_pct(5, 7, 7) == 0.0


class TestBar:
    def test_empty_full_half(self):
        assert mozactl._bar(0, 10) == "[----------]"
        assert mozactl._bar(100, 10) == "[##########]"
        assert mozactl._bar(50, 10) == "[#####-----]"

    def test_clamps_beyond_bounds(self):
        assert mozactl._bar(-20, 4) == "[----]"
        assert mozactl._bar(150, 4) == "[####]"


class TestHistogram:
    def test_bucket_endpoints_and_mid(self):
        assert mozactl._axis_bucket(0, 0, 65535, 24) == 0
        assert mozactl._axis_bucket(65535, 0, 65535, 24) == 23
        assert mozactl._axis_bucket(32768, 0, 65535, 24) == 12

    def test_bucket_clamps_and_degenerate(self):
        assert mozactl._axis_bucket(-5, 0, 100, 24) == 0
        assert mozactl._axis_bucket(999, 0, 100, 24) == 23
        assert mozactl._axis_bucket(5, 7, 7, 24) == 0

    def test_spark_empty_is_spaces(self):
        assert mozactl._spark([0, 0, 0]) == "   "

    def test_spark_binary_vs_analog_shape(self):
        # Binary: mass only at the two ends, spaces between -> the tell.
        binary = mozactl._spark([50, 0, 0, 0, 0, 50])
        assert binary[0] == "█" and binary[-1] == "█"
        assert binary[1:-1] == "    "
        # Analog: every bucket populated -> no interior gaps.
        analog = mozactl._spark([10, 12, 11, 9, 10, 13])
        assert " " not in analog

    def test_spark_scales_to_peak(self):
        assert mozactl._spark([0, 8]) == " █"

    def test_spark_never_blanks_a_populated_bucket(self):
        # An analog pedal dwells on its stops, so its end buckets dwarf the
        # ones the sweep passes through. Rounding those to "empty" drew an
        # analog axis exactly like a binary one — the opposite of the tell.
        dwelling = mozactl._spark([4500] + [30] * 22 + [4500])
        binary = mozactl._spark([100] + [0] * 22 + [100])
        assert " " not in dwelling
        assert binary[1:-1].strip() == ""
        assert dwelling != binary
        assert mozactl._spark([1, 10**9]) == "▁█"


# ---------------------------------------------------------------------------
# Code -> name labelling
# ---------------------------------------------------------------------------
class TestNames:
    def test_axis_name_known(self):
        assert mozactl._axis_name(ecodes.ABS_X) == "ABS_X"

    def test_key_name_known_includes_hex(self):
        label = mozactl._key_name(0x120)
        assert "0x120" in label and "BTN" in label

    def test_key_name_upper_block_uses_key_table(self):
        # The base's 0x270+ "buttons" are actually KEY_* codes; name them.
        assert mozactl._key_name(0x271) == "KEY_STOP_RECORD 0x271"

    def test_unknown_code_falls_back_to_hex(self):
        assert mozactl._key_name(0x10A) == "0x10a"
        assert mozactl._axis_name(0xABC) == "0xabc"


# ---------------------------------------------------------------------------
# Node selection
# ---------------------------------------------------------------------------
def _node(name, vendor, phys, has_abs=True):
    return {"path": f"/dev/input/{name}", "name": name, "vendor": vendor,
            "phys": phys, "has_abs": has_abs}


REAL = _node("Gudsen MOZA R25 Ultra Base", 0x346E, "usb-0000:00:14.0-5/input0")
VIRT = _node("MOZA R25 (mozaproxy)", 0x346E, "py-evdev-uinput")
# An identity-cloned virtual node: real ids, but a uinput transport.
VIRT_CLONE = _node("Gudsen MOZA R25 Ultra Base", 0x346E, "py-evdev-uinput")
OTHER = _node("Some Keyboard", 0x1234, "usb-0000:00:1d.0-1/input0")


class TestChooseWatchNode:
    def test_auto_prefers_virtual(self):
        assert mozactl._choose_watch_node([REAL, VIRT]) is VIRT

    def test_auto_falls_back_to_real(self):
        assert mozactl._choose_watch_node([REAL, OTHER]) is REAL

    def test_want_real(self):
        assert mozactl._choose_watch_node([REAL, VIRT], "real") is REAL

    def test_want_virtual(self):
        assert mozactl._choose_watch_node([REAL, VIRT], "virtual") is VIRT

    def test_want_real_absent_returns_none(self):
        assert mozactl._choose_watch_node([VIRT], "real") is None

    def test_want_virtual_absent_returns_none(self):
        assert mozactl._choose_watch_node([REAL], "virtual") is None

    def test_identity_cloned_virtual_classified_by_transport(self):
        # Same name/ids as the real base; only the uinput phys tells them apart.
        assert mozactl._choose_watch_node([REAL, VIRT_CLONE], "virtual") is VIRT_CLONE
        assert mozactl._choose_watch_node([REAL, VIRT_CLONE], "real") is REAL

    def test_non_moza_ignored(self):
        assert mozactl._choose_watch_node([OTHER]) is None

    def test_prefers_axis_bearing_node(self):
        # A MOZA HID accessory node with no axes must not be chosen over the
        # real axis-bearing base.
        accessory = _node("MOZA HID", 0x346E, "usb-0000:00:14.0-5/input1",
                          has_abs=False)
        assert mozactl._choose_watch_node([accessory, REAL], "real") is REAL
        assert mozactl._choose_watch_node([accessory], "real") is None

    def test_empty_list(self):
        assert mozactl._choose_watch_node([]) is None

    def test_real_prefers_the_base_over_a_usb_accessory(self):
        # Standalone MOZA pedals on their own cable: MOZA vendor, axes, usb —
        # but no force feedback and a different product id. Enumeration order
        # must not let them pass for the base.
        pedals = dict(_node("Gudsen MOZA SR-P Pedals", 0x346E,
                            "usb-0000:00:14.0-3/input0"),
                      has_ff=False, product=0x0003)
        base = dict(REAL, has_ff=True, product=0x0000)
        assert mozactl._choose_watch_node([pedals, base], "real") is base
        assert mozactl._choose_watch_node([pedals, base]) is base
        assert mozactl._choose_watch_node([pedals], "real") is pedals  # all there is
        # Each signal counts on its own: an accessory sharing the base's
        # product id still lacks force feedback, and vice versa.
        same_id = dict(pedals, product=0x0000)
        assert mozactl._choose_watch_node([same_id, base], "real") is base
        ff_other = dict(pedals, has_ff=True)
        assert mozactl._choose_watch_node([ff_other, base], "real") is base

    def test_named_virtual_needs_the_daemons_recorded_name(self):
        pad = _node("Microsoft X-Box 360 pad", 0x045E, "py-evdev-uinput")
        assert mozactl._choose_watch_node([REAL, pad], "virtual") is None
        assert mozactl._choose_watch_node(
            [REAL, pad], "virtual", "Microsoft X-Box 360 pad") is pad
        assert mozactl._choose_watch_node(
            [REAL, pad], None, "Microsoft X-Box 360 pad") is pad

    def test_recorded_name_never_claims_a_usb_device(self):
        # A real pad that happens to share the name is not our virtual device.
        real_pad = _node("Microsoft X-Box 360 pad", 0x045E,
                         "usb-0000:00:14.0-2/input0")
        assert mozactl._choose_watch_node(
            [real_pad], "virtual", "Microsoft X-Box 360 pad") is None

    def test_recorded_name_wins_among_several_virtual_nodes(self):
        other = _node("someone else (mozaproxy)", 0x1209, "py-evdev-uinput")
        mine = _node("MOZA R9 Base", 0x346E, "py-evdev-uinput")
        assert mozactl._choose_watch_node([other, mine], "virtual",
                                          "MOZA R9 Base") is mine


class TestStateVirtualName:
    def _state(self, monkeypatch, state):
        monkeypatch.setattr(mozactl, "_read_state", lambda: state)

    def test_explicit_name_of_the_live_daemon(self, monkeypatch):
        self._state(monkeypatch, {"pid": 7, "argv": ["--mode", "A", "--name", "X Y",
                                                     "--vendor", "0x046d"]})
        assert mozactl._state_virtual_name([7]) == "X Y"

    @pytest.mark.parametrize("argv", [
        ["--mode", "A", "--name=X Y", "--vendor", "0x046d"],
        ["--mode", "A", "--name", "X Y"],
        ["--name", "X Y", "--mode", "C", "--axis-range", "0:32767"],
    ])
    def test_every_spelling_the_daemon_accepts(self, monkeypatch, argv):
        # `mozactl start -- --name=...` records the flags verbatim.
        self._state(monkeypatch, {"pid": 7, "argv": argv})
        assert mozactl._state_virtual_name([7]) == "X Y"

    def test_unparseable_argv_falls_back_to_a_plain_scan(self, monkeypatch):
        self._state(monkeypatch, {"pid": 7, "argv": ["--from-a-newer-daemon",
                                                     "--name=X Y"]})
        assert mozactl._state_virtual_name([7]) == "X Y"

    def test_none_without_an_explicit_name(self, monkeypatch):
        self._state(monkeypatch, {"pid": 7, "argv": ["--mode", "A"]})
        assert mozactl._state_virtual_name([7]) is None

    @pytest.mark.parametrize("state", [None, {}, {"pid": 7}, {"pid": 7, "argv": "x"},
                                       {"pid": 7, "argv": ["--name"]}])
    def test_none_for_missing_or_odd_state(self, monkeypatch, state):
        self._state(monkeypatch, state)
        assert mozactl._state_virtual_name([7]) is None

    def test_stale_state_from_a_dead_daemon_is_ignored(self, monkeypatch):
        self._state(monkeypatch, {"pid": 7, "argv": ["--name", "X"]})
        assert mozactl._state_virtual_name([8]) is None
        assert mozactl._state_virtual_name([]) is None


class TestTextRows:
    def test_wrapping(self):
        assert mozactl._text_rows(["", "a" * 80, "a" * 81, "a" * 160], 80) == 1 + 1 + 2 + 2
        assert mozactl._text_rows(["abc"], 0) == 3  # never divides by zero


class TestNoEcho:
    def test_turns_echo_off_and_restores_it(self):
        import pty
        import termios
        master, slave = pty.openpty()
        try:
            before = termios.tcgetattr(slave)
            assert before[3] & termios.ECHO
            quiet = mozactl._NoEcho(slave)
            assert not termios.tcgetattr(slave)[3] & termios.ECHO
            assert termios.tcgetattr(slave)[3] & termios.ISIG  # Ctrl-C still works
            quiet.close()
            assert termios.tcgetattr(slave) == before
            quiet.close()  # idempotent
        finally:
            os.close(master)
            os.close(slave)

    def test_no_op_without_a_terminal(self):
        r, w = os.pipe()
        try:
            mozactl._NoEcho(r).close()
            mozactl._NoEcho(-1).close()
        finally:
            os.close(r)
            os.close(w)


class TestFrame:
    AXES = [(f"ABS_{i}", 0, -32768, 32767) for i in range(10)]  # the base has 10
    RECENT = [("32", f"press   BTN {i}") for i in range(8)]

    def _frame(self, cols=120, rows=40, axes=None, pressed=(), recent=None):
        return mozactl._watch_frame(self.AXES if axes is None else axes,
                                    list(pressed),
                                    self.RECENT if recent is None else recent,
                                    cols, rows)

    def test_full_frame_when_there_is_room(self):
        frame = self._frame()
        assert len(frame) == 10 + 1 + 1 + 1 + 8
        assert frame[10] == ("", "")
        assert frame[11] == ("90", "  buttons down: (none)")
        assert frame[12] == ("90", "  recent:")

    @pytest.mark.parametrize("rows", [3, 5, 12, 13, 14, 18, 21, 22, 24, 40])
    def test_never_taller_than_the_terminal(self, rows):
        # Redrawing in place moves the cursor back up over the frame, which
        # only works while the frame fits: one line too many and it scrolls.
        frame = self._frame(rows=rows)
        assert len(frame) <= max(3, rows - 1)
        assert any(text.startswith("  buttons down:") for _, text in frame)

    def test_recent_list_gives_way_before_the_axes(self):
        frame = self._frame(rows=18)  # 17 lines: 10 axes + 2 + "recent:" + 4
        texts = [t for _, t in frame]
        assert sum(t.startswith("  ABS_") for t in texts) == 10
        assert sum(t.startswith("    press") for t in texts) == 4

    def test_axes_fold_into_a_note_on_a_very_short_terminal(self):
        texts = [t for _, t in self._frame(rows=8)]  # 7 lines
        assert sum(t.startswith("  ABS_") for t in texts) == 4
        assert "6 more axes" in texts[4]
        assert texts[-1].startswith("  buttons down:")
        assert not any(t.startswith("  recent") for t in texts)

    @pytest.mark.parametrize("cols", [20, 40, 60, 79, 80, 200])
    def test_no_line_is_wider_than_the_terminal(self, cols):
        frame = self._frame(cols=cols, pressed=["BTN_TRIGGER_HAPPY 0x2c0"] * 9)
        assert all(len(text) <= cols for _, text in frame)

    def test_bar_shrinks_before_the_range_is_cut_off(self):
        (_, wide), = [f for f in self._frame(cols=100, axes=self.AXES[:1],
                                             recent=[])[:1]]
        (_, narrow), = [f for f in self._frame(cols=64, axes=self.AXES[:1],
                                               recent=[])[:1]]
        assert wide.count("#") + wide.count("-") > narrow.count("#") + narrow.count("-")
        assert narrow.endswith("(-32768..32767)")

    def test_pressed_buttons_listed(self):
        frame = self._frame(pressed=["0x12c", "0x12d"])
        assert ("", "  buttons down: 0x12c  0x12d") in frame

    def test_fit(self):
        assert mozactl._fit("abcdef", 10) == "abcdef"
        assert mozactl._fit("abcdef", 6) == "abcdef"
        assert mozactl._fit("abcdef", 4) == "abc…"
        assert mozactl._fit("abcdef", 0) == ""


# ---------------------------------------------------------------------------
# End-of-run summary (pure)
# ---------------------------------------------------------------------------
class TestSummary:
    def _stats(self, values, lo, hi):
        st = mozactl._new_axis_stats(24)
        for v in values:
            mozactl._record_axis(st, v, lo, hi)
        return st

    def test_record_axis_tracks_count_range_and_distinct(self):
        st = self._stats([5, 5, 9, -3], -10, 10)
        assert st["n"] == 4
        assert (st["min"], st["max"]) == (-3, 9)
        assert st["distinct"] == {5, 9, -3}
        assert sum(st["buckets"]) == 4

    def test_distinct_set_is_bounded(self, monkeypatch):
        monkeypatch.setattr(mozactl, "_DISTINCT_CAP", 4)
        st = self._stats(range(100), 0, 99)
        assert len(st["distinct"]) == 4 and st["n"] == 100
        (row,) = [ln for ln in mozactl._watch_summary([("ABS_X", st)], [])
                  if ln.startswith("ABS_X")]
        assert row.split()[2] == "4+"  # "+" = hit the cap, i.e. plainly analog

    def test_analog_and_binary_rows_read_differently(self):
        analog = self._stats(range(0, 65536, 97), 0, 65535)
        binary = self._stats([-32768, 32767] * 50, -32768, 32767)
        lines = mozactl._watch_summary(
            [("ABS_X", analog), ("ABS_Z", binary)], ["BTN_JOYSTICK 0x120"])
        rows = {ln.split()[0]: ln for ln in lines}
        assert rows["ABS_X"].split()[2] == str(len(range(0, 65536, 97)))
        assert rows["ABS_Z"].split()[2] == "2"
        # Histogram: analog fills every bucket, binary only the two ends.
        a_hist = rows["ABS_X"].split("[", 1)[1].rstrip("]")
        b_hist = rows["ABS_Z"].split("[", 1)[1].rstrip("]")
        assert " " not in a_hist
        assert b_hist[0] != " " and b_hist[-1] != " "
        assert b_hist[1:-1].strip() == ""
        assert lines[-1] == "buttons pressed: BTN_JOYSTICK 0x120"

    def test_untouched_axis_says_no_motion(self):
        (row,) = [ln for ln in mozactl._watch_summary(
            [("ABS_RZ", mozactl._new_axis_stats(24))], [])
            if ln.startswith("ABS_RZ")]
        assert "(no motion)" in row and row.split()[1] == "0"

    def test_table_fits_an_80_column_terminal(self, monkeypatch):
        # A row that wraps breaks the histogram across two lines — exactly the
        # column the eye is supposed to read. Worst case: longest axis name,
        # a capped distinct count, the widest range, eight-digit sample count.
        monkeypatch.setattr(mozactl, "_DISTINCT_CAP", 20000)
        st = self._stats(range(-32768, 32768), -32768, 32767)
        st["n"] = 99_999_999
        lines = mozactl._watch_summary(
            [("ABS_HAT0X", self._stats([0], -1, 1)), ("ABS_THROTTLE", st)], [])
        assert "20000+" in lines[3]
        assert max(len(ln) for ln in lines) <= 78  # printed with a 2-space indent

    def test_no_buttons_line_when_none_pressed(self):
        lines = mozactl._watch_summary([("ABS_X", mozactl._new_axis_stats(24))], [])
        assert not any(ln.startswith("buttons pressed") for ln in lines)


# ---------------------------------------------------------------------------
# cmd_watch end to end against a fake node (no /dev/input access)
# ---------------------------------------------------------------------------
import errno  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

import evdev  # noqa: E402
from evdev import AbsInfo, InputEvent  # noqa: E402


def _ev(etype, code, value):
    return InputEvent(0, 0, etype, code, value)


class FakeNode:
    """Duck-typed evdev.InputDevice whose fd is a real, selectable pipe.

    `script` is a list of steps for successive read() calls: a list of events
    to deliver, an exception instance to raise, or a number of seconds to
    sleep before delivering nothing. When the script runs out, `then` decides
    what happens: "interrupt" raises KeyboardInterrupt (the user pressed
    Ctrl-C); "quiet" drains the pipe so the node goes silent, and the watch
    must end some other way (--duration, SIGTERM).
    """

    def __init__(self, node, script=(), then="interrupt", abs_caps=None):
        self.path = node["path"]
        self.name = node["name"]
        self.phys = node["phys"]
        self.info = types.SimpleNamespace(vendor=node["vendor"], product=0x0002,
                                          version=0x0111)
        self._has_abs = node.get("has_abs", True)
        self._abs = abs_caps if abs_caps is not None else self._ABS
        self._script = list(script)
        self._then = then
        self._r, self._w = os.pipe()
        os.write(self._w, b"x")
        self.closed = False

    _ABS = {ecodes.ABS_X: AbsInfo(32768, 0, 65535, 0, 0, 0),
            ecodes.ABS_Z: AbsInfo(-32768, -32768, 32767, 0, 0, 0)}

    def capabilities(self, absinfo=False):
        caps = {ecodes.EV_KEY: [0x120, 0x2C0]}
        if self._has_abs:
            caps[ecodes.EV_ABS] = (list(self._abs.items()) if absinfo
                                   else list(self._abs))
        return caps

    def fileno(self):
        return self._r

    def read(self):
        if not self._script:
            if self._then == "quiet":
                os.read(self._r, 1)  # nothing readable any more: select idles
                raise BlockingIOError
            raise KeyboardInterrupt
        step = self._script.pop(0)
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, (int, float)):
            time.sleep(step)
            return iter(())
        return iter(step)

    def close(self):
        if not self.closed:
            self.closed = True
            os.close(self._r)
            os.close(self._w)


@pytest.fixture
def watch(monkeypatch):
    """Run cmd_watch against `nodes`; the chosen node replays `script`."""
    state = types.SimpleNamespace(opened=[], live=None)

    def run(nodes, script=(), *, pids=(), tty=False, then="interrupt",
            abs_caps=None, **argv):
        monkeypatch.setattr(mozactl, "_iter_evdev",
                            lambda: (FakeNode(n) for n in nodes))
        by_path = {n["path"]: n for n in nodes}

        def opener(path):
            state.opened.append(path)
            state.live = FakeNode(by_path[path], script, then, abs_caps)
            return state.live

        monkeypatch.setattr(evdev, "InputDevice", opener)
        monkeypatch.setattr(mozactl, "daemon_pids", lambda: list(pids))
        monkeypatch.setattr(mozactl, "_TTY", tty)
        args = dict(real=False, virtual=False, duration=0.0, log=None)
        args.update(argv)
        return mozactl.cmd_watch(types.SimpleNamespace(**args))

    run.state = state
    return run


_LOG_LINE = re.compile(r"^\+\s*([0-9.]+)\s+(ABS|KEY)\s+(.*)$")
_ANSI = re.compile(r"\033\[[0-9;]*[A-Za-z]")


def _log_events(text: str) -> list[tuple[float, str, list[str]]]:
    """(seconds, kind, remaining fields) for each event line of a watch log."""
    out = []
    for ln in text.splitlines():
        m = _LOG_LINE.match(ln)
        if m:
            out.append((float(m.group(1)), m.group(2), m.group(3).split()))
    return out


def _summary_row(out: str, axis: str) -> list[str]:
    (row,) = [ln for ln in out.splitlines() if ln.strip().startswith(axis + " ")]
    return row.split()


SWEEP = [_ev(ecodes.EV_ABS, ecodes.ABS_X, v) for v in range(0, 65536, 219)]
TOGGLE = [_ev(ecodes.EV_ABS, ecodes.ABS_Z, v) for v in (-32768, 32767) * 30]
PRESS = [_ev(ecodes.EV_KEY, 0x2C0, 1), _ev(ecodes.EV_KEY, 0x2C0, 0)]


class TestCmdWatch:
    def test_analog_sweep_and_binary_toggle_reach_the_summary(self, watch, capsys):
        assert watch([VIRT], [SWEEP, TOGGLE, PRESS]) == 0
        out = capsys.readouterr().out
        assert "VIRTUAL (what games see)" in out
        assert _summary_row(out, "ABS_X")[1:3] == [str(len(SWEEP)), str(len(SWEEP))]
        assert _summary_row(out, "ABS_Z")[1:3] == [str(len(TOGGLE)), "2"]
        assert "buttons pressed: BTN_TRIGGER_HAPPY 0x2c0" in out
        assert watch.state.live.closed

    def test_off_a_tty_button_transitions_stream_as_plain_lines(self, watch, capsys):
        watch([VIRT], [PRESS])
        out = capsys.readouterr().out
        assert "press BTN_TRIGGER_HAPPY 0x2c0\n" in out
        assert "release BTN_TRIGGER_HAPPY 0x2c0\n" in out
        assert "\033[" not in out  # no cursor control or colour in a pipe

    def test_on_a_tty_the_frame_redraws_in_place_under_the_header(self, watch,
                                                                    capsys):
        watch([VIRT], [SWEEP, PRESS], tty=True)
        out = capsys.readouterr().out
        # The header names the node and says how to stop; it used to be wiped
        # by a clear-screen before anyone could read it.
        assert out.count("mozaproxy watch") == 1 and "Ctrl-C to stop" in out
        assert "\033[2J" not in out and "\033[H" not in out
        header_end = out.index("Ctrl-C to stop")
        first_frame = out.index("ABS_X", header_end)
        assert "\033[" + "4A" in out[first_frame:]  # 2 axes + blank + buttons
        assert "[####" in out and "buttons down:" in out

    def test_on_a_tty_a_read_error_is_printed_after_the_last_frame(self, watch,
                                                                    capsys):
        rc = watch([VIRT], [SWEEP, OSError(errno.ENODEV, "No such device")],
                   tty=True)
        out = capsys.readouterr().out
        assert rc == 1
        # It used to be printed mid-frame and then drawn over by the final
        # redraw, so the watch just stopped with no explanation.
        assert out.rindex("device read error") > out.rindex("buttons down:")
        assert "\033[" not in out[out.rindex("device read error"):].split("\n")[1]

    def test_log_holds_the_event_stream_and_the_same_summary(self, watch, capsys,
                                                             tmp_path):
        log = tmp_path / "watch.log"
        assert watch([VIRT], [SWEEP, PRESS], log=str(log)) == 0
        text = log.read_text()
        assert text.startswith("# mozaproxy watch log\n")
        assert "ABS_X[0..65535]" in text and "ABS_Z[-32768..32767]" in text
        assert "  ABS  ABS_X" in text
        assert "  KEY  press   BTN_TRIGGER_HAPPY 0x2c0" in text
        assert "# SUMMARY" in text and "# buttons pressed:" in text
        out = capsys.readouterr().out
        assert f"Wrote {log}" in out
        assert _summary_row(text.replace("# ", ""), "ABS_X")[2] == str(len(SWEEP))

    def test_unwritable_log_is_reported_not_raised(self, watch, capsys, tmp_path):
        rc = watch([VIRT], [SWEEP], log=str(tmp_path / "missing-dir" / "w.log"))
        assert rc == 1
        assert "could not open log" in capsys.readouterr().out
        assert watch.state.live.closed  # the node must not be leaked

    def test_log_ends_on_each_axis_final_value(self, watch, capsys, tmp_path):
        # 1 kHz-style burst: one read() delivers a whole press-and-release.
        # Downsampling to ~50 Hz logs the first sample; the last one — where
        # the pedal came to rest — must still reach the log.
        burst = [_ev(ecodes.EV_ABS, ecodes.ABS_Z, v)
                 for v in list(range(-32768, 32767, 700)) + [-32768]]
        log = tmp_path / "w.log"
        assert watch([VIRT], [burst], log=str(log)) == 0
        abs_lines = [ln for ln in log.read_text().splitlines() if "  ABS  " in ln]
        assert len(abs_lines) == 2  # first sample + the settled value
        assert abs_lines[0].split()[-2:] == ["-32768", "0.0%"]
        assert abs_lines[-1].split()[-2:] == ["-32768", "0.0%"]
        assert _summary_row(capsys.readouterr().out, "ABS_Z")[1] == str(len(burst))

    def test_log_stream_is_downsampled_but_keeps_every_key_event(self, watch,
                                                                 tmp_path):
        log = tmp_path / "w.log"
        watch([VIRT], [SWEEP + PRESS + PRESS], log=str(log))
        lines = log.read_text().splitlines()
        assert sum("  ABS  " in ln for ln in lines) < len(SWEEP)
        assert sum("  KEY  " in ln for ln in lines) == 4

    def test_sigterm_ends_a_quiet_watch(self, watch, capsys, tmp_path):
        # The node goes silent, so only the SIGTERM handler can end this one
        # before the 10 s safety duration (the fake's Ctrl-C never fires).
        import signal
        import threading
        before = signal.getsignal(signal.SIGTERM)
        log = tmp_path / "w.log"
        timer = threading.Timer(0.15, os.kill, (os.getpid(), signal.SIGTERM))
        t = time.monotonic()
        timer.start()
        try:
            rc = watch([VIRT], [PRESS], then="quiet", duration=10, log=str(log))
        finally:
            timer.cancel()
        assert rc == 0
        assert time.monotonic() - t < 3
        assert "# SUMMARY" in log.read_text()  # not cut off mid-run
        assert "SUMMARY" in capsys.readouterr().out
        assert signal.getsignal(signal.SIGTERM) is before  # handler restored
        assert watch.state.live.closed

    def test_a_vanished_stdout_stops_quietly(self, watch, monkeypatch, tmp_path):
        # `mozactl watch | head -1`: print() raises once the reader has left.
        calls = {"n": 0}

        def flaky_print(*a, **k):
            calls["n"] += 1
            if calls["n"] > 3:
                raise BrokenPipeError(errno.EPIPE, "Broken pipe")

        monkeypatch.setattr(mozactl, "print", flaky_print, raising=False)
        monkeypatch.setattr(mozactl.os, "dup2", lambda *a: None)
        log = tmp_path / "w.log"
        assert watch([VIRT], [PRESS, PRESS, PRESS], log=str(log)) == 0
        assert watch.state.live.closed
        assert "# SUMMARY" in log.read_text()  # the log is still completed

    def test_idle_flush_stamps_a_held_value_with_its_read_time(self, watch,
                                                               tmp_path):
        # The release lands 5 ms after the press, inside the 20 ms thinning
        # window, then the node goes quiet: the idle path must write it, and
        # stamp it when it was read, not ~200 ms later when it was flushed.
        log = tmp_path / "w.log"
        watch([VIRT], [[_ev(ecodes.EV_ABS, ecodes.ABS_Z, 20000)], 0.005,
                       [_ev(ecodes.EV_ABS, ecodes.ABS_Z, -32768)]],
              then="quiet", duration=0.5, log=str(log))
        rows = [e for e in _log_events(log.read_text()) if e[1] == "ABS"]
        assert [e[2][1] for e in rows] == ["20000", "-32768"]
        assert rows[1][0] - rows[0][0] < 0.1

    def test_log_keeps_time_order_around_button_lines(self, watch, tmp_path):
        # Pedal released 5 ms after pressing (held back by the thinning), then
        # a paddle 50 ms later: the release must be logged BEFORE the paddle,
        # at its own time.
        log = tmp_path / "w.log"
        watch([VIRT], [[_ev(ecodes.EV_ABS, ecodes.ABS_Z, 20000)], 0.005,
                       [_ev(ecodes.EV_ABS, ecodes.ABS_Z, -32768)], 0.05,
                       [_ev(ecodes.EV_KEY, 0x2C0, 1)]], log=str(log))
        events = _log_events(log.read_text())
        assert [(kind, fields[-1]) for _, kind, fields in events] == [
            ("ABS", "80.5%"), ("ABS", "0.0%"), ("KEY", "0x2c0")]
        stamps = [t for t, _, _ in events]
        assert stamps == sorted(stamps)
        assert stamps[1] - stamps[0] < 0.04  # stamped when read, not flushed

    def test_a_button_inside_the_thinning_window_still_logs_in_order(
            self, watch, tmp_path):
        # Here the paddle fires while the release is STILL held back (5 ms
        # later, inside the 20 ms window), so the paddle's line is produced
        # first. The reorder buffer must still write the release before it.
        log = tmp_path / "w.log"
        watch([VIRT], [[_ev(ecodes.EV_ABS, ecodes.ABS_Z, 20000)], 0.005,
                       [_ev(ecodes.EV_ABS, ecodes.ABS_Z, -32768)], 0.005,
                       [_ev(ecodes.EV_KEY, 0x2C0, 1)]], log=str(log))
        events = _log_events(log.read_text())
        assert [(kind, fields[-1]) for _, kind, fields in events] == [
            ("ABS", "80.5%"), ("ABS", "0.0%"), ("KEY", "0x2c0")]
        stamps = [t for t, _, _ in events]
        assert stamps == sorted(stamps)

    def test_piped_output_is_flushed_line_by_line(self, watch, monkeypatch):
        # A pipe block-buffers stdout: without explicit flushes `watch | tee`
        # showed nothing until exit, and Ctrl-C (which kills tee too) lost it.
        class Recorder(io.StringIO):
            def __init__(self):
                super().__init__()
                self.at_flush = []

            def flush(self):
                self.at_flush.append(self.getvalue())

        out = Recorder()
        monkeypatch.setattr("sys.stdout", out)
        watch([VIRT], [PRESS])
        # The header is out before any event, and each press/release reached
        # the reader as it happened.
        assert any("Ctrl-C to stop" in snap and "press BTN" not in snap
                   for snap in out.at_flush)
        assert any(snap.endswith("press BTN_TRIGGER_HAPPY 0x2c0\n")
                   for snap in out.at_flush)
        assert any(snap.endswith("release BTN_TRIGGER_HAPPY 0x2c0\n")
                   for snap in out.at_flush)

    def test_a_reader_leaving_at_the_end_is_a_quiet_stop(self, watch, monkeypatch):
        # `watch | head -1`: EPIPE surfaces on the final flush. It used to
        # escape to the interpreter's exit flush (exit status 120).
        class GoneAtEnd(io.StringIO):
            raised = False

            def flush(self):
                if "SUMMARY" in self.getvalue():
                    GoneAtEnd.raised = True
                    raise BrokenPipeError(errno.EPIPE, "Broken pipe")

        monkeypatch.setattr("sys.stdout", GoneAtEnd())
        assert watch([VIRT], [PRESS]) == 0
        assert GoneAtEnd.raised  # the final flush ran inside cmd_watch
        assert watch.state.live.closed

    def test_a_failing_log_stops_logging_not_the_watch(self, watch, capsys):
        # /dev/full: every write fails with ENOSPC, like a full disk.
        rc = watch([VIRT], [SWEEP, PRESS], log="/dev/full")
        out = capsys.readouterr().out
        assert rc == 0
        assert _summary_row(out, "ABS_X")[1] == str(len(SWEEP))
        assert "Log /dev/full is incomplete" in out and "No space left" in out
        assert watch.state.live.closed

    def test_on_a_tty_an_idle_watch_redraws_the_final_state(self, watch, capsys):
        # The second batch lands within the 30 fps cap, so the loop does not
        # draw it; the idle path (select timeout) must.
        watch([VIRT], [[_ev(ecodes.EV_ABS, ecodes.ABS_X, 100)],
                       [_ev(ecodes.EV_ABS, ecodes.ABS_X, 65000)]],
              tty=True, then="quiet", duration=0.5)
        out = capsys.readouterr().out
        frames = out.split("\033[J")
        assert re.search(r"ABS_X\s+65000\s+\[", frames[-2])  # last frame drawn

    def test_on_a_tty_the_final_state_is_redrawn_after_the_loop(self, watch,
                                                                capsys):
        watch([VIRT], [[_ev(ecodes.EV_ABS, ecodes.ABS_X, 100)],
                       [_ev(ecodes.EV_ABS, ecodes.ABS_X, 65000)]], tty=True)
        out = capsys.readouterr().out
        assert re.search(r"ABS_X\s+65000\s+\[", out)
        assert out.count("\033[J") >= 2  # frames clear what a taller one left

    def test_on_a_tty_header_and_frame_fit_80x24_with_the_bases_10_axes(
            self, watch, capsys, monkeypatch):
        axes = {c: AbsInfo(0, -32768, 32767, 0, 0, 0)
                for c in (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_Z, ecodes.ABS_RX,
                          ecodes.ABS_RY, ecodes.ABS_RZ, ecodes.ABS_THROTTLE,
                          ecodes.ABS_RUDDER)}
        axes[ecodes.ABS_HAT0X] = axes[ecodes.ABS_HAT0Y] = AbsInfo(0, -1, 1, 0, 0, 0)
        monkeypatch.setattr(mozactl.shutil, "get_terminal_size",
                            lambda fallback=None: os.terminal_size((80, 24)))
        many = [_ev(ecodes.EV_KEY, 0x120 + (i % 2), i % 2) for i in range(12)]
        watch([VIRT], [many], tty=True, abs_caps=axes)
        out = capsys.readouterr().out
        header = _ANSI.sub("", out[:out.index("\r")]).splitlines()
        assert header[0].startswith("mozaproxy watch")
        frame = out.split("\033[J")[-2]  # the last frame, with 8 recent events
        frame_rows = frame.count("\033[K\n")
        assert mozactl._text_rows(header, 80) + frame_rows <= 23
        assert "ABS_HAT0Y" in frame  # every axis still shown

    def test_on_a_tty_a_resize_restarts_from_a_clean_screen(self, watch, capsys,
                                                             monkeypatch):
        sizes = iter([(100, 30)] + [(60, 30)] * 50)
        monkeypatch.setattr(mozactl.shutil, "get_terminal_size",
                            lambda fallback=None: os.terminal_size(next(sizes)))
        watch([VIRT], [[_ev(ecodes.EV_ABS, ecodes.ABS_X, 100)], 0.05,
                       [_ev(ecodes.EV_ABS, ecodes.ABS_X, 200)]], tty=True)
        out = capsys.readouterr().out
        clean = out.index("\033[H\033[2J")
        assert out.count("mozaproxy watch") == 2  # header shown again...
        assert out.index("mozaproxy watch", clean) > clean  # ...after the wipe

    def test_device_loss_ends_the_watch_with_status_1(self, watch, capsys):
        rc = watch([VIRT], [SWEEP, OSError(errno.ENODEV, "No such device")])
        assert rc == 1
        out = capsys.readouterr().out
        assert "device read error" in out
        assert _summary_row(out, "ABS_X")[1] == str(len(SWEEP))  # still summarised
        assert watch.state.live.closed

    def test_spurious_wakeups_are_ignored(self, watch, capsys):
        assert watch([VIRT], [BlockingIOError(), PRESS]) == 0
        assert "press BTN_TRIGGER_HAPPY 0x2c0" in capsys.readouterr().out

    def test_duration_ends_a_quiet_watch(self, watch, capsys):
        t = time.monotonic()
        assert watch([VIRT], [], then="quiet", duration=0.3) == 0
        assert 0.25 <= time.monotonic() - t < 3
        assert "(no motion)" in capsys.readouterr().out

    def test_events_for_axes_the_node_never_advertised_are_ignored(self, watch,
                                                                    capsys):
        stray = [_ev(ecodes.EV_ABS, ecodes.ABS_RUDDER, 123)]
        assert watch([VIRT], [stray, PRESS]) == 0
        assert "ABS_RUDDER" not in capsys.readouterr().out

    def test_auto_reads_the_virtual_node_while_the_daemon_runs(self, watch, capsys):
        assert watch([REAL, VIRT], [PRESS], pids=[4242]) == 0
        assert watch.state.opened == [VIRT["path"]]

    def test_auto_reads_the_real_node_when_the_daemon_is_down(self, watch, capsys):
        assert watch([REAL], [PRESS]) == 0
        assert watch.state.opened == [REAL["path"]]
        assert "REAL hardware" in capsys.readouterr().out

    def test_real_is_refused_while_the_daemon_holds_the_grab(self, watch, capsys):
        assert watch([REAL, VIRT], [PRESS], pids=[4242], real=True) == 1
        out = capsys.readouterr().out
        assert "exclusive grab" in out and "mozactl watch --virtual" in out
        assert watch.state.opened == []  # never even opened the silent node

    @pytest.mark.parametrize("argv, nodes, pids, needle", [
        (dict(virtual=True), [REAL], [], "the daemon is not running"),
        (dict(virtual=True), [REAL], [4242], "virtual device was not found"),
        (dict(real=True), [VIRT], [], "No real MOZA base found"),
        (dict(), [OTHER], [], "No MOZA (real or virtual) node found"),
    ])
    def test_missing_node_messages(self, watch, capsys, argv, nodes, pids, needle):
        assert watch(nodes, [], pids=pids, **argv) == 1
        assert needle in capsys.readouterr().out
        assert watch.state.opened == []

    def test_a_virtual_device_wearing_another_identity_is_found(self, watch,
                                                                monkeypatch):
        # A profile's [identity] table can make the virtual device an Xbox pad:
        # no MOZA vendor id, no "mozaproxy" in the name. The daemon's recorded
        # --name is what identifies it; without that, auto mode sent the user
        # to --virtual, and --virtual said the daemon was not running.
        pad = _node("Microsoft X-Box 360 pad", 0x045E, "py-evdev-uinput")
        state = {"pid": 4242, "mode": "B",
                 "argv": ["--mode", "B", "--name", "Microsoft X-Box 360 pad"]}
        monkeypatch.setattr(mozactl, "_read_state", lambda: state)
        assert watch([REAL, pad], [PRESS], pids=[4242]) == 0
        assert watch([REAL, pad], [PRESS], pids=[4242], virtual=True) == 0
        assert watch.state.opened == [pad["path"], pad["path"]]

    def test_a_node_vanishing_during_the_scan_is_skipped(self, watch, capsys,
                                                         monkeypatch):
        def flaky():
            gone = FakeNode(OTHER)
            gone.capabilities = lambda absinfo=False: (_ for _ in ()).throw(
                OSError(errno.ENODEV, "No such device"))
            yield gone
            yield FakeNode(VIRT)

        def run_with_flaky_scan():
            rc = watch([VIRT], [PRESS])
            return rc

        # Install the flaky scan AFTER the fixture's own patch by wrapping it.
        orig = mozactl.cmd_watch

        def patched(args):
            monkeypatch.setattr(mozactl, "_iter_evdev", flaky)
            return orig(args)

        monkeypatch.setattr(mozactl, "cmd_watch", patched)
        assert run_with_flaky_scan() == 0
        assert watch.state.opened == [VIRT["path"]]
