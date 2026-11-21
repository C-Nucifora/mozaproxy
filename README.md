# mozaproxy

Present a MOZA wheelbase to games as a **clean virtual wheel**, so titles that
crash on the raw base (notably **Forza Horizon 5** under Proton) launch and
run — with **force feedback intact**.

No root at runtime. Pure Linux input plumbing.

---

## The problem

Forza Horizon 5 crashes on startup whenever a MOZA base with the `346e:0000` id
(R16/R21/R25) is connected. It launches fine with the wheel unplugged, then the
game dies during input enumeration, through **every** path Proton offers:

- Default / DirectInput → `EXCEPTION_ACCESS_VIOLATION`.
- `PROTON_PREFER_SDL=1` → routed to `Windows.Gaming.Input.Gamepad` (a Proton
  *semi-stub*) → `EXCEPTION_ILLEGAL_INSTRUCTION`.

No Proton launch flag fixes it. The trigger is the base's **USB identity**:

- The base's own `346e:0000` crashes FH5, real or cloned.
- A slim 24-button virtual wheel wearing `346e:0000` still crashed, so the
  base's 128 buttons (the first suspect) are not what triggers it.
- With `346e:0002` and mozaproxy's default name, FH5 launched but didn't
  accept the wheel.
- Presenting as a MOZA R9 (`346e:0002`, named "MOZA R9 Base"), it launches and
  binds — see [`profiles/fh5.toml`](profiles/fh5.toml).

MOZA's own Windows workaround is a firmware "Forza Horizon compatibility mode",
which isn't reachable from Linux (Boxflat can't set it).

## The fix

`mozaproxy` hides the real base and gives games a virtual wheel it controls:

1. Opens and exclusively **grabs** the real MOZA evdev device.
2. Creates a **virtual joystick** (`uinput`) that mirrors the real axes and a
   small, game-friendly button count (default **24**), advertising the same
   force-feedback effects — i.e. the shape of a normal, supported wheel.
3. **Relays** events real → virtual, and force feedback (effect upload, erase,
   play/stop, gain, autocenter) virtual → real.
4. Wears whatever **identity** a game needs, per profile (the `fh5` profile
   presents as a MOZA R9).

A udev rule clears `ID_INPUT_JOYSTICK` on the real node so games/SDL/Wine skip
it, while the daemon still opens it directly by path. Games see only the clean
virtual wheel.

```
   real MOZA base            mozaproxy daemon                games (Proton)
  128 buttons + PID  ──grab──▶  mirror axes/buttons  ──uinput──▶  clean 24-btn
     (hidden from             relay force feedback              wheel + FFB
      enumeration)         ◀──────────────────────────────────
```

## Requirements

- Linux with `uinput` (standard).
- Python 3.10+.
- A MOZA base already working on Linux (e.g. via the `hid-universal-pidff`
  driver and [Boxflat](https://github.com/lawstorant/boxflat)).

## Install

```bash
git clone https://github.com/C-Nucifora/mozaproxy.git ~/Documents/GitHub/mozaproxy
cd ~/Documents/GitHub/mozaproxy
./install.sh
```

The installer creates a venv, installs the udev rule, adds you to the `input`
group (fallback access), installs a `mozactl` launcher into `~/.local/bin`, and
installs a (disabled) **user** systemd service.

> **Important:** the udev rule *hides* the real base from games permanently, so
> the wheel is visible to games **only while the daemon runs**. Start it before
> playing, stop it when done. Replug the base (or reboot) once after install so
> the rule applies.

## Verify

```bash
mozactl doctor     # base powered on? driver bound? real node hidden? group ok?
mozactl start      # bring up the clean virtual wheel
mozactl status     # expect: Base OK, Daemon running, Virtual wheel present -> "Ready."

# force-feedback relay: a constant force at ~50% of the base's strength for
# ~1.5 s (about 12 Nm on a 25 Nm base at full strength). Keep hands and
# objects clear of the rim:
./.venv/bin/python tools/ffbtest.py
```

(If `~/.local/bin` isn't on your PATH, use `./.venv/bin/python mozactl.py ...`.)

Then launch Forza through the `fh5` profile, so the virtual wheel wears the
identity FH5 accepts. Set its Steam launch options to:

```
mozactl run fh5 -- %command%
```

A plain `mozactl start` presents the default face ("MOZA R25 (mozaproxy)"),
which FH5 launches with but doesn't accept as a wheel. The wheel needs no
Proton options; display options such as `PROTON_ENABLE_HDR=1` can go in front
of `mozactl`.

In the game, bind to the virtual wheel. Its name depends on the profile, because
some games key their behaviour off the wheel's USB identity:

- `fh5` presents as **"MOZA R9 Base"** (`346e:0002`). FH5 matches wheels against
  a supported-hardware list, and the base's own id `346e:0000` crashes it, so
  the profile wears a supported id that launches.
- `ac` sets `identity = "real"`, cloning the base's own name and ids (e.g.
  "Gudsen MOZA R25 Ultra Base"), and exposes all 128 of its buttons, so
  Assetto Corsa's saved wheel binding still matches.
- `jdm` shows **"MOZA Wheelbase (mozaproxy)"** (`346e:0fff`).
- Mode B profiles such as `arcade` show an Xbox 360 pad,
  **"MOZA R25 Pad (mozaproxy)"** (`045e:028e`).
- Other profiles, and a plain `mozactl start`, show **"MOZA R25 (mozaproxy)"**
  (`346e:0002`).

## Modes (per-game faces)

The same wheel can wear different faces. Pick one with `--mode`
(`mozactl modes` lists them):

| Mode | Selector | Presents as | Use when |
|------|----------|-------------|----------|
| **A** | `A` / `wheel` | Passthrough wheel (default) | Wheel games, including FH5 (with the `fh5` profile's identity) |
| **C** | `C` / `normalized` | Wheel with every axis on one **signed** range, optional steering deadzone | Software that reads the evdev values directly and mishandles the base's unsigned steering (`0..65535`) next to its signed pedals. Under Proton, SDL rescales every range, so C can't change how a game decodes the axes; only its steering deadzone still reaches the game — see below |
| **B** | `B` / `gamepad` | **Xbox 360 / XInput** pad (steering→stick, throttle→RT, brake→LT) | Controller-only titles, and Proton games that read the wheel's axes as binary but accept a controller (rumble-only force feedback) |

**Triage a broken game:** start with `A`. If a Proton game reads the axes as
binary (0%/100%, or pegged on one side), mode C won't help — see
[Proton games that read axes as binary](#proton-games-that-read-axes-as-binary).
Mode B is the fallback when the game accepts a controller.

```bash
mozactl start --mode C --deadzone 0.03   # one signed range + steering deadzone
mozactl start --mode B                   # XInput gamepad
```

> Gamepad mode's throttle/brake source axes are best-guess defaults
> (`throttle=ABS_Z`, `brake=ABS_RZ`); the clutch is off until a source is set. Run **`mozactl calibrate`** once (daemon
> stopped, base on) to record your pedals' real axes — every mode B profile
> picks the calibration up automatically (wheel modes mirror the real axes and
> don't need it).

## Profiles & Steam launch options

Instead of juggling `mozactl start/stop` per game, give each game a **profile**
and one launch-option string. A profile bundles: mode, button count, FFB gain,
axis sources/deadzone/invert, and Proton env vars.

```bash
mozactl list                       # shipped + user profiles
mozactl run fh5 -- game_cmd        # ensure daemon in the right mode, then exec
mozactl calibrate                  # record pedal axes -> ~/.config/mozaproxy/calibration.toml
```

**Steam:** set a game's launch options to

```
mozactl run fh5 -- %command%
```

That's the whole per-game switch: `run` starts (or restarts) the daemon in the
profile's mode only when needed, injects the profile's env vars, and `exec`s the
game so Steam still tracks it. If the base is powered off, the game still
launches (it just sees no wheel); add `--require-wheel` to make that fatal, or
`--stop-after` to stop the daemon when the game exits.

Shipped seeds: `fh5`, `ac`, `acc`, `fs22`, `fs25` (Mode A), `normalized` and
`jdm` (Mode C), `arcade` (Mode B). `jdm` does not work on current Proton — see
[Proton games that read axes as binary](#proton-games-that-read-axes-as-binary).
Your own profiles live in `~/.config/mozaproxy/profiles/*.toml` and shadow seeds
by name:

```toml
# ~/.config/mozaproxy/profiles/mygame.toml   (scaffold one: mozactl new mygame)
mode = "A"                    # A|B|C (see Modes above); "D" = passthrough: no
                              # virtual wheel, and the hide rule still hides the base
buttons = 24
# button_codes = [0x120, 0x2c0, 0x2c1]   # expose EXACTLY these real button codes
                              # (wins over `buttons`, which then applies only if
                              # none of them exist on the base): keeps the count
                              # small while still including buttons high in the
                              # code space. Codes the base doesn't report are
                              # skipped and logged (`mozactl logs`). Find which
                              # code is which with `mozactl watch --real`.
identity = "real"             # clone the real base's USB identity (games bound to it, e.g. AC; never FH5)
                              # …or an explicit [identity] table with name/vendor/product
ffb_gain = 80                 # clamp relayed FFB gain to 80%
ffb_autocenter = 0            # seed autocenter (0 = force off) on attach
ffb_drop = ["spring", "damper"]   # hide effect types the game's backend faults on
notes = "one line, shown by mozactl list"
[axes]                        # modes B/C only; mode A mirrors the real axes
steering = { deadzone = 0.03 }                    # modes B and C
throttle = { source = "ABS_Z", invert = false }   # mode B; usually from calibrate
[proton]
env = { PROTON_ENABLE_WAYLAND = "1" }
steam_input = "off"           # prints a reminder; Steam can't be set from here
[hooks]
pre  = "boxflat --whatever"   # shell, before the daemon/game (e.g. base tuning)
post = "notify-send done"     # shell, after the game exits (forces wait-mode)
```

FFB tuning knobs: `ffb_gain` (0–200) clamps every gain the game sets **and**
seeds the base on attach, so below 100 it caps output even for games that
never touch gain; above 100 it boosts the effects themselves.
`ffb_drop` un-advertises effect types (some backends fault on specific PID
effects); the kernel then rejects their upload before it reaches the relay. `ffb_autocenter` seeds a baseline the game
may later override. Hooks run through the shell with the profile's env — the
intended use is invoking Boxflat or other base tuning around a game session; a
`post` hook makes `run` wait on the game instead of exec-replacing itself.

### Beyond Steam

`mozactl run` execs whatever command follows `--`, so the same profiles work
outside Steam:

- **Lutris**: set *System options → Command prefix* to `mozactl run <profile> --`.
- **Native titles / plain Wine**: `mozactl run ac -- ./the-game` or
  `mozactl run arcade -- wine game.exe`.
- **No command at all**: `mozactl run <profile>` just puts the daemon in the
  right mode (and runs the pre hook), then returns.

## Usage / tuning

Everyday use is via `mozactl`:

```bash
mozactl start                 # start the virtual wheel (Mode A, default)
mozactl start --mode C        # start in a specific mode
mozactl modes                 # list modes
mozactl list                  # list game profiles
mozactl run <profile> -- CMD  # per-game launcher (Steam launch option)
mozactl new <name> [--from P] # scaffold a user profile
mozactl watch [--real|--virtual]  # live axis %-travel + button codes (see below)
mozactl calibrate             # record real pedal axes (daemon stopped)
mozactl status                # health of the whole pipeline
mozactl stop                  # hide the wheel again
```

Or run the daemon directly (foreground, Ctrl-C to stop):

```bash
./run.sh -v                   # foreground, debug logging (traces FFB)
./.venv/bin/python mozaproxy.py --buttons 32
```

Useful flags:

| flag | default | meaning |
|------|---------|---------|
| `--buttons N` | 24 | number of buttons to expose (lowest N real codes) |
| `--button-codes A,B,…` | — | expose exactly these real codes (hex ok); wins over `--buttons`, which applies only if none of them exist |
| `--name STR` | `MOZA R25 (mozaproxy)` | virtual device name |
| `--vendor` / `--product` | `0x346e` / `0x0002` | virtual USB ids |
| `--once` | off | don't supervise/re-attach; exit when device leaves |

### Seeing what the wheel sends: `mozactl watch`

Before changing a profile, look at what is actually being emitted:

```bash
mozactl watch --virtual                       # what GAMES see (daemon running)
mozactl stop && mozactl watch --real          # the raw base (daemon stopped)
mozactl watch --virtual --duration 15 --log   # + a shareable log file
```

With no flag it reads the virtual wheel while the daemon runs and the raw base
otherwise. The daemon holds an exclusive grab on the base, and a grabbed node
is silent to everyone else, so `--real` refuses to run until you `mozactl stop`.

It shows every axis as a live %-travel bar and every button as it fires, with
its evdev code — that is how you find the codes to list in `button_codes`. When
it ends (Ctrl-C, or `--duration SECONDS`) it prints a per-axis summary:

```
  axis          samples  distinct  seen min..max    histogram over range
  ABS_X            5300      3661  1..65534         [▄▂▁▁▁▁▁▁▁▁▁▆█▁▁▁▁▁▁▁▁▁▂▄]
  ABS_Z             400         2  -32768..32767    [█                      █]
  ABS_RZ              0         0  (no motion)      [                        ]
```

`distinct` is the verdict. A swept analog axis shows hundreds or thousands of
distinct values and a histogram with no gaps (`ABS_X`); an axis that only ever
reports its two ends shows about two (`ABS_Z`). If `watch --virtual` is analog
but a Proton game reads binary, the fault is downstream of mozaproxy: Proton
turns every axis of the virtual wheel into a signed 32-bit field, and no wheel
mode (A or C), `axis_range`, identity or button setting changes that. Mode B
avoids it only by turning the wheel into an XInput pad — see
[Proton games that read axes as binary](#proton-games-that-read-axes-as-binary).

`--log [FILE]` also writes a plain-text log (default
`$XDG_RUNTIME_DIR/mozaproxy-watch.log`): the event stream, thinned to about
50 lines a second per axis, followed by the same summary. Piped or redirected,
`watch` prints button presses line by line and then the summary.

## Proton games that read axes as binary

Under Proton, the virtual wheel reaches Windows games through Proton's SDL
backend. That backend turns every axis into a signed 32-bit HID field
(−32768..32767), whatever range mozaproxy advertises. Most games read that
correctly; FH5 and Assetto Corsa do. A game that only sign-extends 16-bit
fields reads every negative value as pegged, so half of each axis's travel
sticks at an end. **JDM: Japanese Drift Master** is the known case.

No wheel setting changes those fields: not mode A or C, `axis_range`, identity
or buttons. Mode B can sidestep them, for games that accept a controller, by
presenting an Xbox 360 pad that the game reads through XInput. It's a pad, not
a wheel:
- only the first 11 buttons;
- the clutch only on a stick axis, and only once a clutch source is set
  (`mozactl calibrate`, or `axes.clutch.source` in the profile);
- rumble-only force feedback, and not gentle: each rumble becomes a 10 Hz sine,
  and a full-strength rumble drives it at the base's full force. `ffb_gain` is
  the only setting that scales it.

It hasn't been tried in JDM.

Wine 11.1 fixed this upstream by sizing the fields to the axis range, but no
Proton carries that change yet (checked 2026-11-21). Until one does, the only
route that has worked for JDM is the hidraw route on this repository's `main`
branch, which bypasses SDL (setup: `compat/README.md` on that branch). That
route doesn't use mozaproxy at all:
- Stop the daemon first (`mozactl stop`).
- The game's force feedback then reaches the base directly, without mozaproxy's
  `ffb_gain` clamp. (mozaproxy has no stale-force guard either; the one
  proposed for this route is in
  [`docs/PROTON-AXES.md`](docs/PROTON-AXES.md#force-protection-on-hidraw-routes).)

The verified mechanism, what the July JDM attempts actually showed, and the
ranked options are in [`docs/PROTON-AXES.md`](docs/PROTON-AXES.md).

## How it hides the real device

The daemon does **not** depend on udev tags — it opens the base by path and
grabs it. The udev rule only changes what *other* programs see: it clears
`ID_INPUT_JOYSTICK` on the real event node (so input enumerators skip it) and
blocks the legacy `jsN` node. Access for the daemon is preserved via `uaccess`
(already applied by seat rules) plus `GROUP=input`.

Because the rule hides the real node permanently, the wheel is available to games
**only while the daemon runs**. Start it with `mozactl start` before playing and
`mozactl stop` when done (a disabled systemd unit is also installed if you prefer
always-on: `systemctl --user enable --now mozaproxy`). Boxflat still configures
the base normally (it talks over the serial channel, not this joystick node).

If your distro's Proton build still finds the real device after the tag strip,
the stronger fallback is to have the daemon-owner lock the node (root chmod);
open an issue and it can be added as an opt-in `--hide-mode lock` (deferred; see
[`docs/SPEC.md`](docs/SPEC.md) §8).

## Status

Built and verified (hardware-free tests + live device plumbing): device
creation, grab, event mirroring, the full force-feedback relay path
(upload/play/erase to the real base), the three presentation modes, per-profile
identities and button codes, the profile DB + `mozactl run` Steam launcher,
`mozactl calibrate`, `mozactl watch`, and the status/doctor/start/stop tooling.

In game:
- FH5 works through the `fh5` profile.
- Assetto Corsa read the virtual wheel in July. The `ac` profile's cloned
  identity and 128 buttons (added 2026-11-21) still need an in-game check.
- JDM does not work on current Proton (see
  [above](#proton-games-that-read-axes-as-binary)).
- Mode B has no in-game result yet.

The design and roadmap are specced in [`docs/SPEC.md`](docs/SPEC.md). Phases
1–4 are implemented; its §8 lists the small deferred items. Current state and
open work: [`docs/PROGRESS.md`](docs/PROGRESS.md).

## License

MIT — see [LICENSE](LICENSE).
