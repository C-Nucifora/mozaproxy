# Menu force protection implementation plan

Goal: expose the existing constant-force expiry guard as an optional shared
setting for games whose menus leave the wheel pulling, including ACC and LMU.

Architecture: an off-by-default user preference feeds a direct-game launcher
and the existing relay. Keep the R25 evdev guard scoped to explicitly launched
commands, preserve other environment settings, and never load it globally.
Use native Qt controls and the existing web API for the same saved preference.
The toggle applies on the next game or relay start, not to a running session.
User follow-up requests a configurable timeout with a 100 ms default; use
50–1000 ms in both launch and relay paths.

- [x] Rename and install the shared native helper; retain the old LMU binary for existing launch options.
- [x] Add bounded atomic preference storage and a direct-game launcher that fails clearly if protection cannot load.
- [x] Apply the same expiry behavior in the relay, including explicit system-service starts.
- [x] Add desktop/web controls and ACC/LMU launch suggestions with the requested purpose text.
- [x] Provide ACC and LMU launch lines; user chose to apply them manually.
- [x] Run existing checks and hardware-free guard checks; review the final diff.
Delivery: create signed local commits and push the current feature branch. Do not merge master or create a PR.

Hardware verification in ACC and LMU remains pending until an attended drive,
pause and resume test. Software expiry is not a hardware torque limit.
