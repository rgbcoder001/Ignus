# Ignis

**A one-stop app installer for [Bazzite](https://bazzite.gg).** Ignis finds
your graphics card, then installs and sets up the gaming, emulation, media and
streaming apps that suit it — with no terminal, no commands to copy, and no
guesswork. It was built so that someone who just wants to play games can set
up a machine without help.

> **Status: in development.** Everything described below is implemented, but
> Ignis has not yet been through testing on real Bazzite hardware, and there
> is no published release to download yet. Developers: see
> [SPEC.md](SPEC.md), [CLAUDE.md](CLAUDE.md), and
> [docs/verifying-on-bazzite.md](docs/verifying-on-bazzite.md).

## Installing Ignis

1. Download `ignis.flatpak` from the
   [latest release](https://github.com/rgbcoder001/Ignus/releases/latest).
2. Double-click the downloaded file. Your software store opens with an
   **Install** button.
3. Launch **Ignis** from your applications menu.

That's the whole process — Bazzite already knows how to install a `.flatpak`
file, so nothing else needs setting up first.

## Using Ignis

Ignis opens on a list of apps. Use the buttons along the top to show one
category at a time — Gaming, Emulation, Media, Streaming or System.

- **To install something**, click it, read what it does, and press
  **Install**. A window shows exactly what is happening as it happens.
- **Already installed?** Apps you have are marked *Installed*, so the list
  doubles as a summary of what's set up on the machine. Open one and you get
  an **Open** button to start it, and a switch to **put a shortcut on the
  desktop** so it's there to double-click later.
- **A badge like `AMD`** means an app is built for that graphics card. If it
  doesn't match yours, Ignis says so but still lets you install it — hardware
  detection isn't perfect and you may know better.
- **The Updates button** (top right) checks everything: Ignis itself, apps
  downloaded from GitHub, and apps from Flathub. Ignis can update itself in
  place, so you never have to download it by hand again.
- **The top of the main screen** shows what the machine actually is — your
  graphics card, processor, memory and system version — which is the first
  thing worth knowing when picking apps or reporting a problem.

Every installation shows the exact command being run before it runs, streams
the live output while it works, and writes everything to a log. If something
fails, the error names the command that failed and offers a button to open
the log folder — there are no dead ends.

## What's included

Ignis installs from four places, and which one an app uses is an
implementation detail you never have to think about:

| Section | What's in it |
|---|---|
| Gaming | Heroic, Lutris, Prism Launcher (Minecraft), Bottles, ProtonUp-Qt |
| Emulation | EmuDeck, GitHub Launcher |
| Media | VLC, mpv, HandBrake, Jellyfin (server and player), Komga |
| Streaming | GPU Screen Recorder, OBS Studio, Sunshine, Moonlight |
| Chat | Vesktop, Discord |
| System | NAS connection, Tailscale, Mission Center, Flatseal, OpenRGB, CoolerControl, LACT |

Every app says in plain language what it does, why you might want it, and
when you can safely skip it — written for people arriving from Windows, not
for people who already know Linux.

Behind the scenes these come from Flathub, Bazzite's own `ujust` setup
recipes, GitHub releases, or bundled setup scripts — but which one an app
uses is an implementation detail you never have to think about.

Adding or correcting an app is a change to one data file,
[`data/catalog.toml`](data/catalog.toml) — no code required.

## Privacy

Ignis has no telemetry, no analytics and no accounts. It talks to Flathub and
GitHub only to install and update the apps you pick. The optional GitHub token
in Settings is stored locally in your own config folder and is only used to
raise GitHub's rate limit for update checks.

## Development

Ignis is Python with GTK 4 and libadwaita, shipped as a Flatpak on the GNOME
runtime, with **zero runtime pip dependencies** — the runtime already provides
everything it needs. That is a deliberate choice: the previous attempt at this
project used a heavier stack and failed to launch reliably.

Run the tests. These work on any OS, including Windows, because nothing under
`core/` or `providers/` imports `gi`:

```bash
pip install pytest pyyaml
```

```bash
pytest
```

Diagnose an environment without starting the GUI:

```bash
python -m ignis --self-check
```

Building and running the app itself requires Linux — see
[docs/verifying-on-bazzite.md](docs/verifying-on-bazzite.md) for the build
commands and the acceptance tests for each phase, and
[docs/releasing.md](docs/releasing.md) for cutting a release.

## License

MIT — see [LICENSE](LICENSE).
