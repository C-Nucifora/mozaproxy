# Product
<!-- impeccable:product-schema 1 -->

## Platform
Linux desktop

## Stack
Python and Qt 6 through PySide6, with the existing evdev relay and serial settings
controller. The user explicitly requested a native desktop app. The installed
launcher opens the Qt window directly. The earlier HTTP interface remains an
optional development tool.

## Users
The owner of a MOZA R25 Ultra racing setup on Arch Linux, tuning the wheel and
playing FH5, JDM, Farming Simulator 22/25, Assetto Corsa and ACC.

## Product Purpose
One desktop app for wheel input/FFB compatibility and clear settings, with
Boxflat-like hardware functionality and coordinated ownership to avoid conflicts.

## Operating Context
Local Linux desktop and Steam/Proton. The user participates in driving tests.
The app is installed for the current user, with a desktop menu entry and the
`mozaproxy-app` launch command. Native Wayland launch and GUI interaction have
been verified. App startup does not need a browser or a local web server.

## Capabilities and Constraints
The native Qt app provides six sections for passive input monitoring, wheelbase
and peripheral settings, profiles, relay control, game notes and diagnostics.
It uses a 64-setting serial catalog; read-only R25 Ultra checks returned 59
settings. Explicit drafts and verified readbacks stay separate. Hardware Apply
still needs attended physical validation. No unattended motor probes.

FH5 and JDM have attended driving passes for controls, physical FFB and smooth
play after the T3 preview scanner was prevented from probing Steam. FH5 uses
the compact R9 relay and physical-device isolation. JDM uses direct physical
HIDRAW with the descriptor helper. These are manually configured local routes,
not validation of integrated system mode. FS22/FS25 driving and AC/ACC regressions
remain pending. Full Boxflat parity is not implemented.

Untested games default to the ordinary physical-wheel path. Automatic special
handling requires both a current attended test and implemented game support.
The always-reserved physical ownership design must be revised before activation.

LSFG is disabled at the user's request through `DISABLE_LSFGVK=1`. A subsequent
JDM process inherited the flag and had no `liblsfg` mapping. This is the current
comparison baseline, not a proven freeze or FFB fix.

## Evidence on Hand
[Compatibility tracking](docs/compatibility.md) records hardware/game observations.
[Qt validation](docs/qt-validation.md) records native launch, all-six-page captures,
controller and desktop regressions, and GUI profile save/load/delete without
Apply. The 104-test normal suite had 103 passes and one optional virtual-device
skip; that optional test subsequently passed separately. These checks do not
validate physical configuration writes or in-game FFB.

Remote launch evidence is in
`~/.local/state/mozaproxy/game-tests/remote-20260918/results.md`. Real input and
USB hardware are available locally. Installed Boxflat provides protocol reference.

## Product Principles
- Separate confirmed hardware state from saved preferences.
- One coordinated settings owner; report competing processes.
- Keep game-specific workarounds visible and reversible.
- Never present pending compatibility tests as passing.

## Assumptions
A native desktop tuning interface with resizable layouts is appropriate. Visual
style is an implementation choice, not a user-confirmed brand requirement.
