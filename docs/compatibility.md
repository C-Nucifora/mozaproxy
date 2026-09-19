# Compatibility tracking

Do not interpret an advertised capability, accepted effect upload, or successful
launch as proof of working physical force feedback.

The [Steam library test backlog](game-test-backlog.md) lists 26 additional
wheel-input targets, ten cached games requiring an access check, and six
secondary investigations. None are promoted to built-in support by that audit.

| Game | Steam app | Installed build at baseline | Launch/input/FFB status |
| --- | --- | --- | --- |
| Forza Horizon 5 | 1551360 | 21856128 | 2026-09-18 post-reboot attended driving passed: user confirms all controls, acceptable physical FFB and no freezing; compact R9 relay with physical-device isolation and T3 scanner mitigation |
| Farming Simulator 22 | 1248130 | 14439757 | Latest direct R25 launch reports FFB enabled after backed-up game.xml vibration flag correction. Physical rebinding, driving and FFB observation pending; device category UNKNOWN |
| Farming Simulator 25 | 2300320 | 25209229 | Direct R25 reached main menu and is classified as WHEEL; log reports FFB disabled. Driving and physical FFB pending |
| JDM: Japanese Drift Master | 1153410 | 25209638 | 2026-09-18 attended driving passed: user confirms controls, acceptable physical FFB and no freezing with direct physical HIDRAW, descriptor helper and T3 scanner mitigation; built-in routing pending |
| Assetto Corsa | 244210 | 14923034 | Content Manager detects physical R25 and saved paddles; on-track regression pending |
| Assetto Corsa Competizione | 805550 | 21257365 | Main menu reached; physical R25 constant-force and damper initialization succeed; on-track regression pending |

## BeamNG attended input result, 2026-09-19

User reports "wheel works in beamng fine as is" after the recovery comparison.
BeamNG 0.39.4.0.20972 ran with GE-Proton10-25 and empty Steam launch options.
Only its prefix has WineBus `Devices/346e/0000` `Hidraw=0`; physical R25,
no relay or descriptor helper. The game detected/acquired wheel0 and advertised
FFB. Physical FFB quality was not separately confirmed. Initial USB disappearance
has not recurred in this run, but its cause and repeat-launch reliability remain
unresolved. The kernel recorded 106 `output queue full` warnings between
09:02:22 and 09:06:04 during this session; investigate before marking FFB complete.
Evidence and registry backup: `~/.local/state/mozaproxy/game-tests/beamng-nohidraw-compare-20260919-085916/`.
This is a manual input pass; built-in routing remains unimplemented.

For each run, record Proton version, profile or direct input path, duplicate
device visibility, steering/pedal/button binding, uploaded effect types, runtime
errors, and the user's physical FFB observation. Check game exit and relaunch.
Keep backups of any game settings changed during validation.

## Latest attended JDM result and rollout policy, 2026-09-18

The user confirmed JDM has the same successful result as FH5: working controls,
acceptable physical FFB, and no freezing. This run used GE-Proton11-7, direct
physical R25 HIDRAW access, and `jdm_hid.so`. The relay was stopped. The actual
process environment and applied descriptor-workaround message were verified.
The T3 scanner exclusion remained active. This is a manual local setup pass;
the new system-service route has not been validated.

For rollout, games that have not been tested today and given built-in support
must default to the ordinary physical-wheel path. No automatic virtual identity,
HID descriptor changes, or custom FFB transformation should apply to unknown
or unvalidated games. Successful manual tests do not imply built-in routing.
The system service now preserves desktop physical access and starts with its
relay off. Starting a relay is an explicit action. It does not select game
routes automatically. Installed permissions and attended game tests remain
pending, so the revised service has not been activated.

## Latest attended FH5 result, 2026-09-18

After reboot, repeated Steam stalls continued with both physical and virtual
wheels absent. T3's preview port scanner was connecting to Steam's local
listeners. Excluding Steam from that scanner stopped the stalls for a measured
60 seconds; removing the exclusion brought 6–7 second stalls back. The user
confirmed smooth FH5 driving after the exclusion was restored.

The user then powered on the R25 and relaunched FH5. The existing compact R9
relay, named MOZA R9 Base with identity 346e:0002, forwarded physical event12 to
virtual event13 with 32 buttons and 10 FFB slots. Wine opened the virtual device;
the existing game wrapper isolated the physical interfaces. With Proton 11.0,
the user reported: "everything works and ffb is rather ok too". This follows an
explicit check of steering, pedals, paddles, force feedback, and smooth driving.
No new native Steam stall warnings appeared during the wheel test.

This is an attended driving pass for this configuration. Individual effect
families, long-session reliability, and the new system-service mode were not
validated. The active T3 mitigation is currently a session-specific lsof filter.
A private filter, a `t3-steam-safe` launcher, and a service PATH override are now
installed for future T3 starts, but no running T3 process has switched to them
yet. Use the new launcher for manual sessions; the background service will
pick up its override on its next restart. This is a local workaround, not an
upstream fix. Evidence and rollback details are under
`~/.local/state/mozaproxy/game-tests/post-reboot-20260918-222354/`.

The following remote-check entries predate this attended result.

## Current remote checks and LSFG baseline

The later JDM investigation is recorded in [jdm-ffb-debug.md](jdm-ffb-debug.md)
and `~/.local/state/mozaproxy/game-tests/jdm-freeze-return-20260918-171451/`.
Its 4096 physical HID calls all succeeded, with a maximum forwarded duration of
2.441 ms, during startup and about 19 seconds in a stationary garage. This does
not exclude stalls outside that window or establish physical force quality.
The virtual wheel accepted constant effects and repeated starts, but its current
bindings did not produce verified steering or pedal response. No moving-car
comparison was completed. The separate MangoHud capture covers startup and
menus only; its long frame intervals are not a controlled driving benchmark.
SaveGames and Config were restored byte-for-byte from the fresh pre-test backup.
Temporary capture, isolation and MangoHud launch options were removed. JDM is
left on direct physical input without the descriptor helper, with LSFG disabled.

The earlier remote run record is
`~/.local/state/mozaproxy/game-tests/remote-20260918/results.md`. These checks
establish launch and enumeration evidence, not completed driving tests.

- FH5 used Proton 11.0-2c, the compact R9 relay and game-specific physical-device
  isolation. Quiet logging was verified. The start screen rendered, but Start
  opened a black WebView window. The log reports Vulkan surface creation failure
  and msedgewebview2 activity. The freeze and physical FFB retest did not complete.
- FS22 used GE-Proton10-25 with the obsolete Logitech override removed. It
  enumerated the physical R25 with no virtual R9 present and reached General
  Settings. The log reports Force Feedback disabled, while the UI shows 50%.
  The R25 category is UNKNOWN, the installed MOZA profile matches only R5, and
  vehicle steering is bound only to the old virtual 346E:0002 wheel. There is
  no physical 346E:0000 vehicle-steering binding. No working physical FFB is
  established; changing category alone is not a proven fix.
- FS25 used GE-Proton10-25 and rendered its intro, then reached the main menu
  on a subsequent launch after shader preprocessing with LSFG disabled. Its current log classifies
  the physical R25 as WHEEL and reports Force Feedback disabled. No game settings
  or bindings changed. Its vehicle-steering bindings likewise omit physical
  346E:0000 and retain old virtual and other device IDs. GIANTS chooses the FFB
  device from the active steering binding. Testing stopped for the requested
  LSFG disable.

The user requested disabling LSFG. `DISABLE_LSFGVK=1` is now saved in
`~/.config/environment.d/90-disable-lsfg-vk.conf` and the `hl.env` configuration in
`~/.config/hypr/userprefs.lua`, and was applied to the compositor and user systemd
manager. Steam restarted with the flag. The layer remains installed; its old
configuration was neither migrated nor deleted. The original userprefs was backed up.

The subsequent JDM launch used GE-Proton11-7, build 25209638 and direct HID without
the descriptor helper. Steam and the game inherited the flag, the game process
had no `liblsfg` mapping, and its new log had no lsfg-vk errors. The saved-game
garage rendered; the overlay showed 127 FPS while stationary.
This verifies LSFG disable. It does not establish a freeze or FFB fix. Keep this
user-requested baseline for the next controlled comparison.

AC Content Manager detects the physical R25 and its saved paddle bindings. ACC
reached its main menu after clicking past a black intro. Its current game log
reports successful physical R25 constant-force and damper initialization. Both
used the original direct input path with the relay stopped. On-track regression
and physical force quality checks remain pending.

The user-authorized [virtual wheel harness](virtual-wheel-tests.md) now supports
scripted inputs and captures FFB without opening the physical motor. Kernel
lifecycle and all eight effect-family capture checks passed. These tests are
separate from game compatibility and the direct-hidraw path.

## Earlier launch setup and investigation

The following entries retain the investigation history. Their next-step language
describes the state at that point; the remote checks above are the current record.

Read from Steam on 2026-09-18. FH5 uses Proton 11.0; FS22, FS25, AC and ACC
use GE-Proton10-25; JDM uses GE-Proton10-34. FH5's launch options call
`~/.local/bin/mozactl`, whose script still points to a deleted checkout. Correct
that startup path before treating a failure to launch as a wheel compatibility
failure. The original launch options for all six games were saved locally in
`~/.local/state/mozaproxy/pre-game-test-launch-options.json`.

A newer, separate development checkout at `~/Documents/dev/mozaproxy` contains
uncommitted work and historical diagnostics. It has not been modified. Its
`handoff/HANDOFF.md` records previous FH5 success with an R9 virtual identity,
and JDM analog input reaching Proton but behaving as binary inside the game.
Its explanation involving 32-bit synthesized HID axes is historical evidence
to check against the current game/runtime, not a newly reproduced result.

The direct-device FH5 run crashed under Proton 11.0-2c. The log exposed the
physical `346e:0000` device via SDL. The fatal sequence is a controller property
request, `RoOriginateLanguageException 0x80004001`, then a C++ exception
`0xe06d7363`. This implicates the controller API path; the exact failing property
implementation has not yet been established. The log also contains Vulkan
surface errors, so do not attribute every logged error to the wheel.

The log was archived to
`~/.local/state/mozaproxy/game-tests/fh5-direct-20260918-075529.log` before another
run could overwrite it.

The next run uses compact mode named `MOZA R9 Base`, USB identity `346e:0002`,
plus `tools/run-game.py` to mask the physical wheel only inside the game's
bubblewrap namespace. A host-side probe verified the physical evdev node was
blocked in that namespace, the R9 virtual device remained visible, and the
host physical node was unchanged. The nested Steam/Proton launch subsequently
reached driving with working FFB. No permanent udev hiding rule was installed.

`~/.local/bin/mozaproxy-game` launches this checkout's isolation helper. It does
not start the relay itself; the relay must already be running for this test.
Relay output for the run is `/tmp/mozaproxy-fh5-relay.log`.

The user confirmed reaching the menu and began loading into driving. The current
Proton log creates only MOZA `346e:0002`, named `MOZA R9 Base`, rather than the
physical `346e:0000`. The relay accepted two periodic effects and one each of
constant, spring, and damper, with no logged errors. The game also set global
gain to 65535. Successful uploads establish the software path; driving feel and
input behavior still required user confirmation at that stage.

The user subsequently confirmed that the game seems to work and physical FFB
works while driving. They also reported frequent freezing. Individual pedals,
paddles, steering linearity, and every effect family have not been separately
confirmed. The relay has processed over 23,000 effect uploads/updates across the
four types without logged warnings or errors. Verbose Proton HID/DirectInput
tracing has produced over 272 MB of output, and relay debug logging records
each effect update. Logging overhead is a candidate to test, not an established
cause of the freezes. Shader compilation has not been established either.
The game exited normally and erased all five effects. The relay then shut down
normally with 31,169 uploads/updates and no logged errors. Final logs and JDM's
existing settings/saves were backed up under
`~/.local/state/mozaproxy/game-tests/jdm-preflight-20260917-220858/`.
The quiet-log FH5 retest remains pending; the user requested testing JDM next.

## JDM preflight

The FH5 relay is stopped. Historical tests motivate a direct HID test before
repeating virtual-device axis-range experiments. This will test the wheel's
native HID reports rather than Proton's synthesized reports; success is not
assumed. The current wheel node is `/dev/hidraw9`, verified against USB
`346e:0000`, and its ACL grants access only to root. `sudo -n` requires a password.
A temporary ACL granting only user `desktop user` read/write access is the next
required user action. No persistent udev rule or game setting has been changed
for this test. After verifying access, configure and launch JDM for the direct
HID test, then verify the actual Proton enumeration path and gradual input.

The user applied the temporary ACL. A nonblocking read/write open of
`/dev/hidraw9` now succeeds as `desktop user`; no HID reports were written by this
check. The node still identifies as the physical `346e:0000` R25. No relay or
JDM process is running. The planned short input-screen run uses
`PROTON_LOG=1 WINEDEBUG=-all,+hid PROTON_ENABLE_HIDRAW=0x346e/0x0000 %command%`
to capture the chosen HID backend. The FH5 isolation wrapper must not be used
for this direct-device test. Native HID enumeration and input behavior remain
unverified until the game runs.

### Direct HID result

GE-Proton10-34 created a hidraw `346e:0000` device and deferred the physical
evdev node to that backend. The user reports working steering and pedals after
configuration. Paddles are recognized when binding but do not shift in driving;
physical FFB is absent. Do not mark this game supported yet.

The game exited at Steam log time 08:30:33. Its 1.54 GB HID trace and current
saves were copied to
`~/.local/state/mozaproxy/game-tests/jdm-hidraw-20260917-223131/`.
The HID trace contains input processing but no logged output-report writes or
feature-report operations. This does not establish whether JDM attempted FFB
through DirectInput; that debug channel was disabled. Next capture should use
`WINEDEBUG=-all,+dinput` with the same HIDRAW override, for a short driving test.

Read-only inspection of `JDMSlot_S.sav` found a concrete binding mismatch in
`Custom 2`: ShiftUp button index 13 and ShiftDown index 12 are still under
`346e:0002`, device name `R25 (mozaproxy)`. The separate `346e:0000` device named
`MOZA R25 Ultra Base` contains the newly assigned steering/pedal actions but no
shift actions. Ask the user to clear/rebind those two actions to the physical
device and apply the profile. No save bytes were modified. Transmission mode
and FFB UI settings remain to be confirmed. Preserve the working HID input path
while investigating FFB separately.

### DirectInput diagnosis and next test

The user confirmed the paddle rebinding fixed shifting and only FFB remains
broken. The next DirectInput trace identifies a descriptor/collection-numbering
failure: `unexpected device_control.control_coll parent!`, `device control id 0`,
and similar mismatches for effect update, operation, and block-load collections.
The game calls GetCapabilities but never CreateEffect. Wine only sets
`DIDC_FORCEFEEDBACK` when the detected device-control report ID is nonzero.

The physical descriptor's vendor collection at HID index 2 is omitted from
Wine's exported collection enumeration. Subsequent exported indices are one
less than the real HID link indices used by PID parsing. A process-local
descriptor workaround is implemented in `compat/jdm_hid.c`; see
[build and test instructions](../compat/README.md). It relabels only that vendor
container and restores the vendor usage page before its report fields. It
matches the exact captured descriptor and leaves all report fields unchanged.
This preserves the direct HID input path and needs no new device permissions.

All 35 tests passed, including five descriptor checks and the kernel uinput
integration. A read-only physical ioctl probe, both directly and inside
SteamLinuxRuntime_sniper, returned the corrected 1,317-byte descriptor with
identical report fields. Review found no blocker to a controlled game test.
The helper is built at `~/.local/lib/mozaproxy/jdm_hid.so`; it is not globally
loaded. Its effect on actual game FFB remains unverified. On the next launch,
verify its applied-workaround message, nonzero PID control report IDs, effect
creation, and the user's physical FFB observation.

The preceding DirectInput log and working input bindings were archived under
`~/.local/state/mozaproxy/game-tests/jdm-dinput-20260917-224546/`.

### Descriptor helper game result

The helper was loaded in the game run. The collection warnings disappeared;
device-control report ID became 12 and effect-update ID became 1. JDM created
constant-force effects and issued thousands of parameter updates and starts.
The user nevertheless reports only occasional, incorrect physical feedback and
freezes similar to FH5. FFB is not validated and this is not a completed fix.

The trace reports `unknown angle unit caps 0` 6,028 times. The native direction
field already has a 0..36000 physical/logical range, so that warning alone is
not evidence of incorrectly scaled angles. Do not alter direction or gain
without observing actual reports. Direct HID output bypasses Linux evdev FFB
translation; additional report compatibility may be needed.

The JDM log reached approximately 75 MB and includes repeated vkd3d GPU-memory
allocation failures with fallback to system memory. Those messages also occur
in the earlier JDM run without this helper. The saved FH5 direct and proxy logs
do not contain the same messages. Thus neither one shared freeze cause nor
shader compilation is established. The game had exited by inspection, so the
idle GPU memory reading cannot establish in-game memory pressure.

Next compare the same JDM input/helper setup with `WINEDEBUG=-all`, preserving
`PROTON_LOG=1` for graphics diagnostics. Capture GPU usage during the next run;
do not change graphics, bindings, descriptor, or force parameters at the same
time. Preserve logs before launching. Raw PID output inspection remains the
next FFB-specific diagnostic if the problem persists in the quiet run.

The user reports continued freezing with `WINEDEBUG=-all`, verified in the
running JDM environment. A 15-second GPU/process sample is saved to
`/tmp/mozaproxy-jdm-performance.jsonl`. GPU memory stayed well below the 16 GB
capacity, yet the quiet log accumulated 125 allocation-fallback warnings during
observation. Those warnings therefore do not by themselves prove VRAM exhaustion
or the cause of freezing. Verbose tracing is not necessary for the symptom.
Next controlled comparison: remove only the LD_PRELOAD descriptor helper and
relaunch with quiet logging and the same HIDRAW override/bindings. This returns
to the known working input-only path and prevents DirectInput FFB detection.
Compare the same driving conditions before changing graphics or force encoding.

The user confirmed the freezes also occur with the helper removed. The running
process had no mozaproxy preload, and no relay was running. The supplied GPU
screenshot shows utilization dropping repeatedly while memory stays around
7 GB of 16 GB, rather than filling VRAM. No NVIDIA Xid or kernel OOM messages
were found in the checked interval. This establishes the descriptor helper is
not required for the freeze, but does not rule out all input/backend effects.
Frame generation is disabled in the saved INI. The user proposed changing from
GE-Proton10-34 to the installed Proton 11 next. Preserve quiet logging, direct
HID input, bindings, and graphics settings for that runtime comparison.

The next run actually used GE-Proton11-7, as confirmed by its log header, with
vkd3d-proton 3.1.0. The user reports identical freezing. The helper was absent,
verbose input tracing stayed off, and the log still contains allocation-fallback
warnings. This is not a successful performance fix. The game was closed by
inspection. Next isolate the remaining wheel input path by launching with the
wheel USB disconnected and testing keyboard driving. Do not change graphics
or Proton simultaneously. Disconnecting recreates hidraw nodes on reconnect,
so recheck the physical node identity and ACL before resuming wheel tests.

## Native desktop app

The installed `mozaproxy-app` now opens a native Qt 6 / PySide6 window with
Overview, Wheelbase, Pedals & controls, Profiles, Games and Diagnostics. It uses
the existing `AppState` directly through one worker and needs no HTTP server or
browser. Settings connection, hardware Apply and relay start are explicit actions.
Confirmed readbacks, saved profiles and drafts remain separate. The app reports
settings-owner conflicts and releases its connection on request.

The earlier game-first plan has been superseded by the delivered native app.
Game validation remains incomplete. Full Boxflat parity is not implemented, and
configuration writes still need attended physical validation.

## Hardware observations

See [baseline](rebuild-baseline.md) for measured axis/button mappings and direct
5% constant-force probes. The user confirmed movement in the stronger test.
The user also confirmed movement from the same two opposing pulses through the
rebuilt compact-profile relay. FH5 in-game FFB is now user-confirmed; individual
physical effect families have not been tested in isolation.

## References to verify during game tests

- [MOZA Farming Simulator setup](https://support.mozaracing.com/en/support/solutions/articles/70000677022-farming-simulator)
  describes FFB separately from its telemetry mod. Verify the game's actual
  effect requests under Proton before deciding it needs extra telemetry software.
- [PIDFF effect-update fix](https://github.com/JacKeTUs/universal-pidff/pull/125)
  addresses games updating different simultaneous effects, including Forza.
  The running kernel is 7.2.6. No driver replacement has been performed.
- [Wine's evdev backend](https://github.com/ValveSoftware/wine/blob/bleeding-edge/dlls/winebus.sys/bus_udev.c)
  is one input enumeration path. A udev tag or evdev grab alone is not proof
  that the physical device is hidden from every Proton backend.

## Native app validation and unattended work, 2026-09-18

[Qt validation](qt-validation.md) records the installed native Wayland launch,
all six pages at 1180 by 820 and 900 by 680, and live keyboard/mouse checks.
The normal Python suite ran 104 tests with 103 passes and one optional kernel
virtual-device skip. That optional test subsequently passed separately with
`MOZAPROXY_TEST_UINPUT=1`. Coverage includes nine desktop regressions and eight
controller tests, including invalid edits, profile overrides, per-field errors
and edits made during an in-flight Apply.

The 64-setting serial catalog returned 59 readings from the R25 Ultra. Live GUI
checks connected settings and saved, loaded and deleted a temporary 1080-degree
rotation profile. The confirmed hardware reading stayed at 900 degrees; Apply
was not invoked. Profile storage returned to its original empty state, and normal
close and relaunch completed. No motor tests ran and the relay stayed stopped
during native UI validation. Broader GUI tests, physical configuration writes
and the remaining driving checks are pending. These results do not establish
in-game FFB quality or complete Boxflat parity.

Offline JDM review ruled out swapping direction fields: Wine's HID parser and
Download reverse ordering cancel each other. Disabled-trigger encoding and
repeated effect-start timing remain candidates requiring outgoing HID data.
See [FFB investigation and next capture](jdm-ffb-debug.md). The existing descriptor
workaround remains unchanged. The no-wheel keyboard driving test to isolate
freezing has not yet been run; it needs the user back at the PC.

## Virtual game captures and remaining checks

FH5 and JDM were launched with the test harness in place of the physical relay.
In each running game namespace, physical event8 and hidraw9 were verified to
resolve to /dev/null while the virtual event13 remained an input device.
The harness never opened the physical wheel.

FH5 uploaded two periodic effects plus constant, spring and damper, then started
them. JDM initialized constant-force effects. These are game output captures,
not simulated uploads from the unit test. They do not prove driving feedback:
FH5 did not progress past Start and JDM locked its pointer at the window centre,
preventing reliable Hypruse menu navigation. Scripted buttons did not resolve
those navigation checks. Neither game completed a scripted driving sequence.

Installed FH5 Proton 11.0-2c has only the X11 driver and ignores the existing
PROTON_ENABLE_WAYLAND variable. A temporary WebView --disable-gpu test removed
the previously logged Vulkan-surface error but did not complete startup. The
argument reached CrBrowserMain and CrRendererMain. It was removed afterward.

MangoHud injection worked visually, but its named control socket was owned by
Proton's Xalia helper. Socket commands produced no valid frame-time CSV, even
though the later blacklist message excluded Xalia from drawing. No frame-time
or freeze-fix claim is supported. Future recording needs application-specific
configuration or a verified automatic start in the game process.

The temporary MangoHud/WebView launch flags and JDM isolation wrapper were
removed. The pre-harness FH5 quiet relay launch and JDM direct-HID launch were
restored. The requested persistent LSFG disable remains.

Content Manager automatically duplicated the physical R25 instance record and
moved bindings to the older entry during its launcher check. This was detected
by comparing controls.ini against the backup. The changed file was archived and
the original restored byte-for-byte. AC needs an attended input/FFB check and a
review of device-instance remapping; the launcher check alone is not a pass.
JDM also rewrote its binary save during testing; that copy was archived and the
pre-test save restored. Other sampled controller bindings remained unchanged.
