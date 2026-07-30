# Releasing Ignis

Two separate things: **cutting a GitHub release** (how people install Ignis
today) and **submitting to Flathub** (the long-term goal, where Bazzite's
built-in software store handles installs and updates automatically).

Nothing here should be run until the acceptance tests in
[verifying-on-bazzite.md](verifying-on-bazzite.md) have actually passed on
real hardware. A release that has only been tested on a Windows dev machine
is not a release.

---

## Part 1 — Cutting a GitHub release

### Before tagging

- [ ] `pytest` green, and the Flatpak CI build green on `main`.
- [ ] Every phase acceptance test in `verifying-on-bazzite.md` has passed on
      the Bazzite machine, including at least one **install, update and
      uninstall** cycle.
- [ ] Every `VERIFY` comment in `data/catalog.toml` has been resolved or
      removed — no entry ships unverified. As of writing that means the
      EmuDeck marker path and the `setup-sunshine` recipe.
- [ ] Screenshots captured (see below) and referenced in the metainfo.
- [ ] Version bumped in **both** `src/ignis/__init__.py` and the
      `<releases>` block of `data/io.github.rgbcoder001.Ignis.metainfo.xml`,
      with an accurate release description and today's date.

### Screenshots

Flathub requires at least one, and they make the GitHub release page far more
convincing. They can only be taken on the Bazzite machine.

1. Run Ignis, resize to roughly 1000×700.
2. Capture the browse list, an app's detail page, and an install in progress.
3. Save as PNG under `data/screenshots/`, commit them.
4. Uncomment the `<screenshots>` block in the metainfo and point each
   `<image>` at the committed file's raw URL on `main`.

Screenshots must show the app doing something real. Do not mock them up.

### Tagging

CI builds the bundle and attaches it to the release automatically on any
`v*` tag:

```bash
git tag -a v0.1.0 -m "Ignis v0.1.0"
```

```bash
git push origin v0.1.0
```

Then watch the **Flatpak** workflow. When it finishes, the release will have
`ignis.flatpak` attached.

### After the release

- [ ] Download `ignis.flatpak` from the release page **on the Bazzite
      machine**, double-click it, and install through the software store —
      the exact path an end user takes. Confirm it installs, launches, and
      can install one app.
- [ ] Confirm the README's install instructions match what actually happened.

---

## Part 2 — Flathub submission

Flathub gets Ignis into Bazzite's built-in store with automatic updates,
which is a much better experience than downloading a file. Their review is
handled by volunteers, so arriving with the checklist already satisfied
matters.

### Prerequisites

- [ ] **The app ID must match the repository owner.** Ignis uses
      `io.github.rgbcoder001.Ignis`, which requires the repo to live at
      `github.com/rgbcoder001/Ignus`. If it moves, the ID has to change in
      the manifest, desktop file, metainfo, `src/ignis/__init__.py`, and the
      `.desktop`/icon filenames — `tests/test_packaging.py` checks they stay
      consistent.
- [ ] Metainfo passes validation cleanly:
      `appstreamcli validate --strict data/io.github.rgbcoder001.Ignis.metainfo.xml`.
      CI runs the non-strict version on every build.
- [ ] Desktop entry passes `desktop-file-validate`.
- [ ] At least one screenshot, plus a summary under 35 characters and a
      description that reads as prose, not a feature list.
- [ ] `runtime-version` is a currently supported GNOME runtime (Flathub
      rejects end-of-life runtimes).

### Expect to be asked about permissions

Ignis holds `--talk-name=org.freedesktop.Flatpak`, which lets it run commands
on the host. That is the single most scrutinised permission on Flathub, and
reviewers *will* raise it. The honest answer, which the metainfo description
already states plainly, is:

> Ignis is an installer. Its entire purpose is to run `flatpak install` and
> Bazzite's `ujust` recipes on the user's behalf. It shows the exact command
> before running it, streams the output live, and logs everything.

Do not try to soften or hide this — a reviewer finding an undeclared reason
for that permission is far worse than explaining it up front.

### Submitting

1. Fork [flathub/flathub](https://github.com/flathub/flathub) and create a
   branch named after the app ID.
2. Add the manifest. For Flathub the `type: dir` source must become a `git`
   source pinned to the release **tag and commit**, since Flathub builds from
   a clean checkout rather than a local directory:

   ```yaml
   sources:
     - type: git
       url: https://github.com/rgbcoder001/Ignus.git
       tag: v0.1.0
       commit: <full sha of that tag>
   ```

3. Open a pull request against `new-pr`, and answer review comments.
4. Once merged, update the README's install instructions to point at Flathub
   and keep the GitHub release as the fallback.

### After Flathub

Each new version is a PR to the app's own Flathub repository bumping the tag
and commit. Keep tagging releases here first — the GitHub release stays the
source of truth, and Flathub follows it.
