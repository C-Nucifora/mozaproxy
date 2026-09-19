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
