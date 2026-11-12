# Game profiles, detection and test records

Games → Profiles & test results links one saved profile to a game. Detection
selects it for manual Apply. Detection, global automatic Apply, and per-game
automatic Apply all start off. Automatic writes require both Apply permissions.

The desktop can detect known Steam games while open. An optional user service
keeps detection running after the desktop closes:

```sh
./install.sh --game-service
systemctl --user enable --now mozaproxy-games.service
```

The installer creates the unit but does not enable it. Close the desktop for
initial ownership handoff; the service waits if another detector owns the
settings directory. Enable detection and link profiles in the app. For a custom
`--data-dir`, configure the service with the same directory. To disable the
background service:

```sh
systemctl --user disable --now mozaproxy-games.service
```

The watcher uses exact Steam IDs and known executable basenames. Unknown games,
ambiguous processes and unsupported launch methods do not trigger selection.
A game already running when detection starts is ignored. Changing automation
options or links during a game never applies them retroactively. The watcher
must observe a game exit before treating the same game as a new launch.

When the service owns detection, it publishes the selected profile without
rewriting the profiles document. The desktop offers it as a draft if there are
no pending edits. With automatic Apply explicitly enabled for that game, the
service connects settings on a new launch, rereads eligibility, applies the
linked profile and checks readback. It closes its serial connection afterward. A settings-read timeout skips automatic
Apply even if some requested settings replied; unsupported optional RGB queries
can make this more likely. Use manual Apply after checking the readings.
It skips automatic writes while a desktop window is open, if the serial device
is owned elsewhere, or if the game/options/profile change while reading.
The desktop detector instead requires its settings connection already open.
Neither path defers a missed write until later in a session or retries it each
poll. No profile is automatically restored on game exit.

Detection and profile selection need no Steam launch options. Device isolation,
HID compatibility helpers and menu force protection still require their existing
launch hooks before Wine opens the wheel. The watcher does not inject libraries,
start relays or rewrite Steam/prefix/game files. Keep working FH5/JDM routes.

## Compatibility evidence

Each game has a prerequisite checklist and a local history of attended tests.
Record launch, controls, physical force and pause/resume separately, along with
input route, Proton/native version and wheel/firmware. The last 200 records are
retained. User records do not overwrite shipped historical observations.
Successful preflight or packet reception is not a physical FFB pass.

Game setup is stored in `game-setup.json` alongside profiles. Malformed data is
reported and preserved. Diagnostics export includes setup/evidence. The service
writes a short-lived status file and its last automatic-Apply report locally;
these contain no captured process environments. The last automatic report is
`game-watcher-apply.json` in the same settings directory.

## Validation still needed

Software checks use fake devices and loopback packets. LMU/ACC driving and menu
protection, broader game compatibility, real settings writes, and reboot/startup
behaviour still require attended checks. No services or helpers were installed
or activated during this development while the user was playing.
