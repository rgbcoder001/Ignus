# Ignis — Technical Specification

A one-stop app installer for Bazzite, aimed at non-technical users. Detects your
hardware, then installs and configures the right gaming/media apps for your
system — no terminal required.

This is a **ground-up rewrite** of the abandoned `ignis-setup` project. That
version used Tauri 2 + React + WebKitGTK inside Flatpak and failed to launch
reliably (WebKitGTK-in-Flatpak is notoriously fragile). This rewrite exists to
eliminate every fragile layer. Read [CLAUDE.md](CLAUDE.md) before writing any
code — it contains the coding rules and the Opus/Sonnet task routing.

---

## 1. Goals and non-goals

**Goals**

1. Launches reliably, every time, on a stock Bazzite install. Reliability beats
   features in every trade-off.
2. Installable by double-clicking a `.flatpak` bundle downloaded from GitHub
   Releases (opens the software store, one-click install). Long-term: publish
   on Flathub so it appears in Bazzite's built-in store with auto-updates.
3. Data-driven catalog: adding/fixing an app means editing `data/catalog.toml`,
   never writing code.
4. Absorbs the functionality of SirDiabo/GithubLauncher: install and update
   apps distributed as GitHub release assets (AppImages/tarballs), tracked by
   version.
5. Hardware-aware: detect GPU vendor(s) and badge/filter apps accordingly.
6. Every action the app performs is a plain shell command a human could
   copy-paste. Full logging; failures show the exact command that failed.

**Non-goals (v1)**

- No support for distros other than Bazzite (Fedora Atomic assumptions are fine).
- No system-level changes requiring root beyond what `ujust` recipes already do.
- No plugin system, no remote catalog updates (catalog ships with the app).
- No telemetry of any kind.

## 2. Technology stack (fixed — do not substitute)

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | Ships in the GNOME Flatpak runtime; no compilation |
| UI | GTK4 + libadwaita via PyGObject | Ships in the GNOME runtime; the stack GNOME's own apps use |
| Catalog format | TOML parsed with stdlib `tomllib` | Human-editable, **zero pip dependencies** |
| Packaging | Flatpak on `org.gnome.Platform` (use the latest stable runtime version; verify at build time) | Pinned deps; "works on my machine" = "works everywhere" |
| Host access | `flatpak-spawn --host` via one HostBridge module | The sanctioned way to run host commands from a sandbox |
| State | JSON files in `GLib.get_user_config_dir()` | stdlib only |
| Tests | pytest (dev-only dependency) | Pure-logic tests, no GUI tests |

**Hard rule: zero runtime pip dependencies.** Python stdlib + PyGObject (from
the runtime) only. This is what keeps the flatpak manifest trivial and the
launch path unbreakable.

## 3. Repository layout

```
ignis/
├── CLAUDE.md                  # Coding rules + model routing (read first)
├── SPEC.md                    # This file
├── README.md
├── pyproject.toml             # Metadata + pytest config; no runtime deps
├── src/ignis/
│   ├── __init__.py            # __version__
│   ├── main.py                # Entry point: python -m ignis
│   ├── app.py                 # Adw.Application subclass
│   ├── window.py              # Main Adw.ApplicationWindow
│   ├── views/
│   │   ├── browse.py          # Catalog grid with category filters
│   │   ├── detail.py          # Per-app detail + install controls
│   │   ├── progress.py        # Live command-output dialog
│   │   ├── updates.py         # GitHub-app updates list
│   │   └── settings.py        # PAT, log folder, about
│   ├── core/
│   │   ├── host.py            # HostBridge — ALL subprocess use lives here
│   │   ├── catalog.py         # Load + validate catalog.toml → dataclasses
│   │   ├── hardware.py        # GPU vendor detection
│   │   ├── state.py           # Installed-versions + API-cache JSON store
│   │   └── log.py             # File logging setup
│   └── providers/
│       ├── base.py            # Provider ABC + InstallStatus enum + errors
│       ├── flathub.py
│       ├── ujust.py
│       ├── github_release.py
│       └── script.py
├── data/
│   ├── catalog.toml           # THE app catalog (seed provided)
│   ├── icons/                 # Catalog app icons (png, 64px)
│   ├── io.github.rgbcoder001.Ignis.desktop
│   ├── io.github.rgbcoder001.Ignis.metainfo.xml
│   └── io.github.rgbcoder001.Ignis.svg   # App icon
├── flatpak/
│   └── io.github.rgbcoder001.Ignis.yml   # Flatpak manifest
├── scripts/                   # Vetted shell snippets used by "script" sources
├── tests/                     # pytest — core/ and providers/ pure logic only
└── .github/workflows/
    ├── test.yml               # pytest on push/PR
    └── build.yml              # flatpak-builder on tag → release asset
```

**App ID:** `io.github.rgbcoder001.Ignis`. If the repo ends up under a
different GitHub account, the ID must change to match
(`io.github.<account>.Ignis`) — Flathub verifies ownership through it. The ID
appears in the manifest, desktop file, metainfo, and D-Bus application id;
keep them identical.

## 4. Architecture

```
┌────────────────────────── GTK4 / libadwaita UI ──────────────────────────┐
│  Browse ▸ Detail ▸ Progress          Updates          Settings           │
└───────────────┬──────────────────────────┬───────────────────────────────┘
                │ (worker threads; UI updates via GLib.idle_add only)
┌───────────────▼──────────────┐  ┌────────▼─────────┐
│  Providers                   │  │  core/state.py   │
│  flathub / ujust /           │  │  versions, cache │
│  github_release / script     │  └──────────────────┘
└───────────────┬──────────────┘
┌───────────────▼──────────────────────────────────────────┐
│  core/host.py — HostBridge                               │
│  in flatpak:  flatpak-spawn --host <argv>                │
│  in dev mode: <argv> directly                            │
│  streams output lines, logs everything                   │
└──────────────────────────────────────────────────────────┘
```

### 4.1 HostBridge (`core/host.py`)

The single chokepoint for running commands. **No other module may import
`subprocess`.**

```python
@dataclass
class CommandResult:
    argv: list[str]         # the argv as the USER would type it (without flatpak-spawn prefix)
    returncode: int
    output: str             # merged stdout+stderr

class HostBridge:
    @staticmethod
    def in_flatpak() -> bool:            # os.path.exists("/.flatpak-info")
    def run(self, argv: list[str],
            on_line: Callable[[str], None] | None = None,
            timeout: float | None = None) -> CommandResult:
```

Behavior:
- If `in_flatpak()`, prepend `["flatpak-spawn", "--host"]`; otherwise run argv
  directly (dev mode on a Linux workstation).
- Merge stdout/stderr, stream line-by-line to `on_line` (for the progress
  view), collect full output.
- Log every invocation to the log file: timestamp, argv, returncode, and full
  output. This is non-negotiable — it is the debuggability story.
- Never `shell=True`. argv lists only.
- Raise `CommandError(result)` on nonzero exit unless the caller passes
  `check=False`.

### 4.2 Catalog (`data/catalog.toml`, `core/catalog.py`)

Schema (validated at load; a malformed entry logs a warning and is skipped —
one bad entry must never take down the app):

```toml
[[apps]]
id = "heroic"                       # unique, kebab-case
name = "Heroic Games Launcher"
summary = "Play Epic, GOG and Amazon games"    # one line, shown on card
description = """Longer text shown in the detail view."""
category = "gaming"                 # gaming | emulation | media | streaming | system
hardware = []                       # [] = all; subset of ["amd", "nvidia", "intel"]
icon = "heroic.png"                 # optional; file in data/icons/
post_install = "scripts/foo.sh"     # optional; runs after successful install

[apps.source]                       # exactly one source per app
type = "flathub"
ref = "com.heroicgameslauncher.hgl"
```

Source variants:

```toml
# Flathub
[apps.source]
type = "flathub"
ref = "com.obsproject.Studio"

# Bazzite ujust recipe
[apps.source]
type = "ujust"
recipe = "install-emudeck"
check_cmd = ["flatpak", "info", "org.emudeck.EmuDeck"]   # optional: exit 0 = installed

# GitHub release (the GithubLauncher functionality)
[apps.source]
type = "github"
repo = "SirDiabo/GithubLauncher"
asset_pattern = 'linux-x64\.zip$'   # regex vs asset filename; must match exactly one
install_kind = "zip"                 # appimage | tarball | zip

# Vetted script shipped in this repo
[apps.source]
type = "script"
file = "scripts/discord-fix.sh"
check_cmd = ["test", "-f", "/some/marker"]  # optional
```

`core/catalog.py` parses this into frozen dataclasses (`App`, `Source`
variants) with `tomllib`, and is fully unit-tested including malformed-entry
skipping.

### 4.3 Provider contract (`providers/base.py`)

```python
class InstallStatus(Enum):
    NOT_INSTALLED, INSTALLED, UPDATE_AVAILABLE, UNKNOWN

class Provider(ABC):
    def __init__(self, app: App, bridge: HostBridge, state: State): ...
    def status(self) -> InstallStatus: ...          # must be fast; no network unless cached
    def install(self, on_line: Callable[[str], None]) -> None: ...   # raises InstallError
    def uninstall(self, on_line) -> None: ...       # may raise NotSupportedError
```

Per-provider behavior:

- **flathub** — `status`: `flatpak info <ref>` (exit 0 → installed).
  `install`: `flatpak install -y --noninteractive flathub <ref>`.
  `uninstall`: `flatpak uninstall -y <ref>`.
- **ujust** — `status`: run `check_cmd` if present else `UNKNOWN`.
  `install`: `ujust <recipe>`. Some recipes prompt interactively; each recipe
  added to the catalog must be tested on Bazzite, and prompting recipes either
  get non-interactive flags or are excluded. `uninstall`: not supported.
- **script** — `install`: `bash <absolute path to bundled script>`. Scripts
  live in this repo, are reviewed, and must be idempotent (safe to re-run).
- **github** — see 4.4.

### 4.4 GitHub release provider (`providers/github_release.py`)

This absorbs SirDiabo/GithubLauncher. All pure logic (asset selection, version
comparison, cache handling) must be in standalone functions with unit tests.

- **Release lookup:** `GET https://api.github.com/repos/{repo}/releases/latest`
  using stdlib `urllib.request`. Send `If-None-Match` with the cached ETag;
  on 304 use cached JSON. Cache lives in `state.json`. This keeps us under the
  60 req/hr unauthenticated rate limit. If the user set a PAT in Settings,
  send it as `Authorization: Bearer` — **on API requests only, never on the
  asset download itself**: `browser_download_url` redirects to S3, urllib
  forwards headers through redirects, and S3 rejects a request carrying both
  a signed URL and an Authorization header (HTTP 400). On 403 rate-limit,
  surface a friendly message suggesting the PAT setting — never crash.
- **Asset selection:** apply `asset_pattern` (case-insensitive regex) to asset
  names. Exactly one match required; zero or multiple matches → `InstallError`
  naming the assets found (this is a catalog bug, make it loud and clear).
- **Install (appimage):** download to
  `~/Applications/<app-id>/<asset-name>` (create dirs), `chmod +x`, write a
  `.desktop` file to `~/.local/share/applications/ignis-<app-id>.desktop`
  pointing at it (with the catalog icon copied to `~/.local/share/icons/`),
  run `update-desktop-database` via HostBridge if available (ignore failure).
- **Install (tarball/zip):** extract to `~/Applications/<app-id>/`, find the
  executable, same `.desktop` treatment. Tar extraction uses `filter="data"`;
  zip extraction relies on `ZipFile.extract`'s member-name sanitising — both
  refuse `..` traversal out of the target directory.
- **Finding the executable** (Phase 3 note): the original "largest file with
  the exec bit" heuristic does not survive zip, which does not preserve
  permissions — and "largest" picks the wrong file when an app ships big
  native libraries beside a small launcher. Ignis instead prefers files whose
  first four bytes are the ELF magic number, then a filename resembling the
  app, then the shallowest and largest. Verified against the real
  GithubLauncher release, where it correctly picks `GithubLauncher` over the
  bundled `libSDL2.so`, `libSkiaSharp.so` and `libHarfBuzzSharp.so`.
- **Version tracking:** record `{tag_name, installed_files[]}` in state.
  `status()` compares cached latest `tag_name` vs installed → 
  `UPDATE_AVAILABLE`. Update = install new + delete old files from the
  recorded list. Uninstall = delete recorded files + the `.desktop` entry.
- Downloads are streamed to a `.part` file and renamed on completion; a
  failed/interrupted download must leave no corrupt state.

### 4.5 Hardware detection (`core/hardware.py`)

Read `/sys/class/drm/card*/device/vendor` (visible inside the sandbox — no
HostBridge needed). Map vendor IDs: `0x1002` → amd, `0x10de` → nvidia,
`0x8086` → intel. Return a **set** (iGPU + dGPU machines report both). On any
read failure return the empty set and treat as "show everything" — detection
failures must never hide the catalog. Unit-test with fake sysfs trees via
`tmp_path`.

Catalog use: an app with `hardware = ["amd"]` shows a vendor badge always, and
gets a "not detected on this system" warning style (still installable —
detection can be wrong) when `amd` is not in the detected set.

### 4.6 State (`core/state.py`)

One JSON file at `os.path.join(GLib.get_user_config_dir(), "ignis", "state.json")`
(inside flatpak this maps to `~/.var/app/<id>/config/ignis/`). Written
atomically (temp file + rename), created with mode 0600 (it may contain the
PAT). Corrupt/missing file → start fresh, log a warning, never crash.

```json
{
  "github_apps": {"zelda64recomp": {"tag": "v1.2.0", "files": ["..."]}},
  "api_cache":  {"Owner/Repo": {"etag": "...", "json": {}, "fetched_at": "..."}},
  "settings":   {"github_pat": ""}
}
```

### 4.7 Logging (`core/log.py`)

Python `logging` to both stderr and a rotating file at
`<user_state_dir>/ignis/ignis.log` (keep 3 × 1 MB). The Settings view has an
"Open log folder" button (`Gtk.FileLauncher`). Every HostBridge call, every
provider action, every swallowed exception gets logged.

## 5. UI specification

libadwaita widgets throughout; follow GNOME HIG. Dark/light follows system.
Window title: "Ignis". Default size 1000×700, remember size.

- **Main window** — `Adw.ApplicationWindow` with `Adw.ViewStack` +
  `Adw.ViewSwitcher` (header bar): **Browse**, **Updates** (badge with count
  when updates exist), **Settings**.
- **Browse** — horizontal `Adw.ToggleGroup`/filter chips for categories
  (All, Gaming, Emulation, Media, Streaming, System) above a `Gtk.FlowBox` of
  app cards. Card: icon, name, one-line summary, hardware badge(s), status
  pill (Installed / Update available), and an Install button or checkmark.
  Clicking a card opens Detail.
- **Detail** — `Adw.NavigationView` push page: big icon, name, full
  description, source info ("Installs from Flathub: com.obsproject.Studio"),
  an expander row **"Command that will run"** showing the literal command
  (transparency = trust), Install/Uninstall/Update buttons.
- **Progress** — `Adw.Dialog`, not closable while running. Monospace
  `Gtk.TextView` auto-scrolling the live `on_line` stream, spinner + status
  label. On success: green banner, Close. On failure: red banner with the
  failing command, exit code, and buttons **Copy log** and **Open log folder**.
- **Updates** — `Adw.PreferencesGroup` list of GitHub-sourced apps with
  updates: name, installed → latest version, per-row Update button and an
  Update All. Refresh button triggers a re-check (worker thread).
- **Settings** — `Adw.PreferencesPage`: GitHub token (`Adw.PasswordEntryRow`,
  with an explanation of why/when it's needed), Open log folder, About dialog
  (`Adw.AboutDialog` with version + link to the repo).

**Threading rule (absolute):** every provider call and network call runs in a
`threading.Thread`; the GTK main loop is never blocked; all UI mutation from
workers goes through `GLib.idle_add`. Buttons that start work are disabled
until the work finishes.

**Error UX rule (absolute):** the user must never see a silent failure or a
bare "Something went wrong". Every error dialog shows what command failed and
offers the log.

**Phase 3 implementation note — one navigation stack, no ViewSwitcher.**
Updates and Settings are pushed onto the same `Adw.NavigationView` as Detail,
reached from buttons in Browse's header, rather than being siblings in an
`Adw.ViewStack` behind an `Adw.ViewSwitcher`. Same reasoning as the Phase 2
note below: it reuses the one navigation mechanism already in the code
instead of introducing a second, unrun one. The Updates button carries the
pending-update count. Revisit in Phase 4 if the Bazzite testing shows the
sections are hard to find.

**Phase 2 implementation note — Browse deviates from FlowBox cards.** It
ships as a single filterable `Gtk.ListBox` of `Adw.ActionRow`s (icon, name,
summary, hardware badges, status pill, click-through to Detail) rather than a
`Gtk.FlowBox` grid. Reasoning: this UI code was written on a Windows machine
where nothing in `gi`/GTK4 can be run or rendered, so every additional widget
is unverified until someone runs it on Bazzite. `Adw.ActionRow` in a
`Gtk.ListBox` is a pattern already used successfully in Phase 0/1; a FlowBox
card grid would add layout risk with no way to check it before shipping. This
is a deliberate, lower-risk substitute for the same information — a Phase 4
(UI polish) candidate to upgrade once someone can actually see it on screen.
The Detail, Progress, install/uninstall, and threading behavior all match
this section as written.

## 6. Flatpak packaging

`flatpak/io.github.rgbcoder001.Ignis.yml`:

```yaml
app-id: io.github.rgbcoder001.Ignis
runtime: org.gnome.Platform
runtime-version: '49'        # verify latest stable at build time and bump
sdk: org.gnome.Sdk
command: ignis
finish-args:
  - --share=network                          # GitHub API + downloads
  - --share=ipc
  - --socket=wayland
  - --socket=fallback-x11
  - --device=dri
  - --talk-name=org.freedesktop.Flatpak      # enables flatpak-spawn --host
  - --filesystem=~/Applications:create       # GitHub-app installs
  - --filesystem=~/.local/share/applications:create   # .desktop entries
  - --filesystem=~/.local/share/icons:create
modules:
  - name: ignis
    buildsystem: simple
    build-commands:
      - install -Dm755 bin/ignis /app/bin/ignis          # launcher: exec python3 -m ignis
      - cp -r src/ignis /app/lib/ignis                    # + set PYTHONPATH in launcher
      - cp -r data/catalog.toml data/icons /app/share/ignis/
      - install -Dm644 data/io.github.rgbcoder001.Ignis.desktop -t /app/share/applications
      - install -Dm644 data/io.github.rgbcoder001.Ignis.metainfo.xml -t /app/share/metainfo
      - install -Dm644 data/io.github.rgbcoder001.Ignis.svg -t /app/share/icons/hicolor/scalable/apps
      - cp -r scripts /app/share/ignis/scripts
    sources:
      - type: dir
        path: ..
```

(Exact install commands are Opus's to finalize; the structure above is the
intent. The app locates its bundled data via `/app/share/ignis` when packaged,
falling back to the repo-relative `data/` in dev mode.)

Notes:
- `--talk-name=org.freedesktop.Flatpak` grants full host command access. That
  is the entire point of this app, but Flathub reviewers will ask — the
  metainfo description must state plainly that the app runs system package
  commands on the user's behalf.
- Local build:
  `flatpak-builder --user --install --force-clean build flatpak/io.github.rgbcoder001.Ignis.yml`
- Bundle for release:
  `flatpak build-bundle repo ignis.flatpak io.github.rgbcoder001.Ignis`

## 7. CI (GitHub Actions)

- `test.yml` — on push/PR: Python 3.12, `pip install pytest`, `pytest`.
- `build.yml` — on tag `v*`: use `flatpak/flatpak-github-actions`
  (`flatpak-builder` action, `org.gnome.Sdk` docker image matching the
  runtime version) to build the bundle and upload `ignis.flatpak` to the
  GitHub Release. Also run it on PRs (build-only, no release) so packaging
  breakage is caught early.

## 8. Seed catalog

`data/catalog.toml` ships with a starter set (already in this repo). **Every
entry must be verified on a real Bazzite machine during Phase 2** — Flathub
refs checked against flathub.org, ujust recipe names checked against `ujust`'s
list on current Bazzite (recipe names change between releases; do not trust
the ones written here).

## 9. Build phases and model routing

Work strictly in phase order; each phase ends with its acceptance test
passing and a commit. See CLAUDE.md for the routing rationale.

| Phase | Scope | Model | Acceptance |
|---|---|---|---|
| 0 | Scaffold: repo layout, pyproject, `core/` (host, log, catalog, hardware, state) with tests, minimal window listing the catalog | **Opus** | `pytest` green; app launches on a Linux box in dev mode and shows the catalog |
| 1 | Flatpak packaging: manifest, desktop, metainfo, icon, launcher script, CI build workflow | **Opus** | Bundle installs & launches on Bazzite; a HostBridge call (`flatpak --version`) succeeds from inside the sandbox |
| 2 | Providers: flathub, ujust, script + Progress view + Detail view wiring; verify seed catalog on Bazzite | **Sonnet** | Install Heroic from the UI on Bazzite, live output visible, status pill updates |
| 3 | GitHub release provider + Updates view + state/cache + PAT setting | **Opus** | Install + update a GitHub-sourced AppImage end-to-end; asset-selection and cache logic unit-tested |
| 4 | Hardware badges/filtering, Settings polish, error-UX pass, window-size persistence | **Sonnet** | Badges correct on an AMD machine; every failure path shows command + log access |
| 5 | Release: end-user README, metainfo screenshots, tagged release with bundle, Flathub submission checklist | **Sonnet** | A fresh Bazzite user can download the release bundle, double-click, install, use |

## 10. Definition of done (v1)

- Launches on stock Bazzite from a double-clicked release bundle.
- Installs at least: 6 Flathub apps, 1 ujust recipe, 1 script fix, 1
  GitHub-release AppImage — each verified on real hardware.
- Update flow works for GitHub-sourced apps.
- No unhandled exception can reach the user without the command + log path.
- `pytest` and the flatpak CI build are green on `main`.
