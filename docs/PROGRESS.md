# mozaproxy — progress & resume state

Last updated: 2026-07-11. Snapshot for resuming after a restart.

**Repo working directory:** `/home/christian/Documents/GitHub/mozaproxy`

---

## One-line status

Phase 1 (mozactl tooling) and Phase 2 (per-game presentation modes / binary-axis
fix) are **built, tested, and committed locally**. Nothing is pushed. The only
open work is **in-game validation on hardware** (the base was powered off during
development) and **Phase 3** (profiles + launcher + calibrate).

## Git state

- Branch: `master`. **Local commits, NOT pushed.**
- Recent commits:
  - `8db9a39` Phase 2: per-game presentation modes (binary-axis fix)
  - `e52681e` Add mozactl (status/doctor/start/stop) + full-compat spec
  - `512a068` Singleton guard + manual run helper (pre-existing)
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
   virtual wheel). Built pre-session; just needs the daemon running.
2. **Axes read binary 0%/100%** (unsigned-steering vs signed-pedals convention
   mismatch; XInput/SDL mismapping) → **Mode C** (normalized signed axes) or
   **Mode B** (gamepad).
3. **Inconsistent FFB** → single owned relay path + per-mode gain (Mode B
   translates rumble→periodic).

## What exists now (code map)

- `mozaproxy.py` — daemon. Grabs real base, builds a virtual uinput device from
  the active **Mode**, relays input real→virtual and FFB virtual→real. Has
  `--mode {A,B,C}` / `--deadzone`.
- `modes/` — presentation modes:
  - `base.py` — `Mode` contract (`build_spec`/`map_input`/`translate_effect`),
    `RealCaps`/`VirtualSpec`, pure `rescale()` math, `SIGNED16/TRIGGER8/HAT`.
  - `wheel.py` — `WheelMode` (A, passthrough), `NormalizedMode` (C, signed axes).
  - `gamepad.py` — `GamepadMode` (B, Xbox360 `045e:028e`, rumble→periodic).
  - `__init__.py` — `get_mode(key, ...)` registry, `list_modes()`.
- `mozactl.py` — CLI: `status`, `doctor [--fix]`, `start [--mode X] [--deadzone]`,
  `stop`, `modes`. Installed to `~/.local/bin/mozactl` by `install.sh`.
- `tests/` — 44 pytest cases (transforms + all 3 modes + registry), run with **no
  hardware**: `.venv/bin/python -m pytest tests/ -q`.
- `docs/SPEC.md` — full design/roadmap. `tools/ffbtest.py`, `tools/fs_wheel_map.py`.

## Modes cheat-sheet

| Mode | Selector | Face | Use when |
|------|----------|------|----------|
| A | `A`/`wheel` | passthrough wheel (default) | sim titles; FH5 crash fix |
| C | `C`/`normalized` | wheel, consistent signed axes | game reads axes as binary |
| B | `B`/`gamepad` | Xbox 360 / XInput pad | controller-only / arcade titles |

Triage a broken game: **A → C → B**.

## RESUME HERE — validation runbook (needs base powered on)

```bash
cd ~/Documents/GitHub/mozaproxy
./install.sh                       # once — refreshes mozactl launcher + udev
# power the wheelbase ON, then:
mozactl doctor                     # base on? driver? real node hidden? group?
mozactl start --mode A             # or C / B
mozactl status                     # want: "Ready."
.venv/bin/python tools/ffbtest.py  # wheel should pull ~1.5s
# launch game via Steam launch options, e.g.:
#   PROTON_ENABLE_WAYLAND=1 %command%
# bind to "MOZA R25 (mozaproxy)"  (Mode B shows as "MOZA R25 Pad (mozaproxy)")
mozactl stop                       # when done (wheel hidden again)
```

If `~/.local/bin` isn't on PATH, use `.venv/bin/python mozactl.py <cmd>`.

## Open tasks

1. **Validate on hardware** (base was off): FH5 boots w/ FFB in Mode A; a
   binary-axis game reads smooth analog in Mode C or B. Only the user can run this.
2. **Known caveat:** gamepad-mode pedal source axes are best-guess defaults
   (`throttle=ABS_Z`, `brake=ABS_RZ`); may need swapping per real device.
3. **Phase 3 (not started):** profile DB + `mozactl run <profile> -- %command%`
   Steam launch-option launcher + `mozactl calibrate` (records real pedal axis
   assignment). See `docs/SPEC.md` §4/§6/§8.

## How this was built

Subagent-driven: a locked `modes/base.py` contract, then parallel subagents for
`wheel.py`, `gamepad.py`, and `tests/`, with main-thread integration + review.
