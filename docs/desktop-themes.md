# Desktop theme integration

Mozaproxy uses the desktop's native Qt palette, font and widget style. On a
desktop configured with `QT_QPA_PLATFORMTHEME=qt6ct`, it follows the selected
qt6ct colour scheme and icon theme. Changes made through qt6ct update an open
app through the native plugin, without restarting the app or losing drafts.

PySide6's bundled Qt normally searches its own plugin directory. It can miss
the distribution's platform theme plugin even when that plugin is installed
and the desktop has selected it. The resulting light fallback was the cause
on the tested Hyprland setup.

The desktop entry point now appends compatible system plugin directories before
constructing QApplication. It keeps the bundled Wayland/XCB plugins first and
preserves existing plugin paths and environment preferences. It does not force
a particular colour scheme, set a global `QT_PLUGIN_PATH`, or rewrite qt6ct,
GTK or KDE settings.

Discovery covers the usual `/usr/lib/qt6/plugins`, `/usr/lib64/qt6/plugins`,
`/usr/local/lib/qt6/plugins` and distribution multiarch locations. Platform
themes use private Qt APIs, so automatic discovery requires a theme plugin
built for the same Qt major/minor and build mode as PySide6. If none is found,
normal Qt defaults remain available. Custom installations can use Qt's own
per-application plugin configuration. See [Qt plugin deployment](https://doc.qt.io/qt-6/deployment-plugins.html).

## Validation

On the tested desktop, bundled-only startup used a light `#efefef` window,
Sans Serif font and no icon theme. With the system integration loaded, the app
uses the configured qt6ct `darker` scheme, `#222020` windows, Cantarell and
Tela-circle-purple icons. The actual Wayland process loads qt6ct and its style
from the system while retaining the bundled Wayland platform plugin.

The integration regression runs the real desktop entry point with a fake
hardware backend and a temporary qt6ct configuration. It verifies the initial
palette, changes to a second palette while the same window stays open, and
checks that an unsaved wheel-settings draft survives. It never edits the user's
theme or requires a connected wheel. The test skips when a matching system
qt6ct plugin is unavailable.
