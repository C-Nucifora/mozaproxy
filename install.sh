#!/usr/bin/env bash
# mozaproxy installer: venv + udev rule + user systemd service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "==> Creating Python venv and installing deps"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

echo "==> Installing udev rule (needs sudo)"
sudo install -m 0644 udev/99-mozaproxy.rules /etc/udev/rules.d/99-mozaproxy.rules
sudo udevadm control --reload-rules

echo "==> Ensuring you are in the 'input' group (fallback access; needs sudo)"
if ! id -nG "$USER" | grep -qw input; then
    sudo usermod -aG input "$USER"
    echo "    Added $USER to 'input'. Log out/in (or reboot) for it to take effect."
fi

echo "==> Installing user systemd service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
sed -e "s#%h/Documents/GitHub/mozaproxy#$REPO_DIR#g" \
    systemd/mozaproxy.service > "$UNIT_DIR/mozaproxy.service"
systemctl --user daemon-reload

echo "==> Re-triggering udev so the running base picks up the new rule"
sudo udevadm trigger --subsystem-match=input --attr-match=idVendor=346e || true

cat <<EOF

Done. Next steps:
  1. Replug the MOZA base (or reboot) so the udev rule applies cleanly.
  2. Start the proxy:   systemctl --user enable --now mozaproxy
  3. Verify:            ./.venv/bin/python tools/ffbtest.py   (wheel should pull)
  4. Launch Forza with the wheel. Clean launch options are enough:
        PROTON_DLSS_UPGRADE=1 ENABLE_HDR_WSI=1 PROTON_ENABLE_WAYLAND=1 PROTON_ENABLE_HDR=1 %command%

To watch logs:   journalctl --user -u mozaproxy -f
To stop:         systemctl --user disable --now mozaproxy
EOF
