# System wheel service implementation plan

**Goal:** Build an installable system-owned wheel service and native Qt client while preserving the active FH5 test setup.

**Architecture:** Dedicated unprivileged service shares physical access with the desktop and controls settings plus an optional relay child. Startup leaves the relay off. Qt communicates over an authenticated local Unix socket. Shared device permissions are enabled only at a separate installation switch.

**Spec:** `docs/superpowers/specs/2026-09-18-system-wheel-service.md`.

**Constraints:** No live device grabs, motor tests, Steam edits, installed rules or active service changes. No commits requested. Existing worktree is already isolated; preserve its uncommitted work.

- [x] Service/protocol: implement fixed validated operations, bounded authenticated socket transport, reconnect/shutdown; fake-backed tests.
- [x] Installer: root-owned staged runtime, private account/device rules, explicit activation preflight and rollback; isolated tests and documentation.
- [x] Qt client: remote component adapters, local profiles, explicit system control/status, no hardware fallback or daemon shutdown on UI close; offscreen tests.
- [x] Review authorization and physical access boundaries, run relevant and full tests without kernel opt-in, verify live relay unchanged.
- [x] Prepare installation command and report remaining coordinated permission/game checks. Do not activate during current game tests.
- [x] Revise the default after direct JDM success: retain desktop seat access, remove automatic relay startup, verify both accounts can access physical nodes, and report process liveness separately from unverified virtual readiness.
- [ ] Validate installed direct access and each built-in game route after the remaining existing-setup tests. Do not remove working launch compatibility steps before their replacements pass.

Installed permission checks, reboot behavior after activation, and game/physical FFB validation remain pending. Nothing was installed or activated during implementation.
