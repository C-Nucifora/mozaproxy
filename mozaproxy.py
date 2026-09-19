#!/usr/bin/env python3
"""Compatibility entry point; implementation lives in the mozaproxy package."""

from mozaproxy.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
