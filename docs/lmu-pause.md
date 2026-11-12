# LMU pause-menu force guard

Status: software checks pass; attended R25 pause/resume verification is pending.

On this workstation, Le Mans Ultimate under GE-Proton11-12 uses Wine's evdev
backend and the physical Gudsen MOZA R25 Ultra Base. Mozaproxy is not running.
The captured pause transition stops updates to the constant-force effect
without a subsequent effect-stop or device-pause command. The wheel keeps
pulling. Disabling vendor-specific FFB did not resolve it. Setting evdev gain
to zero released the wheel; restoring 5% gain with autocenter off reproduced
the pull.

`tools/lmu_ffb_guard.c` is an opt-in workaround for this streamed force. It
replaces an infinite constant effect with a 50 ms effect and renews playback
when the game updates an effect it has started. Once updates cease, the last
force expires. Stop and erase requests prevent renewal. The caller's effect
duration remains unchanged, so subsequent updates are still recognized.

Only USB identity `346e:0000` with the exact evdev name
`Gudsen MOZA R25 Ultra Base` is targeted. Finite effects, delayed or triggered
effects, envelopes, other effect types and other devices pass through. It does
not change bindings, firmware, gain or the physical device's descriptor.

## Build and use

Requires Linux x86-64, a C compiler and the normal evdev force-feedback path.

```sh
mkdir -p "$HOME/.local/lib/mozaproxy"
cc -shared -fPIC -O2 -Wall -Wextra -Werror -Wconversion -pthread \
  tools/lmu_ffb_guard.c -ldl \
  -o "$HOME/.local/lib/mozaproxy/lmu_ffb_guard.so"
```

For this workstation, use these Steam launch options for verification:

```text
PROTON_USE_EAC_LINUX=1 PROTON_ENABLE_WAYLAND=1 PROTON_LOG=1 WINEDEBUG=-all,+dinput LD_PRELOAD=/home/christian/.local/lib/mozaproxy/lmu_ffb_guard.so %command%
```

Restart LMU with the base's hardware torque reduced. The Proton log should
contain `lmu_ffb_guard: R25 streamed constant force expires after 50 ms` when
the first effect is uploaded. Verify driving feedback, pause, resume, and
returning to the garage before increasing torque. Remove `PROTON_LOG=1` and
`WINEDEBUG=-all,+dinput` after verification to stop the verbose capture.

Remove the `LD_PRELOAD=...` assignment and restart LMU to undo the workaround.
Never preload the helper globally or use it for another game.

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
