# Managed telemetry lighting

Approved by the user on 2026-11-15 after successful LMU RPM testing. Keep the fixed
`mozaproxy -- %command%` command and make lighting persist across game launches.
The wheel is now confirmed by the user as RS V2, matching `RS Leather # W00`.

## Design

Use a host user service to detect LMU and run its read-only shared-memory helper.
Wait for valid telemetry before connecting to the wheel. A private expiring lease
stops only our reader when the service stops or crashes. Defaults are opt-in and
service failures never prevent game launch. Keep automatic profile Apply separate.

Continue wheel RPM output, with adjustable start/end percentages of reported rev
limit. The SDK has no optimal-shift or dashboard-light thresholds. Do not claim
exact in-game shift timing. Other game sources retain their existing manual setup.

R25 base alerts use player yellow/blue state, a brief green after a known yellow
clears, cyan pit-limiter pulses, and optional amber ABS/TC intervention. Unknown,
paused and stale signals clear alerts. Player caution data is not guaranteed to
cover all local yellow sectors. Probe model, brightness and mode before writes.
Only captured live palette/mask commands are allowed; preserve firmware idle
configuration and all FFB settings. Firmware mode must already be 1.

Use the known serial byte-stuffing protocol for colors and checksums. Independent
implementation uses capture facts from AZOM, not copied GPL implementations.

## Alternatives and limits

The temporary reader proved hardware operation but required manual startup, so it
is replaced by the managed service. A virtual wheel is unnecessary for lighting.
RPM and base telemetry can be verified now; matching physical button functions
still requires the user's button-to-light assignments. Do not infer physical LED
count from spurious readable color slots. RS V2 has ten button lights.
