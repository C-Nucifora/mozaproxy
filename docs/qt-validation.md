# Native Qt6 validation

Validated on 2026-09-18 with PySide6 6.11.2 on Arch Linux/Hyprland.

The installed `mozaproxy-app` launcher opens native Qt Widgets on Wayland.
Hyprland reported a mapped Mozaproxy window. The desktop execution path calls
AppState directly without an HTTP server or browser engine.

The full Python suite ran 104 tests: 103 passed and the optional kernel virtual
device test was skipped. This includes 9 desktop regression tests and 8 Qt
controller tests. Desktop regressions cover invalid edits, profile overrides,
per-field errors, unchanged settings and edits made during an in-flight Apply.

Offscreen captures cover all six pages at 1180×820 and 900×680 in
`.impeccable/review/qt/`. A read-only connection retrieved 59 settings from the
R25 Ultra. No hardware settings were applied and no motor tests were run.

Hypruse is installed and callable through MCP. Its diagnostics passed. Live
window screenshots, keyboard navigation to Wheelbase and mouse navigation to
Profiles were verified. The running Qt app exposes no AT-SPI tree, so this
smoke check used screenshots and coordinates. Broader GUI testing remains
pending. No settings were applied and the relay remained stopped. Automated
Qt tests do not establish game compatibility or physical FFB quality.

Configuration writes still require attended hardware validation. FH5 freezes
and JDM freezes/incorrect FFB remain unresolved. FS22, FS25, AC and ACC driving
and regression checks remain pending. Full Boxflat parity is not implemented.

## Live completion checks

Hypruse MCP verified the native app with the physical R25 present. Connect
read 59 settings. A 1080-degree rotation draft was saved to a temporary profile,
loaded, and deleted through the GUI. The confirmed hardware reading remained
900 degrees; Apply was not invoked. Profile storage returned to its original
empty state. Normal close and relaunch completed after dismissing the profile
dialog. Qt accessibility is enabled by default; the MCP walker has a tree-size
limit, so some controls still require screenshot-based interaction.

The final pass fixed cleanup after exceptions and kept the overview instruments
grouped on tall windows. All 104 normal tests passed apart from the optional
virtual-device skip, then that test passed separately with MOZAPROXY_TEST_UINPUT=1.
