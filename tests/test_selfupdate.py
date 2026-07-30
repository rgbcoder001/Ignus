"""Ignis updating itself from its own GitHub releases."""

from __future__ import annotations

import json

import pytest

from fake_bridge import FakeBridge
from ignis import APP_ID, __version__
from ignis.core.selfupdate import SelfUpdater
from ignis.core.state import State
from ignis.providers.base import InstallError
from ignis.providers.github_api import GithubClient
from test_github_api import FakeResponse, Recorder

REPO = "rgbcoder001/Ignus"


def release_payload(tag: str, asset: str = "ignis.flatpak") -> dict:
    return {
        "tag_name": tag,
        "assets": [
            {
                "name": asset,
                "browser_download_url": f"https://example.invalid/{asset}",
                "size": 4,
            }
        ],
    }


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


def updater(bridge, state, *responses) -> SelfUpdater:
    return SelfUpdater(bridge, state, GithubClient(state, Recorder(*responses)))


def test_reports_a_newer_release(bridge, state):
    payload = release_payload("v99.0.0")
    up = updater(bridge, state, FakeResponse(json.dumps(payload).encode()))
    assert up.available_update() == "v99.0.0"


def test_same_version_is_not_an_update(bridge, state):
    payload = release_payload(f"v{__version__}")
    up = updater(bridge, state, FakeResponse(json.dumps(payload).encode()))
    assert up.available_update() is None


def test_older_release_is_not_an_update(bridge, state):
    payload = release_payload("v0.0.1")
    up = updater(bridge, state, FakeResponse(json.dumps(payload).encode()))
    assert up.available_update() is None


def test_cached_check_needs_no_network(bridge, state):
    state.set_cache(REPO, "etag", release_payload("v99.0.0"))
    up = updater(bridge, state)  # Recorder with no responses: any call raises
    assert up.cached_update() == "v99.0.0"


def test_cached_check_without_a_cache_is_none(bridge, state):
    assert updater(bridge, state).cached_update() is None


def test_installing_when_already_current_is_refused(bridge, state):
    payload = release_payload(f"v{__version__}")
    up = updater(bridge, state, FakeResponse(json.dumps(payload).encode()))
    with pytest.raises(InstallError) as excinfo:
        up.install(lambda _: None)
    assert "already the newest" in str(excinfo.value)


def test_a_release_without_a_bundle_is_a_clear_error(bridge, state):
    payload = release_payload("v99.0.0", asset="source.tar.gz")
    up = updater(bridge, state, FakeResponse(json.dumps(payload).encode()))
    with pytest.raises(InstallError) as excinfo:
        up.install(lambda _: None)
    assert "source.tar.gz" in str(excinfo.value)


def test_install_hands_the_bundle_to_flatpak(bridge, state, tmp_path, monkeypatch):
    from ignis.core import paths

    monkeypatch.setattr(paths, "applications_dir", lambda: tmp_path / "Applications")
    # Not installed in either scope -> falls back to --user.
    bridge.set_result(["flatpak", "info", "--user", APP_ID], returncode=1)
    bridge.set_result(["flatpak", "info", "--system", APP_ID], returncode=1)

    up = SelfUpdater(
        bridge,
        state,
        GithubClient(
            state,
            Recorder(
                FakeResponse(json.dumps(release_payload("v99.0.0")).encode()),
                FakeResponse(b"bundle-bytes"),
            ),
        ),
    )
    lines: list[str] = []
    up.install(lines.append)

    install = next(c for c in bridge.calls if c.argv[1] == "install")
    assert install.argv[:5] == [
        "flatpak", "install", "-y", "--noninteractive", "--user",
    ]
    assert install.argv[5].endswith("ignis.flatpak")
    assert any("restart" in line.lower() for line in lines)


def test_install_uses_the_scope_ignis_is_already_in(bridge, state, tmp_path, monkeypatch):
    """A system-installed Ignis must not sprout a second user copy."""
    from ignis.core import paths

    monkeypatch.setattr(paths, "applications_dir", lambda: tmp_path / "Applications")
    bridge.set_result(["flatpak", "info", "--user", APP_ID], returncode=1)
    bridge.set_result(["flatpak", "info", "--system", APP_ID], returncode=0)

    up = SelfUpdater(
        bridge,
        state,
        GithubClient(
            state,
            Recorder(
                FakeResponse(json.dumps(release_payload("v99.0.0")).encode()),
                FakeResponse(b"bundle-bytes"),
            ),
        ),
    )
    up.install(lambda _: None)

    install = next(c for c in bridge.calls if c.argv[1] == "install")
    assert "--system" in install.argv


def test_failed_bundle_install_reports_the_exit_code(bridge, state, tmp_path, monkeypatch):
    from ignis.core import paths

    monkeypatch.setattr(paths, "applications_dir", lambda: tmp_path / "Applications")
    bridge.set_result(["flatpak", "info", "--user", APP_ID], returncode=1)
    bridge.set_result(["flatpak", "info", "--system", APP_ID], returncode=1)
    bridge.default_returncode = 1

    up = SelfUpdater(
        bridge,
        state,
        GithubClient(
            state,
            Recorder(
                FakeResponse(json.dumps(release_payload("v99.0.0")).encode()),
                FakeResponse(b"bundle-bytes"),
            ),
        ),
    )
    with pytest.raises(InstallError) as excinfo:
        up.install(lambda _: None)
    assert "exit code 1" in str(excinfo.value)


def test_staging_directory_is_cleaned_up(bridge, state, tmp_path, monkeypatch):
    from ignis.core import paths

    apps_dir = tmp_path / "Applications"
    monkeypatch.setattr(paths, "applications_dir", lambda: apps_dir)
    bridge.set_result(["flatpak", "info", "--user", APP_ID], returncode=1)
    bridge.set_result(["flatpak", "info", "--system", APP_ID], returncode=1)

    up = SelfUpdater(
        bridge,
        state,
        GithubClient(
            state,
            Recorder(
                FakeResponse(json.dumps(release_payload("v99.0.0")).encode()),
                FakeResponse(b"bundle-bytes"),
            ),
        ),
    )
    up.install(lambda _: None)
    assert not (apps_dir / ".ignis-update").exists()
