# Heat wheel compatibility experiment

2026-09-19. Manual test, not validated built-in game support.

The physical R25 and an identity-only G29 relay both failed the user's Heat
wheel-recognition check. A read-only probe using GE-Proton11-7 in Heat's prefix
confirmed the virtual G29 as DirectInput driving/limited, with eight axes,
24 buttons, one POV and FFB capability. All XInput slots were disconnected.
Thus Xbox emulation was not observed. The initial probe through Proton's
steam.exe wrapper timed out; direct execution with the same Wine build worked.

The next explicit CLI profile is `--profile g920`. It selects Logitech identity
046d:c262 and maps measured R25 controls into four axes with eleven buttons and
one POV. It is a compatibility layout, not USB HID firmware emulation. It forwards
ordinary Linux FFB effects through the existing relay. It requires R25 steering,
throttle, brake and clutch axes; missing axes fail instead of inventing input.

| Physical R25 | Virtual axis/button | Convention |
| --- | --- | --- |
| ABS_X steering | ABS_X | 0..65535, preserves direction |
| ABS_Z throttle | ABS_Y | 65535 released, 0 pressed |
| ABS_RZ brake | ABS_Z | 65535 released, 0 pressed |
| ABS_THROTTLE clutch | ABS_RZ | 65535 released, 0 pressed |
| Right paddle 301 | button 4 | G920 right bumper |
| Left paddle 300 | button 5 | G920 left bumper |

Other mapped buttons need attended label validation. Native and compact profiles
retain their existing identities and mappings. The system service and Qt do not
select the experimental profile automatically.

[Wine's SDL implementation](https://github.com/ValveSoftware/wine/blob/proton_11.0/dlls/winebus.sys/bus_sdl.c)
contains a G920-specific four-axis mapping. Its
[DirectInput implementation](https://github.com/ValveSoftware/wine/blob/proton_11.0/dlls/dinput/joystick_hid.c)
classifies that identity as driving/dual-pedals. The local probe confirmed
product c262046d, type 00010316, four axes, eleven buttons, one POV and FFB
capability. Actual Heat recognition and physical FFB remain unverified.

Local test unit: `mozaproxy-heat-g920-session.service`. Heat alone uses
`/home/your-user/.local/bin/mozaproxy-game -- %command%` to hide the physical R25
from its device namespace. Start the relay before Heat; stop it before another
game. This is still a manual route, not app-managed automatic compatibility.

Rollback: close Heat, stop the transient test unit, restore Heat's original
empty launch options. The old G29 unit is stopped. No boot service was enabled.
The original launch options and game settings are archived under
`~/.local/state/mozaproxy/game-tests/heat-g29-identity-test-20260919-101258/`.

Separately, the user disabled `kernel.split_lock_mitigate` during startup testing.
It remains 0 until restored with `sudo sysctl kernel.split_lock_mitigate=1` or
reboot. No persistent sysctl file was created.

## Attended feedback and editable correction

The user reported the G920 attempt finds controls but has reversed paddles,
a glance stick mapped to acceleration/brake/nitrous/camera, broken menu input,
and a large centre deadzone. Steering direction is correct. The initial table
above records that attempt, not a passing Heat layout.

An experimental correction is saved in the app's per-game mapping store:
left paddle300 -> slot4, right301 -> slot5 (zero-based). Unidentified buttons
and the hat are disabled pending actual assignment. The Qt Games > R25 mapping
tab supports assigning sources and learning buttons. This saved mapping is not
yet active in the old transient relay. See [mapping editor](game-mapping-editor.md)
for activation and live-reload details. No new physical FFB pass is claimed.

## Throttle-only capture, 2026-09-19 11:32

The user pressed and released only the throttle for 25 seconds. Passive reads
confirmed its physical ABS_Z range -32648..32767, virtual ABS_Y range120..65535,
and Windows DirectInput Accelerator/lY range174..65535. All250Windows reads
succeeded. Brake and clutch remained released. Current throttle reversal is off,
as selected by the user; no mapping was changed during this capture.

This confirms the physical source and nearly full-range delivery through the
relay and Proton. Heat's interpretation of that channel and polarity remain
unverified. Evidence is retained in
`~/.local/state/mozaproxy/game-tests/heat-pedals-20260919-113231/`.

## Menu controls captured and applied, 2026-09-19 11:56

A state-polling capture identified the user's chosen menu stick as ABS_HAT0X/Y
with conventional directions, Confirm as physical button640, Back as639 and
Pause as627. An earlier event-stream capture missed input because the relay
grabs the device. Use current-state reads while the relay owns the wheel.

Saved through Qt and applied live: hat passthrough enabled,640 -> slot0,
639 -> slot1,627 -> slot6. These are the expected G920 A/B/Start slots, using
[this firsthand G920 mapping](https://steamcommunity.com/sharedfiles/filedetails/?id=2489644810)
as a reference. Actual Heat menu behavior still needs attended confirmation.
Pedal assignments and the user's paddle correction were preserved exactly.
The running relay acknowledged the mapping without an error or device restart.
Evidence: `~/.local/state/mozaproxy/game-tests/heat-menu-controls-20260919-114927/`.

- Follow-up: user reports menu directions except Up work, but Confirm/Back
  were reversed. Swapped these through Qt and verified live acknowledgement:
  buttons [639,640,null,null,300,301,627,null,null,null,null].
  Captured Up reaches physical hat(0,-1), virtual hat(0,-1), Windows POV0.
  User sees controller-only UI with no wheel settings; active Heat wheel path
  remains unverified. Paused further input remapping to investigate recognition.

## Missing Heat wheel SDK runtime, 2026-09-19 12:04

Heat's executable contains the wide registry path
`SOFTWARE\Classes\CLSID\{63BD165D-1584-4E75-AB56-08330350545F}\ServerBinary`
at file offset61777568 and Logitech SDK initialization/update exports nearby.
The official SDK8.75.30 wrapper queried the same absent key in the live Heat
namespace: registry result2, wrapper loaded, initializationfalse. This identifies
a missing dependency independently of successful DirectInput enumeration.

Extracted only the x64 LogitechSteeringWheel.dll from Logitech's official
LGS9.04.49 installer. Load-only preflight and five required exports passed.
Registered the DLL in Heat's prefix only, at
`C:\Program Files\Mozaproxy\compat\heat\LogitechSteeringWheel.dll`, using
Wine reg.exe rather than editing a live registry file. Registry verification
now resolves that path. No installer, driver, background service, launch-option
change, or other prefix was applied. SDK initialization after installation and
actual Heat recognition/FFB still need testing after a game restart.

Evidence, original missing-key probe, extracted DLL, source URL, SHA256s,
load result and installation manifest are retained under
`~/.local/state/mozaproxy/game-tests/heat-sdk-20260919/`.
Rollback: delete only the added ServerBinary key and the exact installed DLL
after checking installed.json and evidence.json. The prior key/file were absent.

- Restarted Heat after user closed it. New PID565455 maps the staged Logitech
  runtime DLL, unlike the pre-install session. Physical event8/hidraw9 remain
  masked and virtual event13 visible. Steam left, game right, cursor left.
  Wheel-specific UI, throttle and physical FFB still require attended testing.

## SDK versus relay comparison pending

User reports Heat now working after SDK installation and has corrected bindings.
Latest saved/live mapping: all pedals inverted=true; paddles slot4=301,slot5=300;
Confirm/Back slots0=639,1=640;Pause slot6=627;hat=true. Preserve this latest version.
They request determining whether SDK alone suffices without the relay. The live
editing feature itself does not affect the descriptor or game compatibility;
the unresolved comparison is direct R25 versus the fixed G920 translation.
Prepared archive path is in /tmp/mozaproxy-heat-direct-comparison-path.
Need final post-close settings backup, stop app-owned relay, clear Heat launch
options via Steam UI, relaunch same prefix/Proton with SDK and physical R25.
The current wrapper always hides the R25, even with no relay, so merely stopping
the relay is not a valid direct test. No route changes made while user plays.

## Fixed Heat preset, 2026-09-19

User closed Heat and clarified that the wheel emulation should remain, while
manual binding setup should be unnecessary. Deferred the direct-R25 comparison;
no launch-option or relay-route changes were made. Final post-close settings
are backed up under the comparison archive.

The explicit Heat G920 preset now exactly matches the user's working saved
mapping: inverted pedals, slot4=301/slot5=300, slots0/1=639/640, slot6=627,
and hat passthrough. Selecting G920 for Heat fills these assignments; existing
saved mappings remain authoritative and direct is still the unsaved baseline.
Live editing changes the same compiled profile, not an extra relay/device.
No edits are required each launch. The Logitech SDK runtime is still required
setup for the tested route and is not installed automatically by preset choice.

All203 tests, including opt-in virtual kernel tests, passed after the preset
change. The app's Heat evidence text now reports the user's input pass and
separate SDK setup; physical FFB quality remains unconfirmed.
