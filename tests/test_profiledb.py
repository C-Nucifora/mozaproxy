"""Tests for the per-game profile database (profiledb).

All pure and hardware-free: profiles are written to tmp_path and the module's
directory constants (USER_DIR/SEED_DIR/CALIBRATION_PATH) are monkeypatched, so
nothing under ~/.config is read or written. The one exception is
TestSeedProfiles, which reads the repo's shipped profiles/ directory on purpose.
"""
from __future__ import annotations

import glob
import os
import tomllib

import pytest

import profiledb
from profiledb import (
    AxisOverride,
    Profile,
    ProfileError,
    canon_mode,
    daemon_args,
    emit_calibration_toml,
    emit_profile_toml,
    launch_env,
    list_profiles,
    load_calibration,
    load_profile,
    merge_axes,
    needs_restart,
    save_calibration,
)


def write(dirpath, name: str, text: str) -> str:
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / f"{name}.toml"
    p.write_text(text)
    return str(p)


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """Redirect all profiledb filesystem constants into tmp_path."""
    user = tmp_path / "user"
    seed = tmp_path / "seed"
    calib = tmp_path / "config" / "calibration.toml"
    monkeypatch.setattr(profiledb, "USER_DIR", str(user))
    monkeypatch.setattr(profiledb, "SEED_DIR", str(seed))
    monkeypatch.setattr(profiledb, "CALIBRATION_PATH", str(calib))
    return user, seed


# ---------------------------------------------------------------------------
# canon_mode
# ---------------------------------------------------------------------------
class TestCanonMode:
    @pytest.mark.parametrize("alias,expected", [
        ("a", "A"), ("A", "A"), ("wheel", "A"), ("WHEEL", "A"), (" a ", "A"),
        ("b", "B"), ("gamepad", "B"), ("xinput", "B"), ("pad", "B"), ("Pad", "B"),
        ("c", "C"), ("normalized", "C"), ("norm", "C"), ("NORM", "C"),
        ("d", "D"), ("off", "D"), ("passthrough", "D"), ("none", "D"),
    ])
    def test_aliases(self, alias, expected):
        assert canon_mode(alias) == expected

    @pytest.mark.parametrize("bad", ["e", "", "wheelz", "x360", "1"])
    def test_unknown_raises(self, bad):
        with pytest.raises(ProfileError):
            canon_mode(bad)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
class TestValidation:
    def test_minimal_profile_defaults(self, tmp_path):
        path = write(tmp_path, "mini", 'mode = "A"\n')
        p = load_profile(path)
        assert p.name == "mini"          # filename stem, not TOML name field
        assert p.mode == "A"
        assert p.buttons is None
        assert p.ffb_gain == 100
        assert p.axes == {}
        assert p.env == {}
        assert p.steam_input == "default"
        assert p.notes == ""
        assert p.path == path

    def test_mode_alias_canonicalized(self, tmp_path):
        p = load_profile(write(tmp_path, "g", 'mode = "gamepad"\n'))
        assert p.mode == "B"

    def test_name_field_is_cosmetic(self, tmp_path):
        p = load_profile(write(tmp_path, "real", 'name = "fake"\nmode = "A"\n'))
        assert p.name == "real"

    def test_missing_mode(self, tmp_path):
        path = write(tmp_path, "nomode", 'buttons = 24\n')
        with pytest.raises(ProfileError, match=r"nomode\.toml.*mode"):
            load_profile(path)

    def test_bad_mode(self, tmp_path):
        path = write(tmp_path, "badmode", 'mode = "z"\n')
        with pytest.raises(ProfileError, match=r"badmode\.toml.*unknown mode"):
            load_profile(path)

    def test_unknown_top_level_key(self, tmp_path):
        path = write(tmp_path, "extra", 'mode = "A"\nbogus = 1\n')
        with pytest.raises(ProfileError, match=r"extra\.toml.*'bogus'"):
            load_profile(path)

    @pytest.mark.parametrize("value", ["0", "129", '"24"', "true"])
    def test_bad_buttons(self, tmp_path, value):
        path = write(tmp_path, "btn", f'mode = "A"\nbuttons = {value}\n')
        with pytest.raises(ProfileError, match="buttons"):
            load_profile(path)

    @pytest.mark.parametrize("value", ["-1", "101", '"50"', "true", "50.5"])
    def test_bad_ffb_gain(self, tmp_path, value):
        path = write(tmp_path, "gain", f'mode = "A"\nffb_gain = {value}\n')
        with pytest.raises(ProfileError, match="ffb_gain"):
            load_profile(path)

    def test_bad_notes(self, tmp_path):
        path = write(tmp_path, "notes", 'mode = "A"\nnotes = 3\n')
        with pytest.raises(ProfileError, match="notes"):
            load_profile(path)

    def test_unknown_axis_name(self, tmp_path):
        path = write(tmp_path, "ax",
                     'mode = "B"\n[axes]\nhandbrake = { source = "ABS_Y" }\n')
        with pytest.raises(ProfileError, match="handbrake"):
            load_profile(path)

    def test_unknown_axis_field(self, tmp_path):
        path = write(tmp_path, "axf",
                     'mode = "B"\n[axes]\nsteering = { curve = 1.5 }\n')
        with pytest.raises(ProfileError, match=r"axf\.toml.*'curve'"):
            load_profile(path)

    @pytest.mark.parametrize("src", ['"ABS_NOPE"', '"BTN_A"', '"abs_x"', "3"])
    def test_bad_axis_source(self, tmp_path, src):
        path = write(tmp_path, "src",
                     f'mode = "B"\n[axes]\nthrottle = {{ source = {src} }}\n')
        with pytest.raises(ProfileError, match="source"):
            load_profile(path)

    @pytest.mark.parametrize("dz", ["1.0", "-0.1", '"big"', "true"])
    def test_bad_deadzone(self, tmp_path, dz):
        path = write(tmp_path, "dz",
                     f'mode = "C"\n[axes]\nsteering = {{ deadzone = {dz} }}\n')
        with pytest.raises(ProfileError, match="deadzone"):
            load_profile(path)

    def test_bad_invert(self, tmp_path):
        path = write(tmp_path, "inv",
                     'mode = "B"\n[axes]\nbrake = { invert = 1 }\n')
        with pytest.raises(ProfileError, match="invert"):
            load_profile(path)

    def test_range_accepted_but_warned(self, tmp_path):
        path = write(tmp_path, "rng",
                     'mode = "C"\n[axes]\n'
                     'steering = { source = "ABS_X", range = [-32768, 32767] }\n')
        with pytest.warns(UserWarning, match="range is reserved, not yet applied"):
            p = load_profile(path)
        assert p.axes["steering"] == AxisOverride(source="ABS_X")

    def test_bad_range_shape(self, tmp_path):
        path = write(tmp_path, "rngbad",
                     'mode = "C"\n[axes]\nsteering = { range = [1, 2, 3] }\n')
        with pytest.raises(ProfileError, match="range"):
            load_profile(path)

    def test_unknown_proton_key(self, tmp_path):
        path = write(tmp_path, "pro", 'mode = "A"\n[proton]\nwine = "9"\n')
        with pytest.raises(ProfileError, match=r"pro\.toml.*'wine'"):
            load_profile(path)

    def test_non_string_env_value(self, tmp_path):
        path = write(tmp_path, "env",
                     'mode = "A"\n[proton]\nenv = { DXVK_HUD = 1 }\n')
        with pytest.raises(ProfileError, match="DXVK_HUD"):
            load_profile(path)

    def test_bad_steam_input(self, tmp_path):
        path = write(tmp_path, "si",
                     'mode = "A"\n[proton]\nsteam_input = "on"\n')
        with pytest.raises(ProfileError, match="steam_input"):
            load_profile(path)

    def test_invalid_toml(self, tmp_path):
        path = write(tmp_path, "broken", 'mode = "A\n')
        with pytest.raises(ProfileError, match=r"broken\.toml"):
            load_profile(path)

    def test_full_profile_parses(self, tmp_path):
        path = write(tmp_path, "full", '\n'.join([
            'name = "full"',
            'mode = "b"',
            'ffb_gain = 60',
            'notes = "kitchen sink"',
            '[axes]',
            'steering = { source = "ABS_X", deadzone = 0.05 }',
            'throttle = { source = "ABS_Z", invert = true }',
            '[proton]',
            'env = { PROTON_ENABLE_WAYLAND = "1", DXVK_HUD = "fps" }',
            'steam_input = "off"',
        ]) + '\n')
        p = load_profile(path)
        assert p.mode == "B"
        assert p.ffb_gain == 60
        assert p.axes == {
            "steering": AxisOverride(source="ABS_X", deadzone=0.05),
            "throttle": AxisOverride(source="ABS_Z", invert=True),
        }
        assert p.env == {"PROTON_ENABLE_WAYLAND": "1", "DXVK_HUD": "fps"}
        assert p.steam_input == "off"


# ---------------------------------------------------------------------------
# Lookup and listing
# ---------------------------------------------------------------------------
class TestLookup:
    def test_name_looks_up_user_then_seed(self, dirs):
        user, seed = dirs
        write(seed, "game", 'mode = "A"\nnotes = "seed"\n')
        assert load_profile("game").notes == "seed"
        write(user, "game", 'mode = "C"\nnotes = "user"\n')
        p = load_profile("game")
        assert p.notes == "user"
        assert p.mode == "C"

    def test_unknown_name_raises(self, dirs):
        with pytest.raises(ProfileError, match="nosuch"):
            load_profile("nosuch")

    def test_toml_suffix_loads_directly(self, dirs, tmp_path):
        path = write(tmp_path / "elsewhere", "direct", 'mode = "A"\n')
        # Relative-looking name with .toml suffix bypasses the search dirs.
        assert load_profile(path).name == "direct"

    def test_missing_direct_path_raises(self, dirs):
        with pytest.raises(ProfileError, match="gone"):
            load_profile("/nonexistent/gone.toml")


class TestListProfiles:
    def test_sorted_and_user_shadows_seed(self, dirs):
        user, seed = dirs
        write(seed, "zeta", 'mode = "A"\n')
        write(seed, "alpha", 'mode = "A"\nnotes = "seed"\n')
        write(user, "alpha", 'mode = "B"\nnotes = "user"\n')
        profiles = list_profiles()
        assert [p.name for p in profiles] == ["alpha", "zeta"]
        assert profiles[0].notes == "user"
        assert profiles[0].mode == "B"

    def test_missing_user_dir_tolerated(self, dirs):
        _, seed = dirs
        write(seed, "only", 'mode = "A"\n')
        assert [p.name for p in list_profiles()] == ["only"]

    def test_bad_file_skipped_with_warning(self, dirs):
        _, seed = dirs
        write(seed, "good", 'mode = "A"\n')
        write(seed, "corrupt", 'mode = = "A"\n')
        with pytest.warns(UserWarning, match=r"corrupt\.toml"):
            profiles = list_profiles()
        assert [p.name for p in profiles] == ["good"]

    def test_non_toml_files_ignored(self, dirs):
        _, seed = dirs
        write(seed, "real", 'mode = "A"\n')
        (seed / "README.txt").write_text("not a profile")
        assert [p.name for p in list_profiles()] == ["real"]


# ---------------------------------------------------------------------------
# merge_axes
# ---------------------------------------------------------------------------
class TestMergeAxes:
    def test_profile_field_wins_calibration_fills(self):
        profile = Profile(name="p", mode="B", axes={
            "steering": AxisOverride(deadzone=0.1),               # source unset
            "throttle": AxisOverride(source="ABS_RX", invert=True),
        })
        calibration = {
            "steering": AxisOverride(source="ABS_X", deadzone=0.5),
            "throttle": AxisOverride(source="ABS_Z", invert=False),
            "brake": AxisOverride(source="ABS_RZ"),
        }
        merged = merge_axes(profile, calibration)
        # Profile deadzone beats calibration; calibration supplies the source.
        assert merged["steering"] == AxisOverride(source="ABS_X", deadzone=0.1)
        # Profile fields all set: calibration fully shadowed.
        assert merged["throttle"] == AxisOverride(source="ABS_RX", invert=True)
        # Calibration-only axis still appears.
        assert merged["brake"] == AxisOverride(source="ABS_RZ")

    def test_axis_absent_on_both_sides_absent_in_merge(self):
        merged = merge_axes(Profile(name="p"), {})
        assert merged == {}

    def test_false_invert_is_set_not_unset(self):
        profile = Profile(name="p", axes={"brake": AxisOverride(invert=False)})
        calibration = {"brake": AxisOverride(invert=True)}
        assert merge_axes(profile, calibration)["brake"].invert is False


# ---------------------------------------------------------------------------
# daemon_args — argv order is a contract; compare full lists verbatim.
# ---------------------------------------------------------------------------
class TestDaemonArgs:
    def test_mode_a_minimal(self):
        assert daemon_args(Profile(name="p", mode="A"), {}) == ["--mode", "A"]

    def test_mode_a_buttons_and_gain(self):
        p = Profile(name="p", mode="A", buttons=24, ffb_gain=80)
        assert daemon_args(p, {}) == [
            "--mode", "A", "--buttons", "24", "--ffb-gain", "80"]

    def test_mode_a_ignores_axes(self):
        p = Profile(name="p", mode="A", axes={
            "steering": AxisOverride(source="ABS_X", deadzone=0.2, invert=True)})
        assert daemon_args(p, {}) == ["--mode", "A"]

    def test_mode_c_buttons_and_deadzone(self):
        p = Profile(name="p", mode="C", buttons=20, axes={
            "steering": AxisOverride(deadzone=0.05)})
        assert daemon_args(p, {}) == [
            "--mode", "C", "--buttons", "20", "--deadzone", "0.05"]

    def test_mode_c_deadzone_from_calibration(self):
        p = Profile(name="p", mode="C")
        calib = {"steering": AxisOverride(deadzone=0.1)}
        assert daemon_args(p, calib) == ["--mode", "C", "--deadzone", "0.1"]

    def test_mode_c_zero_deadzone_omitted(self):
        p = Profile(name="p", mode="C", axes={
            "steering": AxisOverride(deadzone=0.0)})
        assert daemon_args(p, {}) == ["--mode", "C"]

    def test_mode_c_no_src_flags(self):
        p = Profile(name="p", mode="C", axes={
            "throttle": AxisOverride(source="ABS_Z", invert=True)})
        assert daemon_args(p, {}) == ["--mode", "C"]

    def test_mode_b_full_canonical_order(self):
        p = Profile(name="p", mode="B", buttons=24, ffb_gain=50, axes={
            "steering": AxisOverride(source="ABS_X", deadzone=0.1, invert=True),
            "throttle": AxisOverride(source="ABS_Z"),
            "brake": AxisOverride(source="ABS_RZ", invert=True),
            "clutch": AxisOverride(source="ABS_Y", invert=False),
        })
        # buttons is ignored in mode B; srcs then inverts, steer→clutch order.
        assert daemon_args(p, {}) == [
            "--mode", "B",
            "--ffb-gain", "50",
            "--deadzone", "0.1",
            "--steer-src", "ABS_X",
            "--throttle-src", "ABS_Z",
            "--brake-src", "ABS_RZ",
            "--clutch-src", "ABS_Y",
            "--steer-invert",
            "--brake-invert",
        ]

    def test_mode_b_sources_from_calibration_merge(self):
        p = Profile(name="p", mode="B", axes={
            "throttle": AxisOverride(source="ABS_RX")})  # overrides calibration
        calib = {
            "throttle": AxisOverride(source="ABS_Z"),
            "brake": AxisOverride(source="ABS_RZ", invert=True),
        }
        assert daemon_args(p, calib) == [
            "--mode", "B",
            "--throttle-src", "ABS_RX",
            "--brake-src", "ABS_RZ",
            "--brake-invert",
        ]

    def test_mode_alias_accepted(self):
        assert daemon_args(Profile(name="p", mode="gamepad"), {}) == ["--mode", "B"]

    def test_mode_d_raises(self):
        with pytest.raises(ProfileError, match="mode D"):
            daemon_args(Profile(name="p", mode="D"), {})


# ---------------------------------------------------------------------------
# launch_env
# ---------------------------------------------------------------------------
class TestLaunchEnv:
    def test_overlay_and_no_mutation(self):
        p = Profile(name="p", env={"B": "profile", "C": "new"})
        base = {"A": "1", "B": "base"}
        env = launch_env(p, base)
        assert env == {"A": "1", "B": "profile", "C": "new"}
        assert base == {"A": "1", "B": "base"}  # copy, not in-place

    def test_default_base_is_os_environ(self, monkeypatch):
        monkeypatch.setenv("MOZAPROXY_TEST_SENTINEL", "yes")
        p = Profile(name="p", env={"PROTON_ENABLE_WAYLAND": "1"})
        env = launch_env(p)
        assert env["MOZAPROXY_TEST_SENTINEL"] == "yes"
        assert env["PROTON_ENABLE_WAYLAND"] == "1"


# ---------------------------------------------------------------------------
# TOML emission
# ---------------------------------------------------------------------------
class TestEmitProfileToml:
    def test_minimal_emits_only_name_and_mode(self):
        text = emit_profile_toml(Profile(name="mini", mode="A"))
        assert tomllib.loads(text) == {"name": "mini", "mode": "A"}

    def test_full_round_trip_through_load_profile(self, tmp_path):
        original = Profile(
            name="rt", mode="B", buttons=24, ffb_gain=70,
            axes={
                "steering": AxisOverride(source="ABS_X", deadzone=0.05),
                "brake": AxisOverride(source="ABS_RZ", invert=True),
            },
            env={"PROTON_ENABLE_WAYLAND": "1"},
            steam_input="off",
            notes="round trip",
        )
        path = write(tmp_path, "rt", emit_profile_toml(original))
        loaded = load_profile(path)
        assert loaded.mode == original.mode
        assert loaded.buttons == original.buttons
        assert loaded.ffb_gain == original.ffb_gain
        assert loaded.axes == original.axes
        assert loaded.env == original.env
        assert loaded.steam_input == original.steam_input
        assert loaded.notes == original.notes

    def test_string_escaping(self):
        nasty = 'quotes " backslash \\ newline \n tab \t'
        text = emit_profile_toml(Profile(name="esc", mode="A", notes=nasty))
        assert tomllib.loads(text)["notes"] == nasty

    def test_alias_mode_emitted_canonical(self):
        text = emit_profile_toml(Profile(name="p", mode="norm"))
        assert tomllib.loads(text)["mode"] == "C"

    def test_axes_with_all_fields_unset_omitted(self):
        text = emit_profile_toml(
            Profile(name="p", mode="B", axes={"clutch": AxisOverride()}))
        assert "axes" not in tomllib.loads(text)


class TestEmitCalibrationToml:
    def test_round_trip_via_tomllib(self):
        axes = {
            "steering": {"source": "ABS_X"},
            "throttle": {"source": "ABS_Z", "invert": False},
            "brake": {"source": "ABS_RZ", "invert": True},
        }
        assert tomllib.loads(emit_calibration_toml(axes)) == {"axes": axes}

    def test_empty_axes(self):
        assert tomllib.loads(emit_calibration_toml({})) == {"axes": {}}


# ---------------------------------------------------------------------------
# Calibration persistence
# ---------------------------------------------------------------------------
class TestCalibrationIO:
    def test_load_absent_returns_empty(self, dirs):
        assert load_calibration() == {}

    def test_save_then_load_round_trip(self, dirs):
        axes = {
            "steering": {"source": "ABS_X"},
            "throttle": {"source": "ABS_Z", "invert": False},
            "brake": {"source": "ABS_RZ", "invert": True},
        }
        path = save_calibration(axes)  # parent dirs did not exist yet
        assert path == profiledb.CALIBRATION_PATH
        assert os.path.exists(path)
        loaded = load_calibration()
        assert loaded == {
            "steering": AxisOverride(source="ABS_X"),
            "throttle": AxisOverride(source="ABS_Z", invert=False),
            "brake": AxisOverride(source="ABS_RZ", invert=True),
        }

    def test_load_rejects_bad_source(self, dirs, tmp_path):
        calib = tmp_path / "config" / "calibration.toml"
        calib.parent.mkdir(parents=True, exist_ok=True)
        calib.write_text('[axes]\nsteering = { source = "ABS_NOPE" }\n')
        with pytest.raises(ProfileError, match="source"):
            load_calibration()


# ---------------------------------------------------------------------------
# needs_restart truth table
# ---------------------------------------------------------------------------
class TestNeedsRestart:
    ARGV = ["--mode", "A", "--buttons", "24"]
    STATE = {"pid": 42, "mode": "A", "argv": ARGV, "profile": "fh5"}

    def test_no_live_daemon(self):
        assert needs_restart(self.STATE, self.ARGV, []) is True

    def test_no_state(self):
        assert needs_restart(None, self.ARGV, [42]) is True

    def test_state_pid_not_live(self):
        assert needs_restart(self.STATE, self.ARGV, [43]) is True

    def test_state_missing_pid(self):
        assert needs_restart({"argv": self.ARGV}, self.ARGV, [42]) is True

    def test_argv_mismatch(self):
        assert needs_restart(self.STATE, ["--mode", "B"], [42]) is True

    def test_state_missing_argv(self):
        assert needs_restart({"pid": 42}, self.ARGV, [42]) is True

    def test_up_to_date(self):
        assert needs_restart(self.STATE, self.ARGV, [42]) is False

    def test_up_to_date_among_several_pids(self):
        assert needs_restart(self.STATE, self.ARGV, [7, 42, 99]) is False


# ---------------------------------------------------------------------------
# Shipped seed profiles (reads the real profiles/ directory)
# ---------------------------------------------------------------------------
SEED_NAMES = {"ac", "acc", "arcade", "fh5", "fs22", "fs25", "normalized"}


class TestSeedProfiles:
    @pytest.fixture(autouse=True)
    def no_user_dir(self, tmp_path, monkeypatch):
        # Keep the developer's real ~/.config profiles from shadowing seeds.
        monkeypatch.setattr(profiledb, "USER_DIR", str(tmp_path / "no-user"))

    def test_expected_seed_set(self):
        stems = {os.path.splitext(os.path.basename(f))[0]
                 for f in glob.glob(os.path.join(profiledb.SEED_DIR, "*.toml"))}
        assert stems == SEED_NAMES

    @pytest.mark.parametrize("name", sorted(SEED_NAMES))
    def test_seed_loads_and_produces_daemon_args(self, name):
        p = load_profile(name)
        assert p.name == name
        assert p.mode in ("A", "B", "C")  # no seed is mode D
        args = daemon_args(p, {})
        assert args[:2] == ["--mode", p.mode]

    def test_fh5(self):
        p = load_profile("fh5")
        assert p.mode == "A"
        assert p.buttons == 24
        assert p.env == {"PROTON_ENABLE_WAYLAND": "1"}
        assert p.steam_input == "off"
        assert daemon_args(p, {}) == ["--mode", "A", "--buttons", "24"]

    def test_arcade(self):
        p = load_profile("arcade")
        assert p.mode == "B"
        assert p.steam_input == "off"

    def test_normalized(self):
        assert load_profile("normalized").mode == "C"

    @pytest.mark.parametrize("name", ["ac", "acc", "fs22", "fs25"])
    def test_wheel_seeds(self, name):
        assert load_profile(name).mode == "A"

    def test_seeds_appear_in_list_profiles(self):
        names = {p.name for p in list_profiles()}
        assert SEED_NAMES <= names
