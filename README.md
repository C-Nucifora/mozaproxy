# mozaproxy

A native Qt 6 Linux desktop app for MOZA wheel settings, live input monitoring,
and game compatibility. Its optional relay exposes a virtual wheel through uinput and
forwards effects to the kernel's existing wheel driver.

The Qt rebuild is in hardware validation. Attended September 2026 tests confirmed
FH5 and JDM driving, controls and physical force feedback with specific manual
compatibility setups. Other game tests and integrated game routing remain
incomplete. These observations do not establish support for every wheel, firmware
or Proton version. See the [compatibility matrix](docs/compatibility.md).

## Desktop app

```bash
./install.sh
~/.local/bin/mozaproxy-app
```

You can also open **Mozaproxy** from your desktop application menu. The installer
creates the virtual environment, installs PySide6, and adds the launcher and
desktop entry for your user. Keep this checkout in place, or rerun the installer
after moving it. No browser or local HTTP server is needed.

The app follows your native Qt colour scheme, fonts and icons, including live
palette updates through qt6ct. See [desktop themes](docs/desktop-themes.md) if
your distribution's Qt theme plugin and the bundled PySide6 use different versions.

To launch directly from the checkout:

```bash
./.venv/bin/python -m mozaproxy.desktop
# The helper also selects this checkout's virtual environment:
python3 tools/open-desktop.py
```

The app monitors inputs without grabbing the wheel.
Connect settings explicitly to read the base, effects, equalizer, curves, pedals,
and wheel controls. Unsupported settings remain unavailable. Connecting only
reads settings; Apply writes your changes and checks the device's readback.
The app takes exclusive serial ownership and reports competing processes such
as Boxflat. Disconnect settings before opening another settings app.

Profiles are saved locally under `~/.config/mozaproxy/profiles.json`, respecting
`XDG_CONFIG_HOME`. Selecting a profile does not write it to hardware. Game pages
show test status and launch options; they do not modify Steam configuration.
The relay starts only when requested and the app stops only its own child.
`--data-dir` selects a different directory for the profile store.

This is not yet full Boxflat parity. Guided calibration, individual LED colors,
telemetry lighting, firmware management, and automatic game switching are not
implemented. Settings writes still need attended hardware validation.

The earlier web interface remains available for development with
`./.venv/bin/python -m mozaproxy.web`, then `http://127.0.0.1:8765`.
It is optional. Its `--port` option changes the localhost port, and changes
require a same-origin session token. Close its settings connection before
connecting from the desktop app.

## What works so far

- R25 Ultra discovery and passive steering, pedal, paddle, and button capture.
- Direct physical constant force, confirmed by the user at 5% effect level.
- Unit tests for mapping, input resynchronization, effect ownership, error
  propagation, and partial initialization cleanup.
- Kernel integration with two virtual devices: input, effect upload/update,
  repeat/stop, gain, erase, and cleanup when the client closes.

The relay copies supported effect parameters without synthesizing road feel.
Constant, ramp, periodic, condition, and rumble effects depend on what the
physical driver advertises and what the game sends. Custom sampled waveforms
are excluded because they contain pointers into the sending process. Physical
validation of effect families beyond constant force is still pending.

## Run from source

Requires Linux and Python 3.10+. The installer supplies PySide6, python-evdev,
and pyserial in the checkout's virtual environment. Wheel monitoring needs
access to the wheel's evdev node. The relay also needs a working kernel FFB
driver and read/write access to `/dev/uinput`. Settings use the base's serial
device and require access to that device.

```bash
./install.sh
./.venv/bin/python mozaproxy.py --diagnose --profile compact
./.venv/bin/python mozaproxy.py --profile compact -v
```

Stop with Ctrl+C. The daemon stops and erases effects it owns, destroys the
virtual device, and releases the physical wheel. Reconnects create a fresh
session. A failed exclusive grab prevents startup.

## Profiles

| Profile | Behavior |
| --- | --- |
| `native`, default | Preserve physical axes and all source button codes |
| `compact` | Preserve axes; select up to 32 real buttons and remap to joystick button codes |

Compact selection prioritizes the R25 controls measured during development.
All 20 buttons exercised on that wheel are included. It avoids using gamepad
button codes for extra wheel controls. Other rims may need a different selection;
`--diagnose --profile compact` prints the mapping and excluded controls.

`--buttons N` changes the cap, up to 128 for native or 56 for compact. `--device`
selects a particular physical wheel, preferably by its `/dev/input/by-id/` path.
`--vendor-real`, `--product-real`, and `--name-hint` narrow discovery. Name matching
never overrides USB identity. `--once` exits on a missing wheel or session failure.

The legacy virtual name and IDs remain configurable through `--name`, `--vendor`,
and `--product`. Defaults are `MOZA R25 (mozaproxy)` and `346e:0002`. These are a
virtual compatibility identity, not proof that a game supports the device.

## Physical FFB test

Choose the exact physical or virtual evdev node. Preview is the default:

```bash
./.venv/bin/python tools/ffbtest.py --device /dev/input/event13
# When ready, with the wheel clear:
./.venv/bin/python tools/ffbtest.py --device /dev/input/event13 --play
```

The test sends two opposing 250 ms pulses at 2% effect level, three seconds apart.
`--strength 0.05 --duration 350` reproduces the successful direct-device probe.
Strength is capped at 10% and duration at 1000 ms. Actual torque also depends on
wheel settings. The test does not change global gain and stops/erases its effects
on normal completion or interruption. Event numbers can change after reconnect.

## Installation and physical-device visibility

`./install.sh` creates a local venv, `~/.local/bin/mozaproxy-app`, and
`~/.local/share/applications/mozaproxy.desktop`, respecting `XDG_DATA_HOME` for
the desktop entry. It backs up launcher files before replacing changed content.
If `~/.local/bin` is on your `PATH`, you can launch with `mozaproxy-app`.

`--service` also installs a user systemd unit for the optional relay, backing up
a previous unit; it does not enable or start it. `--permissions` uses
sudo to install active-seat access rules for uinput and the MOZA base's raw-HID
interface (`346e:0000`). The latter preserves direct-HID game access after a
power cycle or reconnect. Other hardware permissions depend on the driver setup.

The default local installation **does not hide the physical wheel globally**. An evdev grab blocks
other evdev readers but does not stop every game from enumerating the device.
Per-game hiding and identity workarounds require testing against that game's
Proton input backend. Installing the tool does not alter game configurations.

An optional [system wheel service](docs/system-service.md) reserves physical
device access for a dedicated account and lets the Qt app control the relay
over a local socket. It requires separate installation and activation. Real
game compatibility and physical FFB still need validation in this mode.

An experimental per-game isolation helper is available for validation:

```bash
# Start the relay separately, then wrap the game's command:
./.venv/bin/python tools/run-game.py -- GAME_COMMAND ARGUMENTS
```

This requires `bubblewrap`. It masks the physical R25's evdev, legacy joystick,
hidraw, and raw USB nodes only in the child namespace. The host retains access
and the virtual wheel remains visible. This is device isolation, not a security
sandbox. Steam/Proton game validation is in progress; the helper does not manage
the relay or preserve isolation for devices reconnected after the game launches.

For direct AC/ACC operation, stop the proxy before launching the game. This
preserves the pre-existing input path; regression tests are still required.

Older installations may have `/etc/udev/rules.d/99-mozaproxy.rules`, which hides
the physical wheel even when the proxy is stopped. After checking that it is the
old mozaproxy rule, move it out of `/etc/udev/rules.d/`, reload udev rules with
`sudo udevadm control --reload-rules`, and reconnect the wheel. This rebuild does
not install that rule or silently remove an existing one.

## Development checks

```bash
python -m unittest discover -s tests -v
MOZAPROXY_TEST_UINPUT=1 timeout 40s python -m unittest discover -s tests -p test_uinput.py -v
```

The second command requires uinput access. It creates only virtual devices and
does not open the physical wheel. Its simulated driver and relay run in separate
processes because python-evdev's blocking effect ioctls hold Python's GIL.

The [virtual wheel harness](docs/virtual-wheel-tests.md) supports unattended
game checks with scripted steering, pedals and buttons, plus timestamped FFB
capture. It creates a separate compact R9 device and never opens the physical
wheel. Run `python tools/wheel-harness.py --help` for commands and limits.

## Licence and protocol references

The project code is MIT-licensed. See [LICENSE](LICENSE).
The bundled Adwaita Sans font is separately licensed under SIL OFL 1.1; its
copyright notices and licence are in [fonts/LICENSE.txt](mozaproxy/webui/fonts/LICENSE.txt).

The MOZA settings catalogue uses protocol addresses and conversions documented
by [Boxflat](https://github.com/Lawstorant/boxflat). It does not import Boxflat at
runtime. See [hardware settings](docs/hardware-settings.md) for the source
reference and implementation details. Vendor game libraries are not bundled.
