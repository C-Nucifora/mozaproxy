#!/usr/bin/env python3
"""Open the native desktop app using this checkout's virtual environment."""

from pathlib import Path
import os
import sys


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    python = root / ".venv" / "bin" / "python"
    if not python.is_file():
        print(f"Mozaproxy is not installed. Run {root / 'install.sh'} first.", file=sys.stderr)
        raise SystemExit(1)
    os.chdir(root)
    os.execv(str(python), [str(python), "-m", "mozaproxy.desktop", *sys.argv[1:]])


if __name__ == "__main__":
    main()
