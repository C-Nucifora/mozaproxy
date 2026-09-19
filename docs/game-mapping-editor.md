# Per-game R25 mappings

The Qt Games page has an R25 mapping tab. Select a fixed wheel layout, assign
R25 sources to its axes and button slots, save, and explicitly start the saved
mapping. Direct physical access is the default for every game without a saved
configuration. Existing manual FH5, JDM, AC and ACC routes are unchanged.

Only the G920 target layout is currently implemented: USB 046d:c262, four axes,
eleven buttons and one POV. Its identity, output axes, button count and ranges
are fixed. Unassigned slots stay advertised to prevent button renumbering.
Pedal and steering sources and reversal are editable. Button Learn observes a
fresh single press; it sends no input or force. Hat forwarding is opt-in.

Choosing the G920 layout for Heat now fills the mapping that the user reported
working after installing Heat's missing Logitech wheel SDK runtime. Steering
keeps its direction, all three pedals are reversed, and the measured paddles
and menu controls are assigned. Unidentified buttons stay unassigned. Existing
saved mappings take precedence. This preset covers the tested R25 setup; a
different attached rim may need different source buttons. SDK installation is
still a separate setup step; choosing this preset does not install it.

Live editing is optional. Both the initial preset and later edits compile into
the same input relay, with one virtual wheel and one FFB relay. The editor does
not add another input translation pass. Normal use reuses the saved mapping.

Save writes `~/.config/mozaproxy/game-mappings.json` atomically, separately from
hardware settings. It never starts or changes a relay. A locally owned relay
started from a saved mapping supports Apply saved mapping live. The app writes
a private control document; the relay validates it, releases old button/hat
states, synchronizes current inputs through the new mapping, and acknowledges
success or rejection. The virtual device and FFB effect relay stay connected.
Changing games or target identity requires a new relay.

System mode can save drafts but does not yet run custom layouts. Its fixed
service identity remains intact. Physical-device isolation remains an explicit
per-game launch setup; this feature does not rewrite Steam configuration.

## Heat deadzone investigation

The current relay advertises a full-range linear steering axis with flat=0.
Heat's binary PROFILEOPTIONS contains WheelDeadzone=0.000000,
DeadzoneCenter=0.220000 and WheelMaxRotation=900.000000. The user reports a large
centre deadzone. Which game input path consumes the separate 22% setting has
not been established. Do not add an anti-deadzone curve to hide this uncertainty.

## Direction contract

THESIS: Edit R25 assignments against the fixed layout a game expects.
OWN-WORLD: Preserve native Qt widgets, palette, typography and six-page navigation.
STORY: Select a game, choose a layout, assign controls, save, explicitly start or
apply live. Saved drafts and acknowledged running mappings remain distinct.
FIRST VIEWPORT: Game list above Setup & evidence and R25 mapping tabs. Mapping
rows show game-side controls, R25 sources, reversal or Learn. Actions stay below
the scrollable rows. Errors and live acknowledgements remain visible as text.
FORM: Extension of the existing Games page; no concept seed or identity change.
FINISH: Native screenshots at 1180x820 and 900x700, regression tests and an
independent finish review. No HTML/CSS detector is applicable to Qt widgets.

Draft edits survive switching between games and passive device refreshes.
Discard edits restores that game's saved mapping. Saving Direct while a custom
relay is running does not stop it; the page directs the user to Stop relay in
Overview. Unknown/unimplemented layouts are not selectable.

Validation: 203 tests passed with virtual kernel tests enabled. The new kernel
test keeps an existing client connected through a held-button reassignment and
steering reversal. Independent native interface review scored all three status
and capture findings resolved; documentation review confirmed the incumbent Qt
system is preserved. These checks do not validate Heat's actual driving or FFB.
