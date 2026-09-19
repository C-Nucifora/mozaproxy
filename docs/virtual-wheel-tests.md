# Virtual wheel testing

The user authorized a digital wheel harness on 18 September 2026 to allow
unattended input and force-feedback checks. The harness creates a separate
Linux virtual input device. It does not open the physical wheel or send motor
commands.

## What these tests establish

- Scripted steering, pedals and buttons can be checked against the game's input
  display and vehicle response.
- Captured effect uploads, updates, playback, erasure and gain commands show
  what the game requests through the virtual evdev path.
- Timestamped commands and frame-time logs allow repeated comparisons of the
  same short driving sequence.

These results do not establish physical torque, damping direction, firmware
behavior, or the correctness of JDM's separate direct-hidraw path. A successful
virtual test must be followed by an attended physical check before claiming
working force feedback.

## Controlled game runs

1. Close the previous game and stop the physical relay. Back up launch options
   and controller settings before making any test-specific changes.
2. Start the harness before launching the game. Match the compact R9 identity
   and axis layout used by the existing relay, and record the virtual device
   path. Use the game-specific isolation wrapper to hide the physical R25 from
   that game while leaving the virtual device visible.
3. Keep LSFG disabled as requested by the user. Keep Steam and the launch cursor
   on the left monitor, with the game on the right.
4. First inspect neutral inputs. Then exercise steering, each pedal and each
   paddle separately. Return controls to neutral between checks. Do not infer
   a passing binding merely because the game lists a wheel.
5. Use a local practice/free-drive session for a short repeatable sequence.
   Record scene, game build, Proton version, binding changes, input commands,
   FFB events and frame times. Keep shader/loading transitions separate from
   steady driving measurements.
6. Close the game, stop the harness, verify its virtual node disappeared, and
   restore test-specific launch options and bindings. Preserve raw logs with
   the result, including failures and unsupported paths.

## Current evidence

After adding hat-switch commands and fixing pending-effect teardown, the full
suite passed all 122 tests with `MOZAPROXY_TEST_UINPUT=1`, including all three
virtual-only kernel checks. A guarded regression first reproduced a close that
exceeded two seconds with an unanswered FF erase request. Destroying uinput
before closing its discovery handle releases that request and removes the node
without waiting for the kernel's 30-second request timeout.
The new kernel check exercised scripted steering, throttle and a button, FF
upload/update/start/stop/gain/erase, and removal of the virtual node on exit.
A separate SIGTERM check also verified removal. No physical wheel was opened
by these tests. Game runs still need their own evidence in
`docs/compatibility.md` and the local game test archive.

## Running the harness

Run from this checkout with its virtual environment. Use fresh files for each
session; the capture refuses to overwrite an existing log. Prefer tmpfs for
short captures because recording every effect update adds overhead.

```sh
.venv/bin/python tools/wheel-harness.py \
  --commands /dev/shm/mozaproxy-wheel-commands.jsonl \
  --log /dev/shm/mozaproxy-wheel-capture.jsonl \
  --duration 600
```

Append complete JSON lines to the command file from another process. Steering
uses -1 through 1, pedals use 0 through 1 with 0 released, and button numbers
refer to compact slots 1 through 32. `hat_x` and `hat_y` set the directional
pad's horizontal and vertical axes. Each accepts only the integers -1, 0, or 1;
booleans and decimals such as `1.0` are rejected. Zero releases that axis.
Conventional directions are horizontal -1 left/+1 right and vertical -1 up/+1
down; the game's bindings determine the resulting menu action. Omitted controls
keep their previous values. A malformed control rejects the whole command
before any input frame is written.

```jsonl
{"steer":0,"throttle":0,"brake":0,"clutch":0}
{"steer":0.25}
{"wait":0.5}
{"steer":-0.25}
{"wait":0.5}
{"steer":0,"buttons":{"13":true}}
{"wait":0.1}
{"buttons":{"13":false}}
{"hat_x":0,"hat_y":-1}
{"wait":0.1}
{"hat_y":0}
```

These are input commands, not force commands. Games upload effects to the
virtual wheel; the capture records them without forwarding them to a motor.
Append `{"stop":true}` or send SIGTERM to finish. Copy captures out of tmpfs
before rebooting. The kernel smoke test uses only a virtual device:

```sh
MOZAPROXY_TEST_UINPUT=1 .venv/bin/python -m unittest tests.test_harness -v
```
