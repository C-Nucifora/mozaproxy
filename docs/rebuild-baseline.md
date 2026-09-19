# Rebuild baseline

Observed on 2026-09-18. This records the starting state, not a claim of game
compatibility or working physical force feedback.

## Connected hardware

- MOZA R25 Ultra Base, USB `346e:0000`, input version `0111`.
- Arch Linux `7.2.6-arch2-1`, bound to `hid-universal-pidff`.
- Physical input node at inspection: `/dev/input/event8`. Discover by identity
  on subsequent runs; event numbers can change.
- 128 advertised buttons. The first 16 use codes 288–303, followed by codes
  starting at 624. Physical controls still need mapping with the user.
- Eight ordinary axes, codes 0–7, and two hat axes, codes 16–17.
- Steering range 0–65535. Other ordinary axes use -32768–32767.
- Ten simultaneous force-feedback effect slots.
- Advertised force-feedback capabilities: constant, ramp, spring, friction,
  damper, inertia, periodic, rumble, square, triangle, sine, saw up, saw down,
  and gain. Autocenter is not advertised. Capability bits alone do not prove
  the physical response of each effect.

## Confirmed problems in the old installation and code

1. The user service is inactive. Its configured checkout,
   `/home/your-user/Documents/dev/personal/mozaproxy`, does not exist.
2. `/etc/udev/rules.d/99-mozaproxy.rules` is absent. The physical input device
   currently has `ID_INPUT_JOYSTICK=1`.
3. The default button list is 288–311. Eight of these codes do not exist on
   this physical device, while 112 real codes are omitted. The rebuild needs
   explicit mapping from discovered source codes to advertised output codes.
4. Source inspection shows no recovery from `SYN_DROPPED`, no initial pressed
   button snapshot, and no tests. The daemon continues even if exclusive grab
   fails. Erase errors are acknowledged as success and their mappings discarded.
5. The README's previous crash diagnosis is historical and unverified in this
   session. Do not treat its 128-button explanation as an established cause of
   current game failures.

## Checks completed

- Read physical capabilities and current axis values without changing settings.
- Created and destroyed a virtual device through the existing `build_virtual`
  implementation. Device creation succeeded and preserved all advertised FF
  bits and the ten-slot capacity.
- Did not upload or play motor effects, grab the physical wheel, change global
  gain, install rules, or start the installed service.
- Current user can access evdev and uinput. UHID and the wheel's hidraw node
  are not accessible. Noninteractive sudo requires authentication.

## Rebuild direction

Rebuild the userspace tool around the existing kernel driver. Keep discovery,
input mapping, effect ownership, device lifecycle, and compatibility profiles
separate, so failures can be tested at each boundary.

Start with a tested evdev/uinput backend. Map actual source controls, initialize
state, recover after dropped input, fail on grab conflicts, and handle reconnects.
Relay supported effect types and preserve update, playback, repeat, stop, erase,
and gain semantics. Always complete upload/erase requests and propagate errors.
Verify cleanup on game exit and daemon exit.

Compare direct-device behavior with proxy behavior before choosing how to hide
the physical device or introducing another virtual-device backend. Udev tags
and an evdev grab do not establish isolation across every game input backend.
A UHID implementation would require a HID/PID descriptor, report protocol,
effect translation, and additional permissions; adopt it only if measured game
enumeration failures justify that work.

Provide diagnostics and explicit game profiles where needed. Record each tested
game, runtime, enumeration result, input mapping, and physical FFB result.
Universal compatibility remains an objective, not a verified product claim.

## First compatibility targets

The user narrowed the first release to these games:

| Game | Role | Current verification |
| --- | --- | --- |
| Forza Horizon 5 | New compatibility target | Not tested this session |
| Farming Simulator 22 | New compatibility target | Not tested this session |
| Farming Simulator 25 | New compatibility target | Not tested this session |
| JDM: Japanese Drift Master | New compatibility target | Not tested this session |
| Assetto Corsa | Preserve support, regression test | Baseline not yet captured |
| Assetto Corsa Competizione | Preserve support, regression test | Baseline not yet captured |

Keep game-specific identity, input mapping, and enumeration workarounds in
explicit profiles. Capture AC and ACC behavior before replacing their current
input path. For every game, distinguish launch/enumeration, steering and pedal
bindings, button bindings, and physical force feedback. Determine which effects
each game actually sends; do not assume all games implement the same FFB model.

## Next cooperative test

Capture the physical wheel's input while the user turns the wheel, operates each
pedal separately, and presses paddles/buttons in a known order. This test needs
no motor commands. Follow with short, low-amplitude physical FFB tests while the
user is present, first directly and then through the rebuilt relay.

The existing `tools/ffbtest.py` requests approximately 50% constant-force level
for 1.5 seconds. Do not use that as the initial R25 baseline test.

## Cooperative input capture

Completed a passive capture with the user. Raw events are retained locally at
`/tmp/mozaproxy-controls-nxd5_76l.jsonl`; this temporary file is not a portable
test fixture. The recorder closed normally after SIGINT. No force-feedback
commands were sent and no `SYN_DROPPED` events were observed.

The following labels are inferred from the requested control sequence and the
user's correction that the right paddle was pulled before the left:

| Control | Linux event | Observed sequence |
| --- | --- | --- |
| Steering | `ABS_X`, code 0 | Full advertised range 0–65535 observed |
| Accelerator | `ABS_Z`, code 2 | Press/release at 25.8–28.5 seconds |
| Brake | `ABS_RZ`, code 5 | Press/release at 30.0–33.5 seconds |
| Clutch | `ABS_THROTTLE`, code 6 | Press/release at 34.6–37.3 seconds |
| Right shift paddle | `EV_KEY`, code 301 | First paddle at 38.9–40.3 seconds |
| Left shift paddle | `EV_KEY`, code 300 | Second paddle at 41.5–43.2 seconds |

All three pedal axes increased from approximately -32768 at rest to +32767
when pressed. Additional axes `ABS_RX` and `ABS_RY`, codes 3 and 4, were operated
after the shift paddles; their physical labels are not yet established. Both hat
axes were exercised through -1, 0, and +1.

Twenty distinct button codes were exercised:
`288, 289, 296, 297, 298, 299, 300, 301, 626, 627, 628, 629, 630, 639, 640,
641, 642, 643, 653, 655`. The old default proxy would discard twelve of those
twenty controls. The short repeated pulses on 653 and 655 must be preserved,
not debounced away. Exact physical labels for the extra buttons remain unknown.

Next, test brief low-amplitude constant forces directly on the physical device
while the user is ready to observe, then compare the virtual relay. Use a finite
effect duration, stop and erase in cleanup, and begin at approximately 2% effect
level for 250 milliseconds. Do not use the old 50% test.

## First physical FFB probe

With the user ready, sent two constant-force effects directly to the physical
wheel. Each used level 655/32767, duration 250 ms, and 50 ms attack/fade. Directions
were `0x4000` and `0xc000`, separated by two seconds after stopping and erasing
the first effect. Global gain was not changed.

Both uploads, play writes, stop writes, and erases completed without errors.
The device handle closed and the test process exited successfully. Steering
changed from 30339 to 30337 for the first pulse and 30336 to 30337 for the second.
Those tiny changes do not establish motor response. User observation is pending;
successful API calls alone do not prove physical FFB works.

The user thought the first probe moved left and requested stronger pulses.
A second probe used level 1638/32767, duration 350 ms, and 75 ms attack/fade,
with three seconds between directions. Global gain remained unchanged.
Both effects were stopped and erased, and the process exited successfully.
Sampling steering every approximately 10 ms showed:

| Direction | Before | Minimum | Maximum | After |
| --- | --- | --- | --- | --- |
| `0x4000` | 30338 | 30292 | 30338 | 30336 |
| `0xc000` | 30331 | 30331 | 30426 | 30409 |

These readings show small excursions in opposite directions. User confirmation
of the perceived response is still needed; this does not validate other effect
types or the proxy relay.

The user subsequently confirmed that the wheel moved and the result looked good.
Direct physical constant-force response is established at this test strength.

## Rebuilt relay verification

- Replaced the monolithic relay with discovery/runtime, input, profiles, effect
  ownership, diagnostics, and bounded hardware-probe modules.
- All 27 tests passed both with the system Python environment and the installed
  checkout venv using evdev 2.0.0. The opt-in kernel integration test ran with
  virtual devices only. It verifies distinct physical/virtual effect IDs,
  update/repeat/stop/gain/erase, client-close cleanup, and input mapping.
- Independent code review identified missing `UInputError` supervision and
  partial-constructor cleanup. Both have fixes and regression tests. The C
  extension already closes descriptors for many configuration errors; rollback
  also covers failures in Python-side preparation.
- Installed the venv and repaired the user service path, backing up the old
  unit to `mozaproxy.service.backup-1789681295493204936`. The service remains
  inactive; no udev rule or kernel driver was changed.
- Started compact mode against the physical wheel without sending FF commands.
  Virtual `/dev/input/event13` advertised 32 buttons and 10 effects and was tagged
  `ID_INPUT_JOYSTICK=1`. Its current axes matched the physical wheel.
- Ctrl+C stopped the daemon with zero FF transactions. The virtual node
  disappeared, and a separate process successfully grabbed/released the physical
  wheel afterward.
- Physical pulses through the rebuilt relay are the next cooperative test.
  No target game has been validated with the rebuild yet.

## First rebuilt-proxy physical probe

Started compact mode and sent two opposing constant-force pulses through its
virtual evdev node using `--strength 0.05 --duration 350 --play`. The probe
finished successfully. Relay logs confirm two type-82 uploads, play and stop
commands, and two successful physical erases. Extra stop commands from kernel
erase processing were forwarded normally. Ctrl+C stopped the proxy successfully.
User observation of the wheel's response is pending.

Repeated the same proxy probe at the user's request after they missed the first
run. Both uploads/playbacks/stops/erases completed without errors again, and the
proxy exited cleanly. Physical observation is still pending.

The user confirmed seeing the repeated probe move the wheel. Constant force
through the rebuilt compact-profile relay is now physically verified at 5%
level and 350 ms duration. This does not yet establish in-game FFB.

## Upstream research

[universal-pidff PR 125](https://github.com/JacKeTUs/universal-pidff/pull/125)
fixes incorrect effect types when updating one of several different effects.
The author reports fixes for Forza Horizon 5/6, and the discussion says the fix
landed in 7.2-rc. This machine runs 7.2.6; inspect or test the running driver
before deciding that a driver replacement is necessary.
