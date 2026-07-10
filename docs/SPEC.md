# mozaproxy → full-compat spec

**Goal:** make a MOZA base work in *every* game on Linux, starting with Proton,
by evolving `mozaproxy` from a single-game crash fix into a general-purpose
compatibility layer with selectable per-game **modes**.

Status of this document: design spec. Nothing here is built yet except where it
says "(exists)". Target hardware for development: **MOZA R25 Ultra Base**
(`346e:0000`), Arch, kernel 7.x, `hid-universal-pidff`, Proton (Steam native).

---

## 1. Problem statement

The base works natively (kernel FFB is correct — Assetto Corsa is flawless), but
games fail in *game-specific* ways because each title's input backend digests the
raw device differently. Three confirmed failure modes on this system:

1. **Enumeration crash.** Forza Horizon 5 dies on startup. The base advertises
   **128 buttons** (`0x120–0x2df`) + a PID force-feedback block; FH5's DirectInput
   / `Windows.Gaming.Input` enumeration faults on it. No Proton flag fixes it.
   *(mozaproxy already fixes this — see §3.)*

2. **Binary axes.** Some titles see the wheel/pedals but every axis reads 0% or
   100%. Two contributing causes:
   - Games routed through **XInput / SDL GameController** get a *guessed* mapping
     for an unknown wheel; continuous axes get bucketed to digital.
   - The base's axis conventions are **inconsistent**: steering `ABS_X` is
     unsigned `0..65535`, while pedals (`ABS_Z/RZ/…`) are signed `-32768..32767`.
     Backends that assume one convention misread the other.

3. **Inconsistent FFB.** Force feedback is present but flaky across games,
   because whichever input backend a title picks drives FFB with different
   semantics/gain. Note: the base's `hidraw` node is root-only (no `uaccess`) —
   originally flagged as a bug, but for a *hiding* strategy that is a **feature**
   (a user-accessible raw-HID node could let a misbehaving Proton game
   re-enumerate the 128-button profile and crash again). Boxflat configures the
   base over the `ttyACM` serial channel, which already has `uaccess`, so nothing
   legitimate is blocked. FFB is relayed via **evdev** (`event*`), not hidraw, so
   the root-only hidraw does not impede the relay. The fix for inconsistency is a
   single owned FFB path + per-profile gain (§4/§5), not opening the hidraw node.

**Full compatibility** = for any game, there exists a mode the user can select
that makes the wheel enumerate, expose correct analog axes, and deliver FFB.

---

## 2. Design principle: one clean device, several faces

We never let a game touch the raw base. The base is **grabbed** and hidden; games
only ever see a **virtual device** we synthesize via `uinput`. Because we own the
synthesis, we can present the *same* physical wheel with different **faces
(modes)** to satisfy whatever backend a given game uses.

```
   real MOZA base            mozaproxy core                games (Proton)
  128 btn + PID + FFB ─grab─▶  normalize axes/buttons ─uinput─▶  ONE clean face:
   (hidden by udev)           relay force feedback              · Wheel (dinput)
                            ◀──────────────────────────────    · Gamepad (XInput)
                                                                · Passthrough
```

This is the core bet: **modes are cheap once you own the virtual device.** Adding
a new game's fix is usually "pick an existing mode" or "add one profile row," not
new plumbing.

---

## 3. What exists today (baseline)

`mozaproxy.py` (the daemon) already implements the core of Mode A:

- Finds the real base (VID `0x346e`, has `EV_ABS`+`EV_FF`), **grabs** it
  exclusively (singleton guard).
- Builds a virtual `uinput` wheel: mirrors all axes verbatim, exposes a
  **configurable button count** (default 24, down from 128), re-advertises the
  base's FF effects.
- **Full FFB relay**: `UI_FF_UPLOAD` / `UI_FF_ERASE` / `EV_FF` play/stop + gain +
  autocenter, virtual → real, with effect-id remapping.
- Supervises across unplug/replug; runs as the user (no root at runtime).
- `99-mozaproxy.rules` clears `ID_INPUT_JOYSTICK` on the real node so games skip
  it; `99-boxflat.rules` grants `uaccess` on the serial + `uinput`.
- `tools/ffbtest.py`, `tools/fs_wheel_map.py` helpers. User systemd unit (disabled;
  project switched to manual `run.sh`).

**Gaps** this spec closes:
- Only one face (wheel). No gamepad/XInput mode → binary-axis games unsolved.
- Axes mirrored verbatim → inherits the `0..65535` vs signed asymmetry.
- `hidraw10` `uaccess` gap not addressed → FFB/telemetry inconsistency.
- Manual, per-game, remember-to-start-it UX. No profile system, no launcher.
- Real-device hiding not verified live (real `js1`/`event13` still tagged now —
  rule needs reload/replug, or a stronger hide mode).

---

## 4. Architecture (target)

Four layers. Layer 1 exists; the rest are new.

### Layer 0 — System fixups (one-time, `install.sh`) — *implemented (Phase 1)*
- **udev**: keep the joystick-tag strip + `jsN` block (real node hidden). Do **not**
  grant `uaccess` on the base hidraw — root-only aids hiding (see §1.3).
- **`mozactl doctor`** verifies the pipeline applied and `--fix` reloads/re-triggers
  udev; **`mozactl status`** shows base/driver/hidden/daemon/virtual at a glance.
- Warn if the base fell back to `hid-generic` instead of `hid-universal-pidff`.
- Group/`uaccess` for `/dev/uinput` (exists via Boxflat rule).
- **Consequence now live:** the hide rule is permanent, so the wheel is visible to
  games *only while the daemon runs*. `mozactl start`/`stop` manage that; the base
  must be powered on first.

### Layer 1 — Virtual device core (`mozaproxy.py`, extend)
The daemon, generalized to **render a selected mode** rather than a fixed wheel:
- **Axis normalization stage** between real→virtual: optional remap of axis
  codes, rescale to a target range, apply deadzone/curve. Fixes the signed/unsigned
  asymmetry and lets gamepad mode remap steering→stick, pedals→triggers.
- **Mode renderer**: chooses the virtual descriptor (axis set, button count,
  VID/PID, FF advertisement) from the active mode (§5).
- FFB relay stays; gains a per-mode gain clamp + optional effect filtering for
  backends that choke on specific PID effects.

### Layer 2 — Profiles + launcher (`mozactl`, new CLI)
- **Profile DB**: per-game (or per-backend) settings — which mode, axis map,
  button count, deadzones, FFB gain, Proton env, Steam-Input on/off. Ships a
  seeded DB (FH5, AC/ACC, iRacing, FS22/25, "generic arcade"); user-extensible.
- **Launcher**: `mozactl run <profile> -- %command%` used as a Steam launch
  option. It (a) ensures the daemon is up in the right mode, (b) exports the
  profile's env, (c) execs the game, (d) optionally reverts on exit. This is the
  "different mode per game" mechanism you asked for — one launch-option string per
  game, no manual daemon juggling.

### Layer 3 — Config plane (defer / integrate Boxflat)
Base tuning (rotation angle, FFB strength, curves, the Windows-only "Forza
compatibility" firmware mode) is **Boxflat's** job (serial channel). We don't
duplicate it; `mozactl` may *invoke* Boxflat profiles later. Out of scope for v1.

---

## 5. Modes (the faces)

| Mode | Virtual shape | For | Fixes |
|------|---------------|-----|-------|
| **A. Wheel** *(exists)* | Full axes, ~24 buttons, native FF, VID `346e` | Real sim titles: AC, ACC, iRacing, FH5, dirt/rally | Enumeration crash (FH5) |
| **B. Gamepad/XInput** *(new)* | Presents as an **Xbox 360 pad**: steering→`ABS_X` stick, throttle→`ABS_RZ` (RT), brake→`ABS_Z` (LT), clutch/handbrake→buttons/stick; rumble→FFB | Arcade/console-port titles that only accept a controller | Binary axes, "controller-only" games |
| **C. Normalized wheel** *(new)* | Like A but all axes rescaled to a **consistent signed range**, deadzones applied | Games sensitive to the `0..65535` steering asymmetry | Binary/half-axis from range mismatch |
| **D. Passthrough** *(new, trivial)* | Daemon off / real device unhidden | Games that already work (AC) and want lowest latency | — (escape hatch / A-B testing) |

Mode is chosen by the active **profile**; a profile may also pin a specific
**button count** and **FFB gain**. Modes B/C are new renderers over the same core;
they are the bulk of the new work.

**Gamepad-mode note:** an XInput face needs a virtual pad SDL/Steam recognizes as
a 360 controller (right VID/PID + axis/button layout, or a shipped
`gamecontrollerdb` entry). This is the highest-risk new piece — prototype first
(§8, Phase 2) before committing the profile schema around it.

---

## 6. `mozactl` CLI (spec)

```
mozactl status                 # base detected? driver? hidraw ACL ok? daemon up? mode?
mozactl doctor                 # verify udev/uaccess/driver; print fixes; --fix to apply
mozactl mode <A|B|C|D> [opts]  # (re)start daemon rendering a mode; opts: --buttons --gain --deadzone
mozactl list                   # profiles in the DB
mozactl run <profile> -- CMD…  # ensure mode+env for <profile>, then exec CMD (Steam launch option)
mozactl stop                   # drop to passthrough (Mode D)
mozactl calibrate              # interactive axis map/deadzone helper → writes a profile
```

**Steam usage:** in a game's launch options →
`mozactl run fh5 -- %command%` (wheel mode) or `mozactl run <arcade> -- %command%`
(gamepad mode). One string per game; the tool does the rest.

### Profile schema (TOML, `~/.config/mozaproxy/profiles/*.toml`)
```toml
name = "fh5"
mode = "A"                     # A|B|C|D
buttons = 24
ffb_gain = 100                 # 0-100, clamps relayed gain
[axes]                         # optional per-axis overrides (mode C/B)
steering = { source = "ABS_X", range = [-32768, 32767], deadzone = 0 }
throttle = { source = "ABS_Z", invert = false }
brake    = { source = "ABS_RZ" }
[proton]                       # env injected around %command%
env = { PROTON_ENABLE_WAYLAND = "1" }
steam_input = "off"            # off|default  (disable Steam Input interference)
```

---

## 7. Per-game seed profiles (initial DB)

| Profile | Mode | Rationale |
|---|---|---|
| `fh5` | A, buttons=24 | Enumeration crash → slim wheel face. Verify in-game FFB. |
| `ac` / `acc` | D or A | Already work; passthrough default, wheel face if run through launcher. |
| `iracing`-style | A | Full sim, wants a real wheel. |
| `fs22` / `fs25` | A + `fs_wheel_map` | Farming sims need explicit axis mapping (helper exists). |
| `arcade-generic` | B | Console-port/arcade titles with binary-axis symptom → gamepad face. |
| `normalized` | C | Fallback for a wheel-aware game still misreading axis ranges. |

The workflow for a *new* broken game: try `A`, then `C`, then `B`; whichever works
becomes its profile row. Document this triage in the README.

---

## 8. Roadmap & acceptance criteria

**Phase 1 — Make what exists actually work (quick win).**
- Add the `hidraw` `uaccess` udev rule; `mozactl doctor` verifies base +
  driver + ACLs + hide-rule-applied.
- Confirm the real-device hide truly takes effect live (reload/replug; add opt-in
  `--hide-mode lock` fallback that root-locks the node if tag-strip is insufficient).
- Run mozaproxy (Mode A) and **validate FH5 launches with FFB**. This is the
  headline result already designed for.
- *Accept:* `mozactl status` green; FH5 boots + has FFB; AC still works.

**Phase 2 — Normalized + Gamepad modes (the binary-axis fix).** *Implemented; in-game validation pending.*
- ✅ `modes/` package with a `Mode` contract (`build_spec`/`map_input`/
  `translate_effect`) and pure axis math (`rescale`), unit-tested base-off.
- ✅ Mode C (normalized): rescales every non-hat axis to consistent signed range,
  optional steering deadzone. `mozaproxy.py`/`mozactl` gained `--mode`.
- ✅ Mode B (gamepad): Xbox-360 face (vid/pid `045e:028e`), steering→stick,
  throttle→RT, brake→LT, buttons→pad, rumble→periodic FFB translation. Pedal
  source axes are calibratable defaults.
- *Accept (pending hardware):* a currently-binary game reads smooth analog in C
  or B. Needs the base on + the user to test in-game.

**Phase 3 — Profiles + launcher UX.**
- `mozactl run <profile> -- %command%`, profile DB, seeded profiles, Steam
  launch-option docs.
- *Accept:* switching games = changing one launch-option string; no manual daemon
  steps.

**Phase 4 — Polish & reach.**
- FFB gain/effect tuning per profile; auto-detect suggestions; optional Boxflat
  profile hooks. Explore non-Proton (native Linux titles, Wine-non-Steam, Lutris).

---

## 9. Risks / open questions

- **XInput face fidelity (Mode B):** hardest piece; SDL/Steam must accept the
  virtual pad as a 360 controller. Prototype before locking the schema.
- **Latency:** each mode adds an evdev→uinput hop. Measure; Mode D exists as the
  zero-overhead escape hatch for titles that don't need us.
- **Anti-cheat (EAC/BattlEye):** a virtual input device *should* be fine (it's not
  memory tampering), but confirm per online-title before claiming support.
- **hidraw hide vs FFB:** verify the relay path we use (evdev FF, not raw hidraw)
  is unaffected by whatever hidraw hiding we add.
- **Boxflat coexistence:** Boxflat uses the serial channel, orthogonal to our
  joystick node — confirm no contention when both run.

---

## 10. Non-goals (v1)
- Replacing Boxflat / base firmware tuning.
- A GUI (CLI + Steam launch options first; GUI only if warranted later).
- Windows.
