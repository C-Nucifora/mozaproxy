#!/usr/bin/env python3
"""Launch a direct-wheel game with Mozaproxy's saved menu-force protection."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mozaproxy.protection import main

if __name__ == '__main__':
    main()
