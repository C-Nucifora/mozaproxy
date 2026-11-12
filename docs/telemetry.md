# Telemetry lighting

Choose a game in **Pedals & controls → Calibration & telemetry**, match its UDP
port, then start preview. Preview sends no device commands. Enable wheel LED
output separately once the preview shows the correct RPM. Output remains off by
default. Nothing changes Steam launch options or installs into games automatically.

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
plugin send RPM, maximum RPM and running state only. They do not read or change
force feedback, controls or settings.

The bar lights from 50% to 100% of maximum RPM. This is a display scale, not a
verified ideal shift point. BeamNG uses your chosen scale, initially 8000 RPM;
change it when changing vehicles. OutGauge has no pause flag, maximum RPM or
working sequence counter. Its freshness check uses packet arrival, so repeated
packets cannot prove the simulation is advancing.

Stale data clears wheel LEDs after 0.5 seconds. Stop ends output and restores the
wheel's previous telemetry mode. See [hardware tools](hardware-tools.md) for
supported wheel controls and recovery after a failed restoration. System-service
mode supports preview only. The optional game-detection service selects profiles;
it does not start these telemetry readers or enable wheel output.

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
