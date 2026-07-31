"""Providers turn a catalog source into install/uninstall/status actions.

The factory dispatches on source *type*, never on app id — adding a new
source type means adding a branch here, not special-casing an app
(CLAUDE.md hard rule 5).
"""

from __future__ import annotations

from ignis.core.catalog import (
    App,
    ContainerSource,
    FlathubSource,
    GithubSource,
    ScriptSource,
    UjustSource,
)
from ignis.core.host import HostBridge
from ignis.core.state import State
from ignis.providers.base import Provider, UnsupportedSourceError
from ignis.providers.container import ContainerProvider
from ignis.providers.flathub import FlathubProvider
from ignis.providers.github_release import GithubReleaseProvider
from ignis.providers.script import ScriptProvider
from ignis.providers.ujust import UjustProvider

__all__ = [
    "ContainerProvider",
    "GithubReleaseProvider",
    "Provider",
    "UnsupportedSourceError",
    "create_provider",
]


def create_provider(app: App, bridge: HostBridge, state: State) -> Provider:
    """Build the provider that installs ``app``.

    Raises :class:`UnsupportedSourceError` if a catalog entry ever carries a
    source type with no provider. Callers must not crash on it.
    """
    source = app.source
    if isinstance(source, FlathubSource):
        return FlathubProvider(app, bridge, state)
    if isinstance(source, UjustSource):
        return UjustProvider(app, bridge, state)
    if isinstance(source, ScriptSource):
        return ScriptProvider(app, bridge, state)
    if isinstance(source, GithubSource):
        return GithubReleaseProvider(app, bridge, state)
    if isinstance(source, ContainerSource):
        return ContainerProvider(app, bridge, state)
    raise UnsupportedSourceError(f"no provider for source type {source.type!r}")
