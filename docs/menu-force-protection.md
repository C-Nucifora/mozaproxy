# Menu force protection

Intended for games whose menus cause a constant force-feedback pull.

This optional setting expires streamed constant force after a configurable timeout without an
update. The default is 100 ms; the allowed range is 50–1000 ms. New updates renew an effect only after the game has started it. Stop
and erase commands prevent renewal. It does not change wheel bindings or
hardware settings and is separate from hands-off protection.

The setting is off by default. In Mozaproxy, open **Overview → Wheel protection**
and enable **Menu force protection**. Set **Force timeout** beside it.
Increase the timeout if force drops during driving; a longer timeout also lets
stale menu force persist longer. The desktop and web app share the saved
setting in `$XDG_CONFIG_HOME/mozaproxy/protection.json`, or
`~/.config/mozaproxy/protection.json`. Changes take effect on the next game or
relay start. They do not mute a running game or start the relay.

## Direct games, including ACC and LMU

Run `./install.sh` to install the app, `mozaproxy-protect` launcher and native
helper. Building the helper requires a C compiler. A missing helper stops a
protected launch with an error instead of launching unprotected.

Use this in ACC's Steam launch options, replacing the home path as appropriate:

```text
/home/christian/.local/bin/mozaproxy-protect -- %command%
```

LMU on this workstation also uses these existing flags:

```text
PROTON_USE_EAC_LINUX=1 PROTON_ENABLE_WAYLAND=1 /home/christian/.local/bin/mozaproxy-protect -- %command%
```

The local app's Games page provides ACC and LMU launch suggestions. The Overview page
provides a generic copyable command. Preserve existing game flags when adding
the launcher. Other compatible games can use the same launcher; they are not
protected automatically merely because the app is open.

The launcher reads the toggle on each start, preserving unrelated environment
variables and preload libraries. It removes its own legacy `lmu_ffb_guard.so`
entry when migrating an existing launch. Remove the old explicit preload and
verbose debugging options from Steam once the new launcher is configured.

One-launch overrides, independent of the saved preference:

```sh
mozaproxy-protect --menu-force-protection --menu-force-timeout-ms 100 -- game-command
mozaproxy-protect --no-menu-force-protection -- game-command
```

Only the physical R25 evdev path is supported by the native helper. Do not use
this route with native HIDRAW force feedback. The launcher rejects explicit
`PROTON_ENABLE_HIDRAW` enablement rather than implying it protects that path.
Keep the relay stopped for direct ACC and LMU use.

## Relay

Relay sessions use the same expiry behavior in Python, without preloading a
library into the service. The desktop and web controls pass the saved toggle
when starting a relay. In system-service mode, the client passes only a boolean and bounded timeout;
the service retains its fixed virtual-wheel identity.

The command-line relay follows the saved preference, with explicit overrides:

```sh
.venv/bin/python -m mozaproxy --menu-force-protection --menu-force-timeout-ms 100
.venv/bin/python -m mozaproxy --no-menu-force-protection
```

Restart an existing relay to change its protection setting. A system service
must be updated to support the new option; older services reject it.

## Limits and validation

This is not a torque limiter or an emergency stop. The last force can remain
for up to the configured timeout after the last update, subject to kernel, driver and firmware
behavior. Long game stalls can interrupt constant force. Finite effects,
delayed or triggered effects, envelopes and other effect types are unchanged.
The workaround currently targets the Gudsen MOZA R25 Ultra Base, USB
`346e:0000`; other wheel models are not validated or covered.

The native helper expects Wine to upload, play and erase through the same
file descriptor below 4096. Aliases, signal-handler reentrancy and replacement
with another open of the same device without `close()` are not supported.
The [GE-Proton11-12 backend](https://github.com/ValveSoftware/wine/blob/fda79a585939fb7512dc220a11249f9ffe825fcf/dlls/winebus.sys/bus_udev.c)
uses one stored descriptor for those operations.

Software checks cover bounded uploads, playback renewal, stopped effects,
finite-effect passthrough, device selection, descriptor reuse and process
startup. The earlier LMU log confirms a bounded upload reached its running
backend. Physical driving, pause and resume behavior still needs an attended
low-torque check in LMU and ACC. ACC's root cause has not been traced separately.
