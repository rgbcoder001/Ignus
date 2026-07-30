# Verifying on Bazzite

Ignis is developed on Windows, where the GTK stack and `flatpak-builder`
cannot run. Everything below has to be done on the Bazzite machine. Run it
after any change to `flatpak/`, `bin/ignis`, or the GTK code in
`src/ignis/{app,window,main}.py`.

## One-time setup

Bazzite is immutable, so install the builder as a Flatpak rather than with
`rpm-ostree`:

```bash
flatpak install -y flathub org.flatpak.Builder
```

## Build and install locally

From a clone of this repo:

```bash
flatpak run org.flatpak.Builder --user --install --force-clean --install-deps-from=flathub build flatpak/io.github.rgbcoder001.Ignis.yml
```

`--install-deps-from=flathub` pulls `org.gnome.Platform//50` and
`org.gnome.Sdk//50` the first time; expect a large download.

## Phase 1 acceptance test

Two things must be true: **the app launches**, and **it can run a command on
the host from inside the sandbox**.

### 1. It launches

```bash
flatpak run io.github.rgbcoder001.Ignis
```

Expected: a window titled *Ignis* listing every catalog app in a single
filterable list, with category chips (All / Gaming / Emulation / Media /
Streaming / System) above it.

### 2. Host access works

If `flatpak-spawn --host` is broken, a banner reading "Can't run commands on
your system: ..." appears just below the header bar — it should **not**
appear on a working install. If it does, check that
`--talk-name=org.freedesktop.Flatpak` survived in the built manifest.

The same check without the GUI, which also prints where the data and log
files resolved to:

```bash
flatpak run io.github.rgbcoder001.Ignis --self-check
```

Expected output (exit code 0):

```
Ignis 0.1.0
  data dir:      /app/share/ignis
  catalog:       13 apps loaded from /app/share/ignis/catalog.toml
  GPU vendors:   amd
  in flatpak:    True
  host spawn:    True
  host command:  OK — flatpak --version
      Flatpak 1.16.1
```

`data dir` must be `/app/share/ignis` (not a source path), `in flatpak` and
`host spawn` must both be `True`, and `GPU vendors` should match the actual
hardware.

### 3. It appears in the menu

Ignis should show up in the applications menu with the flame icon, and
launch from there.

## Phase 2 acceptance test

Providers (Flathub, ujust, script) plus the Browse -> Detail -> Progress
install flow.

### 1. Status pills populate

Shortly after launch, rows for already-installed apps should show a green
"Installed" pill; others show nothing (not installed) or "Status unknown"
(a `ujust`/`script` app with no `check_cmd`). Every spinner should resolve —
none should spin forever.

### 2. Category filter works

Clicking a category chip (e.g. "Gaming") should hide every row outside that
category; clicking "All" restores the full list.

### 3. Install Heroic end to end

1. Click the **Heroic Games Launcher** row -> opens the Detail page.
2. Confirm the **Source** row reads
   `Installs from Flathub: com.heroicgameslauncher.hgl`, and the **Command
   that will run** expander shows
   `flatpak install -y --noninteractive flathub com.heroicgameslauncher.hgl`.
3. Click **Install**. A progress dialog should appear, not closable, with
   live `flatpak install` output scrolling in the monospace view.
4. On completion: a green "Done" status and a **Close** button appear.
   Closing the dialog, the Detail page's **Status** row should now read
   "Installed" and an **Uninstall** button should appear.
5. Go back (back button in the header, or Escape, or swipe) to Browse — the
   Heroic row's pill should now read "Installed" too, with no manual refresh.

### 4. A failure is never silent

Trigger a failure on purpose — e.g. temporarily rename `data/catalog.toml`'s
`ref` for one app to something bogus like `com.example.DoesNotExist`, rebuild,
and try to install it. The progress dialog should turn red, name the exact
failing command and its exit code, and offer **Copy Log** / **Open Log
Folder** buttons that both work. Revert the catalog edit afterwards.

## Phase 3 acceptance test

The GitHub release provider, the Updates page and Settings.

### 1. Install GitHub Launcher end to end

`githublauncher` is the one `github`-sourced catalog entry. Open it from
Browse and click **Install**. Expected in the progress dialog:

```
[ignis] latest release is v1.73
[ignis] downloading GitHubLauncher-v1.73-Linux-X64.zip
[ignis] downloaded 8 MB of 42 MB
...
[ignis] extracting GitHubLauncher-v1.73-Linux-X64.zip
[ignis] added a launcher: ~/.local/share/applications/ignis-githublauncher.desktop
[ignis] GitHub Launcher v1.73 installed
```

Then confirm:

- `~/Applications/githublauncher/` holds `GithubLauncher` plus three `.so`
  files, and `GithubLauncher` is executable (`ls -l`).
- **GitHub Launcher actually starts**, both from `~/Applications/githublauncher/GithubLauncher`
  and from the desktop menu. Its Linux build embeds the .NET runtime
  (verified against v1.73), so it should not need .NET installed — if it
  complains about a missing runtime, that assumption has changed and the
  catalog entry needs revisiting.
- Detail's Status row reads "Installed" and an **Uninstall** button appears.

### 2. Update detection

```bash
cat ~/.var/app/io.github.rgbcoder001.Ignis/config/ignis/state.json
```

Confirm it records `githublauncher` with `tag` and the exact list of files
installed. To exercise the update path without waiting for a new upstream
release, edit that `tag` to something older (e.g. `v1.72`) and reopen Ignis:
the header's **Updates** button should highlight, and the Updates page should
offer `v1.72 → v1.73`. Clicking Update should reinstall cleanly.

### 3. Uninstall removes exactly what it installed

Click **Uninstall**. `~/Applications/githublauncher/` and
`~/.local/share/applications/ignis-githublauncher.desktop` should both be
gone, and nothing else should be touched.

### 4. Rate limiting degrades gracefully

Open **Settings** and confirm the token row saves (a toast appears). The
token only matters if you hit GitHub's ~60-checks-per-hour limit; if you do,
the Updates page shows a banner naming the problem rather than silently
reporting everything as up to date.

### 5. Uninstall safety

`state.json` is user-writable, so Ignis refuses to delete anything outside
`~/Applications`, `~/.local/share/applications` and `~/.local/share/icons`.
To confirm, add a bogus path such as `/etc/passwd` to an app's `files` list
in `state.json`, then uninstall: the progress log must say
`refusing to delete /etc/passwd` and the file must still exist.

## Phase 4 acceptance test

Hardware badges, settings, error handling and window size.

### 1. Badges match the machine

On an **AMD** machine, LACT (`hardware = ["amd"]`) should show a blue `AMD`
badge; hovering it says the card matches. On an NVIDIA/Intel machine the same
badge turns orange and the tooltip says it wasn't detected **but can still be
installed** — it must never say "incompatible" or block installing, because
detection can be wrong.

Cross-check what Ignis detected:

```bash
flatpak run io.github.rgbcoder001.Ignis --self-check
```

The `GPU vendors` line must match the real hardware. On a laptop with both
integrated and discrete graphics, expect both to be listed.

### 2. Settings shows real diagnostics

Settings should report Graphics, "Running as" (Flatpak, version, catalog
count) and a **System access** row that resolves to `Working — Flatpak 1.x.y`.
This is the page to screenshot when reporting a problem.

### 3. Window size is remembered

Resize the window, close it, reopen: it should come back the same size.
Maximise, close, reopen: it should come back maximised. Then confirm a corrupt
value can't produce an unusable window:

```bash
flatpak run --command=sh io.github.rgbcoder001.Ignis -c 'sed -i "s/\"width\": [0-9]*/\"width\": 3/" ~/.var/app/io.github.rgbcoder001.Ignis/config/ignis/state.json'
```

Reopening should fall back to the default 1000×700, not a 3-pixel window.

### 4. Every failure offers the log

Each of these must name what failed **and** give a way to the log:

- A failed install → red status, the exact command and exit code, **Copy Log**
  and **Open Log Folder** buttons.
- A failed update check → banner on the Updates page with an **Open Log
  Folder** button.
- Broken host access → banner on the browse list, same button.
- A catalog that won't load → full-page message with the same button.

Click **Open Log Folder** at least once and confirm the file manager actually
opens (this call needs the real window, not the dialog, so it's worth
checking rather than assuming).

## Phase 5 acceptance test

The end-user path, exactly as someone else would experience it.

1. On the Bazzite machine, download `ignis.flatpak` from the GitHub release
   page in a browser — do not build it locally.
2. Double-click it in Files. The software store should open with an
   **Install** button.
3. Install, then launch Ignis from the applications menu.
4. Install one app from the catalog.

If any step needs a terminal, the release is not done. See
[releasing.md](releasing.md) for the full pre-release checklist.

## Catalog verification checklist

Every entry in `data/catalog.toml` needs on-machine confirmation before it
ships — see the file's own `VERIFY` comments for specifics. Quick ways to
check each source type:

- **flathub**: `flatpak remote-info flathub <ref>` — nonzero exit means the
  ref is wrong or renamed on Flathub.
- **ujust**: run `ujust` with no arguments to see the interactive menu of
  available recipes and confirm the name is still listed; for the `sunshine`
  entry specifically, also just try installing it — see the catalog comment
  for why that one is higher-risk right now.
- **script**: read the script and run it manually once outside Ignis first.

If a name has drifted, fix it directly in `data/catalog.toml` — that file is
data, not code, so no rebuild logic needs to change.

## Building a double-clickable bundle

CI does this on every tag, but to produce one by hand:

```bash
flatpak run org.flatpak.Builder --force-clean --repo=repo build flatpak/io.github.rgbcoder001.Ignis.yml
```

```bash
flatpak build-bundle repo ignis.flatpak io.github.rgbcoder001.Ignis
```

Double-clicking the resulting `ignis.flatpak` in Files should open the
software store with an Install button — this is the end-user install path
and is worth testing at least once per release.

## If something fails

The log is inside the sandbox:

```bash
cat ~/.var/app/io.github.rgbcoder001.Ignis/.local/state/ignis/ignis.log
```

Every command Ignis ran is in there with its exit code and full output. To
see startup errors that happen before logging is up, launch from a terminal
and read stderr.
