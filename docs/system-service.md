# System wheel service

This opt-in installation gives a dedicated `mozaproxy` account access to the
physical MOZA base alongside the active desktop user. The Qt app sends commands
through `/run/mozaproxy/control.sock`. Service startup and restart leave the relay
off, preserving normal physical wheel access. Unknown games and games without
a validated built-in route keep that baseline.

Starting the compact R9 relay is an explicit action. Closing the app leaves an
explicitly started relay running. Stopping the relay releases its grab and
removes the virtual wheel; physical access permissions remain available throughout.
The service does not select game routes, mask physical devices, inject descriptor
helpers, or change Steam options.

The implementation has isolated tests. Installed permissions, real Wine
behavior, and physical force feedback still require a coordinated test. Do not
activate it during game testing. Installed direct access and each game route
still need attended validation. FH5's confirmed compact relay plus per-game
physical masking and JDM's confirmed direct HIDRAW plus descriptor helper are
different routes. Preserve those working setups until replacements pass testing.

## Stage the runtime

Review the installer and templates before running this administrative command
from the checkout. Replace `YOUR_USER` with the desktop login name.

```sh
sudo /usr/bin/python3 -I tools/install-system-service.py install --client-user YOUR_USER
```

Staging creates an unprivileged `mozaproxy` account and the private
`mozaproxy-hardware` group. The service account's primary group is the desktop
user's primary group, so the desktop can open the control socket. The desktop
user is never added to the hardware group. An existing service account with
unexpected groups or a login shell causes installation to stop.

The installer builds a private Python environment as the desktop user, copies
regular files into a root-owned release under `/opt/mozaproxy/releases`, and
checks imports as the service account. Source symlinks and writable
administrative paths are rejected. Source reads use the desktop user's
credentials. No copied interpreter, dependency build, or daemon module runs as
root. Releases use a copied interpreter, not a link to the checkout or its
virtual environment. `evdev` and `pyserial` are installed for the daemon; Qt is
still supplied by the existing desktop installation.

Staging does not install active rules, start a service, publish the desktop
integration marker, or change Steam options. It can be repeated while no
activation journal exists. The previous staged release remains available on
disk; old releases are not automatically deleted.

Requirements are Python with `venv` and pip support, the build prerequisites for
`evdev`, systemd/udev, `runuser`, `useradd`/`groupadd`, and the `acl` tools
`getfacl` and `setfacl`. Dependency installation needs network access. No install
command has been run as part of development testing.

## Activate during a coordinated switch

1. Close all Wine games, Wine servers, local mozaproxy relays, and the desktop
   app. The activation preflight refuses detected live games or relays.
2. Unplug the physical MOZA USB connection. This removes existing device nodes
   and their seat ACLs without rewriting permissions on a live wheel.
3. Run the command below. Reconnect only when it prints its reconnect prompt.

```sh
sudo /usr/bin/python3 -I tools/install-system-service.py activate
```

Activation saves the previous contents and modes of the service unit, the
system access rule, and the integration marker. It also saves the existing
uinput ownership and ACL, plus the service's previous enabled and active states. A persistent recovery journal is written before
installing new permissions.

The new rule grants the hardware group access to physical `346e:0000` input
event/joystick, hidraw, USB, and serial nodes, with group and mode
`mozaproxy-hardware` and `0660`. It retains `uaccess` for the active desktop seat.
The `346e:0002` virtual input also keeps `uaccess` when explicitly created.
Uinput gains service group access while retaining desktop seat access. The installer does not modify the existing
`70-mozaproxy-access.rules` file or other administrator rules. Conflicting later
rules fail the access checks and cause rollback.

After reconnect, activation waits for udev, checks every discovered physical
node's owner, group, mode, and effective read/write access for both accounts. It
also checks service access to uinput, the running unit, and control socket
ownership and mode. Only then does it publish `/etc/mozaproxy/system.json` to
select system mode in the desktop app. Activation establishes shared physical
access and the control socket; it does not validate a virtual wheel or game FFB.
The default reconnect deadline is
120 seconds; `--reconnect-timeout` accepts 1 through 600 seconds.

The unit runs as `mozaproxy` with an empty capability set, a read-only system
filesystem, and no home-directory access. Its runtime directory is `0750`,
and the daemon creates its socket with mode `0660`. The daemon additionally
checks the caller's Unix peer UID against the one configured desktop user.
It accepts fixed wheel operations; clients cannot choose executables or paths.

Activation enables the service for startup at boot and starts it immediately,
with the relay off. If the service is unavailable, the app reports that failure
and does not silently start a local relay or open hardware for settings itself.
Games retain physical access independently of the daemon. A crash after an
explicit relay start removes that relay; restart returns to the direct baseline.

Protocol status separates child-process liveness from wheel readiness.
`relay.running` means only that the process is alive. `relay.ready` is `false`
when stopped and `null` when running; `relay.readiness` is `inactive` or
`unverified`. A running child may still be waiting for hardware or retrying a
failed session. No virtual readiness handshake has been implemented yet.
The integration fields identify `default_route: direct` and
`physical_access: desktop-and-service`. No route is automatically selected for a game.

## Roll back

Close games, unplug the physical wheel, then run:

```sh
sudo /usr/bin/python3 -I tools/install-system-service.py rollback
```

Rollback stops and disables the new service, restores the saved files and uinput
ACL, and reloads systemd and udev. It then restores the previous boot enablement
and restarts the previous service only if it was active before activation. Reconnect the physical wheel afterward so fresh nodes receive
the previous access policy. An activation failure also restores these files;
its error explicitly requires unplugging and reconnecting to restore the prior
permissions. It never claims existing physical ACLs have been reset.

If rollback cannot finish, the error identifies the failed step and retains
`/var/lib/mozaproxy-system/activation.json`. Fix the reported administrative
problem, keep the wheel unplugged, and run rollback again. Interrupted
activation also leaves this journal for recovery. The installed runtime and
service account remain staged, allowing another activation attempt.

No Steam launch options are edited. The Qt app can eventually package validated
game compatibility steps, but this service does not yet replace FH5's masking
launcher or JDM's HIDRAW and helper setup. Finish the remaining game tests before
staging and activating a replacement. Installed permissions, reboot behavior,
and direct/virtual game regressions remain pending.
