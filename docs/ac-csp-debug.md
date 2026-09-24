# Assetto Corsa CSP investigation, 2026-09-24

The user reports CSP failing to load and asks whether Proton or reinstalls are
needed. Initial diagnostics avoided desktop automation, as requested. The user
subsequently approved a normal Steam launch using Hypruse. The wheel was powered
on later in this session; independent detection and motor-free tests passed.

## Starting state

- Steam selects GE-Proton10-25 for app 244210.
- Launch options remain `PROTON_NO_ESYNC=1 %command%`.
- Content Manager replaces `AssettoCorsa.exe`; the original launcher is retained.
- CSP 0.2.11, build 3465, is present and enabled.
- The executable and PDB identifiers match. `acs.exe` SHA-256 is
  `0df569c840f8303f7018f7891085e3a4c22cf93fb19327c6a0b85325cea23fd1`.
- The existing September 18 CSP log already reports failed initialization.

## Isolated comparisons

Copied the prefix and writable cache/configuration into a diagnostic directory.
Used Xvfb and a mount namespace with the game directory read-only, copied
cache/configuration mounted over their originals, and physical input devices
absent. GPU device nodes were available in later comparisons. Invoked Proton
directly, outside Steam's normal runtime launch. These are startup diagnostics,
not full Steam or on-track compatibility tests.

| Test | Observation |
| --- | --- |
| GE-Proton10-25, original CSP/configuration/cache | CSP cannot find functions including ERS::step and CarLabel::render |
| Same, regenerated memory-layout cache | Same initialization failure |
| Same, NAMES_WINE block removed | Initialization still fails |
| GE-Proton11-7, original CSP/configuration | Initialization fails |
| GE-Proton11-7, regenerated cache | Initialization fails |
| GE-Proton11-7, WINE_DISABLE_EXE_ASLR=1 | Executable loads at preferred base, but initialization still fails |
| GE-Proton9-20, original CSP/configuration/cache | All 2,373 functions found; game log confirms hooks installed |
| GE-Proton9-20, copied video settings changed to windowed | Hooks still install; later display-mode query still crashes |
| Content Manager with GE-Proton10-25 | New log reaches main window loaded and ready |
| Content Manager with GE-Proton9-20 | Stalls before a new CM log; disabling .NET native-image cache or fsync did not resolve it |
| GE-Proton10-25, native x64 dbghelp from installed ACC, test prefix only | No symbols found; unsuccessful, not applied to live prefix |

The later game crash under Proton 9 occurs in DXGI/getDisplayModeDesc. Content
Manager under Proton 10 also reports division by zero when enumerating modes on
the virtual display. This limits what can be concluded about real rendering.
The precise internal Wine/CSP incompatibility remains unresolved. Do not call
this an ASLR or memory-protection fix: the ASLR comparison did not fix it.

The runtime comparisons demonstrate that reinstalling the same AC/CSP files is
not the first useful action. They do not establish that switching the whole
installation to Proton 9 is ready for use: Content Manager needs a normal Steam
launch check first, followed by an on-track CSP check on the real display.

## State after isolated diagnostics

Installed GE-Proton9-20 alongside existing runtimes after verifying the archive
against the upstream SHA-512 file. At that stage it was not selected for any game. No live
prefix, game/mod files, Steam selections or launch options had been changed.
Diagnostic processes were stopped; no physical forces were sent.

Local evidence, copied prefixes and probe scripts are under
`~/.local/state/mozaproxy/game-tests/ac-csp-20260924/`. Keep binary dumps and
vendor DLLs outside this repository. The wheel check log is
`/tmp/mozaproxy-wheel-health-20260924.log`: 39 software tests passed, including
virtual kernel input/FFB lifecycle tests. Physical FFB was not tested.

## Normal Steam verification

After the user approved desktop automation, backed up the live prefix and Steam
configuration again under `live-before-runtime-test/` in the evidence directory.
Restarted Steam to discover GE-Proton9-20 and selected it for AC only. Steam's
settings window did not respond reliably to automation, so the per-game runtime
entry was changed while Steam was fully stopped. The global default and other
games' runtime entries were preserved.

The first normal launch exposed a `rundll32.exe` startup-error dialog during
prefix conversion. Dismissing its offer to open more information let conversion
finish. Content Manager then logged `Main window is loaded and ready` at 17:34:31.
This explains a possible blocker in the earlier isolated CM test; it is not
proof that every isolated stall had the same cause.

Launched the saved NK16/FSAEJ session through Content Manager. The 17:36 CSP log
reports all 2,373 functions found, and the game log confirms all hooks installed.
The real display rendered the car and track at the pre-race screen for several
minutes. This verifies CSP initialization and rendering, not driving or physical
FFB. Automation could not reliably activate the drive control. The compositor
resize during monitor placement also temporarily changed the render size;
toggling fullscreen restored it. No graphics configuration was edited.

Kept `PROTON_NO_ESYNC=1 %command%` unchanged. No game, CSP or .NET reinstall was
needed. First-launch evidence is archived in `normal-steam-ge9-first/`. The game
and Content Manager were closed normally before a second Steam launch.

The second launch completed after Steam rebuilt Vulkan shaders. Content Manager
again logged its main window loaded and ready, without the conversion dialog.
Its log is archived in `normal-steam-ge9-second/`. Content Manager is left open
on the right monitor, Steam on the left, cursor on the left. A user driving/FFB
check remains necessary; do not treat this CSP fix as a new wheel validation.

## References investigated

- [CSP symbol-mapping issue](https://github.com/ac-custom-shaders-patch/acc-extension-config/issues/316)
- [CSP memory-layout cache issue](https://github.com/ac-custom-shaders-patch/acc-extension-config/issues/430)
- [GE-Proton AC compatibility reports](https://github.com/GloriousEggroll/proton-ge-custom/issues/514)
- [Official GE-Proton9-20 release](https://github.com/GloriousEggroll/proton-ge-custom/releases/tag/GE-Proton9-20)
- [GE-Proton executable relocation setting](https://github.com/GloriousEggroll/proton-ge-custom)
