# Project memory

## User preferences and authorization, 2026-09-18

- Finish the native Qt6 app, then test FH5, FS22, FS25, JDM, AC and ACC.
- User authorizes autonomous game launches and testing after app completion.
- `Super+g` brings up Steam through the Hyprland binding.
- Keep Steam on the left monitor and games on the right monitor.
- Whenever launching a game, keep the mouse cursor on the left monitor,
  away from the game on the right. Verify placement for every launch.
- Current geometry: left DP-2 spans x=-2560..-1; right DP-1 x=0..2559.
  Discover current monitors each session instead of assuming unchanged geometry.
- Use the installed Hypruse MCP for desktop interaction.
- User is away. If physical participation is needed, stop and ask; do not
  claim physical FFB quality from software observations alone.
- User authorized dismissing the current screen lock for testing. Automatic
  locking configuration was left unchanged.

## Desktop testing notes

- Hypruse cannot invoke Lua-backed Super+g on this Hyprland version; it reports
  this limitation. Use its window/workspace operations to show existing Steam.
- Hypruse typing works in native Qt. Steam's XWayland text field garbled
  simulated typing and did not accept Ctrl+V reliably. Always verify saved
  launch options. If necessary, exit Steam normally, edit backed-up launch
  options while it is stopped, and reopen it.

- User requested disabling the global Lossless Scaling Vulkan layer after its invalid config was found. DISABLE_LSFGVK=1 is persisted in ~/.config/hypr/userprefs.lua and ~/.config/environment.d/90-disable-lsfg-vk.conf. Keep it disabled for game comparisons; do not call freezes fixed without evidence.

## Virtual wheel testing

- User authorized a digital wheel harness. `tools/wheel-harness.py` creates a
  motor-free compact R9 and accepts JSONL steering/pedals/buttons while capturing
  FFB. See `docs/virtual-wheel-tests.md`. Final full suite passed all 113 tests,
  including both virtual-kernel tests.
- FH5 and JDM issued effects to the harness, but neither completed scripted
  driving. JDM locked its pointer; Hypruse 0.11.0 has no relative-motion or
  held-key interface. Do not repeat absolute clicks while the pointer is locked.
- Temporary game options, harness devices and compositor changes were removed.
  Hypridle was resumed. AC controls.ini and JDM's test-written save were archived
  and restored from the pre-test backups. LSFG stays disabled.
- Current evidence and remaining game checks are in `docs/compatibility.md` and
  `~/.local/state/mozaproxy/game-tests/remote-20260918/results.md`.

- After the wheel power cycle, raw-HID access was lost. User installed the updated
  /etc/udev/rules.d/70-mozaproxy-access.rules, granting active-seat uaccess to
  MOZA 346e:0000 hidraw nodes. Verified installed rule matches and opening
  /dev/hidraw9 read/write succeeds without sending reports.

## Later JDM checks, 2026-09-18

- User confirmed smooth driving without jdm_hid.so but no FFB. Re-enabling it
  brought freezing back; this is an association, not an established root cause.
- Physical startup/stationary-garage capture: 4096 successful HID calls, maximum
  2.441 ms; all 96 set-effect reports contain trigger 255. Firmware interpretation
  and physical force quality remain unverified. No output-report fix was applied.
- Proton puts capture files in private tmpfs. Read them through
  /proc/<winebus-pid>/root/dev/shm and archive before the container exits.
- Virtual R9 accepted constant effects and repeated starts, but moving driving
  remains untested because current bindings did not respond to scripted controls.
- Hypruse wtype creates a fresh keymap with physical code 1 for its first key;
  JDM may treat different synthetic keys as Escape. Mouse warps can also leave
  game cursor coordinates stale. Do not repeat clicks when effects disagree with
  the intended target. Native Lua send_key_state was accepted by the compositor,
  but reliable game navigation through it has not been established.
- Fresh pre-test JDM saves/config were restored. Launch options now use
  DISABLE_LSFGVK=1 PROTON_LOG=1 WINEDEBUG=-all
  PROTON_ENABLE_HIDRAW=0x346e/0x0000 %command%, with no descriptor/capture helper,
  virtual-device isolation or MangoHud injection. See game-tests/
  jdm-freeze-return-20260918-171451/cleanup-verification.json.
- Actual game teardown exposed a pending-FF-erase shutdown delay. SafeUInput
  now destroys uinput before closing its discovery handle. The old order failed
  a guarded two-second kernel regression; the corrected full suite passed 119
  tests, including three virtual-only kernel checks. This is separate from the
  unresolved direct-HID driving freeze. Harness commands now include hat_x/y.
- Added optional MOZAPROXY_JDM_TRACE_ARM marker gating so the next physical
  capture can start after reaching driving. Helper rebuilt and installed but
  inactive in launch options. The final suite passed 122 tests, including all
  three virtual-only kernel checks. See docs/jdm-ffb-debug.md for arming and
  recovering the capture inside Proton's private tmpfs.

- Follow-up autonomous virtual run: button14 shifted JDM fromN to1, but no
  verified vehicle movement. Capture has only near-zero constant uploads and
  repeated starts; stationary evidence cannot establish broken driving FFB.
- Hypruse Down was proven to deliver Escape scan9 to an XCB Qt receiver; native
  compositor Down delivered correct scan116. Correct probe results did not make
  JDM navigation reliable. See archive key-input-findings.md.
- After removing the virtual wheel live, with physicalR25 still masked, nine
  consecutive screen captures were byte-identical over8.67s before resuming.
  This supports persistence of a visible stall without an attached game wheel;
  it does not isolate the original cause or replace a clean startup comparison.
- User requested restart after the game became unresponsive. Archived current
  saves/settings in before-user-requested-restart, preserved user changes,
  restored input-only launch, and relaunched JDM. No virtual harness remains.

- Fresh direct-input restart also froze: ten consecutive whole screen captures
  identical for10.342s. Runtime had no wrapper/helper/tracer/Mango/LSFG; only
  Steam overlay preload. PhysicalR25 was visible and HIDRAW explicitly enabled.
  This excludes the wrapper being active now, not all input/Proton causes.
  129memoryfallbackwarnings preceded the observed freeze by over100s.

## Reboot handoff, 2026-09-18 evening

- User is rebooting after agents finish. All three active agents completed.
  Keep the wheel powered off initially after reboot and check Steam before
  reconnecting. Do not assume the restart fixed the stalls.
- Native Steam logged recurring 6–10.5 second UI stalls even after both physical
  and virtual MOZA devices disappeared at 22:09. Wheel-off observation at
  22:10:13, 22:10:29 and 22:10:54 still recorded stalls. Live wheel traffic is
  not required for these stalls to persist; stale Steam state remains possible.
  AC was playable per user. Root cause remains unresolved.
- Evidence: ~/.local/state/mozaproxy/game-tests/steam-wheel-off-20260918-221003/
  and jdm-freeze-return-20260918-171451/steam-stall-investigation-2205/ under
  the same game-tests directory. findings.md records native Steam main and
  engine threads waiting together, older stalls predating this work, and an
  Xwayland socket backlog. Syscall access was denied; backlog is only a lead.
- New opt-in system service, installer with activation/rollback, authenticated
  Unix-socket client, and Qt system mode are implemented. See
  docs/system-service.md and docs/superpowers/specs/2026-09-18-system-wheel-service.md.
  No installation, activation, system rules, or Steam changes were made during
  this implementation. Installed permissions and real game/FFB tests are pending.
  Activation enables boot startup; rollback restores prior enablement/state.
- Final offscreen suite ran 180 tests successfully with three opt-in kernel
  tests skipped. Log: /tmp/mozaproxy-system-service-tests.log. test_web now mocks
  external relay discovery so it cannot collide with an actual running relay.
- Existing transient user unit mozaproxy-fh5-session had PID 2330555 and was
  waiting for the powered-off wheel. It will not restart after reboot. The
  old persistent user mozaproxy.service remains disabled. New system service
  is not installed. Local Qt behavior remains the default until activation.
- Current JDM launch options were user-changed to DISABLE_LSFGVK=1 PROTON_LOG=1
  WINEDEBUG=-all %command%. FH5 retains its existing mozaproxy-game wrapper.
  Do not edit Steam VDF while Steam runs. LSFG remains persistently disabled.
- Keep work in this worktree; do not touch the separate
  ~/Documents/dev/mozaproxy checkout. Commit/push authorization was updated below.

## Confirmed Steam stall cause, 2026-09-18 after reboot

- Reboot with wheel off and no relays did not clear Steam stalls. FH5 was already
  running when inspected. User supplied ~/steam-backtrace.txt using sudo GDB.
  Native Steam engine LWP6571 blocked in recv, main thread waited on Steam sync.
- T3 preview port discovery is causing the recurring native Steam stalls. Both
  T3 instances initially probed Steam's local listeners27036,44733,57343.
  Installed T3 0.0.40 PortScanner sends HTTP then HTTPS to every local listener,
  with15second negative caching and3second polling. Current T3 PID15569;
  background compiled0.0.42 PID2514. Steam PID5665.
- Pausing T3 processes was a bad comparison: it kept existing sockets open and
  extended Steam's stall to50seconds. Both resumed. Closing tabs stopped probes
  from2514, but15569 kept scanning. Do not use SIGSTOP to suppress this scanner.
- A targeted lsof filter removed only Steam from15569's discovery results.
  Full60second interval had zero Steam stalls, zero sampled probes, engine
  do_epoll_wait60/60 samples. Removing filter brought6475/7428ms stalls back.
  Thus scanner causation for native Steam stalls is demonstrated. Physical FFB
  and full game smoothness still require user driving verification.
- Temporary workaround now installed at ~/.local/bin/lsof. It only filters the
  exact scanner arguments for descendants of current T3 PID15569 with expected
  command; all other calls exec /usr/bin/lsof. No existing file was overwritten.
  This is session-specific and does not cover background service2514's PATH.
  It must be replaced by a proper T3 fix; do not treat it as permanent.
- All evidence, scanner source excerpt, scripts, filter copy, SHA256 and rollback
  details are under ~/.local/state/mozaproxy/game-tests/
  post-reboot-20260918-222354/. active-workaround.json documents active change.
  Remove ~/.local/bin/lsof only if it still matches archived lsof-filter-used.py.
- No new wheel system service installation/activation, Proton edits or wheel
  code changes occurred during this diagnosis. Wheel remains off.

- User then confirmed FH5 driving no longer freezes with the T3 scanner
  exclusion active and wheel off: "nah its good now". JDM and powered-wheel
  combinations remain unverified. Keep the scoped filter active during testing;
  restarting T3 requires revisiting it because it targets PID15569.

- User powered wheel on and launched FH5 again. At22:38:30 restored transient
  mozaproxy-fh5-session user unit, PID59839, compact MOZA R9 identity346e:0002,
  physical event12 to virtual event13,32buttons/10FFslots. Steam stalls remain
  absent with scanner filter active. Current FH5 wrapper masks physical nodes.
  New system service still not installed. Awaiting driving/input/FFB report.

- Attended powered-wheel FH5 retest passed. User explicitly reported
  "everything works and ffb is rather ok too" after steering/pedals/paddles/FFB
  check request. No new Steam stalls. Recorded in docs/compatibility.md.
  Current relay remains running for FH5. Next planned attended game is JDM;
  user must close FH5 before its input path is changed. System-service mode
  and durable T3 fix are still pending, not covered by this pass.

- FH5 closed; stopped mozaproxy-fh5-session. User requested preparing and
  launching JDM. Backed up JDM Saved/Config and SaveGames under game-tests/
  jdm-attended-post-stall-20260918-224315. Hypruse typing garbled launch options;
  corrected only JDM LaunchOptions while Steam was fully stopped, then
  relaunched Steam/JDM. Do not trust Hypruse typing into Xwayland Steam.
- Active JDM launch: DISABLE_LSFGVK=1 PROTON_LOG=1 WINEDEBUG=-all
  PROTON_ENABLE_HIDRAW=0x346e/0x0000
  LD_PRELOAD=/home/christian/.local/lib/mozaproxy/jdm_hid.so %command%.
  GE-Proton11-7, physical R25 direct HID, no virtual relay and no tracer.
  Runtime environment verified; Proton log confirms applied R25 Wine FFB
  collection workaround. Original input-only options saved for rollback.
  Steam restarted, so old Steam PID5665 and thread6571 are obsolete.
  T3 PID15569 remains unchanged, so its targeted lsof filter still applies.

- User confirmed JDM same successful result as FH5: inputs/FFB good and no
  freezing with direct HIDRAW+descriptorhelper. User now requests all outstanding
  work. Explicit rollout policy: games not tested TODAY and built-in-supported
  use ordinary physical/native baseline, no automatic virtual/HID/FFB changes.
  Current always-reserved system service violates policy and JDM directpath;
  DO NOT ACTIVATE it. Need revise ownership/game launch integration first.

## Rollout revision and FS22 handoff, 2026-09-18 23:04

- System service revised: startup/restart leaves relay off; physical uaccess
  retained for desktop alongside service account. Installer requires both
  accounts can access physical nodes. Explicit relay start remains compact R9;
  process liveness is separated from unknown device readiness. No automatic
  game routing. No installation/activation yet; live validation still pending.
- Qt system mode and compatibility docs now explain the direct default.
  All 64 existing settings have descriptions. Full offscreen suite: 183 tests,
  zero failures, 3 opt-in kernel tests skipped. Log /tmp/mozaproxy-rollout-tests.log.
- Durable local T3 workaround staged at ~/.local/libexec/t3-steam-guard/lsof,
  ~/.local/bin/t3-steam-safe, and user t3code.service.d/steam-port-guard.conf.
  Daemon reload only. Current processes and temporary ~/.local/bin/lsof remain
  unchanged. Next manual T3 launch must use t3-steam-safe; service picks up
  private PATH on its next restart. Upstream fix not available. See durable
  investigation/manifest/rollback in post-reboot-20260918-222354 evidence.
- FS22 prepared and launched after JDM exited, direct physical with relay off.
  Backed up game.xml, gameSettings.xml, inputBinding.xml, log.txt and manual
  profiles under game-tests/fs22-attended-direct-20260918-230257.
  ONLY edit: game.xml joystick vibration=false -> true. Strength stays 50%.
  No device profile or binding edits. New log confirms Force Feedback enabled,
  physical R25 category UNKNOWN. Old virtual bindings still require rebinding.
  This does not establish physical FFB; attended driving is pending.
- FS22 window 0x55f0c6687b70 moved to right/workspace1. Steam remains left,
  cursor -1500,650. No changes to Steam launch options. Ask user to bind the
  physical steering/pedals then drive and report controls, force and smoothness.
- Final Hypruse capture showed the screen lock over the game. The process
  and game log confirm launch; no visible menu check was possible. User
  participation is needed for rebinding/driving regardless.

## Steam library audit, 2026-09-18

- User requested a comprehensive list of other library games with ordinary
  wheel support. See docs/game-test-backlog.md: 26 additional account-ticket
  targets, 10 cached-only support candidates requiring current access check,
  and 6 secondary investigations. Installed additions: BeamNG, ETS2, FS2011.
- Read three libraries and active account localconfig app tickets/librarycache,
  parsed appinfo read-only with installed protontricks. 1,014 matched game/demo
  records, including 623 games with local tickets. Tickets/cache are not proof
  of current server-side entitlement; public games page required sign-in.
- Evidence: ~/.local/state/mozaproxy/game-tests/library-audit-20260918/.
  Export contains metadata only, no ticket values or credentials. Primary
  target JSON has all validation untested and built_in_support=false.
- Sources distinguish wheel input from FFB. Most Wanted 2012 supports wheel
  input but EA says no FFB for the cited wheel; F1 24 cached Valve metadata
  flags unsupported anti-cheat. Star Trucker peripheral support was added
  after launch; Bus Bound Demo has an FFB update. Logistics Simulator1617420
  is not Truck and Logistics Simulator873840. Do not conflate these titles.
- No installations, game launches/config edits or runtime changes in this audit.

## BeamNG detection failure, 2026-09-19 morning

- User launched BeamNG with empty options; preflight R25 event8 was accessible,
  no relay. GE-Proton10-25 starts 08:47:11-12. At 08:47:12 physical wheel USB
  IRQ errors begin, resets fail with -32/-71, USB disconnects 08:47:15.
  Wheel absent from host lsusb/evdev/hidraw; Wine retains deleted hidraw9.
  BeamNG 0.39.4.0.20972 starts afterward and enumerates only keyboard/mouse.
- This is a USB disappearance during runtime startup, not merely bindings.
  Cause not isolated: could be HID traffic, driver/firmware, hub/cable/power.
  No relay/helper active, no config changes or pulses made during diagnosis.
  Evidence in game-tests/beamng-usb-disconnect-20260919-*.
- Ask user to close BeamNG, power-cycle wheel, leave game closed, report ready.
  Verify recovery and capture startup before choosing any compatibility override.

- After user power-cycle, R25 returned08:55:38 as event8/hidraw9. For one
  controlled BeamNG comparison, added prefix-only WineBus Devices/346e/0000
  Hidraw DWORD0. Empty launch options, same GE-Proton10-25, no relay/helper.
  Launched08:59:16; game now detects/acquires physicalR25 as wheel0 with FFB
  advertised; no new kernel USB errors. Physical driving and repeatability
  pending. Do not promote to validated built-in support or infer USB root cause.
  Evidence/backed-up registry: game-tests/beamng-nohidraw-compare-20260919-085916.
  Rollback offline by removing only added per-device registry section.

- User reports BeamNG wheel works fine and moved on to ETS2. Record manual
  input pass, FFB quality not separately confirmed. Post-run kernel archive
  contains106 output-queue-full warnings09:02:22–09:06:04; keep investigation
  open despite working input. Wheel still USBdevice18, no disconnect.
- ETS2 started09:06:55 via user's existing Proton Experimental with empty
  launch options. No settings changed, no relay. BeamNG-only override stays
  scoped to284160. Inspect fresh ETS2 log, not previous huge UI-overflow log.

## Steam stall recurrence in ETS2, 2026-09-19

- User reports ETS2 freezes. At09:31 game already exited. Steam console log
  shows recurring10.47second IPC stalls roughly17seconds apart, persisting
  after exit. Native T3 PID2524 held connections to Steam PID5767's local
  ports27036,57343,35103,38659. No new kernel errors during ETS2 period.
- Service/private PATH was correct but scanner login shell prepends
  ~/.local/bin. Old PID15569-only lsof shim there bypassed private filter,
  directly execing /usr/bin/lsof. Captured child scanner PATH proves ordering.
- Backed up and removed old shim ONLY after verifying SHA256 matches archived
  original3534b4f2b8594a549c1282bbe865cb1bc749ce8b9de563c2c28c43361b1daab3.
  Private ancestry-aware filter unchanged; temporary diagnostics restored.
  Real login-shell scanner call now excludes Steam. Synthetic filtering,
  live ancestry recognition and unrelated lsof passthrough checks pass.
- Evidence: game-tests/ets2-freeze-20260919-093204. Initial connections drained;
  post-change observation being recorded. Driving retest still required.
- ETS2 also rebuilt navigation for10seconds after save/map mismatch and uses
  seven mods. Those may affect loading but do not explain native Steam's
  repeated stall cadence. No game settings or mods changed.

- Completed55sample observation: final44 samples had zero probe sockets.
  Last10.47second Steam stall09:33:08 occurred as old connections drained;
  none afterward in observation. One wheel IRQ-75 at09:31:55 after game exit,
  no disconnect; keep separate from demonstrated Steam scanner recurrence.

- User moved to NFS Heat1222680 at09:48; ETS2 driving retest after scanner
  repair not confirmed. Heat now installed in home Steam library, build10351341,
  empty launch options. Baseline physicalR25/no relay, no Heat override applied.
  At09:48:32 no new Steam IPC stalls since09:33:08 and no sampled T3 probes
  to Steam. One wheel IRQ-75 at09:48:20, still enumerated as USBdevice18.

## Heat black screen, 2026-09-19 10:05

- User changed runtime to GE-Proton11-7-x86_64 and relaunched09:58:27.
  Heat PID209091 began09:58:45, renderer initialized around10:04:10.
  Screenshots10:04:54 and10:05:38 show black game with active FPS overlay.
  Game is alive, renderer/asset files open; DXVK cache stayed67.7MB during
  10second sample. Kernel repeatedly logs Heat split-lock and UMIP traps.
  split_lock_mitigate=1. Cause of black screen not yet established.
- sudo requires user's password. Prepared reversible45second diagnostic
  /tmp/mozaproxy-heat-split-lock-test.py to disable only runtime split-lock
  throttling and restore original in finally, including interrupt handling.
  No settings changed yet. Evidence under game-tests/heat-black-screen-*.

- User manually ran sudo sysctl kernel.split_lock_mitigate=0 instead of
  timed script. Verified value0 at10:06:36; remains disabled until restored
  or reboot, no persistent sysctl config created. Screenshot10:06:44 shows
  Heat title/loading artwork and progress bar instead of black. SamePID209091;
  loading progressed after change, but causal A/B and driving pending.
  Restore original with sudo sysctl kernel.split_lock_mitigate=1 after test.

- In-game user suspects Xbox rather than wheel recognition. Wine holds real
  R25 hidraw9/event8 and prefix registers346e:0000, usage joystick0004.
  No host Xbox/virtual controller found, no current Steam mapping activation
  in controller log; Heat per-app UseSteamControllerConfig=0. This does not
  establish Heat's own classification. EA tested list excludes MOZA, says
  other wheels may work; need inspect Heat wheel menu and actual inputs.

- User authorizes supported-wheel spoof experiment for Heat. Prepared G29
  identity046d:c24f using existing compact24button relay, no new corecode.
  This is identity-only comparison, not faithful G29 axis/descriptor support.
 25 targeted input/effects/runtime/isolation tests passed; physical read-only
  preflight found10FFslots. No virtual device started, no launch edits yet.
  Heat must close before switching route. Plan/backup in /home/christian/.local/state/mozaproxy/game-tests/heat-g29-identity-test-20260919-101258.
  Intended transient relay plus Heat-only mozaproxy-game isolation wrapper;
  original options empty. Stop relay after Heat, restore empty options on
  rollback. Do not change FH5/JDM/BeamNG or global default route.

- Heat G29 identity test activated10:14:05 after user closed game. Steam
  restarted to change ONLY Heat LaunchOptions to mozaproxy-game wrapper;
  offline parsed diff verified all other settings unchanged, backup archived.
  Transient user unit mozaproxy-heat-session relay245445, realevent8 ->
  virtualevent13 LogitechG29 046d:c24f, compact24buttons/10FFslots.
  Live Wine248466 opened only virtualevent13 for wheel, physicalevent8/hidraw9
  masked to /dev/null in game namespace. Heat250190 started10:15 approx
  via unchanged GE-Proton11-7. Awaiting actual wheel-menu/input/FFB check.
  Stop transient unit before testing other games. Split-lock setting still0.

## Heat failed G29 identity and new G920 profile

- User reports G29 test not recognized. Heat closed before diagnostics.
  Read-only PE probe compiled with winegcc confirmed G29 driving/limited
  type00010116, 8axes/24buttons/POV/FFB, no XInput slots connected.
  First proton-run probe timed out due launch wrapper; direct same-build
  Wine probe worked with physical masking and same Heat prefix.
- Added explicit CLI g920 profile in profiles.py/input.py/cli.py: identity
  046d:c262, four axes (measured R25 X/Z/RZ/THROTTLE -> X/Y/Z/RZ), inverted
  pedals, 11buttons including right301->4,left300->5. Native/compact default
  mappings preserved. Six new tests include snapshot, dropped-frame recovery,
  bounds, missing axes, fixed layout and identity. No Qt/system auto-route.
- Stopped old mozaproxy-heat-session unit. New transient
  mozaproxy-heat-g920-session running, same Heat isolation launch option.
  Probe confirms G920 driving/dualpedals00010316,4axes/11buttons/POV/FFB and
  disconnected XInput slots. Game validation pending. See docs/heat-wheel-test.md.

- Final suite189tests passed including all3motor-free kernel tests, log
  /tmp/mozaproxy-g920-final-tests.log. Latest G920 relay286696 event13.
  Requested Heat launch10:26 with Steam/cursorleft; at10:27 Steam shader
  processing37%, game not yet running. Do not claim actual Heat G920 pass.
  Latest experiment status corrected to shader processing.

## 2026-09-19 per-game mapping editor and Heat feedback

User wants fixed supported-wheel target layouts with editable per-game R25
source configs in the Qt app. Implemented Games > R25 mapping, currently fixed
G920 or default direct. Save never applies. Separate local game-mappings.json
store; explicit Start saved mapping and Apply saved mapping live. System mode
saves only; custom activation remains local. Existing FH5/JDM/AC/ACC paths intact.

Heat user now reports steering direction correct, paddles reversed, glance
joystick triggers acceleration/brake/nitrous/camera, menus wrong, large centre
deadzone. Saved Heat experimental config swaps 300/301 assignments to slots
4/5 respectively (zero-based), keeps measured pedal axes and steering, disables
all other buttons/hat until learned. Those unidentified buttons have no verified
physical labels. Does not change the CURRENT Heat relay PID286696, started with
old --profile g920. Needs one restart to adopt --mapping-file live reload.
User explicitly allows live mapping updates, but existing process predates it.
Do not falsely claim those corrections are active or game-tested.

Heat PROFILEOPTIONS read-only: WheelDeadzone=0, DeadzoneCenter=.22,
WheelMaxRotation=900. Do not assume which game path consumes .22. No game file
changed. Current split_lock_mitigate=0 remains user's manual setting.

Live reload validates same game/fixed descriptor, releases old keys/hats,
synchronizes source snapshot and retains virtual device + effect relay. Polls
private config every250ms, atomic control/status docs, UI waits for acknowledgement.
Virtual kernel test confirms existing client fd/path and effect-relay object stay
unchanged through remapping held input. No physical FFB sent by these tests.
See docs/game-mapping-editor.md and tests/test_game_mappings.py.

## 2026-09-19 10:53 Heat corrected mapping activated

User closed Heat and authorized proceeding. Stopped old transient unit
mozaproxy-heat-g920-session.service. Started Qt app PID350796 and used its
Games > R25 mapping > Start saved mapping button via Hypruse.
App owns relay PID357702, --mapping-file /tmp/mozaproxy-mapping-cjsu8ait.json.
Status acknowledgement matches saved Heat correction with error=null; event13
046d:c262 fouraxes+POV, 11buttons, 10slots, pedals65535rest and steeringflat0.
Physical isolation wrapper preflight masks event8/hidraw9 to /dev/null, keeps
virtualevent13 visible. No FFB probes or game deadzone changes.
App is open on workspace4; keep it running to keep relay. Live edits can use
app Save then Apply live, or atomic updates to the same mapping control document.
Launched Heat10:53 viaSteam, cursorleft(-1500,700). EA launcher was moved to
workspace3right; waiting for actual Heat window. Steam remains workspace2left.

Heat relaunched PID361783; 10:54 actual game window0x5595c4bd72e0 moved
workspace3right after EA reused its window address on workspace2. Cursor restored
left(-1500,700), Steamleft. Live game namespace verified physicalevent8/hidraw9
masked1:3, virtualevent13visible13:77. Current app-owned saved mapping active.

## Heat throttle investigation, next attended capture

User says paddles fixed, cannot get throttle working. Preserve his edits:
saved+active Heat config now throttle source2,invertedfalse (other axes unchanged).
App currentlyworkspace3LEFT, gameworkspace1RIGHT, user rearranged windows.
Read-only DirectInput axis probe built /tmp/mozaproxy-heat-axis-probe.exe from .c.
Runs in LIVE game mount/user namespace using same GE11wine/prefix, background
nonexclusive acquire, no FFB. Enumerates Accelerator GUIDY -> DIJOYSTATE2.lY,
Brake -> lRz, Clutch -> Slider0. 20samples /tmp/mozaproxy-heat-axis-probe-baseline.log:
after first frame Y=0 throughout, Rz~44k and Slider0 moved24k->650->24k.
Don't infer physical control labels from unattended sample; user might be
pressing clutch. Prepare controlled throttle-only capture.
Ready-to-run /tmp/mozaproxy-capture-heat-pedals.py records25seconds physical,
virtual and Windows data, no grabs or force. Run with .venv/bin/python only when
user confirms beginning throttle-only press/release test, game paused, other
pedals released. Current gamePID361783, relay357702, mappingfile unchanged.

## 2026-09-19 11:32 attended throttle-only capture

User confirmed earlier clutch motion was intentionally pressing/resting on clutch;
not swapped pedal evidence. User then performed25secondsthrottleonly after
"testing throttle". Capture completed normally, no force/grab/config changes.
Archive ~/.local/state/mozaproxy/game-tests/heat-pedals-20260919-113231/:
physical ABS_Z -32648..32767, virtual ABS_Y120..65535, Windows DIJOYSTATE2.lY
(Accelerator)174..65535,250successful Windows samples,619Linux samples.
Physicalbrake/clutch stayed-32768, WindowsRz/Slider0=65535 (released convention).
605/619Linux snapshots exact,618within256, max430 due sequentialreadtiming.
Throttle source and fullrange delivery are confirmed across allthree layers.
This does NOT prove Heat interprets Accelerator or polaritycorrectly. Current
throttleinvertedfalse, paddleassignmentsunchanged. Need exact in-game symptom
(nothing vsacceleratesreleased vs partialtravel) before another mappingchange.

## Heat throttle ignored after confirmed DirectInput sweep

User says pedal does NOTHING in Heat. No mapping changes made. Live same-namespace
DirectInput/XInput probe again reports only046d:c262 driving/dualpedals FF-capable
4axes/11buttons/POV; all4XInputslots disconnected. SteamXboxconversion not observed.
Heatbinary has WheelModel enum LogitechG920; does not establish activewheelpath.
EA official Jan2020 notes require GHub for ALL wheelmakes onPC:
https://forums.ea.com/discussions/need-for-speed-franchise-discussion-en/need-for-speed-heat---january-update---update-notes/9439444
Potential dependency, NOTprovenrootcause. No installer/registry/DLL changes done.
ValveProtonissue3955 comments644231367,647164545,1483895932 reportG27/G29 generic
controller behavior. Not proofcurrentG920case. Latestgameguide sim-gamer-kit
says Heatwheelmode requires DirectInputwheel, doesn'tallowrebinding; ours reportswheel.

Investigated tracewithoutrestart: sameWine winedbg info proc works, HeatWindowsPID
0x6e4 (Linux361783); no debugger attach performed. ptrace_scope1; stdout/dev/null,
stderrpipe. No debug flags changed. Wine docs say runtime channel toggles limited
to channels initialized by WINEDEBUG; actualgameflagsnotchanged. Game stillrunning.

Hyprusefocusgame succeeds, but injectedEsc/Escape/Tab did NOTopenmenu in repeated
screenshots. NeeduseropenHeatSettings/Controls to inspect whetherwheel-specific
rotation/FFB optionsavailable vscontrolleronly beforefurtherblindmappingchanges.
Gamecurrentlyrightworkspace1, appleftworkspace3, Steamleftworkspace2 (userlayout).

## Heat menu mapping, 2026-09-19 11:56

- Attended sequence measured hat0 up/down/left/right and chosen Confirm640,
  Back639, Pause627. Saved and applied through Qt: hat=true, buttons
  [640,639,null,null,300,301,627,null,null,null,null]. User pedals/paddles unchanged.
- Relay PID357702 acknowledged live mapping. Game menu success pending user test.
- Capturing evdev events separately fails while relay grabs wheel. Poll
  active_keys()/absinfo() instead; these captured the sequence successfully.

- Follow-up: user reports menu directions except Up work, but Confirm/Back
  were reversed. Swapped these through Qt and verified live acknowledgement:
  buttons [639,640,null,null,300,301,627,null,null,null,null].
  Captured Up reaches physical hat(0,-1), virtual hat(0,-1), Windows POV0.
  User sees controller-only UI with no wheel settings; active Heat wheel path
  remains unverified. Paused further input remapping to investigate recognition.

## Heat SDK dependency test installed, 2026-09-19 12:04

- Found actual Heat binary registry path for Logitech Wheel SDK, matching
  official SDK8.75.30. Missing-key result2 and official wrapper initfalse.
- Extracted official LGS9.04.49 x64 LogitechSteeringWheel.dll without running
  installer. Load-only preflight passed. Registered only in Heat prefix with
  reg.exe, CLSID{63BD165D-1584-4E75-AB56-08330350545F}/ServerBinary pointing to
  C:\Program Files\Mozaproxy\compat\heat\LogitechSteeringWheel.dll.
- SDK initialization after installation and Heat wheel-mode success still
  untested. Need close/relaunch Heat; current PID361783 started before install.
- Archive ~/.local/state/mozaproxy/game-tests/heat-sdk-20260919 contains
  hashes, before/after probes, installed.json with rollback targets. Prior
  registry key and file absent. No other prefix or launch options changed.
- Live mapping remains [639,640,null,null,300,301,627,null,null,null,null],
  hat=true. SDK wheel path may interpret controls differently; preserve it
  until the next attended test establishes which actions need adjustment.

- Restarted Heat after user closed it. New PID565455 maps the staged Logitech
  runtime DLL, unlike the pre-install session. Physical event8/hidraw9 remain
  masked and virtual event13 visible. Steam left, game right, cursor left.
  Wheel-specific UI, throttle and physical FFB still require attended testing.

## SDK versus relay comparison pending

User reports Heat now working after SDK installation and has corrected bindings.
Latest saved/live mapping: all pedals inverted=true; paddles slot4=301,slot5=300;
Confirm/Back slots0=639,1=640;Pause slot6=627;hat=true. Preserve this latest version.
They request determining whether SDK alone suffices without the relay. The live
editing feature itself does not affect the descriptor or game compatibility;
the unresolved comparison is direct R25 versus the fixed G920 translation.
Prepared archive path is in /tmp/mozaproxy-heat-direct-comparison-path.
Need final post-close settings backup, stop app-owned relay, clear Heat launch
options via Steam UI, relaunch same prefix/Proton with SDK and physical R25.
The current wrapper always hides the R25, even with no relay, so merely stopping
the relay is not a valid direct test. No route changes made while user plays.

## Fixed Heat preset, 2026-09-19

User closed Heat and clarified that the wheel emulation should remain, while
manual binding setup should be unnecessary. Deferred the direct-R25 comparison;
no launch-option or relay-route changes were made. Final post-close settings
are backed up under the comparison archive.

The explicit Heat G920 preset now exactly matches the user's working saved
mapping: inverted pedals, slot4=301/slot5=300, slots0/1=639/640, slot6=627,
and hat passthrough. Selecting G920 for Heat fills these assignments; existing
saved mappings remain authoritative and direct is still the unsaved baseline.
Live editing changes the same compiled profile, not an extra relay/device.
No edits are required each launch. The Logitech SDK runtime is still required
setup for the tested route and is not installed automatically by preset choice.

All203 tests, including opt-in virtual kernel tests, passed after the preset
change. The app's Heat evidence text now reports the user's input pass and
separate SDK setup; physical FFB quality remains unconfirmed.

## Commit and push preference, 2026-09-19

- User explicitly requests frequent commits and pushes to the remote.
- Commit and push at tested milestones on the current feature branch, without
  asking again. Do not accumulate the entire rebuild as uncommitted work.
- Remote: origin, https://github.com/C-Nucifora/mozaproxy.git.
- Branch: t3code/rebuild-linux-ffb-compatibility. Preserve unrelated remote work;
  do not force push. Keep downloaded vendor DLLs, private game saves, logs and
  runtime captures outside the repository.

## Native desktop theme integration, 2026-09-19

Fixed PySide6's missing system theme plugin discovery. The desktop now appends
system roots containing a platform theme built for the same Qt major/minor and
build mode, while keeping bundled platform plugins first. The user's selected
qt6ct darker palette, Cantarell font and Tela-circle-purple icons now load.
No global theme configuration was changed. A regression verifies live palette
changes through qt6ct and preservation of an unsaved settings draft.

All 204 tests passed, including opt-in virtual kernel tests. Dark and light
native screenshots were checked. The restarted Wayland app loaded system
qt6ct and the bundled Wayland platform plugin. The wheel is powered off and
the app-owned relay stopped when the old app closed. Heat mappings remain saved.

## AC CSP investigation, 2026-09-24

The user initially prohibited computer use, then explicitly approved it for
normal Steam verification. The wheel is powered on. Independent read-only
hardware detection and 39 motor-free software tests passed. No relay is active.

See docs/ac-csp-debug.md. CSP 0.2.11 fails initialization on GE-Proton10-25 and
11-7, but finds all 2,373 functions and installs hooks under GE-Proton9-20 with
the same game/CSP files. AC now selects GE-Proton9-20 only; other runtime
selections and launch options are unchanged. AC launch options remain
`PROTON_NO_ESYNC=1 %command%`.

A normal Steam launch revealed a rundll32 startup-error dialog during prefix
conversion. Answering No to its information-link question allowed startup to
finish. Content Manager loaded successfully, launched the saved NK16/FSAEJ
session, and the game rendered the car and track at the pre-race screen. Fresh
logs confirm CSP initialized and loading completed. Driving and physical FFB
were not verified. No game/CSP/.NET reinstall was performed.

The live prefix and Steam settings were backed up before the runtime change in
`~/.local/state/mozaproxy/game-tests/ac-csp-20260924/live-before-runtime-test/`.
First normal launch evidence is in `normal-steam-ge9-first/` alongside it.
Steam rebuilt Vulkan shaders for the second launch after the runtime change.
The second normal Steam launch opened Content Manager without the conversion
dialog. Evidence is in `normal-steam-ge9-second/`. Content Manager is left open
on the right monitor; Steam and cursor are on the left. User driving/FFB check
remains outstanding.
