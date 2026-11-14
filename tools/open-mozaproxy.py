#!/usr/bin/env python3
"""Open Mozaproxy, or launch a game with its saved settings."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args:
        from mozaproxy.protection import main as launch
    else:
        from mozaproxy.desktop import main as launch
    return launch(args)


if __name__ == '__main__':
    raise SystemExit(main())
