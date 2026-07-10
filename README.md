# mozaproxy

Present a MOZA wheelbase to games as a **clean virtual wheel**, so titles that
crash on the base's raw HID profile (notably **Forza Horizon 5** under Proton)
launch and run — with **force feedback intact**.

No root at runtime. Pure Linux input plumbing.

---

## The problem

Forza Horizon 5 crashes on startup whenever a MOZA base is connected. It launches
fine with the wheel unplugged, then the game dies during input enumeration.

Root cause, confirmed from the base's HID report descriptor and Proton crash logs:

- The MOZA base (via the `hid-universal-pidff` kernel driver) advertises a HID
  profile with **`Usage Max = 128` / `Report Count = 128` buttons** plus a large
  PID force-feedback block.
- FH5's input enumeration cannot digest this device. It crashes through **every**
  path Proton offers:
  - Default / DirectInput → `EXCEPTION_ACCESS_VIOLATION` in the 128-button enum.
  - `PROTON_PREFER_SDL=1` → routed to `Windows.Gaming.Input.Gamepad` (a Proton
    *semi-stub*) → `EXCEPTION_ILLEGAL_INSTRUCTION`.

So no Proton launch flag fixes it — the game simply can't handle what the wheel
advertises. MOZA's own fix on Windows is a firmware "Forza Horizon compatibility
mode" that slims the button profile, but that setting isn't reachable from Linux
(Boxflat can't set it).

## The fix

`mozaproxy` does on Linux what MOZA's compatibility mode does in firmware:

1. Opens and exclusively **grabs** the real MOZA evdev device.
2. Creates a **virtual joystick** (`uinput`) that mirrors the real axes and a
   small, game-friendly button count (default **24**), advertising the same
   force-feedback effects — i.e. the shape of a normal, supported wheel.
3. **Relays** events real → virtual, and force feedback (effect upload, erase,
   play/stop, gain, autocenter) virtual → real.

A udev rule clears `ID_INPUT_JOYSTICK` on the real node so games/SDL/Wine skip
it, while the daemon still opens it directly by path. Games see only the clean
virtual wheel.

```
   real MOZA base            mozaproxy daemon                games (Proton)
  128 buttons + PID  ──grab──▶  mirror axes/buttons  ──uinput──▶  clean 24-btn
     (hidden from             relay force feedback              wheel + FFB
      enumeration)         ◀──────────────────────────────────
```

## Requirements

- Linux with `uinput` (standard).
- Python 3.10+.
- A MOZA base already working on Linux (e.g. via the `hid-universal-pidff`
  driver and [Boxflat](https://github.com/lawstorant/boxflat)).

## Install

```bash
git clone https://github.com/C-Nucifora/mozaproxy.git ~/Documents/GitHub/mozaproxy
cd ~/Documents/GitHub/mozaproxy
./install.sh
```

The installer creates a venv, installs the udev rule, adds you to the `input`
group (fallback access), installs a `mozactl` launcher into `~/.local/bin`, and
installs a (disabled) **user** systemd service.

> **Important:** the udev rule *hides* the real base from games permanently, so
> the wheel is visible to games **only while the daemon runs**. Start it before
> playing, stop it when done. Replug the base (or reboot) once after install so
> the rule applies.

## Verify

```bash
mozactl doctor     # base powered on? driver bound? real node hidden? group ok?
mozactl start      # bring up the clean virtual wheel
mozactl status     # expect: Base OK, Daemon running, Virtual wheel present -> "Ready."

# force-feedback relay (the wheel should pull for ~1.5s):
./.venv/bin/python tools/ffbtest.py
```

(If `~/.local/bin` isn't on your PATH, use `./.venv/bin/python mozactl.py ...`.)

Then launch Forza with the wheel connected. Plain launch options are enough:

```
PROTON_DLSS_UPGRADE=1 ENABLE_HDR_WSI=1 PROTON_ENABLE_WAYLAND=1 PROTON_ENABLE_HDR=1 %command%
```

In the game, bind to the **"MOZA R25 (mozaproxy)"** device.

## Modes (per-game faces)

The same wheel can wear different faces so whatever input backend a game uses
digests it correctly. Pick one with `--mode` (`mozactl modes` lists them):

| Mode | Selector | Presents as | Use when |
|------|----------|-------------|----------|
| **A** | `A` / `wheel` | Passthrough wheel (default) | Sim titles; fixes the FH5 enumeration crash |
| **C** | `C` / `normalized` | Wheel with consistent **signed** axes | A game reads axes as **binary 0%/100%** — the base's steering is unsigned `0..65535` while pedals are signed, and C rescales everything to one convention |
| **B** | `B` / `gamepad` | **Xbox 360 / XInput** pad (steering→stick, throttle→RT, brake→LT) | Controller-only / arcade titles, or when even C reads binary |

**Triage a broken game: try `A`, then `C`, then `B`.**

```bash
mozactl start --mode C            # normalized wheel (binary-axis fix)
mozactl start --mode C --deadzone 0.03
mozactl start --mode B            # XInput gamepad
```

> Gamepad mode's throttle/brake/clutch source axes are best-guess defaults
> (`throttle=ABS_Z`, `brake=ABS_RZ`) until calibration lands — if a pedal is on
> the wrong trigger, that's the knob to adjust. A `mozactl calibrate` helper is
> planned (Phase 3, see [`docs/SPEC.md`](docs/SPEC.md)).

## Usage / tuning

Everyday use is via `mozactl`:

```bash
mozactl start                 # start the virtual wheel (Mode A, default)
mozactl start --mode C        # start in a specific mode
mozactl modes                 # list modes
mozactl status                # health of the whole pipeline
mozactl stop                  # hide the wheel again
```

Or run the daemon directly (foreground, Ctrl-C to stop):

```bash
./run.sh -v                   # foreground, debug logging (traces FFB)
./.venv/bin/python mozaproxy.py --buttons 32
```

Useful flags:

| flag | default | meaning |
|------|---------|---------|
| `--buttons N` | 24 | number of buttons to expose |
| `--name STR` | `MOZA R25 (mozaproxy)` | virtual device name |
| `--vendor` / `--product` | `0x346e` / `0x0002` | virtual USB ids |
| `--once` | off | don't supervise/re-attach; exit when device leaves |

## How it hides the real device

The daemon does **not** depend on udev tags — it opens the base by path and
grabs it. The udev rule only changes what *other* programs see: it clears
`ID_INPUT_JOYSTICK` on the real event node (so input enumerators skip it) and
blocks the legacy `jsN` node. Access for the daemon is preserved via `uaccess`
(already applied by seat rules) plus `GROUP=input`.

Because the rule hides the real node permanently, the wheel is available to games
**only while the daemon runs**. Start it with `mozactl start` before playing and
`mozactl stop` when done (a disabled systemd unit is also installed if you prefer
always-on: `systemctl --user enable --now mozaproxy`). Boxflat still configures
the base normally (it talks over the serial channel, not this joystick node).

If your distro's Proton build still finds the real device after the tag strip,
the stronger fallback is to have the daemon-owner lock the node (root chmod);
open an issue and it can be added as an opt-in `--hide-mode` (see TODO).

## Status

Built and verified: device creation, grab, event mirroring, and the full
force-feedback relay path (upload/play/erase to the real base), plus the
`mozactl` status/doctor/start/stop tooling. In-game validation with Forza
Horizon 5 is the remaining confirmation.

The broader roadmap — a general per-game compatibility layer with selectable
modes (wheel / gamepad-XInput / normalized) and a Steam-launch-option launcher
that fixes the *binary-axis* and *controller-only* game classes, not just the FH5
crash — is specced in [`docs/SPEC.md`](docs/SPEC.md).

## License

MIT — see [LICENSE](LICENSE).
