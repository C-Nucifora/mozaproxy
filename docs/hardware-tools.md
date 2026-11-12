# Calibration, RGB and telemetry tools

Pedals & controls → Calibration & telemetry contains explicit operations.
Nothing starts automatically. These implementations have offline validation;
physical results on the user's wheel remain pending.

## Settings evidence and RGB

Diagnostics shows the last Apply request with previous, requested and actual
values. Outcomes distinguish not written, written but unconfirmed, confirmed
mismatch and confirmed match. A failed readback never proves the previous value
was retained. Device configuration remains unknown where readback failed.

RGB editors accept `#RRGGBB` and offer a colour picker. They use the newer wheel
protocol at address 23: ten RPM lights and fourteen button lights. Each control
must return a valid three-byte read before it can be written. The R25 base name
alone does not establish its rim's capabilities. Legacy wheel colour protocols
and independent USB accessory addresses are not enabled by these additions.

## Pedal calibration

The supported procedure is the MOZA base-connected pedal protocol at address 25,
write group 38: throttle/brake/clutch start commands 12/13/14 with value 1 and stop
commands 16/17/18 with value 0. Matching min/max/reverse readings must already be
available for the chosen pedal. This is protocol capability detection, not a
claim that every pedal model has been physically tested.

Stop driving, start explicitly, and fully depress/release the pedal during the
seven-second window. The app sends Stop automatically and rereads range settings.
Stop ends capture; it cannot undo learned calibration. Other settings writes are
blocked during capture. A failed stop remains unresolved with Stop available
for retry. If the device disconnected before Stop could be sent, use the MOZA
recovery procedure before restarting the app; reopening it is not proof that
hardware calibration ended. No wheel motor calibration or center reset is added.

## Telemetry lighting

[Telemetry setup](telemetry.md) covers LMU, ACC, AC, BeamNG.drive, ETS2 and FH5.
Preview opens a loopback listener and sends no device commands. Each game has an
explicit source selection; shared-memory games need the optional Windows reader,
and ETS2 needs the SDK plugin. These feeds have offline validation only.

Optional RPM LED output requires a local connected wheel with readable newer
RGB controls and telemetry mode. The app saves the prior mode, enters external
mode, and sends bounded ten-light masks at at most 20 Hz. Stale data clears the
mask after 0.5 seconds; output ends on Stop, settings Apply, calibration, disconnect
or app close. Restoration failures stay visible and Stop can retry after a
settings reread. The bar starts at half the game's reported maximum RPM, or the
configured BeamNG scale. This is not a verified ideal shift point.

System-service mode supports telemetry preview only. LED output stays unavailable
there rather than opening a second settings connection.

## Firmware and accessories

The UI links the [official MOZA tools](https://support.mozaracing.com/en/support/solutions/articles/70000628053-downloads).
No supported flashing/image-verification/recovery protocol was established, so
firmware flashing is unavailable. No fake version or update status is shown.
Independent USB pedals, handbrakes and additional wheel addresses require their
own identity and protocol validation before writes are enabled.

Protocol references: the installed Boxflat `data/serial.yml` and pedal/wheel
panels; [Boxflat source](https://github.com/Lawstorant/boxflat);
[FH4/FH5 Data Out implementation and format](https://github.com/nikidziuba/Forza_horizon_data_out_python).
No Boxflat runtime or implementation code is imported.
