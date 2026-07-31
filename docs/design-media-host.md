# Design — connecting Bazzite to a NAS

Status: **built in v0.6.0.** The settings layer, the NAS mount and the
container source type all exist. §6 (running media servers) was pulled back
into scope for Komga, which has no desktop package and so had no alternative.

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
dialog first. Values are substituted into the provider's command as
`{nas_host}` placeholders, and stored in `state.json` under
`app_settings.<app_id>`.

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

## 5. Phases

| Phase | Scope |
|---|---|
| A | Settings layer: `[[apps.settings]]` schema, config dialog, storage in `state.json` |
| B | NAS mount catalog entry + bundled script |

That is the whole committed scope. Two phases, no credentials, no containers.

## 6. Running media servers — built for Komga only

**Revised:** originally optional, but Komga has no desktop package (see the
constraint at the end of this section), so "install Komga" had no shortcut.
The `container` source type was built for it.

Jellyfin's **server** is still deliberately out of scope — the client is in
the catalog and is what most people actually want. Adding the server later is
now a catalog entry rather than new code, which is the test the design set
for itself.

Ignis *could* grow a `container` source type, writing rootless Podman
[Quadlet](https://docs.bazzite.gg/Installing_and_Managing_Software/Quadlet/)
units to `~/.config/containers/systemd/` to run Jellyfin server
(`docker.io/jellyfin/jellyfin`) and Komga (`docker.io/gotson/komga`). Bazzite
documents Quadlet as its own way to run services, so the mechanism is sound.

**Why it is not in scope:**

- The client is what most people want, and the Jellyfin client is already in
  the catalog.
- Library mapping is done well by Jellyfin's and Komga's own web interfaces.
  Ignis reimplementing that would be worse than what already exists.
- It turns an app installer into a service manager, which is a much larger
  thing to maintain and to get right.

**One constraint to know if this is ever revisited:** Komga has no desktop
package. It is a server, reached through a browser, with no Flathub entry —
so "just install Komga" is not available as a simple catalog entry the way
Jellyfin's client is. Komga specifically requires the container work in this
section; there is no shortcut.

If it is built, the volume mount stays read-only (`{media_dir}:/media:ro`)
regardless of the NFS export being read/write, and uninstall must never remove
a media folder or a config volume.

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
