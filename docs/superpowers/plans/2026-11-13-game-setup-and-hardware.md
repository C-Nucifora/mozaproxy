# Game setup and hardware implementation plan

> Execute inline using superpowers:executing-plans; one final branch review.

Goal: implement the approved game setup, validation and supported hardware expansion without disturbing the user's game.
Architecture: shared bounded stores and pure validation; Qt invokes explicit backend operations; passive game monitoring never writes hardware from snapshots.
Tech stack: Python, Qt6, evdev, existing serial transport and vanilla web UI.
Spec: docs/superpowers/specs/2026-11-13-game-setup-and-hardware-design.md

## Global constraints

- No real device access, runtime installation, Steam mutation or game/service restart during development.
- Automatic Apply and per-game permission default off. Never apply retroactively or defer a missed launch.
- Keep existing manual routes and hardware readback validation. Physical results require user confirmation.
- Use existing tests and temporary self-checks; no new permanent tests without a request.
- Firmware flashing and unidentified accessory writes remain blocked by protocol/identity evidence.

## Review focus

- Malformed/oversized stored data must not be overwritten.
- Ambiguous games, PID reuse and multiple clients must never duplicate automatic writes.
- Dirty drafts and busy/disconnected hardware skip the launch permanently.
- Failed writes distinguish unknown device state from unchanged values.
- Calibration cancellation and stale telemetry stop output without false success claims.

## Task 1: compatibility and setup

Files: new mozaproxy/game_setup.py and game_setup_ui.py; app_state.py, service_client.py, desktop.py, web.py, webui/app.js.
Interfaces: GameSetupStore.settings/save/record/snapshot; preflight(game, route); shared snapshot game_setup.
- [x] Add bounded atomic storage for links, detection/auto flags and dated evidence.
- [x] Expose setup and result controls and diagnostic export in both clients.
- [x] Verify defaults, invalid records, lost profiles and prerequisite reports in temporary fixtures; run existing UI/API checks.

## Task 2: game detection

Files: game_setup.py, game_setup_ui.py, desktop.py.
Interfaces: running_games(proc_root), GameSession.poll(snapshot, dirty) returning one launch decision; UI executes explicit operations.
- [x] Scan bounded same-user process metadata at two-second intervals, collapse child processes by Steam ID and retain launch identity.
- [x] Add single-owner opt-in monitoring, profile selection preserving drafts, per-game/global opt-in Apply.
- [x] Verify initial-running suppression, mid-game enable suppression, ambiguity, disconnect/busy/dirty skip, no retry, default-off behavior.

## Task 3: settings reports

Files: hardware.py, desktop.py, webui/app.js.
Interface: hardware.status.last_apply and apply.report with previous/requested/actual/outcome/error per field.
- [x] Capture bounded last-apply evidence using existing writes/readback, including partial failures.
- [x] Expose report and export. Verify simulated mismatch and failure paths; run hardware/service tests.

## Task 4: calibration and RGB

Files: new capabilities.py and calibration.py as needed; settings.py, hardware.py, qt_widgets.py, desktop.py, service protocol, web UI.
- [x] Establish supported identity/protocol entries from local reference, keeping unknown devices disabled.
- [x] Implement explicit pedal start/stop procedure with cancellation and readback, excluded from profiles/automation.
- [x] Implement typed RGB schema and editors using existing readback and profile flow.
- [x] Verify framing, invalid colors, unknown capabilities, cancellation and disconnected behavior without hardware.

## Task 5: telemetry and firmware/accessory research

Files: new telemetry.py and UI integration; docs/hardware-settings.md.
- [x] Verify FH5 Data Out format, implement bounded parser and offline RPM/LED preview.
- [x] Add opt-in bounded-rate output only for identified supported wheel; stop on stale input and relinquish serial ownership to explicit operations.
- [x] Record firmware/accessory capability limits, official tool links and remaining attended prerequisites.
- [x] Verify synthetic malformed/stale packets, default-off output and unavailable device behavior.

## Task 6: delivery

- [x] Run full existing suite, browser/Qt checks and focused offline self-checks.
- [x] Obtain final code review and fix important findings.

Delivery: verify the signed local commit and report hardware/protocol blockers.
No live installation while the user plays.

## Execution rulings and evidence

- User approved the design and later requested a background service. Added
  game_service.py and install.sh --game-service. No runtime installation occurred.
- Accessory support is determined by valid protocol readbacks, never R25 base
  identity alone. Independent USB accessory writes and firmware flashing remain
  blocked by missing verified protocols; documented in hardware-tools.md.
- New code was checked with temporary self-checks rather than adding repository
  tests, honoring the realistic-commits instruction. Existing suites remain intact.
- Reviewer findings corrected stop-failure state, independent telemetry mode
  recovery, web Stop dispatch, watcher ownership, eligibility rechecks, shutdown
  cleanup, unit ordering and unconfirmed telemetry activation.
- Physical compatibility, settings writes and startup/reboot tests remain pending.

Final checks: 209 existing tests pass with 4 skips; 12 hardware tests pass; browser regression and new Stop actions pass; temporary storage/game-service/calibration/telemetry checks pass; generated unit passes systemd-analyze.
