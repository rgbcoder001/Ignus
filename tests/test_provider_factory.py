"""create_provider() dispatches on source type, never on app id."""

from __future__ import annotations

import pytest

from fake_bridge import FakeBridge
from ignis.core.catalog import (
    App,
    Category,
    FlathubSource,
    GithubSource,
    InstallKind,
    ScriptSource,
    UjustSource,
)
from ignis.core.state import State
from ignis.providers import (
    GithubReleaseProvider,
    UnsupportedSourceError,
    create_provider,
)
from ignis.providers.flathub import FlathubProvider
from ignis.providers.script import ScriptProvider
from ignis.providers.ujust import UjustProvider


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


def make_app(source, app_id="x") -> App:
    return App(id=app_id, name="X", summary="s", category=Category.SYSTEM, source=source)


def test_flathub_source_gets_flathub_provider(bridge, state):
    app = make_app(FlathubSource(ref="org.example.App"))
    assert isinstance(create_provider(app, bridge, state), FlathubProvider)


def test_ujust_source_gets_ujust_provider(bridge, state):
    app = make_app(UjustSource(recipe="do-thing"))
    assert isinstance(create_provider(app, bridge, state), UjustProvider)


def test_script_source_gets_script_provider(bridge, state):
    app = make_app(ScriptSource(file="x.sh"))
    assert isinstance(create_provider(app, bridge, state), ScriptProvider)


def test_github_source_gets_github_provider(bridge, state):
    app = make_app(
        GithubSource(repo="a/b", asset_pattern=".*", install_kind=InstallKind.APPIMAGE),
        app_id="githublauncher",
    )
    assert isinstance(create_provider(app, bridge, state), GithubReleaseProvider)


def test_unknown_source_type_raises_rather_than_crashing(bridge, state):
    """Callers rely on this being a ProviderError they can display."""

    class MysterySource:
        type = "carrier-pigeon"

    app = make_app(MysterySource())
    with pytest.raises(UnsupportedSourceError) as excinfo:
        create_provider(app, bridge, state)
    assert "carrier-pigeon" in str(excinfo.value)
