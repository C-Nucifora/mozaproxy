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

echo "==> Installing 'mozactl' launcher into ~/.local/bin"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/mozactl" <<EOF
#!/usr/bin/env bash
exec "$REPO_DIR/.venv/bin/python" "$REPO_DIR/mozactl.py" "\$@"
EOF
chmod +x "$BIN_DIR/mozactl"
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
    echo "    NOTE: $BIN_DIR is not on your PATH; add it, or run '$REPO_DIR/.venv/bin/python mozactl.py'."
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

Done. Because the udev rule HIDES the real base from games, the wheel exists for
games ONLY while the daemon runs. Manual, per-session workflow:

  1. Replug the MOZA base (or reboot) so the udev rule applies cleanly.
  2. Power the wheelbase on, then check setup:  mozactl doctor
  3. Start the clean virtual wheel:             mozactl start
  4. Confirm it is up:                          mozactl status
  5. Launch Forza with the wheel. Clean launch options are enough:
        PROTON_DLSS_UPGRADE=1 ENABLE_HDR_WSI=1 PROTON_ENABLE_WAYLAND=1 PROTON_ENABLE_HDR=1 %command%
     Bind in-game to the "MOZA R25 (mozaproxy)" device.
  6. When done:                                 mozactl stop

FFB smoke test:  ./.venv/bin/python tools/ffbtest.py   (wheel should pull)
EOF
