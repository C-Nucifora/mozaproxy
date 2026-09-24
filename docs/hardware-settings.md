# Hardware settings

The local app includes a serial settings client alongside the optional evdev
force-feedback relay. These are separate connections. Input observation does
not grab the wheel or send effects. Connecting settings opens the base's serial
port and issues read requests only.

The implementation uses MOZA command IDs, addresses and conversions documented
in the installed [Boxflat project](https://github.com/Lawstorant/boxflat), notably
`data/serial.yml` and the base, pedals and wheel panels. Packet framing, checksum,
stream parsing, validation and lifecycle code here are independently implemented.
Boxflat is not launched or imported at runtime.

The current routing supports peripherals attached through the base. Standalone
USB pedals, handbrakes and alternative wheel addresses are not implemented.
Unavailable values remain absent; the app will not apply a setting unless the
connected device first returns a valid reading. The R25 Ultra returned 59 of 64
catalogued settings during a read-only check. Game effect gains and rotary mode
did not reply. Availability can differ with attached peripherals and firmware.

The client checks existing serial owners, requests pyserial's exclusive lock,
sets the kernel's TIOCEXCL flag, then checks owners again. Disconnect releases
both locks. It does not kill Boxflat or another app. Linux device permissions
still apply; no root service is installed by the web app.

Apply validates the whole requested batch before writing. Pedal intervals use
confirmed existing boundaries and widen before narrowing when both ends move.
Each written value is read back and compared with its wire-quantized target.
A failed or mismatched readback removes the cached value and reports an error.
There is no automatic rollback: an earlier setting in a batch can succeed while
a later setting fails, and failed readback means the hardware state is unknown.
Read settings again before retrying. Rotation writes both limit and maximum
angle and verifies both. No settings are applied automatically at startup or
when selecting a saved profile.

Guided calibration, center reset, firmware operations, emergency-stop overrides,
individual LED colors and telemetry lighting are deliberately absent from this
first implementation. Actual configuration writes require attended validation;
the development checks so far queried the wheel without changing configuration.

## R25 torque limits in Nm

The native Qt app displays **Maximum torque** in Nm when the connected serial
port identifies a MOZA R25 Ultra Base. Shared USB product IDs or a relay name
are not sufficient to identify its 25 Nm rating. Other bases and disconnected
settings use percent. Profiles, the HTTP API and the serial protocol continue
to store `torque` as a percentage, so existing profiles remain compatible.

For the R25, the supported 50–100% register range is 12.5–25 Nm nominal.
Whole-percent steps correspond to 0.25 Nm. An intermediate request rounds down,
and the control shows the actual Apply target. Confirmed device readback stays
separate from the draft. This is a configured limit derived from the rated
25 Nm output, not a measurement from the torque sensor or a calibrated guarantee.

An authorized check on 2026-09-24 requested 32%, corresponding to 8 Nm. The
firmware returned **50%**, and a fresh connection confirmed that value. The
previous setting was 70%; the lower 50% setting was retained. Game FFB strength
remained at 20%. No force effects were sent by the check. Evidence is saved
locally at `~/.local/state/mozaproxy/game-tests/r25-torque-20260924.json`.

**8 Nm is not supported by this hardware-limit command on the tested firmware.**
The app rejects that input rather than silently substituting 12.5 Nm. Lowering
game gain can reduce game effects, but does not prove a total motor-torque cap;
base effects and soft stops are separate. Do not multiply game gain by the torque
limit and claim the result is an enforced maximum. A lower verified hardware
limit needs another supported firmware control or further protocol evidence.

References: [MOZA Pit House manual](https://support.mozaracing.com/en/support/solutions/articles/70000625635-moza-pit-house-user-manual),
[R25 specification](https://support.mozaracing.com/en/support/solutions/articles/70000679654-moza-r25-ultra-true-torque-wheelbase),
[Boxflat base controls](https://github.com/Lawstorant/boxflat/blob/master/boxflat/panels/base.py).

A follow-up interference check found no running Boxflat process, no Boxflat
Flatpak instance, no matching user service or autostart entry, and no existing
serial owner. An exclusive reconnect still returned torque50% and gain20%.
Boxflat being installed was not evidence of it running or changing the setting.
