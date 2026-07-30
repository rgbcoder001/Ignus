# CLAUDE.md — Ignis

Read [SPEC.md](SPEC.md) before writing any code. It defines the architecture,
the phase plan, and the acceptance criteria. This file defines *how* to work.

## What this project is

A Python + GTK4/libadwaita Flatpak app for Bazzite that installs curated apps
(Flathub / ujust / GitHub releases / vetted scripts) for non-technical users.
The previous attempt (Tauri + React + WebKitGTK) died from stack fragility.
**Reliability beats features and beats cleverness in every decision.**

## Model routing

Different phases are assigned to different Claude models (SPEC.md §9). If you
are the wrong model for the current phase, say so and stop instead of
proceeding.

- **Opus builds:** Phase 0 (scaffold + core/), Phase 1 (flatpak packaging),
  Phase 3 (GitHub release provider). These contain the subtle failure modes:
  sandbox/host boundary, streaming subprocess handling, packaging, API
  caching, file-install bookkeeping.
- **Sonnet builds:** Phases 2, 4, 5 — providers that are thin wrappers over
  HostBridge, UI views, catalog entries, CI polish, docs.
- **Any later change to these files goes back to Opus:** `core/host.py`,
  `providers/github_release.py`, `flatpak/*.yml`, `core/state.py`.
- When in doubt mid-task whether something is "Opus territory": if it touches
  subprocess handling, the flatpak sandbox boundary, or file
  deletion/bookkeeping, it is.

## Hard rules

1. **Zero runtime pip dependencies.** Python stdlib + PyGObject only. If you
   feel you need a library, you are designing it wrong — stop and reconsider.
   (`pytest` is allowed as a dev/CI-only dependency.)
2. **No `subprocess` outside `core/host.py`.** Every external command goes
   through HostBridge so it is logged, streamed, and works both in-sandbox
   and in dev mode. Never `shell=True`; argv lists only.
3. **Never block the GTK main loop.** Provider/network work runs in
   `threading.Thread`; UI mutation from workers only via `GLib.idle_add`.
   Disable the triggering button while work runs.
4. **No silent failures.** No bare `except:`, no `except Exception: pass`.
   Every caught exception is logged; every user-facing failure shows the
   failing command and offers the log. If you swallow an error deliberately
   (e.g., optional `update-desktop-database`), log it and comment why it is
   safe to ignore.
5. **Data-driven, no special cases.** Adding an app = editing
   `data/catalog.toml`. If an app seems to need custom code, it needs a
   `script` source or a new *generic* capability — never an `if app.id ==`.
6. **Destructive file operations only on recorded paths.** Uninstall/update
   deletes exactly the files listed in state for that app — never a glob,
   never a whole directory the app didn't create.
7. **Atomic writes** for state and downloads: temp file + rename. A crash
   mid-write must never corrupt state or leave a half-file that looks whole.
8. **One bad catalog entry never breaks the app.** Validate, log, skip.

## Code style

- Python 3.12+, full type hints, `dataclass`/`Enum` for data, `pathlib.Path`
  for paths, f-strings.
- Keep modules under ~300 lines; split before they grow past it.
- Docstring on every public class/function — one line saying what it's for.
- Comments only for non-obvious constraints (e.g., "GitHub returns 304 with
  an empty body — must reuse cache"), not narration of the code.
- UI code declares widgets in Python (no `.ui` XML files, no Blueprint) —
  fewer build steps, easier for follow-up models to modify.
- Conventional commits (`feat:`, `fix:`, `chore:`), one phase = at least one
  commit, working state at every commit.

## Testing and verification

- `pytest` covers pure logic: catalog parsing/validation, GitHub asset
  selection, version comparison, cache/ETag handling, state
  read/write/corruption recovery, hardware detection (fake sysfs via
  `tmp_path`). **Do not** write GTK widget tests.
- Network calls in tests: never hit the real GitHub API — inject fake
  responses.
- **Environment caveat:** development may be happening on a Windows machine.
  The GTK UI and flatpak build cannot run there — do not try. What you can
  always do: run `pytest` (keep `core/` and `providers/` logic importable
  without `gi`), and rely on CI for the flatpak build. Real verification of
  UI and installs happens on the Bazzite box; when a phase's acceptance test
  needs that, prepare exact step-by-step instructions for the human to run
  and ask them for the results rather than declaring it done.
- Keep `gi` imports out of `core/catalog.py`, `core/state.py` (pass paths in
  from callers), `providers/` pure logic, so tests run on any OS.

## Things that will bite you (learned the hard way)

- `flatpak-spawn --host` requires the `--talk-name=org.freedesktop.Flatpak`
  finish-arg; without it commands fail confusingly. Test a trivial host
  command (`flatpak --version`) as part of Phase 1 acceptance.
- `ujust` recipes can prompt interactively. Every recipe added to the catalog
  must be tested on Bazzite; prefer non-interactive variants; drop recipes
  that can't run unattended.
- GitHub API unauthenticated limit is 60 req/hr per IP — ETag caching is not
  optional, and rate-limit errors must degrade gracefully with a hint about
  the PAT setting.
- Inside the sandbox, `~/.config` maps to `~/.var/app/<id>/config`. Use
  `GLib.get_user_config_dir()` — never hardcode `~/.config`.
- The GNOME runtime version in the flatpak manifest must match the SDK
  version in the CI builder image, or CI breaks.
