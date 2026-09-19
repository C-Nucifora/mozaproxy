#!/usr/bin/env bash
# Install the native desktop app for the current user.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_service=false
install_permissions=false
for argument in "$@"; do
    case "$argument" in
        --service) install_service=true ;;
        --permissions) install_permissions=true ;;
        -h|--help)
            echo "Usage: ./install.sh [--service] [--permissions]"
            echo "Creates a venv, mozaproxy-app launcher, and desktop application entry."
            echo "Optional relay service is installed but not started."
            echo "--permissions installs uinput and MOZA base hidraw access rules using sudo."
            exit 0 ;;
        *) echo "Unknown option: $argument" >&2; exit 2 ;;
    esac
done

cd "$project_dir"
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

./.venv/bin/python - "$project_dir" <<'PY'
import os
import pathlib
import shlex
import shutil
import sys
import time

root = pathlib.Path(sys.argv[1])
launcher = pathlib.Path.home() / '.local/bin/mozaproxy-app'
applications = pathlib.Path(os.environ.get('XDG_DATA_HOME') or pathlib.Path.home() / '.local/share') / 'applications'

def install_file(target, content, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.read_text() != content:
            backup = target.with_name(f'{target.name}.backup-{time.time_ns()}')
            shutil.copy2(target, backup, follow_symlinks=False)
            print(f'Previous file saved to {backup}')
            if target.is_symlink():
                target.unlink()
    target.write_text(content)
    target.chmod(mode)

def desktop_string(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

def desktop_argument(value):
    # Exec arguments have their own quoting, followed by desktop string escaping.
    value = str(value).replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return desktop_string('"' + value + '"')

command = f'exec {shlex.quote(str(root / ".venv/bin/python"))} {shlex.quote(str(root / "tools/open-desktop.py"))} "$@"'
install_file(launcher, '#!/bin/sh\n' + command + '\n', 0o755)
desktop = '\n'.join([
    '[Desktop Entry]',
    'Type=Application',
    'Name=Mozaproxy',
    'Comment=MOZA wheel settings and game compatibility',
    f'Exec={desktop_argument(launcher)}',
    f'Icon={desktop_string(root / "mozaproxy/webui/wheel.svg")}',
    'Terminal=false',
    'Categories=Settings;HardwareSettings;',
    'Keywords=MOZA;wheel;racing;force feedback;',
    'StartupNotify=true',
    '',
])
install_file(applications / 'mozaproxy.desktop', desktop, 0o644)
print(f'App launcher installed at {launcher}')
print(f'Desktop entry installed at {applications / "mozaproxy.desktop"}')
PY

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${XDG_DATA_HOME:-$HOME/.local/share}/applications"
fi

if "$install_permissions"; then
    sudo modprobe uinput
    sudo install -m 0644 udev/70-mozaproxy-access.rules /etc/udev/rules.d/70-mozaproxy-access.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=misc --sysname-match=uinput
    sudo udevadm trigger --action=change --subsystem-match=hidraw
    sudo udevadm settle
fi

if "$install_service"; then
    unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unit_dir"
    ./.venv/bin/python - "$project_dir" "$unit_dir/mozaproxy.service" <<'PY'
import pathlib
import shutil
import sys
import time

root, target = map(pathlib.Path, sys.argv[1:])
if target.exists():
    backup = target.with_name(f'{target.name}.backup-{time.time_ns()}')
    shutil.copy2(target, backup)
    print(f'Previous service saved to {backup}')
escaped = str(root).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
template = (root / 'systemd/mozaproxy.service').read_text()
target.write_text(template.replace('@CHECKOUT@', escaped))
PY
    systemctl --user daemon-reload
    echo "Service installed. Start manually with: systemctl --user start mozaproxy"
fi

echo "Ready. Inspect the wheel with: ./.venv/bin/python mozaproxy.py --diagnose"
echo "Open Mozaproxy from your desktop application menu."
echo "Or run: $HOME/.local/bin/mozaproxy-app"
echo "Run the compact profile with: ./.venv/bin/python mozaproxy.py --profile compact -v"
echo "Installation does not hide the physical wheel or enable the service."
if [[ -f /etc/udev/rules.d/99-mozaproxy.rules ]]; then
    echo "Legacy hiding rule detected: /etc/udev/rules.d/99-mozaproxy.rules"
    echo "See README.md for removal and restoration of direct wheel access."
fi
