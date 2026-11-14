# Managed lighting implementation plan

Implement the approved design in ../specs/2026-11-15-managed-lighting.md using the
existing hardware controller, telemetry monitor and user-service installation.

- [x] Verify SDK alert fields and base commands against primary sources.
- [x] Extend helper flags and lease lifetime without changing 24-byte packets.
- [x] Add gated base output, alert rendering and configurable RPM scaling.
- [x] Correct serial stuffing and verify fragmented frames and checksum escapes.
- [x] Add validated settings, host-service lifecycle and fixed-wrapper startup.
- [x] Expose saved lighting controls in desktop and web interfaces.
- [x] Run existing tests, cross-build helpers, review and address findings.
- [x] Install and enable the user's approved RPM/base alert configuration.
- [x] Commit reviewed changes locally.
- [x] User confirmed physical base alerts work.

Verification: 205 tests passed, four skipped. Helper builds with and without LMU
passed. Inline checks covered all 256 payload bytes at every frame split, captured
checksum escaping, old/new packets and stale/unknown alert transitions. Review
found helper-exit detection and byte stuffing defects, both corrected. R25 read-only
probe confirmed model, brightness and mode1. Live managed telemetry has RPM and
blue-flag samples with base_output true and no base error. Optional activity
alerts remain off. Defaults for new installs remain off; local user settings are on.

User confirmed base alerts work after the blue-flag / cyan-limiter observation
request. Yellow, green and optional ABS/TC effects were not individually verified.
