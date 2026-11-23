"""Smoke tests for the two command-line parsers.

Nothing else in the suite builds them, so a malformed argparse help string
(an unescaped ``%``) went unnoticed — and since Python 3.14 validates help
strings when an argument is ADDED, that one character made every ``mozactl``
invocation die before it parsed anything, including the ``mozactl run`` Steam
launch glue. Building the parser and rendering every help page pins both
behaviours: render-time failures (any Python) and build-time failures (3.14+).
"""
from __future__ import annotations

import pytest

import mozactl
import mozaproxy

SUBCOMMANDS = ("status", "doctor", "start", "stop", "modes", "list", "run",
               "new", "logs", "watch", "calibrate")


def _help_exits_cleanly(fn, argv, capsys) -> str:
    with pytest.raises(SystemExit) as exc:
        fn(argv)
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage:")
    return out


class TestMozactlParser:
    def test_top_level_help_lists_every_subcommand(self, capsys):
        out = _help_exits_cleanly(mozactl.main, ["--help"], capsys)
        for cmd in SUBCOMMANDS:
            assert cmd in out

    @pytest.mark.parametrize("cmd", SUBCOMMANDS)
    def test_subcommand_help_renders(self, cmd, capsys):
        _help_exits_cleanly(mozactl.main, [cmd, "--help"], capsys)

    def test_watch_help_keeps_its_percent_sign(self, capsys):
        # The literal the bad help string was reaching for: "%-travel".
        out = _help_exits_cleanly(mozactl.main, ["--help"], capsys)
        assert "(%-travel)" in out

    def test_percent_in_runtime_dir_cannot_break_the_parser(self, monkeypatch,
                                                            capsys):
        # The --log help quotes the default path, which comes from
        # $XDG_RUNTIME_DIR. argparse %-formats help text, so an unescaped "%"
        # in that path was the same crash as the watch help, by another route.
        import importlib
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp/mz100%.x")
        try:
            importlib.reload(mozactl)
            assert mozactl.WATCHLOG == "/tmp/mz100%.x/mozaproxy-watch.log"
            out = _help_exits_cleanly(mozactl.main, ["watch", "--help"], capsys)
            assert "/tmp/mz100%.x/mozaproxy-watch.log" in " ".join(out.split())
            assert mozactl.main(["modes"]) == 0  # every command builds the parser
        finally:
            monkeypatch.undo()
            importlib.reload(mozactl)

    def test_missing_subcommand_is_a_usage_error_not_a_crash(self, capsys):
        with pytest.raises(SystemExit) as exc:
            mozactl.main([])
        assert exc.value.code == 2

    def test_watch_flags_parse(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(mozactl, "cmd_watch",
                            lambda args: seen.update(vars(args)) or 0)
        assert mozactl.main(["watch", "--virtual", "--duration", "2.5",
                             "--log"]) == 0
        assert seen["virtual"] is True and seen["real"] is False
        assert seen["duration"] == 2.5
        assert seen["log"] == mozactl.WATCHLOG  # bare --log -> default path

    def test_watch_real_and_virtual_are_exclusive(self, capsys):
        with pytest.raises(SystemExit) as exc:
            mozactl.main(["watch", "--real", "--virtual"])
        assert exc.value.code == 2


class TestStartForwardsDaemonArgs:
    """`mozactl start -- <daemon flags>`: the advertised pass-through."""

    @pytest.fixture
    def spawned(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(mozactl, "daemon_pids", lambda: [])
        monkeypatch.setattr(mozactl, "_spawn_daemon",
                            lambda argv: seen.setdefault("argv", list(argv)) and 4242)
        monkeypatch.setattr(mozactl, "_write_state",
                            lambda pid, mode, argv, profile=None:
                            seen.update(state=(pid, mode, list(argv), profile)))
        return seen

    def test_separator_is_not_forwarded(self, spawned, capsys):
        # The "--" used to reach the daemon, whose parser then refused every
        # flag after it and exited: no form of the pass-through ever worked.
        rc = mozactl.main(["start", "--mode", "C", "--",
                           "--button-codes", "0x120,0x2c0"])
        assert rc == 0
        assert spawned["argv"] == ["--mode", "C", "--button-codes", "0x120,0x2c0"]
        assert mozaproxy.parse_args(spawned["argv"]).button_codes == [0x120, 0x2C0]

    def test_state_matches_what_a_profile_renders(self, spawned, capsys):
        # So a later `mozactl run` of an equivalent profile leaves this daemon
        # alone instead of restarting it.
        from profiledb import Profile, daemon_args, needs_restart
        mozactl.main(["start", "--mode", "normalized", "--",
                      "--button-codes", "0x120,0x2c0"])
        pid, mode, argv, profile = spawned["state"]
        want = daemon_args(Profile(name="g", mode="C",
                                   button_codes=[0x120, 0x2C0]), {})
        assert (mode, argv, profile) == ("C", want, None)
        assert needs_restart({"pid": pid, "argv": argv}, want, [pid]) is False

    def test_plain_start_is_unchanged(self, spawned, capsys):
        assert mozactl.main(["start", "--mode", "C", "--deadzone", "0.05"]) == 0
        assert spawned["argv"] == ["--mode", "C", "--deadzone", "0.05"]

    def test_only_the_leading_separator_is_dropped(self, spawned, capsys):
        mozactl.main(["start", "--", "--name", "--"])
        assert spawned["argv"] == ["--mode", "A", "--name", "--"]

    def test_a_forwarded_mode_is_the_mode_recorded(self, spawned, capsys):
        # The daemon takes the LAST --mode, so `status` (which shows the
        # recorded mode) must report that one, not start's own default.
        mozactl.main(["start", "--", "--mode", "normalized"])
        assert spawned["argv"] == ["--mode", "A", "--mode", "normalized"]
        assert spawned["state"][1] == "C"
        assert "Starting mode C" in capsys.readouterr().out

    def test_argv_the_daemon_rejects_keeps_starts_mode(self, spawned, capsys):
        # Nothing to read the mode from; the spawn itself reports the error.
        mozactl.main(["start", "--mode", "C", "--", "--no-such-flag"])
        assert spawned["state"][1] == "C"
        assert capsys.readouterr().err == ""


class TestDaemonCmdline:
    """Which processes `stop`/`run` treat as the daemon (and so signal)."""

    @pytest.mark.parametrize("cmdline", [
        "/x/.venv/bin/python /x/mozaproxy.py --mode A",      # _spawn_daemon
        ".venv/bin/python mozaproxy.py -v",                  # run.sh
        "/usr/bin/python3 ./mozaproxy.py",                   # ./mozaproxy.py
        "/usr/bin/python3.14 -u /x/mozaproxy.py --once",
        # Interpreter options that take a value, as a debugging session might
        # start it: the value is not the script.
        "/x/.venv/bin/python -X dev mozaproxy.py -v",
        "/x/.venv/bin/python -W error mozaproxy.py",
        "/x/.venv/bin/python -Xfaulthandler -Werror mozaproxy.py",
        "/x/.venv/bin/python -uX faulthandler mozaproxy.py",
        "/x/.venv/bin/python -uXdev mozaproxy.py",
        "/x/.venv/bin/python --check-hash-based-pycs never mozaproxy.py",
        "/x/.venv/bin/python -B -- mozaproxy.py",
    ])
    def test_matches_the_daemon(self, cmdline):
        assert mozactl._is_daemon_cmdline(cmdline.encode().split())

    @pytest.mark.parametrize("cmdline", [
        # Another tool whose script name merely ENDS in mozaproxy.py: the old
        # substring match would SIGTERM it on `mozactl stop`.
        "/w/.venv/bin/python /w/tools/open-mozaproxy.py",
        "/w/.venv/bin/python /w/tools/open-mozaproxy.py -- proton run game.exe",
        "/w/.venv/bin/python -m mozaproxy.game_service",
        # -c/-m run a command or module, never the script, also when the
        # module or command is attached (the rest of the entry is no flags).
        "/x/.venv/bin/python -m pdb mozaproxy.py",
        "/x/.venv/bin/python -um pdb mozaproxy.py",
        "/x/.venv/bin/python -mpdb mozaproxy.py",
        "/x/.venv/bin/python -c pass mozaproxy.py",
        "/x/.venv/bin/python -cpass mozaproxy.py",
        # A value is not the script, even when it is named like it.
        "/x/.venv/bin/python -W mozaproxy.py other.py",
        "/x/.venv/bin/python - mozaproxy.py",               # script on stdin
        "vim mozaproxy.py",
        "/x/.venv/bin/python /x/mozactl.py run jdm -- mozaproxy.py",
        "/x/.venv/bin/python",
        "/x/.venv/bin/python -X",
        "",
    ])
    def test_ignores_everything_else(self, cmdline):
        assert not mozactl._is_daemon_cmdline(cmdline.encode().split())

    def test_daemon_pids_reads_proc(self, tmp_path):
        # The wiring around the match: /proc/<pid>/cmdline holds NUL-terminated
        # entries, and only numeric directories are processes.
        procs = {
            "101": b"/x/.venv/bin/python\0/x/mozaproxy.py\0--mode\0A\0",
            "102": b"/w/.venv/bin/python\0/w/tools/open-mozaproxy.py\0--\0game.exe\0",
            "103": b"/usr/bin/python3\0-W\0\0/x/mozaproxy.py\0",  # -W '' (empty value)
            "104": b"vim\0mozaproxy.py\0",
            "105": b"",                                             # kernel thread
            "7x": b"/x/.venv/bin/python\0/x/mozaproxy.py\0",        # not a pid
            "self": b"/x/.venv/bin/python\0/x/mozaproxy.py\0",
        }
        for pid, cmdline in procs.items():
            (tmp_path / pid).mkdir()
            (tmp_path / pid / "cmdline").write_bytes(cmdline)
        (tmp_path / "106" / "cmdline").mkdir(parents=True)        # unreadable
        assert sorted(mozactl.daemon_pids(str(tmp_path))) == [101, 103]


class TestDaemonParser:
    def test_help_renders(self, capsys):
        out = _help_exits_cleanly(mozaproxy.parse_args, ["--help"], capsys)
        assert "--button-codes" in out and "--buttons" in out
