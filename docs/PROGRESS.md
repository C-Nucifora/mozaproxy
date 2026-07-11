# mozaproxy — progress & resume state

Last updated: 2026-07-11. Snapshot for resuming after a restart.

**Repo working directory:** `/home/christian/Documents/dev/personal/mozaproxy`

---

## One-line status

Phases 1–4 are **built, tested, and committed locally**. Nothing is pushed. The
only open work is **in-game validation on hardware** (the base was powered off
during development); remaining deferred items are small (latency tooling,
`--hide-mode lock`, `axes.*.range`).

## Git state

- Branch: `master`. **Local commits, NOT pushed.**
- Recent commits (newest first):
  - Phase 3: profile DB + `mozactl run` launcher + `mozactl calibrate`
  - `9541565` Add docs/PROGRESS.md resume snapshot
  - `8db9a39` Phase 2: per-game presentation modes (binary-axis fix)
  - `e52681e` Add mozactl (status/doctor/start/stop) + full-compat spec
- To push when ready: `git push` (remote: github.com/C-Nucifora/mozaproxy).

## The hardware (MOZA R25 Ultra Base, `346e:0000`) — verified facts

- Kernel driver `hid-universal-pidff` binds correctly; real FFB works (Assetto
  Corsa is flawless natively). System: Arch, kernel 7.x.
- USB interfaces: two `cdc_acm` (serial — Boxflat uses this) + one `usbhid`
  (the joystick/FFB node).
- Axes: `ABS_X` steering is **unsigned 0..65535**; pedals/others are **signed
  -32768..32767**; two hats -1..1. **128 buttons** from `BTN_JOYSTICK` (0x120).
  FF effects count ~10 (constant/periodic/spring/damper).
- The udev hide-rule (`99-mozaproxy.rules`) is **live**: the real node's
  `ID_INPUT_JOYSTICK` is stripped and `jsN` blocked. Consequence: **the wheel is
  invisible to games unless the mozaproxy daemon is running.**
- `hidraw` node is root-only — intentional (aids hiding; FFB rides evdev, not
  hidraw; Boxflat uses the serial channel which has uaccess).

## The three original failure modes → fix

1. **FH5 crashes on launch** (128-button + PID descriptor) → **Mode A** (slim
   virtual wheel), profile `fh5`.
2. **Axes read binary 0%/100%** → **Mode C** (`normalized`) or **Mode B**
   (`arcade`).
3. **Inconsistent FFB** → single owned relay path + per-profile `ffb_gain`
   clamp (applied to game FF_GAIN writes AND seeded on attach).

## What exists now (code map)

- `mozaproxy.py` — daemon. Grabs real base, builds a virtual uinput device from
  the active **Mode**, relays input real→virtual and FFB virtual→real. Flags:
  `--mode {A,B,C}`, `--deadzone` (steering, modes B/C), `--ffb-gain 0..100`
  (clamps game gain + seeds on attach), `--ffb-autocenter 0..100` (seed),
  `--ffb-drop spring,damper,…` (un-advertise effect types + refuse uploads),
  `--steer/throttle/brake/clutch-src ABS_*`, `--*-invert`.
- `modes/` — presentation modes:
  - `base.py` — `Mode` contract, `RealCaps`/`VirtualSpec`, pure `rescale()` +
    `scale_gain()` math, `SIGNED16/TRIGGER8/HAT`.
  - `wheel.py` — `WheelMode` (A), `NormalizedMode` (C).
  - `gamepad.py` — `GamepadMode` (B, Xbox360 `045e:028e`, rumble→periodic,
    calibratable srcs + inverts + steering deadzone).
  - `__init__.py` — `get_mode(key, ...)` registry, `list_modes()`.
- `profiledb.py` — profile DB (Phases 3–4). TOML schema (mode/buttons/ffb_gain/
  ffb_autocenter/ffb_drop/axes/proton env/steam_input/hooks), seed dir
  `profiles/` shadowed by `~/.config/mozaproxy/profiles/`, calibration overlay
  (`~/.config/mozaproxy/calibration.toml`), `daemon_args()` renders a profile
  into the daemon argv (ORDER IS A CONTRACT — compared verbatim vs the state
  file), `needs_restart()`, `save_profile()` (mozactl new), did-you-mean
  suggestions on unknown names.
- `calibration.py` — `TravelTracker`/`detect_invert` (pure) +
  `interactive_calibrate()` (asks the user to move one control at a time,
  detects the axis + whether it rests at max → invert).
- `mozactl.py` — CLI: `status`, `doctor [--fix]`, `start`, `stop`, `modes`,
  `list`, `run <profile> [--stop-after] [--require-wheel] -- CMD…`, `new
  <name> [--mode M] [--from P] [--force]`, `calibrate`. `run` is the Steam
  glue; it errs on the side of launching (a broken profile/calibration or
  powered-off base never bricks the game start). Profile `[hooks] pre/post`
  run through the shell around the game (post forces wait-mode instead of
  exec). Runtime state: `$XDG_RUNTIME_DIR/mozaproxy.state.json`
  (pid/mode/argv/profile).
- `profiles/` — seeds: `fh5` `ac` `acc` `fs22` `fs25` (A), `normalized` (C),
  `arcade` (B).
- `tests/` — 248 pytest cases (transforms, modes, profiledb, calibration), no
  hardware: `.venv/bin/python -m pytest tests/ -q`.
- `docs/SPEC.md` — design/roadmap. `tools/ffbtest.py`, `tools/fs_wheel_map.py`.

## Modes cheat-sheet

| Mode | Selector | Face | Use when |
|------|----------|------|----------|
| A | `A`/`wheel` | passthrough wheel (default) | sim titles; FH5 crash fix |
| C | `C`/`normalized` | wheel, consistent signed axes | game reads axes as binary |
| B | `B`/`gamepad` | Xbox 360 / XInput pad | controller-only / arcade titles |

Triage a broken game: **A → C → B**, then save whichever works as a profile.

## RESUME HERE — validation runbook (needs base powered on)

```bash
cd ~/Documents/dev/personal/mozaproxy
./install.sh                       # once — refreshes mozactl launcher + udev
# power the wheelbase ON, then:
mozactl doctor                     # base on? driver? real node hidden? group?
mozactl calibrate                  # once: records real pedal axes + inverts
mozactl list                       # see the seed profiles
# Steam per-game launch options (the Phase 3 way):
#   mozactl run fh5 -- %command%
# or manually: mozactl start --mode A && mozactl status  (want: "Ready.")
.venv/bin/python tools/ffbtest.py  # wheel should pull ~1.5s
# bind to "MOZA R25 (mozaproxy)"  (Mode B shows as "MOZA R25 Pad (mozaproxy)")
mozactl stop                       # when done (wheel hidden again)
```

If `~/.local/bin` isn't on PATH, use `.venv/bin/python mozactl.py <cmd>`.

## Open tasks

1. **Validate on hardware** (base was off): FH5 boots w/ FFB via
   `mozactl run fh5 -- %command%`; a binary-axis game reads smooth analog via
   `run normalized` or `run arcade`; `mozactl calibrate` detects the real pedal
   axes. Only the user can run this.
2. Deferred (small): latency measurement tooling, opt-in `--hide-mode lock`
   fallback, `axes.*.range` (accepted but warns "reserved, not yet applied"),
   Boxflat-specific hook integration (generic `[hooks]` shell hooks exist).

## How this was built

Phases 1–3 subagent-driven: locked contracts first, then parallel subagents for
disjoint files, main-thread integration + inline review (Phase 3's multi-agent
review pass was skipped — spend limit — replaced by a manual seam review that
caught 3 launcher bugs: corrupt-calibration bricking `run`, `--stop-after` on a
missing binary, non-canonical mode letters defeating the restart comparison).
Phase 4 built inline (spend limit still in effect), same review discipline.
