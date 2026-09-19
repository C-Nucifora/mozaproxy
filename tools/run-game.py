#!/usr/bin/env python3
"""Run the per-game isolation launcher from a source checkout."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mozaproxy.launch import main

if __name__ == '__main__':
    main()
