# Steam library wheel test backlog

Audited 2026-09-18. This is a test inventory, not a supported-games list.

## Scope and evidence

Read all three configured Steam libraries, the active account's local app
tickets and library cache, and Steam's app metadata. The scan matched 1,014
game/demo records; 623 game records have a local app ticket. These counts
include cached history, free games and subscription entries, not just purchases.
Seventy installed app manifests include games, tools and runtimes.

The main queue below has **26 additional targets** with local account tickets
and primary-source evidence of wheel support. Local tickets are stronger
evidence than a cached store entry but do not guarantee a current entitlement.
Confirm Steam offers Install/Play before downloading an uninstalled title.
The public games page required sign-in, so current server-side ownership was
not independently verified. Cached-only titles are kept in a separate queue.
Other local Steam accounts were not merged into this account's queue.

The entire matched game/demo name list was reviewed, with racing genres and
driving/farming/simulation names checked for omissions. DLC, dedicated servers,
tools and unrelated simulators do not need separate wheel tests. Wheel support
on Windows does not establish R25 support, Linux launchability or physical FFB.

Sanitized local inventory evidence is saved at
`~/.local/state/mozaproxy/game-tests/library-audit-20260918/library-metadata.json`.
No account ticket values, login credentials or licence secrets were exported.

## Existing six-game scope

| Game | App ID | Current evidence |
| --- | --- | --- |
| Forza Horizon 5 | 1551360 | Attended manual-route pass today; integrated route pending |
| JDM: Japanese Drift Master | 1153410 | Attended direct-HID/helper pass today; integrated route pending |
| Farming Simulator 22 | 1248130 | Latest direct launch reports FFB enabled; physical rebinding/driving pending |
| Farming Simulator 25 | 2300320 | Driving and FFB pending |
| Assetto Corsa | 244210 | On-track regression pending |
| Assetto Corsa Competizione | 805550 | On-track regression pending |

See [compatibility tracking](compatibility.md) for configurations and evidence.

## Additional primary queue

Built-in rollout support remains unvalidated for every row. BeamNG has a manual
input pass on 2026-09-19; physical FFB confirmation and queue-warning investigation
remain open. ETS2 testing is underway with the user's existing Proton Experimental
configuration. P1 is the proposed next group
after the existing six; P2 expands coverage; P3 covers older or limited-input
implementations. Gate means resolve launchability before wheel testing.
The proposed checks are our test plan, not claims about completed tests.

| Priority | Game | App ID | Installed | Support evidence and proposed check |
| --- | --- | --- | --- | --- |
| P1 | BeamNG.drive | 284160 | Yes | [Developer hardware guide][beam]. 2026-09-19 manual wheel-input pass; FFB quality, kernel queue warnings, reset and reconnect remain open. |
| P1 | Euro Truck Simulator 2 | 227300 | Yes | [SCS FFB release][scs]. Test native Linux first; test Proton separately if needed. Include truck range and gearbox. |
| P1 | American Truck Simulator | 270880 | No | [SCS FFB release][scs]. Separate result from ETS2 despite shared engine; native Linux first. |
| P1 | DiRT Rally 2.0 | 690790 | No | [Manufacturer PC list][logi]. Check steering load, gravel effects, handbrake and sequential shifts. |
| P1 | Le Mans Ultimate | 2399420 | No | [Developer wheel guide][lmu]. Check calibration, car steering range and FFB reset. Launch preflight first; old cached Valve result is unsupported. |
| P1 | RaceRoom Racing Experience | 211500 | No | [Manufacturer PC list][logi]. Test a free car/track, calibration, force direction and session restart. |
| P2 | DIRT 5 | 1038250 | No | [Official wheel-support patch notes][dirt5]. Separate compatibility test from DiRT Rally 2.0. |
| P2 | MudRunner | 675010 | No | [Manufacturer PC list][logi]. Test steering resistance, separate pedals and gearbox. This is the original PC game, not MudRunner VR. |
| P2 | SnowRunner | 1465360 | No | [Manufacturer PC list][logi]. Check device presets, terrain forces and gearbox/menu transitions. |
| P2 | The Crew 2 | 646910 | No | [Manufacturer PC list][logi]. Check Ubisoft launch, binding persistence, car FFB and mixed vehicle controls. |
| Gate | F1 24 | 2488620 | No | [Manufacturer PC list][logi]. Local Valve metadata reports UnsupportedAntiCheat_Other, tested 2024-06-01. Recheck launch compatibility before downloading/testing; do not diagnose a launch block as broken wheel FFB. |
| P2 | Need for Speed (2015; PC release 2016) | 1262540 | No | [Manufacturer PC list][logi]. Test EA launcher, recognition and pedals before force quality. |
| P2 | Need for Speed Payback | 1262580 | No | [Manufacturer PC list][logi]. Treat its limited device support as a separate compatibility case. |
| P2 | Need for Speed Heat | 1222680 | Yes | [EA wheel-support announcement][heat]. Check supported-device matching, steering range and forces. |
| P2 | Need for Speed Unbound | 1846380 | No | [EA supported wheel list][unbound]. Named models are limited; no assumption that generic HID or R25 works. |
| P3 | Need for Speed Most Wanted (2012) | 1262560 | No | [EA staff confirmation][mw]. Wheel input target; EA explicitly says no FFB for the cited supported wheel. Missing force is not automatically a proxy defect. |
| P3 | Farming Simulator 2011 | 90200 | Yes | [Publisher store description][fs11] explicitly lists wheel support. Check legacy axes/buttons; establish available FFB separately. |
| P2 | Farming Simulator 15 | 313160 | No | [Manufacturer PC list][logi]. Check older GIANTS bindings, range and separate pedals; assess actual force capability. |
| P2 | Farming Simulator 19 | 787860 | No | [Manufacturer PC list][logi]. Separate input/FFB result from FS22/25. |
| P2 | Lawn Mowing Simulator | 1480560 | No | [Official pinned support thread][lawn]. Model-specific support; check analog pedals, operating range and whether forces are game-driven. |
| P3 | Euro Truck Simulator | 232010 | No | [Publisher system requirements][ets1] recommend a steering wheel. Legacy configuration and force-capability check. |
| P3 | Bus Driver | 302080 | No | [Publisher system requirements][busdriver] list a DirectX wheel. Check axes and pedals; FFB capability not established by that listing. |
| P2 | Bus Bound Demo | 4010830 | No | [Developer demo patch notes][busdemo] add wheel support and FFB. Test the available demo separately from the full game. |
| P3 | Absolute Drift | 320140 | No | [Developer confirms G27 wheel, pedals and paddles][absolute]. Input compatibility target; no verified FFB expectation. |
| P3 | Farmer's Dynasty - Final Harvest Edition | 678900 | No | [Publisher update][dynasty] adds steering-wheel/analog-device support. Check input mapping and combined/separate pedal behavior; FFB remains unestablished. |
| P3 | Star Trucker | 2380050 | No | [Developer follow-up][startrucker] confirms players using HOTAS and wheels after peripheral support shipped. Check six-axis vehicle controls and mixed devices; do not assume road-car FFB. |

## Cached titles requiring an access check

These ten additional games have ordinary wheel support, but no matching local
app ticket or installation in this audit. Some have historical playtime, which
does not prove access today. They may reflect previous subscriptions, sharing
or historical cache entries. Do not buy them or claim ownership from this list.

| Game | App ID | Evidence / next step |
| --- | --- | --- |
| Farming Simulator 17 | 447020 | [Manufacturer PC list][logi]; historical playtime present |
| Project CARS | 234630 | [Manufacturer PC list][logi]; historical playtime present |
| GRID (2019) | 703860 | [Manufacturer PC list][logi] |
| GRID Legends | 1307710 | [Manufacturer PC list][logi]; historical playtime present |
| F1 2021 | 1134570 | [Manufacturer PC list][logi]; historical playtime present |
| F1 22 | 1692250 | [Manufacturer PC list][logi] |
| F1 23 | 2108330 | [Manufacturer PC list][logi] |
| EA SPORTS WRC | 1849250 | [Manufacturer PC list][logi]; launch preflight required, old cached Valve result says SteamOS unsupported |
| My Summer Car | 516750 | [Manufacturer PC list][logi] |
| Bus Bound | 2095420 | [Publisher wheel announcement][busfull]; only the demo has an account ticket in this audit |

## Secondary investigation queue

Keep these visible so the audit is comprehensive, but do not promote them to
documented wheel/FFB support without checking the actual implementation.

| Game | App ID | Local evidence | Why separate |
| --- | --- | --- | --- |
| Trackmania | 2225070 | Account ticket | Check analog wheel/pedal binding; primary-source device/FFB contract not established in this audit. |
| TrackMania Nations Forever | 11020 | Account ticket | Legacy analog-controller check; do not assume force feedback. |
| TrackMania United Forever | 7200 | Cache only | Confirm access, then legacy wheel-input check. |
| STAR WARS Episode I Racer | 808910 | Account ticket | Inspect legacy joystick/force implementation before deciding wheel-test expectations. |
| Logistics Simulator | 1617420 | Account ticket | Wheel support unverified. This is NOT Truck and Logistics Simulator, app 873840; that other game's wheel documentation is not applicable. |
| F1 Race Stars | 203680 | Cache/history only | Do not infer wheel support from the F1 name; inspect separately. |

## Not ordinary wheel/FFB targets on present evidence

Need for Speed Hot Pursuit Remastered has an [EA staff statement that wheel
support is absent][hpr]. Do not confuse its capabilities with the original game.
For Burnout Paradise Remastered, Need for Speed Rivals, Asphalt Legends,
Warhammer 40,000: Speed Freeks and RV There Yet?, this audit did not establish
a documented native wheel/FFB path. They stay outside the main queue until
there is positive evidence. A controller mapping alone does not establish FFB.

GTA titles and other action games with drivable vehicles belong in a separate
mod/integration investigation if requested. Ordinary gamepad driving, flight
joystick support and a racing Steam tag do not by themselves meet this scope.
Wreckfest, Automobilista 2, rFactor 2, iRacing, Forza Horizon 4 and Forza
Motorsport were not found among this account's matched game records. They are
not being added as owned test targets merely because they are common wheel games.

## Test and rollout rules

Start each unvalidated game on direct physical input with the relay off. Keep
existing working manual FH5/JDM routes intact. Nothing in this inventory enables
automatic identity changes, physical-device masking, HID helpers or force
transformations. A game becomes eligible for a built-in exception only after
attended validation and implementation of its supported route.

Record launch/runtime, device identity, duplicate device visibility, steering
linearity and range, separate pedals, buttons/paddles, shifter/handbrake where
applicable, physical force direction/quality, smoothness, menu/session changes,
exit/relaunch and reconnection. Test native Linux and Proton as separate routes.
Record input, FFB, launch blocking and built-in support as separate results.
Games with limited/no native FFB are not held to invented effect expectations.

No game was installed, launched or reconfigured during this library audit.

[beam]: https://documentation.beamng.com/support/hardware/
[scs]: https://blog.scssoft.com/2021/10/ets2ats-142-release.html
[logi]: https://support.logi.com/hc/en-001/articles/360051040854-Logitech-G923-G29-G920-Driving-Force-Racing-Wheel-Game-Compatibility-List
[lmu]: https://guide.lemansultimate.com/hc/en-gb/articles/13152295737359-How-to-set-up-your-wheel-and-pedals
[dirt5]: https://forums.ea.com/discussions/other-ea-racing-games-en/dirt-5---patch-notes/7230770/replies/7230775
[heat]: https://forums.ea.com/discussions/need-for-speed-franchise-discussion-en/under-the-hood-january-update/9435668
[unbound]: https://forums.ea.com/discussions/need-for-speed-unbound-tech-issues-en/re-need-for-speed-unbound-ts-xw/9397419
[mw]: https://forums.ea.com/discussions/need-for-speed-franchise-discussion-en/need-for-speed-most-wanted-2012-release-compatible-with-logitech-drive-force-gt/9238821/replies/9238822
[fs11]: https://store.steampowered.com/app/90200
[lawn]: https://steamcommunity.com/app/1480560/discussions/0/3046108212602987187/
[ets1]: https://help.steampowered.com/en/wizard/HelpWithGameTechnicalIssue?appid=232010
[busdriver]: https://help.steampowered.com/en/wizard/HelpWithGameTechnicalIssue?appid=302080
[busdemo]: https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/1825093633182097
[absolute]: https://steamcommunity.com/app/320140/discussions/0/1842367319517623553/
[dynasty]: https://store.steampowered.com/news/posts/?appids=678900&enddate=1517326445
[startrucker]: https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/1814309641437971
[busfull]: https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/1830163047269163
[hpr]: https://forums.ea.com/discussions/need-for-speed-franchise-discussion-en/wheel-support-/9512104
