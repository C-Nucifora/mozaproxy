# Proton games that read the wheel's axes as binary

Last verified: 2026-11-21. Checked against:
- the installed GE-Proton builds 10-3, 10-12, 10-25, 10-34, 11-7 and 11-12;
- Valve's Proton 11.0-2e and Proton Experimental 11.0-20261112;
- a system (non-Proton) Wine 11.22 package;
- SDL 3.4.18 from Steam Linux Runtime 4.0;
- JDM: Japanese Drift Master, Steam build 26542938.

Everything marked *verified* was read from those binaries (see
[Evidence](#evidence)).

## Symptom

`mozactl watch --virtual` shows smooth analog axes with thousands of distinct
values. The game's input screen shows the same axes jumping between extremes:
either steering that works one way and pegs the other (JDM's input screen showed
"2000%"), or pedals that read only 0% or 100%.

Known case: **JDM: Japanese Drift Master** (Unreal Engine). FH5 and Assetto
Corsa read the same virtual wheel correctly.

## Cause

Two facts combine.

**1. Proton presents every axis of the virtual wheel as a signed 32-bit HID field** *(verified)*.
- A uinput device has no hidraw node, so Proton's `winebus` always hands it to
  its SDL backend.
- The evdev branch defers every input device to SDL unconditionally. The only
  exception is Steam Input's virtual pad (`28de:11ff`). No registry key or
  environment variable changes this.
- SDL rescales each axis onto −32768..32767, whatever range the virtual device
  advertises.
- winebus then describes every axis with `REPORT_SIZE 32` and logical
  −32768..32767.
- Every Proton build listed above does this. The GE-Proton10 builds are based on
  Wine 10.0 and the others on Wine 11.0, so none of them includes Wine 11.1's
  change (see [The fix upstream](#the-fix-upstream)).

**2. JDM reads HID axis values as unsigned unless the field is 16 bits wide** *(verified)*.

JDM's RawInput plugin reads each axis with `HidP_GetUsageValue`. It
sign-extends the raw value only when the field is 16 bits and the logical range
spans zero. Every other field is converted as **unsigned**, divided by
`(max − min)`, offset by a centre ratio, and **not clamped**:

| Field | Raw value | JDM reads |
|---|---|---|
| 16-bit, 0..65535 | 0 / 32768 / 65535 | 0% / 50% / 100% |
| 16-bit, −32768..32767 | −32768 / 0 / 32767 | 0% / 50% / 100% |
| 32-bit, −32768..32767 (Proton) | 0 / +32767 | 50% / 100% |
| 32-bit, −32768..32767 (Proton) | any negative value | about 65 537 × full scale (pegged) |
| any size, LogicalMin 0 | min / max | 0% / 100% |

So half of every axis's travel pegs. The base's own HID descriptor uses 16-bit
fields (steering 0..65535, the rest −32768..32767). That's why JDM reads the
**physical** base correctly when Proton opens its hidraw node directly.

The centre ratio lives in a per-axis field that an internal axis-offset setter
in JDM can overwrite. When the game calls that setter is unknown. If it does,
16-bit sign extension switches off silently. Fields with LogicalMin 0 don't
depend on the ratio.

## What does not help

- **The wheel modes (A, C) and `axis_range`.** SDL rescales whatever range
  mozaproxy advertises before winebus sees it. The game therefore decodes A and
  C identically; only C's optional steering deadzone still reaches it.
  `axis_range` only matters to software that reads the evdev values directly.
- **Identity or button changes.** With the real button codes (no
  `BTN_GAMEPAD`), every identity keeps the 32-bit joystick layout. The one
  combination that changed the outcome (attempt 5, below) did so by turning the
  wheel into an SDL gamepad, which loses the clutch and most buttons.
- **Proton options.** `PROTON_ENABLE_HIDRAW` only applies to devices with a
  hidraw node, which a uinput wheel doesn't have. `SDL_GAMECONTROLLER_IGNORE_DEVICES`
  can hide a device, but it can't reroute it.

Mode B sidesteps the 32-bit fields only by presenting an Xbox 360 pad instead
of a wheel (route 5 below).

### The July JDM attempts, explained

These six configurations were tried in July 2026. The explanations were
reconstructed from the git history and from the SDL and winebus binaries,
because the July logs no longer exist.

| # | Configuration | Result |
|---|---|---|
| 1 | mode A, R9 identity `346e:0002` | Steering worked one way and pegged the other ("2000%") |
| 2 | mode C (signed range), R9 identity | Same |
| 3 | mode C, `axis_range = [0, 32767]`, R9 identity | Same |
| 4 | R9 identity, after redoing JDM's custom binding | 0%/100% binary |
| 5 | mode C, `axis_range = [0, 32767]`, identity `346e:0fff`, 24 buttons | Analog steering, throttle and brake; clutch and wheel buttons dead |
| 6 | as 5, but `buttons = 128` with the real button codes (commit `ee3d234`) | Binary again |

**Attempts 1–4: binary.** SDL lists the real MOZA ids (`346e:0000`, `0002`,
`0004`, …) as wheels, and winebus never opens a wheel as a gamepad. So the game
got the 32-bit joystick layout.

**Attempt 5: analog, but the clutch and buttons were dead.**
- Before `ee3d234`, the daemon exposed a synthetic button block `0x120..0x137`.
  It includes `BTN_GAMEPAD` (`0x130`), the only capability SDL's Linux
  auto-mapping checks.
- `0fff` is not on SDL's wheel list, so SDL mapped the device as a **gamepad**.
- winebus then built its gamepad layout: two sticks, two triggers (0..32767)
  and 14 buttons, with no clutch axis. That explains the dead clutch and
  buttons.
- The stick is still a signed 32-bit field, so the analog steering implies JDM
  read the pad through XInput. That step is inferred, not traced.

**Attempt 6: binary again.** The real codes skip `0x130`, so SDL treated the
device as a joystick again.

JDM also ships per-wheel input presets, for MOZA's R5 and R9 among others, and
the July notes blamed them for the binary axes. The 32-bit fields explain all
six results without the presets, but the presets haven't been ruled out. The
`jdm` profile's `346e:0fff` identity matches none of them.

## The fix upstream

Wine 11.1 (January 2026) sizes each synthesized axis to its range. The change
is Rémi Bernon's "winebus: Use smallest report size for joystick axis", merged
through merge request !9886, which superseded !9789. With it, SDL axes become
16-bit fields, and JDM sign-extends them correctly while the centre ratio is
intact.

A system (non-Proton) Wine 11.22 package has this change *(verified)*. No Proton
build checked here has it. GE-Proton11-12 is built on Valve's bleeding-edge
branch of 2026-10-31; both it and Proton Experimental 11.0-20261112 still use
32 bits. No backport was found. Don't copy a system `winebus.so` into a Proton
tree: Proton's copy has its own patches, and its Unix and Windows halves must
match.

**Once a Proton carries it, re-test JDM through the virtual wheel** with the
`jdm` profile (`mozactl run jdm -- %command%`):
- Its `346e:0fff` identity matches none of JDM's per-wheel presets. A plain
  `mozactl start` wears the R9's `346e:0002` instead.
- Redo JDM's custom binding from scratch.
- With that identity, mode A should then work too, with no helpers.

## Routes, ranked

Ranked for JDM on a direct-drive base. The goal is analog axes **and**
protected force feedback. Only route 1 has passed in game, on the older build
25209638. Routes 2, 3 and 6 are proposals that haven't been built or run,
route 4 exists only as a compile-only prototype that was never loaded, and
route 5 has no in-game result yet.

1. **The physical base through hidraw (this repository's `main` branch).**
   - **How:**
     - Stop mozaproxy first (`mozactl stop`). The attended pass ran with the
       relay stopped, so JDM saw only the base.
     - Build `compat/jdm_hid.c` from the `main` branch as that branch's
       `compat/README.md` describes (`git show origin/main:compat/README.md`).
       `jdm_hid.so` relabels one vendor collection so Wine's DirectInput numbers
       the force-feedback collections correctly. It checks the descriptor's
       fingerprint and leaves an unrecognised descriptor alone.
     - Give your user read/write access to the base's hidraw node. The pass
       used a temporary ACL; a permanent udev `uaccess` rule needs root.
     - Set JDM's Steam launch options to
       `PROTON_ENABLE_HIDRAW=0x346e/0x0000 LD_PRELOAD=<path to>/jdm_hid.so %command%`.
   - **Status:** passed an attended drive on 2026-09-18 with analog axes,
     paddles and acceptable force feedback. That was JDM build 25209638; the
     route hasn't been re-tested on 26542938.
   - **Gap:** no force protection. The game's force-feedback reports reach the
     firmware directly, with no `ffb_gain` clamp and no stale-force guard.
   - **Proposed next step:** a preload filter in the same library (see
     [Force protection](#force-protection-on-hidraw-routes)).
2. **A Proton build that carries the Wine 11.1 change, on the evdev path.**
   - **How:** use this repository's virtual wheel, or the physical base's evdev
     node with the `main` branch's force guard. Protection stays where it is
     today.
   - **Costs:** building and maintaining a separate compatibility tool, a new
     binding in JDM, and JDM's force feedback over SDL, which hasn't been seen
     working yet.
   - **Variant:** a patch that presents the axes as 0..65535 instead. That's
     immune to the centre-ratio overwrite, but it isn't upstream.
3. **A UHID copy of the base.**
   - **How:** a relay serves the base's own descriptor through `/dev/uhid` on
     the virtual bus (`0x06`), so `hid-universal-pidff` leaves it to
     `hid-generic`. Proton's hidraw backend opens the copy, and the relay
     forwards every report.
   - **Protection:** it can send Stop All when the game exits or crashes. If
     the relay itself dies, the kernel removes the copy and nothing reaches the
     base, so an infinite effect keeps playing. Covering that needs a separate
     guardian process that holds its own handle on the base and sends Stop All.
   - **Needs:**
     - root setup: access to `/dev/uhid` and a uaccess rule for the copy's
       hidraw node;
     - the physical base's hidraw **and** evdev nodes hidden from the game, or
       duplicates race;
     - a new device identity (`WINEBUS\…` instead of `USB\…`, no container id),
       so expect to rebind.
4. **A `hid.dll` proxy in the game folder.**
   - **How:** opt in with `WINEDLLOVERRIDES=hid=n,b`. The proxy rewrites the
     32-bit axis caps and values to 0..65535, only for calls coming from the
     game's executable.
   - **Costs:** there's nothing to install yet. A compile-only prototype was
     built with `winegcc` during the investigation, but it was never loaded and
     isn't in this repository. The route also means an extra file in the game
     folder, and force feedback stays on the SDL path. Use it as a fallback.
5. **Mode B (Xbox 360 pad).** Steering and pedals arrive as XInput analog axes,
   but the wheel becomes a pad: the first 11 buttons and rumble-only force
   feedback. It's a downgrade, it only works for games that accept a
   controller, and it hasn't been tried in JDM.
6. **HID-BPF on the physical base.** HID-BPF can do this (checked on kernel
   7.3), but it applies to the whole device and needs a root loader. Not
   recommended.

## Force protection on hidraw routes

These numbers come from a capture of JDM's hidraw force-feedback traffic on
2026-09-18. It covers startup and a stationary garage only; no driving was
captured.

**What JDM sends:**
- JDM keeps one infinite-duration constant-force effect and sends an Effect
  Start with every update.
- In the garage that was about 207 Starts a second, never more than 8 ms apart.
- Menus and loading sent 13 Starts in 196 s.
- Wine's DirectInput sends the force magnitude only when it changes. Starts kept
  coming for 18 s with no magnitude report.

**What a stale-force guard must do:**
- Key on the absence of Effect Starts, never on the absence of magnitude
  reports.
  - This would be a new limit: today this path has no timeout. The proposed
    value is 100–250 ms.
  - The stationary garage never came close to it (Starts at most 8 ms apart),
    and menus will trip it (Starts up to about 2 minutes apart).
  - Driving hasn't been captured. Capture a moving drive before fixing the
    value, because a guard that trips while driving cuts the force mid-corner.
- Never inject a lone zero-magnitude report. Wine won't resend an unchanged
  magnitude, so the wheel would stay without force.
- Instead, replay the cached magnitude before the next Start, or end the effect
  with Effect Stop or a finite duration. Under PID semantics the game's next
  Start should undo either one, but neither is verified on the R25 yet.

**Still unknown:**
- Whether the R25 firmware times finite durations, restarts them on repeated
  Starts, and resumes after a Stop. One attended probe at about 2% force
  settles it.
- Whether JDM build 26542938 still ends every update with a Start. Re-capture
  before building on it.

## Evidence

Addresses are for the files named, so they can be re-checked after updates.

**`winebus.so`, GE-Proton11-7** (`files/lib/wine/x86_64-unix/`, symbols present):
- `hid_device_add_axes` at `0xf280`: `mov r9d,0x2075`, i.e. `REPORT_SIZE 32`.
- `sdl_add_device` axis loop at `0x563d..0x566a`: each axis is −32768..32767.
- `udev_add_device` defers the `input` subsystem at `0xa1c1..0xa1d2`.
- Every Proton build checked hard-codes the same `0x2075` (`REPORT_SIZE 32`)
  and has no range-dependent size.

**Wine 11.22 `winebus.so`:** `hid_device_add_axes` at `0xd0f0` picks 8, 16 or
32 bits at `0xd105..0xd1cf`.

**`JDM-Win64-Shipping.exe`, build 26542938** (virtual addresses, image base
`0x140000000`):
- The report handler is at `0x14420d160` (RVA `0x420d160`).
- The unsigned conversion is `cvtsi2ss` at `0x14420d59a`.
- 16-bit-only sign extension is `movsx` at `0x14420d5a8`.
- `HidP_GetUsageValue` is resolved by name at `0x144209f39`.

**SDL 3.4.18:** Linux gamepad auto-mapping bails out unless `BTN_GAMEPAD` is
present (`has_key[0x130]`). The wheel table lists `346e:0000/0002/0004`, but
not `0fff`.
