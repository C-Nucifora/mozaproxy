#!/usr/bin/env python3
"""
Generate Farming Simulator (22/25) wheel bindings for the mozaproxy virtual
MOZA wheel, derived from an existing Logitech G29 binding set in the same file.

FS stores a recognized wheel's core driving axes (steer/throttle/brake/clutch) in
its *device profile*, and only per-user button customisations in inputBinding.xml.
The mozaproxy virtual wheel is an *unrecognised* generic device, so it has no
profile defaults - we must supply the driving axes ourselves and copy the button
layout across from the G29 by button number.

Axis assignment (from live axis rest-state + the user's own partial mapping):
  steering  -> AXIS_0 (ABS_X, the only self-centering axis)
  accelerate-> AXIS_7   brake -> AXIS_3   clutch -> AXIS_6
Pedal polarity mirrors the user's tested FS22 values (input AXIS_n-, neutral 1).

Usage: fs_wheel_map.py <inputBinding.xml>
Writes a .bak-<timestamp> alongside the file before modifying.
"""
import re
import shutil
import sys
import time

# Virtual device id string (HID-path based, identical across FS22/FS25).
VIRT = ("0_346E-0002-0111-XFw/XEhJRCNWSURfMzQ2RSZQSURfMDAwMiMyNzMmMDAwMEZGRkZG"
        "RkZGMDAwMjM0NkUmMCYwJjAjezREMUU1NUIyLUYxNkYtMTFDRi04OENCLTAwMTExMTAw"
        "MDAzMH0A")
G29_PREFIX = "046D-C266"
MAX_BUTTON = 24  # virtual device exposes 24 buttons

# Explicit driving-axis bindings for the virtual wheel: action -> list of
# (input, axisComponent, neutralInput).
AXIS_ACTIONS = {
    "AXIS_MOVE_SIDE_VEHICLE": [("AXIS_0-", "-", "0"), ("AXIS_0+", "+", "0")],
    "AXIS_ACCELERATE_VEHICLE": [("AXIS_7-", "+", "1")],
    "AXIS_BRAKE_VEHICLE": [("AXIS_3-", "+", "1")],
    "AXIS_CLUTCH_VEHICLE": [("AXIS_6-", "+", "1")],
}

BUTTON_RE = re.compile(r"BUTTON_(\d+)")
AXIS_TOK_RE = re.compile(r"AXIS_(\d+)")


def input_fits(inp: str) -> bool:
    """Keep a copied binding only if every button it references exists on the
    virtual device, and it references no G29-only high axis (11/13...)."""
    for n in BUTTON_RE.findall(inp):
        if int(n) > MAX_BUTTON:
            return False
    for n in AXIS_TOK_RE.findall(inp):
        if int(n) > 9:  # virtual device only has AXIS_0..9
            return False
    return True


def transform(path: str) -> None:
    src = open(path, encoding="utf-8").read()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, f"{path}.bak-{stamp}")

    added_axis = 0
    added_btn = 0
    dropped = 0

    def do_action(m: re.Match) -> str:
        nonlocal added_axis, added_btn, dropped
        action = m.group(1)
        body = m.group(2)

        # Strip any pre-existing virtual-device bindings for a clean redo.
        body = re.sub(r'\s*<binding device="0_346E-0002[^"]*"[^/]*/>', "", body)

        # Highest existing index in this action, to append uniquely.
        idxs = [int(i) for i in re.findall(r'index="(\d+)"', body)]
        next_idx = (max(idxs) + 1) if idxs else 1

        new_lines = []

        if action in AXIS_ACTIONS:
            for inp, comp, neutral in AXIS_ACTIONS[action]:
                new_lines.append(
                    f'        <binding device="{VIRT}" input="{inp}" '
                    f'axisComponent="{comp}" neutralInput="{neutral}" index="{next_idx}"/>'
                )
                next_idx += 1
                added_axis += 1
        else:
            # Copy each G29 binding onto the virtual device by button number.
            for gm in re.finditer(
                r'<binding device="0_' + G29_PREFIX + r'[^"]*"([^/]*)/>', body
            ):
                attrs = dict(re.findall(r'(\w+)="([^"]*)"', gm.group(1)))
                inp = attrs.get("input", "")
                if not inp or not input_fits(inp):
                    dropped += 1
                    continue
                comp = attrs.get("axisComponent", "+")
                neutral = attrs.get("neutralInput", "0")
                new_lines.append(
                    f'        <binding device="{VIRT}" input="{inp}" '
                    f'axisComponent="{comp}" neutralInput="{neutral}" index="{next_idx}"/>'
                )
                next_idx += 1
                added_btn += 1

        if new_lines:
            body = body.rstrip() + "\n" + "\n".join(new_lines) + "\n    "
        return f'<actionBinding action="{action}">{body}</actionBinding>'

    out = re.sub(
        r'<actionBinding action="([^"]+)">(.*?)</actionBinding>',
        do_action,
        src,
        flags=re.S,
    )
    open(path, "w", encoding="utf-8").write(out)
    print(f"{path}")
    print(f"  axis bindings added : {added_axis}")
    print(f"  button bindings added: {added_btn}")
    print(f"  dropped (>24 btn / hi axis): {dropped}")
    print(f"  backup: {path}.bak-{stamp}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: fs_wheel_map.py <inputBinding.xml>")
    transform(sys.argv[1])
