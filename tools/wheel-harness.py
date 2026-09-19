#!/usr/bin/env python3
"""Run the isolated virtual-wheel test harness from a source checkout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mozaproxy.harness import main

if __name__ == '__main__':
    raise SystemExit(main())
