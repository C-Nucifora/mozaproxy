#!/usr/bin/env python3
"""Run the bounded FFB probe from a source checkout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mozaproxy.probe import main

if __name__ == '__main__':
    raise SystemExit(main())
