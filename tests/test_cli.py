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


class TestDaemonParser:
    def test_help_renders(self, capsys):
        out = _help_exits_cleanly(mozaproxy.parse_args, ["--help"], capsys)
        assert "--button-codes" in out and "--buttons" in out
