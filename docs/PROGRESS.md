# mozaproxy — progress & resume state

Last updated: 2026-11-21. Snapshot for resuming work. `git log` and the README
are authoritative where they differ.

## Status

Phases 1–4 of [`SPEC.md`](SPEC.md) are built and committed on `master`. The
suite needs no hardware: `.venv/bin/python -m pytest tests/ -q` (504 cases).

Added since July 2026:

- **Per-profile identity.** `identity = "real"` clones the base, or an
  `[identity]` table sets a fixed name/vendor/product. Games key off it (FH5,
  AC).
- **`button_codes`.** Exposes exactly the listed real button codes;
  `--button-codes` on the daemon. It decouples which buttons appear from how
  many.
- **`mozactl watch`.** A live axis %-travel and button view, ending with a
  per-axis analog-vs-binary summary. `--log` writes a shareable file.
- **`mozactl start -- <daemon flags>`.** Passes the flags through to the daemon.
- **Daemon detection.** `stop`/`run` recognise the daemon by its script name,
  not by a substring of the command line.

## Games

| Game | Profile | State |
|---|---|---|
| Forza Horizon 5 | `fh5` (A, identity "MOZA R9 Base" `346e:0002`) | Works. The base's own id `346e:0000` crashes it, whatever the button count. |
| Assetto Corsa | `ac` (A, cloned real identity, 128 buttons) | Read the virtual wheel in July, with the default identity and 24 buttons. On 2026-11-21 the seed gained the cloned real identity (AC's saved binding keys on `346e:0000`) and all 128 buttons. Re-check in game. |
| JDM: Japanese Drift Master | `jdm` (C, identity `346e:0fff`) | **Does not work** through the virtual wheel on current Proton: every axis arrives as a signed 32-bit field that JDM reads as pegged. See [`PROTON-AXES.md`](PROTON-AXES.md). The `main` branch's hidraw route drove JDM build 25209638 on 2026-09-18, without force protection; it hasn't been re-tested on 26542938. |
| ACC, FS22, FS25 | `acc`, `fs22`, `fs25` | Seeds; no in-game result recorded here. |

## The hardware (MOZA R25 Ultra Base, `346e:0000`) — verified facts

- **Driver and FFB.** The kernel driver `hid-universal-pidff` binds correctly,
  and native FFB is correct.
- **USB interfaces.** Two `cdc_acm` serial interfaces (Boxflat uses these) and
  one `usbhid` (the joystick/FFB node).
- **Axes.** `ABS_X` steering is **unsigned 0..65535**; the other axes are
  **signed −32768..32767**; one hat switch, reported as `ABS_HAT0X`/`ABS_HAT0Y`
  (−1..1).
- **Buttons.** 128, in two runs: `0x120..0x12f` (16) and `0x270..0x2df` (112).
  There is no `0x130` (`BTN_GAMEPAD`), so SDL never auto-maps the base as a
  gamepad. SDL also lists `346e:0000` as a wheel.
- **Hide rule.** The udev hide-rule (`99-mozaproxy.rules`) strips
  `ID_INPUT_JOYSTICK` from the real node and blocks `jsN`, so games see the
  wheel only while the daemon runs.

## Code map

- **`mozaproxy.py`** — the daemon. It grabs the real base, builds a virtual
  uinput device from the active **mode**, relays input real→virtual and FFB
  virtual→real. Flags include:
  - `--mode {A,B,C}`, `--buttons`, `--button-codes`;
  - `--identity-real`, `--name`/`--vendor`/`--product`;
  - `--deadzone` (modes B and C), `--axis-range` (mode C), `--ffb-gain`,
    `--ffb-autocenter`, `--ffb-drop`;
  - `--steer/throttle/brake/clutch-src`, `--*-invert` (mode B).
- **`modes/`** — the presentation modes. `wheel.py` has `WheelMode` (A) and
  `NormalizedMode` (C), `gamepad.py` has `GamepadMode` (B, Xbox 360
  `045e:028e`), and `base.py` holds the `Mode` contract and the pure axis math.
- **`profiledb.py`** — the TOML profile DB. Seeds in `profiles/` are shadowed
  by `~/.config/mozaproxy/profiles/`, with a calibration overlay.
  `daemon_args()` renders a profile into the daemon argv. **Its order is a
  contract**: it's compared verbatim with the state file.
- **`calibration.py`** — interactive pedal-axis detection.
- **`mozactl.py`** — the CLI: `status`, `doctor`, `start`, `stop`, `modes`,
  `list`, `run`, `new`, `logs`, `watch`, `calibrate`. `run` is the Steam glue
  and errs on the side of launching the game. Runtime state lives in
  `$XDG_RUNTIME_DIR/mozaproxy.state.json`.
- **`profiles/`** — seeds: `fh5`, `ac`, `acc`, `fs22`, `fs25` (A); `normalized`
  and `jdm` (C); `arcade` (B).
- **`docs/`** — `SPEC.md` (design and roadmap), `PROTON-AXES.md` (the JDM
  binary-axis analysis), this file.

## Open work

1. **JDM.** Choose a route from [`PROTON-AXES.md`](PROTON-AXES.md). The next
   step needs the user at the powered base:
   - re-test the `main` branch's hidraw route on JDM build 26542938, with
     tracing;
   - run a ~2% force probe of how the firmware handles effect duration and
     Stop/Start.
2. **Re-test `jdm` through the virtual wheel** once a Proton based on Wine 11.1
   or later (or carrying its axis-size change) ships.
3. **Known limitation.** `virtual_present()`, used by `status` and `start`, finds
   the virtual wheel by "mozaproxy" in its name or by a MOZA vendor id. A
   profile with a custom name **and** a non-MOZA vendor isn't detected there.
   `watch` uses the daemon's recorded `--name` instead.
4. **Deferred (small):** latency tooling, an opt-in `--hide-mode lock`, and
   `axes.*.range`.

## Resume

```bash
cd <this checkout>
.venv/bin/python -m pytest tests/ -q
mozactl doctor        # base on? driver? real node hidden? group?
mozactl list          # profiles
mozactl watch         # what the wheel / virtual wheel sends
```

`install.sh` writes `~/.local/bin/mozactl` with the checkout's **absolute
path**. If the checkout moves, re-run `./install.sh` or rewrite that launcher,
or every `mozactl run … -- %command%` Steam launch option stops starting its
game. If `~/.local/bin` isn't on PATH, use `.venv/bin/python mozactl.py <cmd>`.
