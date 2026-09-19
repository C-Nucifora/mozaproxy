# Game preflight, 18 September 2026

Read-only inspection of installed manifests, Steam configuration, wrappers,
Proton prefixes, saved controller settings, and existing logs. No game was
launched, no desktop input was sent, and no settings were changed during this
preflight. Native app work must finish before game testing begins.

## Installed games and selected runtimes

All six manifests report `StateFlags=4`, `UpdateResult=0`, and downloaded bytes
equal to requested bytes. This establishes Steam's installed state, not file
integrity or successful launch.

| Game | App ID | Installed build | Selected Proton | Steam library |
| --- | --- | --- | --- | --- |
| FH5 | 1551360 | 21856128 | `proton_11` | `/data/Internal/Steam Library` |
| FS22 | 1248130 | 14439757 | `GE-Proton10-25` | `/data/GamesLibrary/SteamLibrary` |
| FS25 | 2300320 | 25209229 | `GE-Proton10-25` | `/data/Internal/Steam Library` |
| JDM | 1153410 | 25209638 | `GE-Proton11-7-x86_64` | `~/.local/share/Steam` |
| AC | 244210 | 14923034 | `GE-Proton10-25` | `~/.local/share/Steam` |
| ACC | 805550 | 21257365 | `GE-Proton10-25` | `~/.local/share/Steam` |

Evidence: each library's `steamapps/appmanifest_<appid>.acf`,
`~/.local/share/Steam/steamapps/libraryfolders.vdf`, and
`~/.local/share/Steam/config/config.vdf` under
`InstallConfigStore/Software/Valve/Steam/CompatToolMapping`.
JDM and FS25 have newer builds than the baseline in `compatibility.md`.
The latest existing Proton headers confirm FH5 used `proton-11.0-2c-x86_64`
and JDM used `GE-Proton11-7`; both used Steam Runtime 4.

## Launch options actually stored in Steam

Source: `~/.local/share/Steam/userdata/STEAM_USER_ID/config/localconfig.vdf`,
`UserLocalConfigStore/Software/Valve/Steam/apps`. Other local Steam account
configurations did not contain launch-option records for these games.

| Game | Current options |
| --- | --- |
| FH5 | `PROTON_DLSS_UPGRADE=1 ENABLE_HDR_WSI=1 PROTON_ENABLE_WAYLAND=1 PROTON_ENABLE_HDR=1 PROTON_LOG=1 WINEDEBUG=+hid,+dinput /home/your-user/.local/bin/mozaproxy-game -- %command%` |
| FS22 | `PROTON_LOG=1 PROTON_ENABLE_HIDRAW=0x046d/0xc266 %command%` |
| FS25 | `WINE_HID=1 WINE_HIDRAW=1 PROTON_ENABLE_HIDRAW=046d:c266 %command%` |
| JDM | `PROTON_LOG=1 WINEDEBUG=-all PROTON_ENABLE_HIDRAW=0x346e/0x0000 %command%` |
| AC | `PROTON_NO_ESYNC=1 %command%` |
| ACC | No launch-option value stored |

FH5, FS25, JDM and ACC also have `UseSteamControllerConfig=0` stored under
`UserLocalConfigStore/apps`. FH5 has `OverlayAppEnable=0`. Inspect the actual
Steam UI before changing these; this preflight does not infer undocumented
numeric enum meanings.

## Concrete issues to address before testing

1. `~/.local/bin/mozactl` still invokes two missing files under
   `/home/your-user/Documents/dev/personal/mozaproxy`. It is broken, but none of
   these six current launch-option strings invokes it. Do not restore the old
   FH5 option from the morning backup. Replace this obsolete launcher only if
   a documented current interface needs it; its old arguments cannot safely
   be assumed compatible with the new relay.
2. `~/.local/bin/mozaproxy-game` is valid and points to this worktree's
   `.venv/bin/python` and `tools/run-game.py`, both present. It only isolates
   physical R25 device nodes with bubblewrap. It does not start the relay or
   verify that a virtual wheel exists. FH5 must have the intended compact
   `MOZA R9 Base`, `346e:0002` relay running before this wrapper is used.
3. FH5 still has verbose HID/DirectInput logging enabled. Its existing
   `~/steam-1551360.log` is 330,927,872 bytes. Archive it, then change only the
   debug setting to `WINEDEBUG=-all` for the planned quiet comparison. Preserve
   the HDR/Wayland options for that comparison rather than changing several
   variables together. Logging was a candidate, not a proven freeze cause.
4. Both farming games retain Logitech `046d:c266` overrides. The connected
   physical wheel is USB `346e:0000`, `MOZA R25 Ultra Base`, and currently
   `/dev/input/event8` is named `Gudsen MOZA R25 Ultra Base`. Remove the stale
   Logitech override for a direct-device baseline. FS25 also carries old
   `WINE_HID`/`WINE_HIDRAW` overrides and a differently formatted identifier.
   Their current runtime effects have not been established. A clean baseline
   with `PROTON_LOG=1 WINEDEBUG=-all %command%` avoids preserving unverified
   historical overrides. Do not simultaneously switch Proton or rewrite binds.
5. JDM's current options correctly preserve the last input-only route and do
   not load the descriptor helper. `~/.local/lib/mozaproxy/jdm_hid.so` and
   `jdm_trace.so` exist, but their presence does not mean they are loaded.
   Preserve this baseline before any helper experiment on the newer build.

Steam was running during inspection. Apply launch-option changes through its
UI or after a controlled Steam exit; direct VDF edits can be overwritten by
the running client. The earlier backup at
`~/.local/state/mozaproxy/pre-game-test-launch-options.json` predates later
changes and is historical evidence, not a current restore snapshot.

## Saved bindings worth checking in the game UI

- FS22 `inputBinding.xml` contains both old virtual `R25 (mozaproxy)`
  `346E-0002` and Logitech G923 records. Its old log detected the virtual R25.
  A direct-device test may require new MOZA bindings; absent response alone
  would not establish an input-driver failure.
- FS25's active library prefix contains physical R25 `346E-0000`, Logitech
  G923, and Saitek records. There is also an older FS25 prefix under the home
  Steam library containing a separate `inputBinding.xml`. Back up and inspect
  the prefix in `/data/Internal/Steam Library`, where the game is installed,
  and verify the actual prefix from the running process at test time.
- AC `controls.ini` identifies `Gudsen MOZA R25 Ultra Base` and physical
  `PGUID0=0000346E-0000-0000-0000-504944564944`. It stores `FF_GAIN=1.2`.
  Preserve its existing tuning for the initial regression check; remote
  software inspection cannot establish a comfortable physical force level.
- ACC `controls.json` names `MOZA R21 Base` with
  `productId=13422-0-0-00807368867368`. The old display name alone does not
  prove a mismatch, since 13422 is hexadecimal 346e. Check the active device
  and each binding rather than clearing the profile based only on its name.
- JDM binds are in `AppData/Local/JDM/Saved/SaveGames/JDMSlot_S.sav`.
  Back up this binary save; use the game UI to inspect or change bindings.

## Test sequence and evidence

Finish and verify the native app first. A practical sequence is FH5, FS22,
FS25, JDM, AC, ACC. Only FH5 initially uses the relay/isolation route; stop
the relay before direct-device tests so a second virtual wheel does not
confuse enumeration. Confirm the app's stop state and actual input-device
list instead of assuming the relay exited.

For each game:

1. Back up that game's current launch options, controller configuration, and
   existing Proton log. Record build, runtime, and chosen input route.
2. Open Steam using the user's `Super+g` binding. Keep Steam on left monitor
   DP-2, global x=-2560, and the game on right monitor DP-1, global x=0.
   Put the cursor on the left monitor before every game launch, as requested.
3. Confirm launch, actual runtime/prefix, and device list. Inspect controller
   settings, input bars, duplicate devices, pedals and paddle bindings before
   entering driving. Live axis movement requires physical user input.
4. Capture a short driving check, performance evidence if freezes recur, and
   a screenshot of the relevant settings. Do not equate an effect upload,
   moving input bar, or successful launch with correct physical FFB.
5. Exit normally, verify the game and relay stop, archive new logs, then test
   one relaunch. Record exactly what passed and what remains user-unconfirmed.

Physical steering feel, damping direction, torque strength, and pedal motion
cannot be validated remotely. They require the user's observations.

## Diagnostic locations and tools

For each game, `<prefix>` is `<its library>/steamapps/compatdata/<appid>/pfx`.
The user directory below is `<prefix>/drive_c/users/steamuser`.

| Game | Configuration and game logs relative to the user directory |
| --- | --- |
| FH5 | `AppData/Local/ForzaHorizon5`; use Proton log and Steam process log for startup evidence |
| FS22 | `Documents/My Games/FarmingSimulator2022/{inputBinding.xml,game.xml,gameSettings.xml,log.txt}` |
| FS25 | `Documents/My Games/FarmingSimulator2025/{inputBinding.xml,game.xml,gameSettings.xml,log.txt}` |
| JDM | `AppData/Local/JDM/Saved/Config/Windows/GameUserSettings.ini`, `AppData/Local/JDM/Saved/SaveGames/JDMSlot_S.sav`; crash logs under `AppData/Local/CrashReportClient/Saved/Logs` |
| AC | `Documents/Assetto Corsa/cfg/{controls.ini,video.ini,race.ini}` and `Documents/Assetto Corsa/logs/` |
| ACC | `Documents/Assetto Corsa Competizione/Config/controls.json`; `AppData/Local/AC2/Saved/Config/WindowsNoEditor/` and `AppData/Local/AC2/Saved/Logs/` |

Proton logs are `~/steam-<appid>.log` when `PROTON_LOG=1` is set. At preflight,
FH5's log exists at about 331 MB and JDM's at 68 KB. Steam records launches in
`~/.local/share/Steam/logs/gameprocess_log.txt`, runtime choices in
`compat_log.txt`, and downloads in `content_log.txt`.

Installed diagnostic commands: `nvidia-smi`, `journalctl`, `evtest`, `jstest`,
`fftest`, `mangohud`, and `bwrap`; system Python has `evdev` and `vdf`.
`fftest` can drive physical force and was not run. `evtest`/`jstest` can observe
input without grabbing it, but meaningful changes need the user to move the
controls. Use `nvidia-smi` sampling during a freeze comparison, then correlate
with process and kernel timestamps. Existing JDM reports already show that
allocation-fallback warnings alone do not establish exhausted GPU memory.

Historical artifacts are under `~/.local/state/mozaproxy/game-tests/` and
`/tmp/mozaproxy-jdm-performance.jsonl`; see `compatibility.md` for what was
actually observed. Do not reuse earlier results as proof for updated builds.
