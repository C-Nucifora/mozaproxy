# Fixed protection launcher

The user accepted a single Steam wrapper command on 2026-11-14. Changing saved
settings must never require changing that command. Existing saved-settings reads
already provide this behavior; previous instructions supplied fixed CLI overrides.

## Approach

Keep direct wheel access and the existing `mozaproxy-protect` wrapper. A permanent
virtual wheel would require separate game validation and possible rebinding, so
the user chose the wrapper. No automatic Steam-file editor is needed for this
one-time launch entry.

Show the installed launcher in the app. Use the same command for LMU and ACC,
with LMU's existing EAC and Wayland defaults selected by consistent Steam IDs.
Preserve explicit environment values. Retain diagnostic overrides, but warn when
they bypass app preferences. Document that changes take effect on the next launch.

Wheel profile Apply remains optional and off by default. No live FFB changes,
relay changes, Steam-file writes while Steam runs, or hardware validation belong
to this change.

## Approved command naming follow-up

The user requested the installed command from PATH and a single `mozaproxy` name.
Without arguments it opens the desktop app; with a command it runs the saved-settings
launcher. No compatibility aliases are retained. Retire old generated local
launchers with backups, update the desktop entry, and leave game launch lines for
the user to update. Preserve unrelated custom executables.
