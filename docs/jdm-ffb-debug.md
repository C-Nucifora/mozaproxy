# JDM force-feedback investigation

Updated after the attended post-reboot test on 2026-09-18. The user confirmed
working controls and acceptable physical FFB with no freezing using direct
HIDRAW and the existing descriptor helper. The recurring freezes were traced
to T3 preview scans of Steam ports; excluding Steam from those scans fixed the
attended FH5 and JDM runs. No output-report encoding change was required for
these passes. The analysis below records earlier hypotheses, not established
remaining defects. Integrated system-mode routing still needs validation.

## Current physical capture

Evidence is archived under
`~/.local/state/mozaproxy/game-tests/jdm-freeze-return-20260918-171451/`:
`hid-capture.jsonl`, `physical-capture-proton.log`, `waits.jsonl` and
`gpu-samples.jsonl`. The game ran with the descriptor helper and capture helper.
This covers startup and a stationary garage, not moving driving.

The HID file reached its configured 4096-record limit. First-to-last report
timestamps span 216.286 seconds, including startup. Approximately 18.9 seconds
were garage activity, estimated from screenshot arrival rather than a precise
scene-transition timestamp. Reaching the collector cap ends the evidence; it
does not mean the game stopped issuing reports.

- All recorded calls succeeded; none had truncated payloads. The longest
  forwarded call took 2.441 ms. No long HID call was captured in this interval.
  The measurement excludes tracer bookkeeping and cannot rule out later stalls,
  other threads, unrecorded calls or moving-driving problems.
- All 96 set-effect reports used trigger byte `ff`, infinite duration and zero
  start delay. This confirms the predicted trigger encoding; it does not show
  whether the R25 firmware interprets it correctly. No envelope reports were
  captured. A repeatedly restarted nonzero start delay is unsupported by this
  sample.
- The capture includes three resets and two stop-all commands. PID Reset enables
  actuators as part of its defined behavior, so absence of a separate enable
  command is not evidence that actuators stayed disabled. See the
  [PID specification, printed page 23](https://www.usb.org/sites/default/files/documents/pid1_01.pdf).
- The archive also contains GPU and thread-wait samples. Wait-channel snapshots
  alone do not identify the cause of a stall. Allocation-fallback warnings can
  reflect vkd3d-proton's internal resizable-BAR upload budget, which can be limited
  to one-sixteenth of the relevant heap. The
  [budget setup](https://github.com/HansKristian-Work/vkd3d-proton/blob/af89350cc2eacd9/libs/vkd3d/resource.c#L11107)
  and [allocation fallback](https://github.com/HansKristian-Work/vkd3d-proton/blob/af89350cc2eacd9/libs/vkd3d/memory.c#L984)
  show why the warning does not establish exhaustion of total GPU memory.
  Neither warning counts nor idle utilization establish the freeze cause.

The user has renewed authorization for autonomous game testing while away,
superseding the earlier attended-only restriction on running captures. Physical
force feel and safe driving quality still require the user's observation.

## What the archived trace establishes

Reviewed `~/.local/state/mozaproxy/game-tests/jdm-descriptor-test-20260917-225229/proton.log`,
recorded under GE-Proton10-34 with `WINEDEBUG=-all,+dinput`.

The collection workaround repaired DirectInput PID recognition. The trace now
reports device control ID 12, set-effect ID 1, and constant-force ID 5. Across
875,279 lines it contains:

| Event | Count |
| --- | ---: |
| CreateEffect | 2 |
| SetParameters | 18,398 |
| Start | 18,400 |
| Download | 12,941 |
| Unknown angle unit warning | 6,028 |
| Stop | 4 |
| Unload | 7 |

18,396 parameter updates use `0x20000140`, meaning direction and type-specific
parameters plus `DIEP_START`. Only two use the initial full-parameter flags
`0x800003ff`. This establishes frequent restart requests, but does not show
their magnitude, duration, envelope, or device result. Function-entry trace
counts are not counts of successful HID writes.

No collection-parent warnings, time-unit warnings, or logged HidP setter
errors were found. The many hex dumps are **input reports**. They cannot tell
us which PID bytes Wine sent to the base. The user's report of intermittent or
incorrect force therefore remains unresolved.

## Encoding differences to check

### Disabled trigger encoding is confirmed; its effect is unresolved

The fixture's set-effect report has an 8-bit trigger field at byte 12, including
the report-ID byte. Its advertised logical range is 1 through 8.

Wine initializes `dwTriggerButton` to `-1`, uses that value for an unmapped or
disabled trigger, and passes it directly to `HidP_SetUsageValue` during Download.
Wine's HID setter copies the requested bits without range validation, so the
predicted wire value for a disabled trigger is `0xff`.

Linux PIDFF instead writes zero when a trigger exceeds the device's advertised
maximum and also clears the repeat interval. These are different encodings.
The working direct evdev pulse used a zero trigger. The current physical capture
confirms JDM's `0xff` trigger byte, but does not establish whether this firmware
treats it as disabled. The encoding difference remains a candidate to compare,
not an explanation for the reported force or freeze.

Source references: Wine
[effect initialization and Download](https://github.com/wine-mirror/wine/blob/master/dlls/dinput/joystick_hid.c),
[HidP_SetUsageValue](https://github.com/wine-mirror/wine/blob/master/dlls/hid/hidp.c),
and Linux
[pidff_set_effect_report](https://github.com/torvalds/linux/blob/master/drivers/hid/usbhid/hid-pidff.c).
The local Wine source used for line-by-line review is
`/tmp/mozaproxy-wine-joystick_hid.c`. Upstream sources describe the compared
implementations, not proof of every byte in the installed GE build.

### The angle warning alone is insufficient

The two direction fields have logical range 0 through 36000, unit zero, and
exponent zero. Wine warns about the missing angle unit but still scales the
angle. It replaces the physical range with 0 through 35900. For example, a
9000 input becomes 9025, and 27000 becomes 27075. Those are small angular
differences, not an established explanation for intermittent force.

Do not swap the direction fields based on Download's reverse indexing.
[Wine's HID parser](https://github.com/wine-mirror/wine/blob/master/dlls/hidparse.sys/main.c)
stores these multi-usage variable fields in reverse order, and Download's
indexing reverses that again. The first direction belongs at bytes 14–15.

### Inspect restart timing and envelope together

The game repeatedly asks to start the existing effect when updating direction
and magnitude. Capture reports 1, 2, 5, and 10 with monotonic timestamps. An
attack envelope or nonzero start delay repeatedly restarted before completion
would be distinguishable from a steady effect with a wrong sign. The archived
DirectInput log omits those values. The new physical capture shows infinite
duration and zero start delay, with no envelope report in the bounded sample.
Further testing must distinguish moving-driving behavior from the stationary
garage.

## Offline decoder

`tools/jdm_reports.py` decodes supplied hex reports and summarizes saved logs.
It has no device discovery, capture, ioctl, or report-write functions. Offsets
are specific to the captured `tests/fixtures/r25-ultra-descriptor.bin`.

```sh
python tools/jdm_reports.py --log ~/.local/state/mozaproxy/game-tests/jdm-descriptor-test-20260917-225229/proton.log
python tools/jdm_reports.py --report-hex '05 02 9a f9'
python -m unittest discover -s tests -p 'test_jdm_reports.py' -v
```

The second command is synthetic input, a constant magnitude of -1638 in slot 2.
It does not send anything. The decoder accepts longer padded output buffers
and identifies padding separately. It rejects truncated and unknown reports.

Important set-effect offsets, counting the report ID as byte zero:

| Bytes | Field |
| --- | --- |
| 0 | Report ID, 1 |
| 1 | Effect slot, 1 through 10 |
| 2 | Effect type, constant is 1 |
| 3–4 | Duration in milliseconds, `ffff` means infinite |
| 5–6 | Trigger-repeat interval in milliseconds |
| 7–8 | Sample period in milliseconds |
| 9–10 | Start delay in milliseconds |
| 11 | Effect gain, 0 through 255 |
| 12 | Trigger button |
| 13 | X enable bit 0, Y enable bit 1, direction enable bit 2 |
| 14–15, 16–17 | First and second direction values |
| 18–19, 20–21 | Type-specific offsets |

Report 5 contains its ID, slot, and signed little-endian 16-bit magnitude.
Report 10 contains its ID, slot, operation, and repeat count. Report 12 is a
control **bitmask**, not a numeric operation selector.

## Next controlled test

The separate `compat/jdm_trace.c` helper captures outbound hidraw `write` reports
and feature-report ioctls. It does not generate, modify, or replay reports.
Autonomous captures are now authorized; physical force-feel conclusions remain
pending user observation.

For the next comparison, retain the existing descriptor workaround and known
wheel settings. Decode the captured reports and check:

1. Whether the confirmed `ff` trigger encoding changes in the comparison.
2. Direction, signed magnitude, and gain while steering in each direction.
3. Start frequency against duration, start delay, and envelope attack time.
4. Device-control resets, disables, or pauses interleaved with playback.
5. Write failures or unexpected report lengths.

The confirmed `ff` byte makes `ff` to `00` a narrow candidate A/B change for
that field only, scoped to the exact descriptor and device. No such change or
successful result is established by this capture. Compare the same short input
sequence and obtain user confirmation of physical feel before calling it a fix.
Keep this separate from descriptor recognition and the independently reproduced
game freeze.

## Capture helper setup

Build the helper without activating it:

```sh
mkdir -p "$HOME/.local/lib/mozaproxy"
cc -shared -fPIC -O2 -Wall -Wextra -Werror compat/jdm_trace.c -ldl -pthread \
  -o "$HOME/.local/lib/mozaproxy/jdm_trace.so"
```

Capture remains off unless `MOZAPROXY_JDM_TRACE` names an absolute log path on
tmpfs. Use a fresh file under `/dev/shm`. Non-tmpfs directories and symlink log
targets are rejected. The default limit is 512 matching calls, configurable
with `MOZAPROXY_JDM_TRACE_LIMIT` up to 4096. Existing records count toward the
per-file limit, including records from other processes. The file cannot grow
beyond 1 MiB through this helper, and each payload is capped at 128 bytes.

For a capture, prepend the capture helper to the existing
descriptor-helper preload. Ordering matters: `jdm_hid.so` calls the kernel
directly for ioctls, so a tracer placed after it would miss feature requests.
For this workstation, the relevant environment assignments are:

```text
MOZAPROXY_JDM_TRACE=/dev/shm/mozaproxy-jdm-attended.jsonl
MOZAPROXY_JDM_TRACE_LIMIT=512
LD_PRELOAD=/home/your-user/.local/lib/mozaproxy/jdm_trace.so:/home/your-user/.local/lib/mozaproxy/jdm_hid.so
```

Keep the already-tested hidraw enablement. These assignments are documentation,
not installed launch options. Do not turn broad dinput input tracing back on
for this capture. After the test, copy the file to the game-test archive before
rebooting, then remove the capture helper and its capture environment variables.

To save the event budget for driving, also set an optional arm marker path:

```text
MOZAPROXY_JDM_TRACE_ARM=/dev/shm/mozaproxy-jdm-driving.arm
```

Choose a fresh marker name that does not exist in the game's mount namespace.
Once the desired driving scene is ready, create the marker in that namespace.
For a verified winedevice PID and `arm_name=mozaproxy-jdm-driving.arm`:

```sh
touch -- "/proc/${winedevice_pid}/root/dev/shm/${arm_name}"
```

The marker must be an absolute path to a regular file owned by the process's
UID on tmpfs; a final symlink is rejected. Its contents are unused. Until a
valid marker exists, each eligible call performs a metadata check and forwards
normally, without capture clocks, device probes, or event-budget consumption.
Metadata inspection uses `O_PATH`, so invalid device nodes and FIFOs are not
activated. Invalid or missing markers are retried on subsequent calls. After
the first valid marker, capture stays armed in that process without further
marker checks; removing the marker does not pause or reset capture. Existing
event and file limits still apply. Use a fresh marker and log for the next
session. Leaving `MOZAPROXY_JDM_TRACE_ARM` unset retains immediate capture.

Proton may provide a private `/dev/shm`; the host's directory can therefore look
empty while capture is active. The successful run recovered the file through the
owning winedevice process's mount namespace. With the verified PID and actual
capture basename, archive it before that process exits:

```sh
cp -- "/proc/${winedevice_pid}/root/dev/shm/${capture_name}" \
  "${capture_archive}/hid-capture.jsonl"
```

Those variables identify the running game's winedevice process, its capture
file and the existing archive directory. The recorded run used
`MOZAPROXY_JDM_TRACE_LIMIT=4096`; the example above retains the shorter default.

The tracer checks hidraw VID/PID `346e:0000` and an R25 model name, since other
MOZA bases can share that USB identity. It records process/thread IDs, original
fd, operation, ioctl request, requested byte count, result, errno on failure,
monotonic start time, call duration, and payload bytes. Failed calls retain
metadata with an empty payload, avoiding a dereference of a rejected pointer.
`get_feature` records reply bytes; `set_feature` and `write` record successful
output data. It never reads normal wheel input reports.

The capture adds synchronous identity checks, formatting, and tmpfs operations
to the calling thread. It is not latency-neutral. `elapsed_ns` measures the
forwarded call only and excludes subsequent tracer work. The file lock is
nonblocking, so contention can drop records; the output is not guaranteed to
contain every report. Per-thread inode/offset caching avoids rescanning the
whole growing log on each event, and after the local cap the wrappers skip
configuration checks, clocks, and device probes. Use the shortest capture that
answers the encoding question, and assess game freezes separately without it.

Decode the saved capture offline:

```sh
python tools/jdm_reports.py --capture /dev/shm/mozaproxy-jdm-attended.jsonl
python -m unittest discover -s tests -p 'test_jdm_*.py' -v
```

The decoder preserves unknown reports and failed calls for inspection. It
decodes supported output reports and PID create-effect, block-load, and pool
feature reports. Mock tests exercise forwarding, errno, device filtering,
disabled behavior, failed pointers, shared event/file bounds, tmpfs-only
logging, and marker activation between calls. They verify invalid markers leave
the budget untouched and removal after activation does not disarm capture.
They do not establish Proton container loading or physical FFB.

## Follow-up live detach observation

The virtual wheel could shift the stationary car from neutral into first, but
scripted pedals did not establish vehicle movement. Its capture contains two
near-zero constant uploads separated by an erase and repeated effect starts.
The capture path logs every upload/update and does not coalesce parameters.
This stationary result cannot establish driving force quality.

After virtual-device removal, while the physical R25 remained masked, nine
consecutive Hypruse screenshots were byte-identical for at least8.67seconds,
including the animated menu and performance overlay. Later captures changed
again. No descriptor helper, HID tracer, LSFG or MangoHud was mapped in the
observed game process. This shows a stall persisted in the same session without
an attached game wheel; a fresh no-wheel launch is still needed to separate
initialization effects. The user was navigating graphics settings during this
period, so it is not a controlled graphics comparison. Evidence is archived in
`jdm-freeze-return-20260918-171451/no-wheel-screenshot-hashes.json`.

The user then requested a restart. Current saves/settings were archived and
preserved, virtual-device isolation removed, and direct input-only launch
settings restored. This run does not establish a stutter fix.
