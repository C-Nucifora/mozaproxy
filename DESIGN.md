# Mozaproxy visual system

Mozaproxy is a working wheel utility. Its visual direction borrows the restrained
blue, clear labels and aligned measurements of endurance racing team graphics.
The shared signature is an ink-blue navigation rail beside a quiet working area.
Confirmed readings, draft values and explicit actions remain separate.

## Palette and type

The web uses an ink-blue rail `#142b40`, pale blue-gray ground `#eef2f6`, white
working surfaces and dark ink `#182a3b`. Secondary text is `#526578`. Blue
`#195b83` identifies primary actions; amber identifies pending changes and
warnings, green confirmed status, and red errors and Stop controls. State always
has a text label. Adwaita remains locally bundled; measurements use tabular figures.

The native window uses the same rail and action accents. Working surfaces, text,
inputs, disabled states and selection inherit the desktop palette and font.
Window-local styling in `desktop_style.py` leaves the application's native Qt
widgets, keyboard behavior, dialogs and desktop plugin discovery intact. It does
not change the user's desktop theme. Page titles, device names and section
headings carry the hierarchy; body text follows native font metrics.

## Layout and navigation

Six persistent destinations remain: Overview, Wheelbase, Pedals & controls,
Profiles, Games and Diagnostics. Web navigation becomes a horizontal scrollable
rail on small screens. Form rows stack on phones. Desktop retains list navigation,
native tabs and Alt+1 through Alt+6. The overview scrolls at smaller sizes rather
than compressing the input instruments and protection guidance. Relay controls
precede the instruments. Persistent settings actions sit below the current page.

Settings place descriptions beside editors and confirmed readbacks below them.
Native settings rows have 14-pixel vertical margins. Web groups use white surfaces
with one-pixel boundaries and 24-pixel insets. Calibration and telemetry have
separate sections with Start and Stop together. Game profile linking and attended
test records are distinct form groups. Raw diagnostic evidence remains selectable.

## Interaction and safety

Loading, disconnected, unread, invalid, pending and disabled states remain explicit.
Focus is visible; labels retain native buddies or HTML associations. Web motion
is limited to control feedback and measured input, with reduced-motion support.

Selecting a profile prepares a draft. Apply remains explicit and subject to the
existing controller's validation and ownership gates. Detection, automatic Apply
and telemetry output remain off by default. Preview sends no device commands.
Stop and recovery errors remain available under the existing controller rules.
No visual change establishes physical FFB, calibration or RGB compatibility.

## Validation

Visual review uses static web files with mocked API routes and native Qt windows
with injected fake state and offscreen rendering. It must never initialize a live
backend or connect physical hardware. Capture desktop and mobile web and both
1180×820 and 900×680 Qt windows. Check the overview, settings, profiles, game
setup, diagnostics, RGB and calibration/telemetry. Run existing regression suites;
physical validation remains an attended task outside this visual overhaul.
