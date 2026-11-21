#!/usr/bin/env bash
# Start ONE mozaproxy node in the foreground. Press Ctrl-C to stop it.
#
# Manual use (the systemd service is intentionally disabled): run this in a
# terminal before launching a game that needs the virtual wheel, and Ctrl-C it
# when you're done. The singleton guard refuses to start a second copy, so you
# can't accidentally stack duplicates.
#
#   ./run.sh          # normal
#   ./run.sh -v       # verbose (logs force-feedback traffic)
cd "$(dirname "$(readlink -f "$0")")"
exec .venv/bin/python mozaproxy.py "$@"
