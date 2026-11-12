# LMU pause-menu force guard

Status: software checks pass; attended R25 pause/resume verification is pending.

On this workstation, Le Mans Ultimate under GE-Proton11-12 uses Wine's evdev
backend and the physical Gudsen MOZA R25 Ultra Base. Mozaproxy is not running.
The captured pause transition stops updates to the constant-force effect
without a subsequent effect-stop or device-pause command. The wheel keeps
pulling. Disabling vendor-specific FFB did not resolve it. Setting evdev gain
to zero released the wheel; restoring 5% gain with autocenter off reproduced
the pull.

`tools/menu_force_guard.c` is an opt-in workaround for this streamed force. It
replaces an infinite constant effect with a 50 ms effect and renews playback
when the game updates an effect it has started. Once updates cease, the last
force expires. Stop and erase requests prevent renewal. The caller's effect
duration remains unchanged, so subsequent updates are still recognized.

Only USB identity `346e:0000` with the exact evdev name
`Gudsen MOZA R25 Ultra Base` is targeted. Finite effects, delayed or triggered
effects, envelopes, other effect types and other devices pass through. It does
not change bindings, firmware, gain or the physical device's descriptor.

## Shared protection option

The guard is now shared with ACC and other compatible games. Use the
[Menu force protection toggle and launcher](menu-force-protection.md).
The source is `tools/menu_force_guard.c`; the original installed
`lmu_ffb_guard.so` is retained for existing launch options until they are migrated.

## Limits and checks

The guard is not a torque limiter or an emergency stop. The last force can
remain for up to 50 ms after its last update, subject to driver and firmware
behavior. Constant force drops during update gaps longer than 50 ms, including
game stalls. Restarting effects is appropriate only for this continuous,
unenveloped stream. Hardware feel and the physical expiry still need testing.

Strict compiler warnings and GCC's static analyzer passed. A separate virtual
uinput device verified baseline and guarded uploads, play repetition,
active-update renewal, stopped updates, erasure, unchanged finite effects,
unchanged behavior for a different device name, and descriptor replacement with
an ordinary file. A concurrent fork/close check passed 100 cycles. Those checks sent no force
to the physical wheel and do not establish its firmware behavior.

The helper tracks descriptors below 4096 and expects Wine to upload, play and
erase through the same descriptor. It does not support passing effect ownership
between duplicated descriptors or using the native HIDRAW path.
The [Wine backend used by GE-Proton11-12](https://github.com/ValveSoftware/wine/blob/fda79a585939fb7512dc220a11249f9ffe825fcf/dlls/winebus.sys/bus_udev.c)
uses the same stored descriptor for effect uploads, playback and erasure.
Signal-handler reentrancy and replacing a descriptor with another open of the
same device without `close()` are outside this workaround's scope.
