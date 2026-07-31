# Design — connecting Bazzite to a NAS

Status: **built.** v0.6.0 delivered the settings layer, the NAS mount and the
container source type (§6 was pulled back into scope for Komga, which has no
desktop package and so had no alternative). v0.7.0 added Jellyfin Server as a
catalog entry with no new code — which was the test this design set for
itself — and hardened the NAS script (see the security note in §4).

The goal is narrow and worth stating plainly: **make connecting this machine
to a NAS simple, and make the connection survive a reboot.** Everything else
here is optional and explicitly not committed to.

Running media *servers* on Bazzite (Jellyfin server, Komga) was considered and
deliberately pushed into §6 as optional. Jellyfin's client is already in the
catalog, and mapping libraries is something the apps' own web interfaces do
well. Ignis does not need to reimplement that.

---

## 1. Decisions already made

| Decision | Rationale |
|---|---|
| **NFS, not SMB** | Faster for the metadata-heavy work (library scans, comics), lighter on CPU, and removes password handling entirely |
| **Export is Read/Write** | The user wants to add, delete and organise files from Bazzite |
| **Any container mount is `:ro`** | Export permission and container view are separate controls; servers never need write access |
| **One rule for one IP, via DHCP reservation** | NFS has no password — the IP *is* the credential. Subnet-wide read/write hands delete rights to every device on the network |
| **systemd units, not `/etc/fstab`** | See §4. Removing a mount becomes "delete two files" rather than editing a file the boot depends on |

### Rejected: SMB with stored credentials

The earlier draft of this design had Ignis collect a NAS password, add a
`stdin_data` channel to `HostBridge` so the password never reached the log,
and write a root-owned `0600` credentials file. Choosing NFS deletes that
entire branch: no password field, no credentials file, no change to
`HostBridge`, and no way to leak a secret into `ignis.log`.

This is the main reason NFS is the right call here, over and above the
performance argument.

## 2. What Ignis is missing

Every catalog entry to date is static data — no app has ever needed to ask
the user a question. A NAS mount needs three answers:

| Field | Example | Type |
|---|---|---|
| NAS address | `192.168.1.50` | text |
| Export path | `/volume1/Media` | text |
| Mount point | `/mnt/nas` | path |

No password, so no secret storage. This is a small settings layer, not a
configuration system.

### Catalog schema

```toml
[[apps.settings]]
key = "nas_host"
label = "Your NAS address"
type = "text"
default = ""
help = "The IP address of the NAS, for example 192.168.1.50"
```

Types needed for this phase: `text` and `path`. (`port` and `password` were
in the earlier draft and are no longer required — do not build them until
something needs them.)

### Flow

If an entry declares `settings` and has no saved values, Install opens a
dialog first. Answers are stored in `state.json` under
`app_settings.<app_id>` and reach the provider two ways: **scripts** get them
as shlex-quoted shell variables prepended below the shebang (never
interpolated into the script text, so an answer containing a quote cannot
become code), while **container units and check commands** get `{nas_host}`
placeholders substituted as plain text. An unanswered placeholder stays
literal, which makes a not-yet-configured status check fail — correctly
reading as "not installed" — and makes a container install error out rather
than create a directory literally named `{books_dir}`.

## 3. The export path is the usual mistake

On the Synology, the value to mount is the **mount path** shown at the bottom
of the NFS Permissions dialog — `/volume1/Media` — not the share's display
name. The settings dialog should say so in its help text, because this is the
single most common way an NFS mount fails for a first-timer.

## 4. The mount itself

A pair of systemd units, written by a bundled script under `pkexec`:

```
/etc/systemd/system/mnt-nas.mount
/etc/systemd/system/mnt-nas.automount
```

```ini
# mnt-nas.mount
[Unit]
Description=NAS media (managed by Ignis)
After=network-online.target
Wants=network-online.target

[Mount]
What=192.168.1.50:/volume1/Media
Where=/mnt/nas
Type=nfs4
Options=rw,noatime,_netdev,vers=4.1

[Install]
WantedBy=multi-user.target
```

```ini
# mnt-nas.automount
[Automount]
Where=/mnt/nas
TimeoutIdleSec=600
```

Then `systemctl daemon-reload && systemctl enable --now mnt-nas.automount`.

**Why units rather than `/etc/fstab`:** a malformed fstab line is a genuinely
nasty failure for a non-technical user, and removal means editing a shared
file rather than deleting our own. Units are self-contained, and the file name
identifies them as ours.

**Why automount rather than a plain mount:** the share is mounted on first
access instead of at boot, so a NAS that is switched off, asleep or moved does
not delay or block startup. `TimeoutIdleSec` lets the NAS spin its disks down
again.

**Unit naming is not free-form.** The file name must be the escaped mount
path: `/mnt/nas` becomes `mnt-nas.mount`. Derive it with
`systemd-escape --path --suffix=mount "$MOUNT_POINT"` rather than by string
substitution.

**The mount point must be canonical — this bit Bazzite specifically.**
Bazzite is an ostree system, so `/mnt`, `/home`, `/opt` and `/srv` are all
symlinks into `/var`. `mount(8)` follows a symlink without complaint, so a
test mount of `/mnt/nas` succeeds — but systemd refuses the automount:

```
mnt-nas.automount: Mount path /mnt/nas is not canonical (contains a symlink).
Failed with result 'resources'.
```

Resolve with `realpath -m` (`-m` so it works before the folder exists)
before deriving the unit name or writing `Where=`. `/mnt/nas` becomes
`/var/mnt/nas` and the unit becomes `var-mnt-nas.automount`. The user can
still use `/mnt/nas` — it is the same folder.

**The status check must resolve the path the same way.** Looking for
`mnt-nas.automount` when systemd created `var-mnt-nas.automount` reports a
perfectly good mount as missing.

**Guard the `/var/*` originals too.** A refuse-list containing `/home` does
not catch `/var/home`, which is the same directory.

**Mount options:** `hard` (the default) is kept rather than `soft`. With
writes enabled, `soft` risks silent corruption on a flaky link; the hang risk
that usually argues for `soft` is already handled by automount plus
`_netdev`.

### Status, uninstall

- **Status:** `systemctl is-enabled mnt-nas.automount` — no privileges, no
  network, fast enough for the catalog list.
- **Uninstall:** stop and disable the automount, delete the two unit files,
  `daemon-reload`. **Never** touch anything under the mount point — that is
  the user's NAS, and Ignis has no business deleting from it. The refusal
  guard already used for GitHub-app uninstall applies here.

### Security note: the privileged step (added after review)

The script escalates once with `pkexec` to write the units. The rule the
implementation must keep: **nothing the user typed is ever interpolated into
the root shell as code.** The `-c` body is single-quoted and every value —
unit contents, mount point, unit file names — arrives as a positional
argument, expanded only inside double quotes as data. The first version
interpolated `${mount_point}` directly into the root command string, which
let a crafted answer like `/mnt/x'; rm -rf /; '` escape its quoting and run
as root; the settings dialog's "starts with a slash" check was no defence.

The script also refuses to mount over critical system directories or any
non-empty folder (hiding a user's files under a mount is unrecoverable-by-
appearance), and the post-mount check runs under `timeout` so a hard NFS
mount that stops answering cannot hang the install behind a progress dialog.

## 5. Phases

| Phase | Scope | Status |
|---|---|---|
| A | Settings layer: `[[apps.settings]]` schema, config dialog, storage in `state.json` | built (v0.6.0) |
| B | NAS mount catalog entry + bundled script | built (v0.6.0), hardened (v0.7.0) |
| C | `container` source type + Komga | built (v0.6.0) |
| D | Jellyfin Server — a catalog entry only, no new code | built (v0.7.0) |

No credentials anywhere: choosing NFS removed the only password this design
ever had to handle.

## 6. Running media servers — built for Komga and Jellyfin Server

**History:** this section was originally optional. It came into scope because
Komga has no desktop package at all — it is a server reached through a
browser, with no Flathub entry, so "just install Komga" had no shortcut. The
`container` source type was built for it, and Jellyfin Server then cost one
catalog entry, which was the test the design set for itself. The Jellyfin
*client* (Media Player) stays in the catalog alongside it: the server hosts
the library, the player watches it.

How it works: a `container` catalog entry becomes a rootless Podman
[Quadlet](https://docs.bazzite.gg/Installing_and_Managing_Software/Quadlet/)
unit written to the real `~/.config/containers/systemd/` (Bazzite documents
Quadlet as its own way to run services). Status is
`systemctl --user is-active`; the Open button opens
`http://localhost:<port>`; lingering is enabled once via `pkexec` (and
skipped on later installs if already on) so services survive logging out.

What Ignis deliberately does **not** do: library mapping, users, metadata —
Jellyfin's and Komga's own web setup does that far better than an installer
could. Ignis stops at "running, can see the media folder, browser open at
the right address."

### Containers reading an automounted share (found on hardware)

A container reading the NAS needs two things beyond the obvious bind mount,
and without them it silently sees an empty folder:

- **`:rslave` propagation on the volume.** Podman's default is `rprivate`.
  A container that starts while the automount is idle binds the empty autofs
  directory, and can never see the files: the host mounting it later does not
  propagate in, and the container touching the path cannot trigger the host's
  automounter either. This is [podman#12122](https://github.com/containers/podman/issues/12122).
- **`RequiresMountsFor=<path>` in `[Unit]`.** Makes systemd trigger the
  automount and wait for it before starting the container, and hold it
  mounted while the service runs — otherwise `TimeoutIdleSec` unmounts the
  share out from under a running server.

The symptom is badly misleading: whichever server happened to be installed
while the share was still mounted works perfectly, and the next one installed
after the 10-minute idle timeout sees nothing. That looks like a difference
between the two applications, and is not.

Paths must be canonicalised (`realpath -m`) before going into either
directive, for the same `/mnt` → `/var/mnt` reason as §4.

Standing rules for any container entry:

- The media volume stays read-only (`{media_dir}:/media:ro`) regardless of
  the NFS export being read/write — export permission and container view are
  separate controls.
- Uninstall removes the unit file and nothing else. The config volume holds
  the user's library database; the media folder was never ours.
- Placeholders that survive substitution are an install-time error, not a
  literal directory on disk.

## 7. Risks

- **Deleting a user's media.** The worst possible outcome. Uninstall touches
  only the two unit files, never the mount point's contents.
- **A bad mount delaying boot.** Handled by `automount` + `_netdev`; the
  share is only touched when something reads it.
- **A changing NAS IP silently breaking the mount.** Not solvable in software
  — the setup notes tell the user to set a DHCP reservation.
- **Scope creep into a service manager.** §6 exists to make that a conscious
  decision rather than a drift.

## 8. Synology setup (reference)

The user does this once, before installing the Ignis entry.

1. **Control Panel → File Services → NFS**: enable NFS, set maximum protocol
   to **NFSv4.1**.
2. **Control Panel → Shared Folder → [share] → Edit → NFS Permissions →
   Create**:
   - **Hostname or IP**: the Bazzite machine's reserved IP
   - **Privilege**: Read/Write
   - **Squash**: Map all users to admin
   - **Security**: sys
   - Tick asynchronous, non-privileged ports, and access to mounted
     subfolders
3. Note the **mount path** at the bottom of that dialog — `/volume1/Media`.
   That is what goes in the Ignis settings dialog.
4. Set a **DHCP reservation** for the Bazzite machine on the router.
5. If Synology's firewall is on, allow NFS.

SMB can stay enabled on the same shared folder throughout — Synology serves
both protocols at once, so Windows machines are unaffected.
