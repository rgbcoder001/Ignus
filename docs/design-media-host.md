# Design — turning Bazzite into a media host

Status: **proposed, not built.** This covers three related asks: mounting a
Synology NAS, running a Jellyfin *server*, and running Komga for e-books and
comics.

Read this before writing any of it. It changes the catalog schema, adds a
source type, and is the first thing in Ignis that handles a password.

---

## 1. Why this needs a design at all

Everything Ignis installs today is static data. `catalog.toml` says "install
`com.obsproject.Studio`" and that is the whole story — no app has ever needed
to ask the user a question.

These three do:

| | Needs to know |
|---|---|
| NAS mount | host, share name, username, password, where to mount it |
| Jellyfin server | which folder holds the media |
| Komga | which folder holds the books |

So the blocking piece is **per-app configuration**, and one of those fields is
a password. That is the actual work; the containers themselves are easy.

## 2. Dependency order

The obvious order (Jellyfin, Komga, NAS) is backwards. Both servers exist to
serve media that lives on the NAS, so:

```
1. NAS mount        →  media is readable at a real path
2. Container support →  Jellyfin server
3.                   →  Komga
```

Building the servers first means configuring their libraries twice.

## 3. Scope decision: let the apps configure themselves

Jellyfin and Komga both have good web-based setup wizards. Ignis should not
reimplement them.

**Ignis's job ends at:** the service is running, it can see the media folder,
the firewall allows it, and the browser is open at the right address. Library
setup, users, metadata and transcoding settings all happen inside the app,
where the good UI already exists.

That keeps the configuration Ignis has to collect down to roughly one path per
server, rather than a whole settings system.

## 4. Per-app configuration

### Catalog schema

Add an optional `settings` array to an entry:

```toml
[[apps.settings]]
key = "media_dir"
label = "Where your films and shows are"
type = "path"          # path | text | port | password
default = "~/Media"
help = "Ignis will let the server read this folder."
```

Field types map to widgets: `path` to an `Adw.EntryRow` with a folder picker,
`port` to a spin row with a validated range, `password` to
`Adw.PasswordEntryRow`, `text` to a plain entry row.

### Flow

Detail page gains a **Configure** step: if an app declares `settings` and has
no saved values, Install opens a dialog first. Values are substituted into the
provider's command as `{media_dir}`-style placeholders.

### Where values live

Non-secret values go in `state.json` under `app_settings.<app_id>`, alongside
the existing install records.

**Passwords do not.** See §6.

## 5. New source type: `container`

Bazzite [documents Quadlet](https://docs.bazzite.gg/Installing_and_Managing_Software/Quadlet/)
as its way to run services, and Podman recommends Quadlet over
`podman generate systemd`. Use Quadlet.

```toml
[apps.source]
type = "container"
image = "docker.io/jellyfin/jellyfin:latest"
port = 8096
volumes = [
  "{media_dir}:/media:ro",
  "%h/.local/share/ignis/jellyfin/config:/config:Z",
]
```

Ignis writes a rootless user Quadlet unit to
`~/.config/containers/systemd/ignis-<id>.container`, then:

```
systemctl --user daemon-reload
systemctl --user start ignis-<id>.service
```

- **Status:** `systemctl --user is-active ignis-<id>.service` — fast, local,
  no network. Fits the existing `status()` contract.
- **Autostart without logging in:** needs `loginctl enable-linger $USER`,
  which needs privilege, so one `pkexec` prompt at install.
- **Open:** the existing Open button becomes "open `http://localhost:<port>`"
  via `xdg-open`, which is genuinely the right action for a server.
- **Uninstall:** stop the service and delete the unit file — and **never**
  touch the media folder or the config volume. Removing someone's library
  because they uninstalled a server would be unforgivable. Same
  deletable-roots guard as the GitHub provider.

Images verified: `jellyfin/jellyfin` (396M pulls), `gotson/komga` (43M pulls).

### Sandbox note

Quadlet units must land in the **real** `~/.config/containers/systemd/`.
Inside the Flatpak, `~/.config` is redirected to `~/.var/app/<id>/config`, the
same trap already documented in `core/paths.py`. Since these run through
`HostBridge`, the script executes on the host where `$HOME` is correct — but
any Python that writes these paths directly must not use `XDG_CONFIG_HOME`.

## 6. The NAS mount, and the password problem

For a *container* to read the NAS, it has to be a real kernel mount. A Dolphin
`smb://` browse is per-session and per-user and invisible to services, so it
cannot work here.

Proposed: a systemd `.mount` unit plus a root-owned credentials file.

```
/etc/systemd/system/mnt-nas.mount        (What=//host/share, Type=cifs)
/etc/ignis/nas-<name>.credentials        (0600, root-owned)
```

`x-systemd.automount` so the share is mounted on first access rather than
blocking boot when the NAS is off.

### Credentials must never reach the log

This is the part to get right. `HostBridge` logs every command **and its full
output**, which is the whole debuggability story — and it would happily write
a NAS password into `ignis.log` in plaintext if the password were passed as a
command argument.

So:

- **Extend `HostBridge.run()` with `stdin_data`**, piped to the process and
  **never logged**. `core/host.py` is Opus-owned per CLAUDE.md.
- The password reaches the host script on stdin, which writes the credentials
  file with `umask 077`.
- The password is never stored in `state.json`, never placed in argv, never
  echoed. Host, share and mount point are ordinary settings and can be.
- The credentials file is root-owned 0600 — the standard arrangement for
  `cifs-utils`.

### SMB vs NFS

Worth asking the user before building:

- **SMB/CIFS** — works with Synology's defaults, needs a username and
  password, slightly more per-file overhead.
- **NFS** — faster for large media, no credentials to store at all (which
  removes the entire password problem above), but requires enabling NFS and
  setting host permissions on the Synology first.

If NFS is acceptable, the design gets materially simpler and safer.

## 7. Firewall

Jellyfin (8096) and Komga (25600) need their ports open for other devices on
the LAN — `firewall-cmd --add-port`, so another privileged step.

Not needed if access is only ever over Tailscale, which is a reasonable
default for a home setup and avoids exposing anything to the LAN. Suggest
asking, defaulting to Tailscale-only.

## 8. Phases

| Phase | Scope | Notes |
|---|---|---|
| A | Per-app settings: catalog schema, config dialog, storage | No new services yet; the enabling work |
| B | `stdin_data` on HostBridge, NAS mount entry | The credentials-handling phase; smallest and most security-sensitive |
| C | `container` source type + Jellyfin server | The bulk of the container work |
| D | Komga | Should be a catalog entry only, if C generalised properly |

C being one catalog entry once B and A exist is the test of whether the design
is right.

## 9. Risks

- **Uninstall deleting media.** The single worst outcome here. Container
  uninstall must remove only the unit file, never a volume path.
- **Password leaking into the log.** Addressed in §6, but it is the reason
  that section exists.
- **A wrong NAS mount blocking boot.** `x-systemd.automount` plus `nofail`.
- **Scope.** This is a service manager growing inside an app installer. If it
  gets much past Jellyfin and Komga, it deserves to be its own screen rather
  than more catalog entries.

## 10. Open questions for the user

1. **SMB or NFS** for the Synology? NFS removes the password handling
   entirely.
2. **Where should media be mounted** — `/mnt/nas`, or somewhere under home?
3. **LAN access or Tailscale-only?** Tailscale-only means no firewall changes
   and nothing exposed locally.
4. **Should the servers start without logging in?** Yes implies enabling
   lingering, which is one more privileged step at install.
