---
name: Mozaproxy
description: Native Qt 6 wheel setup and input monitoring for Linux
---

# Mozaproxy design system

## Overview

**Creative North Star: "A native wheel setup utility"**

Mozaproxy is a native Linux desktop utility for observing wheel input, preparing settings and controlling the game relay. Qt 6 through PySide6 supplies the system palette, fonts, controls, focus treatment and dialogs. The interface follows the desktop theme.

The implemented sources are `mozaproxy/desktop.py`, `mozaproxy/qt_widgets.py` and `mozaproxy/qt_controller.py`. This document describes that desktop app. Theme-dependent colors and fonts have no fixed token values to extract into frontmatter. Native component details live in `.impeccable/design.json` without HTML or CSS previews.

**Key Characteristics:**

- Six persistent sections with native list navigation and tabbed settings.
- Confirmed device readings stay separate from editable drafts.
- A palette-aware steering drawing and native pedal progress bars show measured input.

## Colors

The system Qt palette owns backgrounds, text, selection, borders and disabled states. The custom steering drawing reads `QPalette.Text` for available input, `QPalette.Mid` for unavailable input, `QPalette.Window` for its hub and `QPalette.Highlight` for the center marker. Native progress bars use the active widget style.

Written states carry meaning independently of color. Missing axes say "Not available"; unread settings say "Not read". Connection, relay, operation and validation messages remain visible as text. There is no fixed brand accent or application-specific light or dark palette.

## Typography

Widgets inherit the Qt application font supplied by the desktop. The device name is bold and two points larger than its inherited font; page headings are bold and five points larger. Labels, descriptions, buttons and readbacks use native font metrics. `QPlainTextEdit` provides selectable text for profile previews, launch options, pressed buttons and relay output.

Setting labels wrap and identify their editor through a buddy relationship. Editors and input displays have accessible names and descriptions. Avoid fixed web font families, rem scales and custom letter spacing.

## Layout

A `QMainWindow` starts at 1180 by 820 logical pixels with a minimum of 820 by 620. Its central horizontal layout has 12-pixel outer margins. A 175-pixel `QListWidget` stays on the left, with five-pixel item spacing. The right column contains the device header, connection state, a growing `QStackedWidget`, operation feedback, hardware status and persistent draft actions. File and View menus and a status bar complete the window. Alt+1 through Alt+6 select sections.

The six sections are Overview, Wheelbase, Pedals & controls, Profiles, Games and Diagnostics. Wheelbase and Pedals & controls use `QTabWidget`; settings tabs contain resizable `QScrollArea` widgets. Setting rows keep descriptions on the left and editors on the right. Their editors are 160 to 245 pixels wide, with a separate device readback below. Rows use eight-pixel vertical margins, a 16-pixel column gap and a three-pixel row gap.

Overview divides the input bench between steering and pedals with stretch factors of one and two and a 24-pixel gap. Profiles uses a resizable `QSplitter`, initially allocating 280 and 520 pixels to its list and editor. Games and Diagnostics use native trees with resizable columns. Qt layouts and scroll areas handle smaller desktop windows; there are no mobile breakpoints or alternate navigation modes.

Native review captures are in `.impeccable/review/qt/`, with `overview`, `wheelbase`, `controls`, `profiles`, `games` and `diagnostics` captured at widths of 1180 and 900 pixels. These record the runtime state with settings disconnected; they do not establish successful hardware writes or game compatibility.

## Elevation & Depth

Native widget frames, tabs, group boxes, selection and spacing distinguish regions. Qt supplies the depth and focus treatment appropriate to the current desktop style. The app adds no custom shadows, floating notifications or animated overlays. Operation feedback and draft actions occupy normal layout space below the current page.

## Shapes

Buttons, fields, tabs, scrollbars and progress bars retain the shapes of the native Qt style. The custom steering wheel is an antialiased `QPainter` drawing with a circular rim, three spokes, a hub and a highlighted center marker. It has a preferred size of 180 by 180 pixels, bounded between 140 and 240 pixels. Its dimensions scale to its widget rectangle. The launcher uses the local wheel icon; the input instrument is painted directly in Qt.

## Components

- **Navigation.** `QListWidget` selects one of six persistent pages. Native selection, keyboard navigation and View menu shortcuts remain available.
- **Input bench.** `QPainter` rotates the steering drawing from measured input. Without a confirmed rotation range, the text reports percent from center; with a confirmed range, it reports degrees. Three `QProgressBar` widgets display throttle, brake and clutch to one decimal place. Missing readings stay explicitly unavailable. Input updates repaint directly, without interpolated motion.
- **Setting rows.** `QComboBox` handles boolean and enumerated settings; a `QDoubleSpinBox` subclass handles numeric values, units and schema limits. The editable draft and the "Device:" readback are distinct. Invalid text survives focus changes, page switches and state refreshes. A local error message explains the valid range; Apply and profile saving stay disabled until the edit is repaired or replaced.
- **Draft actions.** The persistent bottom row provides Connect settings or Read settings, Disconnect, draft count, Discard and Apply to device. Apply requires valid pending values, a connection, no ownership conflict and an idle controller. A verified write replaces its draft with the actual readback, including device precision adjustments. Failed or unconfirmed writes retain their draft and error. Discard explicitly restores readings.
- **Profiles.** A native list sits beside name and game fields and a read-only value preview. New saves combine known device readings with draft changes. Loaded profiles retain saved values as their base and preserve explicit edits, including edits matching current device readings. Loading prepares a draft; saving stores a profile. Neither writes settings or starts the relay. Deletion uses a native confirmation dialog.
- **Game relay.** A `QGroupBox` contains the Full input mapping and Compact R9 compatibility selector and an explicit Start relay or Stop relay button. Both modes create a virtual input device. Direct Assetto Corsa and ACC use keeps the relay stopped.
- **Games and diagnostics.** Native trees show observed compatibility and device checks. Selectable launch options have a Copy button. Diagnostics provides read-only relay output and a native save dialog for export. Compatibility labels report evidence, including pending tests.

The window talks directly to one injected `AppState` through a single-worker controller. A 200 ms timer requests snapshots only while idle. Operations and snapshots run sequentially off the GUI thread, and queued Qt signals deliver results on the GUI thread. Refreshes preserve focused editors and invalid text. The desktop does not need an HTTP server or browser.

Settings ownership is separate from passive input observation and relay state. Connecting settings is explicit, conflicts are shown in the hardware status, and unsafe actions are disabled while busy. A runtime lock prevents duplicate desktop instances. Closing waits for backend cleanup and stops the relay owned by this app. These boundaries are part of the interaction design.

## Do's and Don'ts

- Do use the active Qt palette, application font and native widget style.
- Do show confirmed readings, saved profile values and drafts separately.
- Do preserve invalid edits and display a repair message.
- Do keep Apply, settings connection and relay start as explicit actions.
- Do keep launch commands selectable and copyable.
- Do report missing readings and ownership conflicts in text.
- Don't hardcode a web palette, bundle a UI font or style native controls with web CSS.
- Don't invent telemetry or mark a write confirmed before verified readback.
- Don't connect settings, write hardware or start the relay when a page or profile is selected.
- Don't replace native controls with HTML previews or decorative dashboard cards.
