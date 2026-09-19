# App validation, 2026-09-18

Implemented and checked in the rebuilding worktree. No game was launched and
no motor test or physical configuration write was performed during this app work.

## Automated checks

- Full Python suite: 84 tests discovered, 83 passed, optional virtual-device test
  skipped in the normal run. The skipped test was then enabled and passed with
  `MOZAPROXY_TEST_UINPUT=1 .venv/bin/python -m unittest tests.test_uinput -v`.
  It creates two virtual devices and never opens the physical motor.
- Hardware protocol checks cover packet checksums, float request encoding,
  invalid values, exact boolean/enum and quantized numeric readback, unavailable
  settings, competing serial owners and safe pedal-boundary write ordering.
- HTTP checks cover hostile origins, session tokens, malformed requests, static
  path traversal, atomic profile persistence, relay ownership and shutdown.
- Mocked Chromium tests in `tests/browser/app-regressions.cjs` passed. They cover
  saved-profile overrides, invalid input blocking Apply/Save, route persistence,
  correction recovery, failed settings reads and relay selection after reload.
  All API requests in these tests are intercepted.
- JavaScript syntax, shell syntax and `git diff --check` passed.
- JDM capture shared library builds with `-Wall -Wextra -Werror`. Capture is
  inactive; live Proton loading and actual output reports remain untested.

## Real device and browser checks

The serial read-only check received 59 of the 64 catalogued settings from the
connected R25 Ultra. Rotation was 900 degrees. The five absent settings were
four game-effect gains and rotary control mode. No substitute defaults were
reported as hardware values.

The actual app was checked in headless Chromium at 390×844, 1440×1000 and
2560×1440. All six routes at each size passed the overflow check. The run
reported no JavaScript or console errors. It created, selected and deleted a
temporary profile and checked that polling preserved a draft. Requests were
recorded: connect/read settings, profile CRUD and disconnect only. No Apply or
relay-start endpoint was called. Final state had zero test profiles, the serial
connection released and the relay stopped.

Independent UI review found two relay labeling/selection defects. Both were
fixed and covered by the mocked browser regressions. The reviewer scored both
resolved and returned a ship verdict for the implemented UI. Design detector
findings were reviewed; pedal animation now uses transforms. The warm neutral
palette is intentional in the documented calibration-bench design.

## Remaining work

Configuration Apply needs attended readback and behavior checks on the real
wheel. Full Boxflat parity is not claimed: calibration, individual LED colors,
telemetry lighting, firmware tools and automatic game switching are absent.
Only peripherals connected through the base are supported by the serial client.

FH5 driving and physical FFB were confirmed earlier, but freezes remain. JDM
inputs work and its FFB remains intermittent/incorrect. FS22, FS25, AC and ACC
still need the rebuilt-tool driving/regression tests. See compatibility.md and
jdm-ffb-debug.md for the separate game evidence and next attended tests.
