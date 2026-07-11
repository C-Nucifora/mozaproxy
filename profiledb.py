"""
profiledb - the per-game profile database (SPEC section 4 Layer 2, 6, 7).

WHY profiles exist: the udev hide-rule makes the real wheel invisible to games,
so every game must be routed through the daemon - and different games need
different faces (mode A/B/C), button counts, FFB gain and Proton env. A profile
captures all of that per game in one TOML file, so switching games is a single
Steam launch-option string (`mozactl run <profile> -- %command%`) instead of
manual daemon juggling.

Two profile directories: `profiles/` in the repo ships the seed DB, and
`~/.config/mozaproxy/profiles/` holds user profiles which shadow seeds by name.
A separate `calibration.toml` (written by `mozactl calibrate`) records which
real ABS axis actually carries throttle/brake/clutch on this user's hardware;
`merge_axes()` overlays a profile on top of it field-by-field, so a profile only
has to state what it wants to differ from the calibrated baseline.

`daemon_args()` renders a profile into the exact argv tail for mozaproxy.py.
The ordering is a contract: mozactl compares argv lists verbatim against the
running daemon's state file to decide whether a restart is needed, so two
equivalent profiles must always render identical argv.

Everything here is pure file/dict manipulation - no device I/O - so it is unit
testable with the base unplugged. TOML is parsed with stdlib tomllib; emitted
TOML is hand-generated (there is no TOML-writer dependency) with json.dumps
supplying valid basic-string escaping.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
import warnings
from dataclasses import dataclass, field

from evdev import ecodes

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_DIR = os.path.join(REPO_DIR, "profiles")
USER_DIR = os.path.expanduser("~/.config/mozaproxy/profiles")
CALIBRATION_PATH = os.path.expanduser("~/.config/mozaproxy/calibration.toml")


class ProfileError(Exception):
    """Any profile/calibration validation failure. Messages name the file."""


@dataclass
class AxisOverride:
    """Per-axis settings; None means 'unset' so profile/calibration can merge."""
    source: str | None = None      # evdev ABS_* name, e.g. "ABS_Z"
    invert: bool | None = None     # None = unset (tri-state for merging)
    deadzone: float | None = None  # None = unset; else 0..0.9


@dataclass
class Profile:
    """One game's settings. `name` is the lookup key (filename stem)."""
    name: str
    mode: str = "A"                # canonical letter A|B|C|D
    buttons: int | None = None     # 1..128
    ffb_gain: int = 100            # 0..100
    axes: dict[str, AxisOverride] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    steam_input: str = "default"   # "off" | "default"
    notes: str = ""
    path: str = ""                 # file it was loaded from


# ---------------------------------------------------------------------------
# Mode canonicalization.
# ---------------------------------------------------------------------------
_MODE_ALIASES: dict[str, str] = {
    "a": "A", "wheel": "A",
    "b": "B", "gamepad": "B", "xinput": "B", "pad": "B",
    "c": "C", "normalized": "C", "norm": "C",
    "d": "D", "off": "D", "passthrough": "D", "none": "D",
}


def canon_mode(s: str) -> str:
    """Resolve a mode selector or alias to its canonical letter A|B|C|D."""
    m = _MODE_ALIASES.get(str(s).strip().lower())
    if m is None:
        raise ProfileError(
            f"unknown mode {s!r}; expected one of A/wheel, B/gamepad/xinput/pad, "
            "C/normalized/norm, D/off/passthrough/none"
        )
    return m


# ---------------------------------------------------------------------------
# TOML schema validation. Strict on purpose: a typo'd key silently ignored
# would look like "the profile doesn't work", so unknown keys are errors that
# name the file and the key.
# ---------------------------------------------------------------------------
_TOP_KEYS = frozenset({"name", "mode", "buttons", "ffb_gain", "notes", "axes", "proton"})
_AXIS_NAMES = ("steering", "throttle", "brake", "clutch")
_AXIS_KEYS = frozenset({"source", "invert", "deadzone", "range"})
_PROTON_KEYS = frozenset({"env", "steam_input"})


def _is_int(v) -> bool:
    # bool is an int subclass; `buttons = true` must not pass as a count.
    return isinstance(v, int) and not isinstance(v, bool)


def _parse_axis(path: str, axis: str, table) -> AxisOverride:
    if not isinstance(table, dict):
        raise ProfileError(f"{path}: axes.{axis} must be a table")
    for key in table:
        if key not in _AXIS_KEYS:
            raise ProfileError(f"{path}: unknown key '{key}' in axes.{axis}")
    ov = AxisOverride()
    if "source" in table:
        src = table["source"]
        if (not isinstance(src, str) or not src.startswith("ABS_")
                or src not in ecodes.ecodes):
            raise ProfileError(
                f"{path}: axes.{axis}.source {src!r} is not a known evdev ABS_* name")
        ov.source = src
    if "invert" in table:
        inv = table["invert"]
        if not isinstance(inv, bool):
            raise ProfileError(f"{path}: axes.{axis}.invert must be a boolean")
        ov.invert = inv
    if "deadzone" in table:
        dz = table["deadzone"]
        if (isinstance(dz, bool) or not isinstance(dz, (int, float))
                or not 0.0 <= dz <= 0.9):
            raise ProfileError(f"{path}: axes.{axis}.deadzone must be a number in 0..0.9")
        ov.deadzone = float(dz)
    if "range" in table:
        rng = table["range"]
        if (not isinstance(rng, list) or len(rng) != 2
                or not all(_is_int(v) for v in rng)):
            raise ProfileError(f"{path}: axes.{axis}.range must be a list of 2 ints")
        warnings.warn(f"{path}: axes.{axis}.range is reserved, not yet applied")
    return ov


def _parse_axes(path: str, table) -> dict[str, AxisOverride]:
    if not isinstance(table, dict):
        raise ProfileError(f"{path}: [axes] must be a table")
    axes: dict[str, AxisOverride] = {}
    for axis, sub in table.items():
        if axis not in _AXIS_NAMES:
            raise ProfileError(
                f"{path}: unknown axis '{axis}' in [axes] "
                f"(expected one of {', '.join(_AXIS_NAMES)})")
        axes[axis] = _parse_axis(path, axis, sub)
    return axes


def _parse_profile_file(path: str) -> Profile:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ProfileError(f"{path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ProfileError(f"{path}: invalid TOML: {e}") from e

    for key in data:
        if key not in _TOP_KEYS:
            raise ProfileError(f"{path}: unknown key '{key}'")

    if "mode" not in data:
        raise ProfileError(f"{path}: missing required key 'mode'")
    if not isinstance(data["mode"], str):
        raise ProfileError(f"{path}: 'mode' must be a string")
    try:
        mode = canon_mode(data["mode"])
    except ProfileError as e:
        raise ProfileError(f"{path}: {e}") from None

    if "name" in data and not isinstance(data["name"], str):
        raise ProfileError(f"{path}: 'name' must be a string")

    buttons = data.get("buttons")
    if buttons is not None and (not _is_int(buttons) or not 1 <= buttons <= 128):
        raise ProfileError(f"{path}: 'buttons' must be an integer in 1..128")

    ffb_gain = data.get("ffb_gain", 100)
    if not _is_int(ffb_gain) or not 0 <= ffb_gain <= 100:
        raise ProfileError(f"{path}: 'ffb_gain' must be an integer in 0..100")

    notes = data.get("notes", "")
    if not isinstance(notes, str):
        raise ProfileError(f"{path}: 'notes' must be a string")

    axes = _parse_axes(path, data["axes"]) if "axes" in data else {}

    env: dict[str, str] = {}
    steam_input = "default"
    if "proton" in data:
        proton = data["proton"]
        if not isinstance(proton, dict):
            raise ProfileError(f"{path}: [proton] must be a table")
        for key in proton:
            if key not in _PROTON_KEYS:
                raise ProfileError(f"{path}: unknown key '{key}' in [proton]")
        if "env" in proton:
            if not isinstance(proton["env"], dict):
                raise ProfileError(f"{path}: proton.env must be a table")
            for k, v in proton["env"].items():
                if not isinstance(v, str):
                    raise ProfileError(
                        f"{path}: proton.env value for '{k}' must be a string")
                env[k] = v
        if "steam_input" in proton:
            steam_input = proton["steam_input"]
            if steam_input not in ("off", "default"):
                raise ProfileError(
                    f"{path}: proton.steam_input must be 'off' or 'default'")

    # The filename stem is the lookup key; the in-file `name` is cosmetic only,
    # so a copied file can never impersonate another profile.
    stem = os.path.splitext(os.path.basename(path))[0]
    return Profile(name=stem, mode=mode, buttons=buttons, ffb_gain=ffb_gain,
                   axes=axes, env=env, steam_input=steam_input, notes=notes,
                   path=path)


# ---------------------------------------------------------------------------
# Lookup.
# ---------------------------------------------------------------------------
def load_profile(name_or_path: str) -> Profile:
    """Load a profile by name (USER_DIR shadows SEED_DIR) or by direct path."""
    if "/" in name_or_path or name_or_path.endswith(".toml"):
        if not os.path.exists(name_or_path):
            raise ProfileError(f"{name_or_path}: no such profile file")
        return _parse_profile_file(name_or_path)
    for d in (USER_DIR, SEED_DIR):
        candidate = os.path.join(d, name_or_path + ".toml")
        if os.path.exists(candidate):
            return _parse_profile_file(candidate)
    raise ProfileError(
        f"no profile named {name_or_path!r} in {USER_DIR} or {SEED_DIR}")


def list_profiles() -> list[Profile]:
    """All loadable profiles, sorted by name; user profiles shadow seeds."""
    # Seed dir first so a same-named user profile overwrites its entry.
    profiles: dict[str, Profile] = {}
    for d in (SEED_DIR, USER_DIR):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".toml"):
                continue
            path = os.path.join(d, fn)
            try:
                prof = _parse_profile_file(path)
            except ProfileError as e:
                warnings.warn(f"skipping profile {path}: {e}")
                continue
            profiles[prof.name] = prof
    return sorted(profiles.values(), key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Calibration overlay.
# ---------------------------------------------------------------------------
def load_calibration() -> dict[str, AxisOverride]:
    """Parse CALIBRATION_PATH into per-axis overrides; {} if the file is absent."""
    path = CALIBRATION_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ProfileError(f"{path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ProfileError(f"{path}: invalid TOML: {e}") from e
    for key in data:
        if key != "axes":
            raise ProfileError(f"{path}: unknown key '{key}'")
    return _parse_axes(path, data.get("axes", {}))


def merge_axes(profile: Profile,
               calibration: dict[str, AxisOverride]) -> dict[str, AxisOverride]:
    """Field-level merge: a profile's set fields win, calibration fills the rest.

    An axis appears in the result if either side mentions it, so a calibrated
    throttle source applies even to profiles that never name the throttle.
    """
    merged: dict[str, AxisOverride] = {}
    for axis in _AXIS_NAMES:
        p = profile.axes.get(axis)
        c = calibration.get(axis)
        if p is None and c is None:
            continue
        p = p or AxisOverride()
        c = c or AxisOverride()
        merged[axis] = AxisOverride(
            source=p.source if p.source is not None else c.source,
            invert=p.invert if p.invert is not None else c.invert,
            deadzone=p.deadzone if p.deadzone is not None else c.deadzone,
        )
    return merged


# ---------------------------------------------------------------------------
# Daemon argv rendering. ORDER IS A CONTRACT: mozactl compares this list
# verbatim against the running daemon's state to decide whether to restart, so
# equivalent profiles must render byte-identical argv.
# ---------------------------------------------------------------------------
# (profile axis name, daemon flag stem) in canonical flag order.
_AXIS_FLAGS = (("steering", "steer"), ("throttle", "throttle"),
               ("brake", "brake"), ("clutch", "clutch"))


def daemon_args(profile: Profile,
                calibration: dict[str, AxisOverride]) -> list[str]:
    """Render the mozaproxy.py argv tail for a profile + calibration overlay."""
    mode = canon_mode(profile.mode)
    if mode == "D":
        raise ProfileError(
            f"profile {profile.name!r} is mode D (passthrough): "
            "the daemon is not run for it")
    merged = merge_axes(profile, calibration)

    argv = ["--mode", mode]
    if mode in ("A", "C") and profile.buttons is not None:
        argv += ["--buttons", str(profile.buttons)]
    if profile.ffb_gain != 100:
        argv += ["--ffb-gain", str(profile.ffb_gain)]
    if mode in ("B", "C"):
        steering = merged.get("steering")
        if steering is not None and steering.deadzone is not None \
                and steering.deadzone > 0:
            argv += ["--deadzone", str(steering.deadzone)]
    if mode == "B":
        for axis, flag in _AXIS_FLAGS:
            ov = merged.get(axis)
            if ov is not None and ov.source is not None:
                argv += [f"--{flag}-src", ov.source]
        for axis, flag in _AXIS_FLAGS:
            ov = merged.get(axis)
            if ov is not None and ov.invert is True:
                argv.append(f"--{flag}-invert")
    return argv


def launch_env(profile: Profile, base_env: dict | None = None) -> dict[str, str]:
    """A copy of base_env (default os.environ) overlaid with the profile's env."""
    env = dict(os.environ if base_env is None else base_env)
    env.update(profile.env)
    return env


# ---------------------------------------------------------------------------
# TOML emission. Hand-generated (no writer dep); json.dumps produces valid TOML
# basic-string escaping for the values we emit (str/bool/int/float).
# ---------------------------------------------------------------------------
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(k: str) -> str:
    return k if _BARE_KEY.match(k) else json.dumps(k)


def _toml_scalar(v) -> str:
    if isinstance(v, (str, bool, int, float)):
        return json.dumps(v)
    raise ProfileError(f"cannot emit {type(v).__name__} as a TOML value")


def _inline_table(items: list[tuple[str, object]]) -> str:
    if not items:
        return "{}"
    return "{ " + ", ".join(f"{_toml_key(k)} = {_toml_scalar(v)}" for k, v in items) + " }"


def emit_profile_toml(profile: Profile) -> str:
    """Serialize a Profile; only set/non-default keys are emitted."""
    lines = [
        f"name = {_toml_scalar(profile.name)}",
        f"mode = {_toml_scalar(canon_mode(profile.mode))}",
    ]
    if profile.buttons is not None:
        lines.append(f"buttons = {profile.buttons}")
    if profile.ffb_gain != 100:
        lines.append(f"ffb_gain = {profile.ffb_gain}")
    if profile.notes:
        lines.append(f"notes = {_toml_scalar(profile.notes)}")

    axis_lines = []
    for axis in _AXIS_NAMES:
        ov = profile.axes.get(axis)
        if ov is None:
            continue
        items: list[tuple[str, object]] = []
        if ov.source is not None:
            items.append(("source", ov.source))
        if ov.invert is not None:
            items.append(("invert", ov.invert))
        if ov.deadzone is not None:
            items.append(("deadzone", ov.deadzone))
        if items:
            axis_lines.append(f"{axis} = {_inline_table(items)}")
    if axis_lines:
        lines += ["", "[axes]"] + axis_lines

    if profile.env or profile.steam_input != "default":
        lines += ["", "[proton]"]
        if profile.env:
            lines.append(f"env = {_inline_table(list(profile.env.items()))}")
        if profile.steam_input != "default":
            lines.append(f"steam_input = {_toml_scalar(profile.steam_input)}")
    return "\n".join(lines) + "\n"


def emit_calibration_toml(axes: dict[str, dict]) -> str:
    """Serialize calibrator output ({axis: {field: value}}) to calibration TOML."""
    lines = ["[axes]"]
    ordered = [a for a in _AXIS_NAMES if a in axes]
    ordered += [a for a in axes if a not in _AXIS_NAMES]
    for axis in ordered:
        lines.append(f"{_toml_key(axis)} = {_inline_table(list(axes[axis].items()))}")
    return "\n".join(lines) + "\n"


def save_calibration(axes: dict[str, dict]) -> str:
    """Write calibrator output to CALIBRATION_PATH (creating dirs); return path."""
    path = CALIBRATION_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(emit_calibration_toml(axes))
    return path


# ---------------------------------------------------------------------------
# Restart decision. Pure so mozactl's "is the daemon already right?" check is
# trivially testable; mozactl supplies the state file dict and live pids.
# ---------------------------------------------------------------------------
def needs_restart(state: dict | None, desired_argv: list[str],
                  live_pids: list[int]) -> bool:
    """True unless a live, state-tracked daemon is already running desired_argv."""
    if not live_pids:
        return True
    if state is None:
        return True
    if state.get("pid") not in live_pids:
        return True
    return state.get("argv") != desired_argv


__all__ = [
    "REPO_DIR", "SEED_DIR", "USER_DIR", "CALIBRATION_PATH",
    "ProfileError", "AxisOverride", "Profile",
    "canon_mode", "load_profile", "list_profiles",
    "load_calibration", "merge_axes", "daemon_args", "launch_env",
    "emit_profile_toml", "emit_calibration_toml", "save_calibration",
    "needs_restart",
]
