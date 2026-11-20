# Telemetry lighting

Choose a game in **Pedals & controls → Calibration & telemetry**, match its UDP
port, then start preview. Preview sends no device commands. Enable wheel LED
output separately once the preview shows the correct RPM. Output remains off by
default. Managed LMU lighting is a separate saved opt-in described below.

| Game | Feed | Setup |
| --- | --- | --- |
| LMU | Read-only `LMU_Data` mapping | Windows helper built against the installed game's SDK |
| ACC | `acpmf` shared memory | Windows helper in ACC's Proton context |
| AC | `acpmf` shared memory | Windows helper in AC's Proton context |
| BeamNG.drive | OutGauge UDP, 92 or 96 bytes | Enable OutGauge and set the RPM scale for the current vehicle |
| ETS2 | SCS telemetry SDK | Install the matching Windows or Linux plugin with the game closed |
| FH5 | 324-byte Dash Data Out | Enable Data Out in the game |

All feeds target `127.0.0.1`, default port **20777**. Only one listener can own a
port. Select the matching source; packets for another game are rejected. The
first sender owns the stream until it goes stale. The shared-memory readers and
plugin publish display telemetry. They do not change force feedback, controls
or game settings. LMU can also report supported flag and activity alerts.

The bar defaults to 50% through 100% of maximum RPM. The saved managed-lighting
percentages can change its start and end. This is a display scale, not a
verified ideal shift point. BeamNG uses your chosen scale, initially 8000 RPM;
change it when changing vehicles. OutGauge has no pause flag, maximum RPM or
working sequence counter. Its freshness check uses packet arrival, so repeated
packets cannot prove the simulation is advancing.

Stale data clears wheel LEDs after 0.5 seconds. Stop ends output and restores the
wheel's previous telemetry mode. See [hardware tools](hardware-tools.md) for
supported wheel controls and recovery after a failed restoration. System-service
mode supports preview only. The optional game-detection service selects profiles;
it does not start these telemetry readers or enable wheel output.

## Managed LMU lighting

`install.sh` installs `mozaproxy-lighting.service` for the current user without
enabling or starting it. Saved settings live in
`~/.config/mozaproxy/lighting.json`, or the equivalent `XDG_CONFIG_HOME` directory.
All lighting toggles default to off. The fixed Steam launch line remains:

```text
mozaproxy -- %command%
```

When the saved lighting toggle is on, the launcher asks the host user-service
manager to start the watcher. A lighting failure never prevents game startup.
The watcher stays available for later launches and rereads saved settings each
second. Turning the toggle off stops output and releases the wheel connection.
To start the watcher for an already running game, use:

```sh
systemctl --user start mozaproxy-lighting.service
```

Managed startup currently supports LMU only. Other games and ambiguous game
sessions are skipped. It requires `protontricks-launch` on the user service's PATH
and the current LMU helper at
`~/.local/lib/mozaproxy/telemetry/mozaproxy-shared-memory.exe`. Build it against the
installed game's SDK, then copy the executable there. The watcher starts the
reader in LMU's Proton context and waits up to three minutes for valid telemetry
before taking the exclusive wheel settings connection. Enter a driving session
within that window. If another app owns the serial connection or UDP port, status
reports the conflict. Close that connection, then toggle lighting off and on to
retry. The watcher never applies profiles or force-feedback settings.

Wheel RPM output, optional base alerts, and optional activity alerts use the
supported telemetry fields. The saved RPM start/end percentages are fractions of
the game's reported maximum RPM, not a verified per-car shift recommendation.
ACC and other game alert support is not enabled by this watcher.

On game exit or disable, the watcher stops output and restores previous lighting
modes. If the wheel disconnects first, the running watcher remembers the previous
mode and restores it when the next managed session reconnects. Until then, the
wheel may remain in external telemetry mode. The helper receives a private
heartbeat-file argument and exits when the
file disappears or has not been updated for ten seconds. This also handles a
watcher crash. The service terminates only its own launcher process; it never
stops Wine's shared server or signals the game's process group. Older helper
builds do not support this lease argument and must be rebuilt. Inspect status in
the app or `journalctl --user -u mozaproxy-lighting.service` when startup fails.

## Build the optional helpers

Use an x64 MinGW C++ compiler, or Zig with its Windows target. The script compiles
locally and installs nothing. It does not download dependencies or SDKs.

```sh
python tools/telemetry/build.py \
  --lmu-sdk '/path/to/Le Mans Ultimate/Support/SharedMemoryInterface' \
  --scs-sdk '/path/to/scs-sdk/include'
```

For Zig, add `--windows-cxx 'zig c++ -target x86_64-windows-gnu'`.
The default output is `build/telemetry`. Omit `--lmu-sdk` to build an ACC/AC reader
without LMU support. Omit `--scs-sdk` to skip ETS2 plugins. Linux ETS2 also needs a
native C++ compiler, configurable through `--linux-cxx`. SDK headers are not
redistributed. Get the [SCS SDK from its official page](https://modding.scssoft.com/wiki/Documentation/Engine/SDK/Telemetry).
Rebuild LMU's reader against the current installed SDK after game updates.

## LMU and ACC first, then AC

Start the game and enter a session so its mappings exist. In another terminal,
run one matching command from the repository root:

```sh
protontricks-launch --appid 2399420 "$PWD/build/telemetry/mozaproxy-shared-memory.exe" lmu 20777
protontricks-launch --appid 805550 "$PWD/build/telemetry/mozaproxy-shared-memory.exe" acc 20777
protontricks-launch --appid 244210 "$PWD/build/telemetry/mozaproxy-shared-memory.exe" ac 20777
```

[Protontricks](https://github.com/Matoking/protontricks) runs the executable in the
selected game's prefix. It must also match the running game's Proton/runtime
context. A missing mapping is an error, not permission to open another prefix.
If custom runtime/container isolation prevents access, stop the helper and resolve
that context before retrying. No Steam launch-option change is required.

Keep the helper terminal open and stop it with Ctrl+C when finished. Stopping the
UI listener does not terminate a separately launched helper. Restart the helper
after restarting the game. It opens mappings read-only and never acquires or
writes LMU's game-thread lock. It samples the small RPM fields and rechecks them;
this is best-effort display sampling, not an atomic simulation snapshot.

## BeamNG and FH5

In BeamNG, enable **Options → Other → Protocols → OutGauge UDP protocol** and
set address `127.0.0.1` and the listener port. Select BeamNG and set its RPM scale.
The format and constant timestamp are documented in the
[BeamNG protocol reference](https://documentation.beamng.com/modding/protocols/).

In FH5, enable Data Out and use the same address and port. Select FH5. If a game
restart resets its timestamp while retaining the sender port, restart preview.

## ETS2

Close ETS2 before installing. Copy only `mozaproxy-ets2.dll` to
`Euro Truck Simulator 2/bin/win_x64/plugins/` for Proton, or
`mozaproxy-ets2.so` to `bin/linux_x64/plugins/` for native Linux. Create the
`plugins` directory if needed. Keep other installed plugins. The next game
launch loads the plugin; accept the game's SDK notice if shown. The plugin
publishes to loopback port 20777 without launch options. An optional
`MOZAPROXY_TELEMETRY_PORT` environment value overrides that port at game startup.

Select ETS2 in Mozaproxy and start preview. The plugin waits for the truck's
reported RPM limit and engine RPM. It uses the game's paused/started events and
sends at most 20 packets per second. Remove only this plugin file, with the game
closed, to uninstall it.

## Validation status

Parsers and helpers have offline checks. Compilation and synthetic telemetry do
not establish live Proton shared-memory access or physical wheel compatibility.
Attended checks remain necessary for each game: RPM matches the car, pause/exit
clears LEDs, resuming restores the display, and Stop restores the wheel mode.
No helper has been installed into the user's games as part of this change.

## R25 base alerts and shift timing

The two base strips show flashing yellow/blue, one second of green after a known
caution clears, cyan pulsing for the engaged limiter, and optional brief amber
for ABS/TC intervention. Yellow/blue take priority over green, limiter and activity.
Unknown flags cannot trigger a green transition. Player caution fields do not
establish complete local-yellow coverage. Stale data and pause release the strips
to their stored idle effect, which may itself flash or breathe.

The driver requires a probed R25 model, brightness reply and indicator state1.
It does not change stored idle modes, brightness, palettes or force settings.
Base setup errors are shown separately and leave RPM output running. The protocol
uses two nine-light strips, unpadded 5+4 color chunks and little-endian masks.
Wire framing doubles body/checksum 0x7e bytes and includes stuffing in the checksum.
Facts were checked against [AZOM capture documentation](https://github.com/giantorth/AZOM/blob/6f820a8dd373d51764600b42e5c922204f663743/docs/protocol/leds/base-ambient-0x20-0x22.md).

The installed LMU SDK defines `mEngineMaxRPM` as the rev limit. It does not expose
optimal shift RPM, per-gear shift targets or individual dashboard LED thresholds.
The configurable percentages are an approximation, not a copy of the car's dash.
LMU alert bits use ID-matched player scoring and separate freshness checks. Updated
helpers need the updated parser; old RPM-only packets remain accepted.

On this workstation the R25 capability probe succeeded and the user confirmed
physical wheel RPM output and base alerts. Yellow/green and optional ABS/TC
effects were not individually verified. Firmware reports the RS V2 as `RS Leather # W00`.
Only its ten button LEDs are physical; higher RGB slots are not additional lights.
Function-colour grouping still needs a verified button-to-light assignment.
