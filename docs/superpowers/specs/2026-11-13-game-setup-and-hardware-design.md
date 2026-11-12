# Game setup and hardware support

Status: approved by the user on 2026-11-13. User requested work on compatibility, automatic game
setup, settings validation, calibration, lighting, firmware and accessories.
Automatic application is an option and must default off, as explicitly requested.

## Constraints

The user is playing while development happens. Do not open the real wheel,
send settings or effects, restart services, alter Steam configuration, replace
installed helpers, or attach instrumentation to the running game. Build and
verify using fake transports, saved captures and isolated virtual devices.
Do not call software checks a physical compatibility pass.

Use the existing Python, Qt6, serial and evdev implementation. Preserve profiles,
existing launch flags, the 100 ms protection preference and manual routes.
Keep Windows/Proton game adapters separate from native Linux adapters.
No new permanent tests unless requested, per the repository commit skill;
run existing suites and temporary focused self-checks for new logic.

## Approaches

1. Extend the existing app and shared backend, exposing explicit per-game setup
   and optional launch detection. Recommended: reuses profiles, readback and
   launch helpers without requiring a system service for ordinary use.
2. Require the privileged service for every game and device operation. Rejected
   for this phase: existing direct games work without it and its game routes
   still need physical validation.
3. Automatically rewrite Steam/game files and infer wheel settings from process
   names. Rejected: this would disturb existing working setups and does not
   provide reliable identity or consent for hardware changes.

Implementation details below are proposed engineering choices, not additional
user requirements. Hardware work that cannot be verified remains explicitly
pending instead of acquiring a simulated success state.

## 1. Compatibility records and preflight

Keep the shipped game catalogue and add local, dated test records. Each record
contains game ID, input route, Proton/native runtime, wheel identity, separate
launch/input/FFB/pause-resume results, and a bounded free-text note. Results are
untested, pass or fail. Only an explicit user action records an attended result.
New records do not erase the historical evidence bundled with the application.

Add read-only preflight for known launch routes: required executable/helper
presence, selected mapping and profile validity, and conflicting route options.
Report missing prerequisites without installing them or modifying prefixes.
Do not equate process detection, successful effect uploads, or a game reaching
its menu with working FFB. Keep the existing six-game backlog plus LMU, BeamNG,
Heat and ETS2 visible; new game support requires its own evidence.

Games UI: select game; inspect route and prerequisites; copy launch command;
link a saved profile; record a test result. Export records with diagnostics.
Mirror stored data and explicit actions in the web API and optional web UI.

## 2. Game selection and optional automatic application

Add explicit per-game links to profile IDs. Multiple profiles may carry the
same game tag, so a tag alone must not choose which one gets applied.
Saved links are validated against existing profiles and known game IDs.

Detection is opt-in. Resolve a Steam game from bounded reads of same-user
process metadata, using Steam application IDs rather than executable-name
substrings. Unknown, conflicting or ambiguous matches make no changes.
Poll no faster than every two seconds; do not enumerate processes from each
high-frequency input/UI refresh. Retain only IDs and process start tokens,
not environment contents or command-line credentials.

Default behaviour selects the linked profile and visibly offers it for manual
Apply. Preserve unsaved UI edits and show a pending selection rather than
replacing a dirty draft. Detection does not start/stop a relay, hide devices,
rewrite launch options, or apply hardware settings by itself.

Separate option: **Apply linked profiles automatically**, default off.
It requires detection to be enabled, a valid explicit game/profile link, and
a separate per-game automatic-Apply opt-in, also off by default. Existing
selection-only links never become write-enabled merely by enabling the global option.
Consume each observed game-launch transition once. Opening the app during a
game, enabling the option during a game, or editing a link while a game is
running does not apply anything retroactively. Never retry failed automatic
writes on each poll. Display failure and require manual Apply or a new launch.

Automatic application requires an already connected, identified settings
device and no operation in progress. It does not acquire a serial connection
or restart a service. Use the same validation and readback as manual Apply.
If the UI has a dirty draft or settings are busy/disconnected at a launch, skip
automatic Apply for that launch and show why. Never defer it until later in the
session. Do not automatically restore a previous force profile when a game exits.
Selection and write ownership belong to one desktop controller, not a GET
request or an unauthenticated monitoring endpoint. Multiple running app clients
must not independently auto-apply the same launch.

System mode passes supported settings operations through its existing service;
do not expand its fixed relay identity or trust arbitrary client commands.
Unsupported automation capabilities are disabled visibly rather than silently
falling back to direct hardware access.

## 3. Settings validation evidence

The current controller already validates before writing and reads back each
setting. Build on it instead of adding a second write implementation.
Record the requested, previous and actual values, per-setting failures,
device identity and time for each explicit Apply. Distinguish not written,
written but unconfirmed, confirmed mismatch and confirmed match. A readback
failure is not evidence that the device retained its previous value.

Offer an exportable last-apply report and a settings verification view. No
background write sweeps. Restoration is an explicit preview-and-Apply action,
using the same validation and readback; no blind automatic rollback of force.
Bound persistent reports and preserve malformed stores rather than overwriting.
Reports must work in local and service modes and remain useful after partial
failures. Software tests use fake serial replies, not the physical base.

## 4. Calibration and lighting

First establish a capability table from the connected models recorded in prior
diagnostics and the documented protocol; base identity alone is insufficient.
If no reliable accessory identity can be established without touching the live
wheel, complete the offline implementation but keep activation blocked pending
an attended identification check. Do not select a model by guessing.

Provide guided calibration for supported base-connected pedals first, using
the documented start/stop procedure and device identity. Do not infer raw
calibration endpoints from already scaled evdev readings. Wizard sequence:
check idle/connected state, explain movement, start explicitly, capture the
user's completion, stop calibration, reread settings, show the result.
Cancellation and errors must attempt the documented stop command; disconnect
cannot be described as successfully restored. Calibration never runs as part
of a saved profile or game launch. Wheel motor calibration and center reset
require separate documented procedures and are not disguised as pedal actions.

Add RGB setting types for documented, readable wheel LED controls. Reuse
profile storage, schema validation, draft edits and readback. UI provides a
colour picker and exact RGB/hex entry; unknown values remain unknown.
Detect the supported wheel address/capabilities before enabling controls.
Do not probe by writing or assume every wheel attached to an R25 has the same
LED layout. Legacy and newer wheel protocols need separate capability entries.

Telemetry lighting is a separate opt-in runtime feature, default off. Initial
implementation targets Forza Horizon 5 Data Out UDP, because it is already in
the supported manual game routes and does not require a Windows shared-memory
bridge. Verify its published packet format before implementing the adapter;
use explicitly synthetic packet fixtures for offline checks and require a real
capture before marking the game adapter physically validated. Validate packet sizes/version/source, bound frequency,
and stop sending when data becomes stale. Reuse the single serial owner;
manual settings and calibration take priority. Preview/simulation must work
without opening a device. ACC/LMU Windows shared-memory telemetry needs a
verified bridge and must not be claimed supported by a generic UDP adapter.

## 5. Firmware and additional accessories

The examined local protocol reference documents calibration and lighting but
does not establish a firmware flashing/recovery protocol. The initial firmware
page may report only verifiable installed versions and provide official MOZA
update/recovery links. Unknown versions stay unknown. No update execution,
download-and-flash, bootloader switching or firmware compatibility claims
without a supported image format, model matching and recovery procedure.

Additional USB pedals/handbrakes require device-specific discovery and protocol
evidence. Implement only identified devices with verified addresses and packet
formats, retaining explicit device selection when multiple devices exist.
Discovery alone does not enable writes. Unavailable hardware remains a tracked
validation gap, not a reason to invent a generic protocol.

## Delivery and verification

Deliver in independent changes: compatibility records and setup; detection and
profile selection/optional Apply; settings reports; calibration; RGB lighting;
telemetry adapter; firmware/accessory investigation and supported controls.
Run the existing 209-test baseline, Qt offscreen and browser checks, plus
temporary self-checks for storage limits, ambiguous detections, launch identity,
dirty drafts, default-off settings, mismatched replies and cancellation.

No installation, physical testing or live activation while the user is playing.
Present an attended checklist after software verification. Record unresolved
hardware/protocol dependencies individually. Do not call the entire expansion
complete while those dependencies remain.

## Reference evidence

- Existing `HardwareController.apply` provides per-setting readback and partial
  failure handling; `ProfileStore` provides bounded atomic saved profiles.
- Existing `launch.py` isolates devices; `protection.py` wraps direct launches.
- Installed Boxflat `data/serial.yml` and wheel/pedal panels contain distinct
  calibration commands, newer and legacy RGB formats and write-only telemetry.
- [MOZA downloads](https://support.mozaracing.com/en/support/solutions/articles/70000628053-downloads)
  and [Pit House FAQs](https://support.mozaracing.com/en/support/solutions/articles/70000627928-moza-pit-house-faqs)
  document official update tools, not a third-party flashing protocol.

## Approved follow-up: background detection service

The user additionally requested a service that detects games without repeated
Steam launch-option edits. Provide an optional per-user systemd watcher sharing
the same links and default-off flags. It must not inject helpers after launch.
In service mode, explicitly opted-in automatic Apply may acquire its own serial
connection on a new launch, check all eligibility again after reading, and close
it afterward. Skip automatic writes while the desktop is open; the window can
have unsaved drafts. The watcher publishes selection separately from the profile
document to avoid overwriting concurrent profile edits. A single-owner lock
coordinates desktop fallback and service; service startup waits for handoff.
Installation and live activation remain deferred while the user plays.
