# System wheel service

User-approved direction: the Qt app manages a native Linux virtual wheel without wheel-specific Proton commands. Build alongside the running test setup; do not activate device permissions or alter Steam while tests are in progress.

Latest baseline requirement supersedes the original always-reserved design: only games tested today with built-in support may receive game-specific defaults. All other games use normal physical/native access, with the relay off. No automatic virtual identity, descriptor helper, or custom FFB changes. A game-specific route requires both validation and built-in support before becoming a default.

## Ownership and presentation

A dedicated unprivileged system account provides hardware settings control and explicit control of the existing compact R9 relay. Root-installed udev rules give its private hardware group access to MOZA 346e:0000 physical input, hidraw, USB and serial nodes while retaining seat uaccess. The desktop can continue using direct physical input when the service is stopped or unavailable. A manually created virtual 346e:0002 also stays available to the active desktop user. This installation does not mask physical interfaces.

Keep the current relay and input/FF algorithms unchanged. Service startup and restart leave the relay off. An explicit relay_start starts one compact R9 relay, survives Qt window closure, reconnects through the existing supervisor and releases effects on service shutdown. UI actions must not recreate the virtual identity while a relay is running. No automatic serial probes or settings writes. The existing passive evdev monitor reads input state without grabbing or sending effects.

The confirmed FH5 route uses compact virtual input plus per-game physical masking. The confirmed JDM route uses direct R25 HIDRAW plus its descriptor helper and no relay. Neither route can be replaced by always reserving the physical wheel. Preserve working launch setups; there is no automatic game selection or privileged permission switcher in this revision.

## Local control

A versioned, bounded JSON protocol runs on `/run/mozaproxy/control.sock`. Authenticate SO_PEERCRED against the configured desktop UID. Only fixed operations are accepted: status, schema, relay_start, relay_stop, hardware_connect, hardware_disconnect, hardware_apply. No client-selected executables, device paths, USB identities, filesystem paths or raw packets. The backend reuses validated settings and relay classes. Profiles remain in the desktop user's existing store.

Request: `{ "version": 1, "method": "status", "params": {} }`. Response: `{ "version": 1, "ok": true, "result": ... }` or `{ "version": 1, "ok": false, "error": "..." }`, newline-delimited. Request maximum64KiB, response maximum1MiB. `status` returns device, hardware, relay and integration dictionaries. Mutations return the relevant component result. `relay_start` accepts only an empty params object and fixes profile compact/name MOZA R9 Base/product2. `hardware_apply` accepts `{ "settings": {...} }`.

Keep `relay.running` as child-process liveness, not wheel readiness. Add `relay.ready: false` and `relay.readiness: inactive` when stopped; use `ready: null` and `readiness: unverified` while running until a real session handshake is implemented. Return these fields in status and relay mutation responses. Add integration `default_route: direct` and `physical_access: desktop-and-service`; `owner` names the service account, not exclusive physical ownership.

## Packaging and migration

Installer stages a root-owned copy outside the writable checkout, with a private Python environment. The daemon runs as `mozaproxy`, primary group matching the authorized desktop user's primary group for socket access, supplementary group `mozaproxy-hardware` for devices. No desktop user is added to the hardware group. Installation is separate from activation, and activation refuses an existing relay or Wine game session. Activation requires reconnect, installs shared access rules, starts the service with relay off, and verifies read/write access for both accounts. A rollback restores previous rules. Do not run this installation during development testing.

The app selects system mode only when root-installed integration configuration exists, or an explicit system-backend argument is supplied. Service failure produces a visible settings/control error and never silently opens physical hardware or starts a local relay. Games retain direct physical access. Without installation, existing local mode remains unchanged. Closing the system-mode UI closes only its client resources. Show shared physical access, direct default, and experimental virtual game validation. Do not claim blank launch options replace a working game's helper or masking requirement.

## Verification and boundaries

Use socket integration tests with fake hardware/relay and Qt offscreen tests. Test authorization, malformed/oversized requests, rejected methods/params, service loss and UI close semantics. Test staging/activation/rollback with fake filesystem/commands; never write installed udev/systemd files in tests. No live wheel grabs, effect playback, Steam mutations or service restarts during implementation. Existing FH5 relay must retain its PID and virtual device. All game validation and installed permission checks remain pending until a coordinated switch.
