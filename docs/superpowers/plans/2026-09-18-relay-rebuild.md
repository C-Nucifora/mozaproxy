# Linux wheel relay rebuild implementation plan

**Goal:** Establish a tested relay for the R25 before validating FH5, FS22,
FS25, and JDM, with AC and ACC as regression targets.

**Architecture:** Keep the kernel's PIDFF driver. Separate pure profile mapping,
input state, effect ownership, and runtime lifecycle. Use evdev/uinput first;
game-specific enumeration changes follow measured game failures.

**Tech stack:** Python 3.10+, python-evdev 1.9+, Linux uinput, unittest.

**Spec:** [Baseline and scope](../../rebuild-baseline.md).

## Constraints

- No physical FFB in automated tests. Hardware probes must be explicit.
- Preserve existing game configurations and kernel drivers.
- Do not install permanent physical-device hiding by default.
- No claim of game support without a launch, binding, and FFB test.
- Only advertise effects the real device supports, with its actual capacity.
- Keep physical detection distinct from virtual identities.

## Task 1: Profiles and input state

Files: `mozaproxy/profiles.py`, `mozaproxy/input.py`, `tests/test_input.py`.

- [x] Add failing tests using the observed R25 noncontiguous button codes.
  Check source 653 becomes a real virtual button and retains press/release
  pulses; assert held buttons and current axes are initialized.
- [x] Implement `make_profile(capabilities, name, buttons=None)` returning
  capabilities, axis codes, and source-to-output button mapping. Native preserves
  all inputs. Compact uses observed R25 controls, up to 32, with output codes
  in joystick ranges, avoiding gamepad buttons.
- [x] Implement `InputRelay(real, virtual, profile)` with `sync_state()` and
  `handle(event)`. Ignore events after `SYN_DROPPED` until `SYN_REPORT`, then
  restore axes and every mapped button from device state.
- [x] Run `python -m unittest discover -s tests -v`.

## Task 2: Effect ownership and error propagation

Files: `mozaproxy/effects.py`, `tests/test_effects.py`.

- [x] Add failing tests for multiple effect IDs, updating an older effect,
  upload failure, erase failure, repeat/stop, gain, and cleanup.
- [x] Implement `EffectRelay(real, virtual)` with `handle(event)` and `close()`.
  Copy effect structures before replacing IDs; retain mappings after erase
  errors. Complete every begun uinput request in `finally`. Reject unsafe custom
  waveform pointer transfer. Forward supported control writes and surface errors.
- [x] Stop/erase owned effects before releasing physical access, including after
  partial initialization or shutdown.
- [x] Run unit tests with injected I/O fakes, never physical devices.

## Task 3: Runtime, diagnostics, and hardware integration

Files: `mozaproxy/runtime.py`, `mozaproxy/cli.py`, `mozaproxy/__init__.py`,
`mozaproxy.py`, `tests/test_runtime.py`, `tools/ffbtest.py`.

- [x] Test exact discovery, virtual exclusion, ambiguity, grab conflicts, cleanup,
  argument validation, and one-shot nonzero failure exits.
- [x] Runtime exclusively grabs one physical device, creates the virtual device,
  initializes input, and services both queues with a selector. Retry reconnects
  with fresh state; signal handlers request orderly shutdown.
- [x] Add `--device`, `--profile`, and `--diagnose` while retaining existing
  identity and button flags where their meanings remain valid.
- [x] Replace the 50% probe with an explicit-device, finite-duration pulse tool.
  Default 2%, cap at 10%, require `--play`, and clean up on exceptions/signals.
- [x] Run a real uinput-to-uinput integration test with no motor hardware. Check
  upload, update, play, repeat, stop, erase, and physical-client close cleanup.
- [x] Run the established 5% pulse through the rebuilt relay with the user.

## Task 4: Installation and game validation

Files: `install.sh`, `systemd/mozaproxy.service`, `udev/99-mozaproxy.rules`,
`README.md`, `docs/compatibility.md`.

- [x] Make service installation opt-in and stop hiding physical devices globally
  during ordinary installation. Document restoring direct access for AC/ACC.
- [x] Document CLI profiles, mapping, motor-test limits, and measured status.
- [ ] Inspect Proton enumeration and game logs starting with FH5. Apply only
  evidence-backed per-game configuration, with backups and rollback commands.
- [ ] Cooperatively test the four target games and AC/ACC regressions. Record
  runtime/build, detected device, bindings, effects requested, and physical result.

Game validation requires user interaction and may span turns. Completing the
relay does not complete this plan or establish support for all six games.
