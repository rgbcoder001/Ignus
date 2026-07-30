"""Installs apps distributed as GitHub release assets.

This is the SirDiabo/GithubLauncher functionality (SPEC.md §4.4): download
an AppImage/tarball/zip from a project's latest release, give it a desktop
launcher, and track its version so updates can be offered later.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path

from ignis.core import paths
from ignis.core.catalog import App, Category, GithubSource, InstallKind
from ignis.core.host import HostBridge
from ignis.core.state import InstalledApp, State
from ignis.providers.base import (
    InstallError,
    InstallStatus,
    LineCallback,
    Provider,
)
from ignis.providers.github_api import (
    GithubClient,
    Release,
    ReleaseError,
    download_asset,
    select_asset,
)

log = logging.getLogger(__name__)

ELF_MAGIC = b"\x7fELF"

DESKTOP_CATEGORIES = {
    Category.GAMING: "Game;",
    Category.EMULATION: "Game;Emulator;",
    Category.MEDIA: "AudioVideo;",
    Category.STREAMING: "AudioVideo;",
    Category.SYSTEM: "System;",
}


class GithubReleaseProvider(Provider):
    """Installs, updates and removes an app from its GitHub releases."""

    supports_uninstall = True

    def __init__(
        self,
        app: App,
        bridge: HostBridge,
        state: State,
        client: GithubClient | None = None,
    ) -> None:
        super().__init__(app, bridge, state)
        self.client = client or GithubClient(state)

    @property
    def source(self) -> GithubSource:
        """This app's GitHub source definition."""
        return self.app.source  # type: ignore[return-value]

    @property
    def install_dir(self) -> Path:
        """Where this app's files live."""
        return paths.applications_dir() / self.app.id

    @property
    def desktop_entry_path(self) -> Path:
        """Where this app's launcher is written."""
        return paths.desktop_entries_dir() / f"ignis-{self.app.id}.desktop"

    def status(self) -> InstallStatus:
        """Installed state, using only the cache — never the network."""
        record = self.state.installed(self.app.id)
        if record is None:
            return InstallStatus.NOT_INSTALLED
        cached = self.client.cached_release(self.source.repo)
        if cached is not None and cached.tag != record.tag:
            return InstallStatus.UPDATE_AVAILABLE
        return InstallStatus.INSTALLED

    def installed_tag(self) -> str | None:
        """The release tag currently installed, if any."""
        record = self.state.installed(self.app.id)
        return record.tag if record else None

    def fetch_latest(self) -> Release:
        """Network refresh of the latest release. Raises :class:`ReleaseError`."""
        return self.client.latest_release(self.source.repo)

    def install(self, on_line: LineCallback) -> None:
        """Download and install the latest release, replacing any older one."""
        try:
            release = self.fetch_latest()
            asset = select_asset(release, self.source.asset_pattern)
        except ReleaseError as exc:
            raise InstallError(str(exc)) from exc

        previous = self.state.installed(self.app.id)
        if previous and previous.tag == release.tag:
            on_line(f"[ignis] {release.tag} is already installed — reinstalling")

        on_line(f"[ignis] latest release is {release.tag}")
        on_line(f"[ignis] downloading {asset.name}")

        staging = self.install_dir / ".download"
        try:
            archive = download_asset(asset, staging / asset.name, on_line)
            installed_files = self._place_files(archive, on_line)
        except ReleaseError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise InstallError(str(exc)) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        executable = _find_executable(installed_files, self.app.name)
        _make_executable(executable)

        entry = self.desktop_entry_path
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(_desktop_entry(self.app, executable), encoding="utf-8")
        installed_files.append(entry)
        on_line(f"[ignis] added a launcher: {entry}")

        # Record the new install *before* removing the old files, so a crash
        # in between can never leave state pointing at files that are gone.
        record = InstalledApp(tag=release.tag, files=tuple(str(p) for p in installed_files))
        self.state.set_installed(self.app.id, record)
        try:
            self.state.save()
        except OSError as exc:
            raise InstallError(f"Installed, but could not record it: {exc}") from exc

        if previous:
            stale = [Path(p) for p in previous.files if Path(p) not in set(installed_files)]
            _remove_files(stale, on_line)

        _prune_empty_dirs(self.install_dir)
        self._refresh_desktop_database(on_line)
        on_line(f"[ignis] {self.app.name} {release.tag} installed")

    def uninstall(self, on_line: LineCallback) -> None:
        """Delete exactly the files recorded for this app, nothing else."""
        record = self.state.installed(self.app.id)
        if record is None:
            raise InstallError(f"{self.app.name} is not recorded as installed by Ignis")

        _remove_files([Path(p) for p in record.files], on_line)
        _prune_empty_dirs(self.install_dir)

        self.state.clear_installed(self.app.id)
        try:
            self.state.save()
        except OSError as exc:
            raise InstallError(f"Removed the files, but could not update state: {exc}") from exc

        self._refresh_desktop_database(on_line)
        on_line(f"[ignis] {self.app.name} removed")

    def describe_source(self) -> str:
        """e.g. 'Installs from GitHub releases: Owner/Repo'."""
        return f"Installs from GitHub releases: {self.source.repo}"

    def command_preview(self) -> str:
        """There is no single shell command here — describe what happens."""
        return (
            f"Downloads the file matching /{self.source.asset_pattern}/ from\n"
            f"https://github.com/{self.source.repo}/releases/latest\n"
            f"into {self.install_dir}"
        )

    def _place_files(self, archive: Path, on_line: LineCallback) -> list[Path]:
        """Move/extract the downloaded archive into the install directory."""
        kind = self.source.install_kind
        self.install_dir.mkdir(parents=True, exist_ok=True)

        if kind is InstallKind.APPIMAGE:
            target = self.install_dir / archive.name
            os.replace(archive, target)
            return [target]

        on_line(f"[ignis] extracting {archive.name}")
        if kind is InstallKind.TARBALL:
            return _extract_tar(archive, self.install_dir)
        if kind is InstallKind.ZIP:
            return _extract_zip(archive, self.install_dir)
        raise InstallError(f"Unsupported install kind {kind!r}")

    def _refresh_desktop_database(self, on_line: LineCallback) -> None:
        """Ask the desktop to notice the new launcher. Optional, never fatal."""
        result = self.bridge.run(
            ["update-desktop-database", str(paths.desktop_entries_dir())],
            on_line=on_line,
            timeout=30,
            check=False,
        )
        if not result.ok:
            # Purely a refresh hint: the launcher still works, it may just not
            # appear in the menu until the next login.
            log.info("update-desktop-database unavailable (exit %d)", result.returncode)


def _extract_tar(archive: Path, target: Path) -> list[Path]:
    """Extract a tar archive safely, returning the files written."""
    try:
        with tarfile.open(archive) as tar:
            # filter="data" refuses absolute paths, .. traversal, links out of
            # the tree, and device files.
            tar.extractall(target, filter="data")
            names = [m.name for m in tar.getmembers() if m.isfile()]
    except (tarfile.TarError, OSError) as exc:
        raise InstallError(f"Could not extract {archive.name}: {exc}") from exc
    return _existing_paths(target, names)


def _extract_zip(archive: Path, target: Path) -> list[Path]:
    """Extract a zip archive safely, returning the files written.

    ZipFile.extract sanitises member names (drops drive letters, leading
    separators and .. components), so extraction cannot escape ``target``.
    """
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
            names = [info.filename for info in bundle.infolist() if not info.is_dir()]
    except (zipfile.BadZipFile, OSError) as exc:
        raise InstallError(f"Could not extract {archive.name}: {exc}") from exc
    return _existing_paths(target, names)


def _existing_paths(root: Path, names: list[str]) -> list[Path]:
    """Resolve archive member names to files that actually landed inside root."""
    found: list[Path] = []
    for name in names:
        candidate = root / name
        if candidate.is_file() and _is_within(candidate, root):
            found.append(candidate)
    return found


def _is_within(path: Path, root: Path) -> bool:
    """True if ``path`` resolves to somewhere inside ``root``."""
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _find_executable(files: list[Path], hint: str) -> Path:
    """Pick the program to launch out of everything the archive contained.

    Prefers real ELF binaries (a zip won't preserve the executable bit, so
    the mode is not a reliable signal), then a name resembling the app, then
    the shallowest and largest candidate.
    """
    if not files:
        raise InstallError("The download contained no files")

    elves = [p for p in files if _is_elf(p)]
    pool = elves or [p for p in files if os.access(p, os.X_OK)] or files

    def rank(path: Path) -> tuple[int, int, int]:
        name = path.name.lower()
        return (
            0 if _hint_matches(hint, name) else 1,
            len(path.parts),
            -_size(path),
        )

    return sorted(pool, key=rank)[0]


def _hint_matches(hint: str, filename: str) -> bool:
    """Loose match of an app name against a filename."""
    condensed = "".join(c for c in hint.lower() if c.isalnum())
    target = "".join(c for c in filename.lower() if c.isalnum())
    return bool(condensed) and condensed[:6] in target


def _is_elf(path: Path) -> bool:
    """True if the file starts with the ELF magic number."""
    try:
        with path.open("rb") as handle:
            return handle.read(4) == ELF_MAGIC
    except OSError:
        return False


def _size(path: Path) -> int:
    """File size, or 0 if it cannot be read."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _make_executable(path: Path) -> None:
    """Add the executable bit for the user, as zip extraction drops it."""
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as exc:
        raise InstallError(f"Could not make {path.name} executable: {exc}") from exc


def _desktop_entry(app: App, executable: Path) -> str:
    """Build the .desktop file contents for an installed app."""
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={app.name}",
            f"Comment={app.summary}",
            f"Exec={_quote_exec(executable)}",
            f"Path={executable.parent}",
            "Icon=application-x-executable",
            "Terminal=false",
            f"Categories={DESKTOP_CATEGORIES.get(app.category, 'Utility;')}",
            f"X-Ignis-App={app.id}",
            "",
        ]
    )


def _quote_exec(executable: Path) -> str:
    """Quote a path for a .desktop Exec= line."""
    escaped = str(executable).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def deletable_roots() -> tuple[Path, ...]:
    """Directories Ignis is allowed to delete installed files from."""
    return (
        paths.applications_dir(),
        paths.desktop_entries_dir(),
        paths.user_icons_dir(),
    )


def is_deletable(path: Path) -> bool:
    """True only if ``path`` sits under a directory Ignis installs into.

    state.json is user-writable and could be corrupted or hand-edited, so a
    recorded path is not trusted on its own — this is the backstop for
    CLAUDE.md hard rule 6.
    """
    return any(_is_within(path, root) for root in deletable_roots())


def _remove_files(files: list[Path], on_line: LineCallback) -> None:
    """Delete exactly these files, refusing any path outside our own roots."""
    for path in files:
        if not is_deletable(path):
            on_line(f"[ignis] refusing to delete {path} — outside Ignis's folders")
            log.error("refused to delete out-of-scope recorded path: %s", path)
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            # Report and continue: a leftover file is better than a half-done
            # uninstall that stops at the first error.
            on_line(f"[ignis] could not delete {path}: {exc}")
            log.warning("could not delete %s", path, exc_info=True)


def _prune_empty_dirs(root: Path) -> None:
    """Remove empty directories left under ``root``, then root itself."""
    if not root.is_dir() or not is_deletable(root):
        return
    for directory in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                log.debug("kept non-empty directory %s", directory)
    try:
        root.rmdir()
    except OSError:
        log.debug("kept non-empty directory %s", root)
