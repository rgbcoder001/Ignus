"""Keeping Ignis itself up to date.

Ignis is installed from a downloaded .flatpak bundle rather than a remote,
so `flatpak update` will never see a new version. This checks Ignis's own
GitHub releases and installs the newer bundle, saving the user a manual
download.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ignis import APP_ID, GITHUB_REPO, __version__
from ignis.core import paths
from ignis.core.host import HostBridge
from ignis.core.state import State
from ignis.core.version import is_newer
from ignis.providers.base import InstallError, LineCallback
from ignis.providers.flathub import USER_SCOPE, installed_scope
from ignis.providers.github_api import GithubClient, ReleaseError, select_asset

log = logging.getLogger(__name__)

#: The release asset holding the installable bundle.
BUNDLE_PATTERN = r"\.flatpak$"


class SelfUpdater:
    """Checks for, and installs, a newer release of Ignis."""

    def __init__(
        self, bridge: HostBridge, state: State, client: GithubClient | None = None
    ) -> None:
        self.bridge = bridge
        self.state = state
        self.client = client or GithubClient(state)

    @property
    def current_version(self) -> str:
        """The version running right now."""
        return __version__

    def available_update(self) -> str | None:
        """The newer release tag, or None. Hits the network."""
        release = self.client.latest_release(GITHUB_REPO)
        if is_newer(release.tag, __version__):
            return release.tag
        return None

    def cached_update(self) -> str | None:
        """The newer release tag from cache only, or None. No network."""
        release = self.client.cached_release(GITHUB_REPO)
        if release is not None and is_newer(release.tag, __version__):
            return release.tag
        return None

    def install(self, on_line: LineCallback) -> None:
        """Download the newest bundle and install it over this one."""
        try:
            release = self.client.latest_release(GITHUB_REPO)
            asset = select_asset(release, BUNDLE_PATTERN)
        except ReleaseError as exc:
            raise InstallError(str(exc)) from exc

        if not is_newer(release.tag, __version__):
            raise InstallError(f"Ignis {__version__} is already the newest version.")

        # Must land somewhere the *host* can read: the bundle is installed by
        # flatpak running outside this sandbox, which cannot see /app or the
        # app's private data directory.
        staging = paths.applications_dir() / ".ignis-update"
        on_line(f"[ignis] downloading Ignis {release.tag}")
        try:
            bundle = self.client.download(asset, staging / asset.name, on_line)
            self._install_bundle(bundle, on_line)
        except ReleaseError as exc:
            raise InstallError(str(exc)) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        on_line(f"[ignis] Ignis {release.tag} installed — restart Ignis to use it")

    def _install_bundle(self, bundle: Path, on_line: LineCallback) -> None:
        """Hand the downloaded bundle to flatpak on the host."""
        scope = installed_scope(self.bridge, APP_ID) or USER_SCOPE
        on_line(f"[ignis] installing the new version ({scope.lstrip('-')})")
        result = self.bridge.run(
            ["flatpak", "install", "-y", "--noninteractive", scope, str(bundle)],
            on_line=on_line,
            timeout=None,
            check=False,
        )
        if not result.ok:
            raise InstallError(
                f"Installing the new version failed with exit code {result.returncode}",
                result=result,
            )
