# Fixed protection launcher implementation plan

> Execute inline with the executing-plans skill and review the complete change.

**Goal:** One Steam wrapper line follows saved protection settings on every launch.

**Architecture:** Reuse ProtectionStore and the installed launcher. Share the
generated command between Overview, LMU and ACC. Keep game defaults in the wrapper.

**Tech stack:** Python, existing Qt and web UI.

**Spec:** ../specs/2026-11-14-fixed-protection-launcher.md

## Constraints and review focus

Preserve unrelated environment values and preload libraries. Unknown or conflicting
Steam IDs must not acquire LMU defaults. Keep explicit diagnostic overrides working
but visible. Preserve custom settings directories and source-only launch fallback.
Do not write hardware or edit a running Steam client's files. Follow the user's
realistic-commits policy, running existing tests without adding test files.

## Task

- [x] Update protection.py to generate the installed launcher command, supply LMU
  defaults and warn about explicit overrides. Update app_state.py's LMU suggestion.
- [x] Clarify the one-time setup in desktop.py, webui/app.js, README and protection docs.
- [x] Run existing relevant checks and inspect subprocess launches using temporary
  settings at two timeouts and with protection disabled. Check argument preservation,
  explicit defaults, conflicting IDs and diagnostic override reporting.
- [x] Review, verify installed launcher behavior and create one signed local commit.

## Execution notes

The selected approach needs no new dependencies or native-helper changes. Existing
installation points to this checkout, so launcher updates use the installed entry.

Verification: 209 existing tests ran, 205 passed and four skipped. Installed-wrapper
subprocess checks confirmed successive saved timeouts, disabled protection, LMU
ID selection, environment and argument preservation, source fallback, override
warnings and invalid-config refusal. JavaScript syntax and diff checks passed.
Independent review reported no actionable issues. No game or wheel test was run.
