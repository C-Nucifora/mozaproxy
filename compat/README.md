# JDM direct HID compatibility experiment

`jdm_hid.c` is an opt-in, Linux x86-64 LD_PRELOAD helper. It is a
manual compatibility workaround. An attended JDM test on 18 September 2026
confirmed working controls and acceptable physical FFB with the helper and a
separate Steam port-scanner mitigation. Integrated routing and broader hardware
coverage remain unverified. See the [compatibility matrix](../docs/compatibility.md).

The captured R25 Ultra descriptor contains a vendor collection before the PID
force-feedback collections. Wine's DirectInput enumeration omits the vendor
collection and numbers the remaining collections consecutively, but later uses
those numbers as HID link-collection indices. GE-Proton10-34 consequently logs
`unexpected device_control.control_coll parent!` and `device control id 0`, and
does not expose the `DIDC_FORCEFEEDBACK` capability. Steering and pedal input
through the native HID reports works; changing back to SDL would lose that
verified input path.

The helper labels just that container as Generic Desktop / Pointer, then
immediately restores the vendor usage page for its report fields. Collection
nesting, input/output/feature report IDs, usages, sizes, ranges, and offsets
remain unchanged. It intercepts descriptor-read ioctls only for USB identity
346e:0000 and an exact fingerprint of the 1,315-byte captured descriptor. Other
devices and unrecognized firmware descriptors pass through. It does not change
firmware, kernel descriptors, bindings, force strengths, or output reports.

The binary is loaded only by commands given the LD_PRELOAD environment variable.
Do not add it globally to the shell, Steam environment, or ld.so.preload.

Build from the repository root:

```sh
mkdir -p "$HOME/.local/lib/mozaproxy"
cc -shared -fPIC -O2 -Wall -Wextra -Werror compat/jdm_hid.c \
  -o "$HOME/.local/lib/mozaproxy/jdm_hid.so"
```

Example JDM launch options, replacing `/home/your-user` with your home directory:

```text
LD_PRELOAD=/home/your-user/.local/lib/mozaproxy/jdm_hid.so PROTON_LOG=1 WINEDEBUG=-all,+dinput PROTON_ENABLE_HIDRAW=0x346e/0x0000 %command%
```

The physical hidraw node must still be readable/writable by the user. The
current temporary ACL disappears when the device node is recreated. No udev
rules or system-wide library overrides are installed by this helper.

Remove the LD_PRELOAD assignment to revert. Keep HIDRAW enabled to retain the
working native input path. No virtual relay is needed for this experiment.

`tests/fixtures/r25-ultra-descriptor.bin` was read from the connected physical
R25's sysfs report_descriptor. It contains protocol metadata, not input history
or a serial number. Tests independently decode all report fields and verify
that Wine's exported collection indices now coincide with HID link indices.
A live read-only ioctl probe also verified the descriptor through this helper;
no motor commands were sent by that probe. Later attended game observations are
recorded in the compatibility matrix; they do not validate other firmware descriptors.

Reference: [Wine DirectInput HID implementation](https://github.com/ValveSoftware/wine/blob/bleeding-edge/dlls/dinput/joystick_hid.c),
`enum_objects`, `init_pid_reports`, and `hid_joystick_create_device`.
