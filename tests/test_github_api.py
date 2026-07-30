"""Release parsing, asset selection, and the ETag-cached client.

No test here touches the network: the client takes an injectable opener.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from ignis.core.state import State
from ignis.providers.github_api import (
    Asset,
    GithubClient,
    RateLimitError,
    ReleaseError,
    download_asset,
    parse_release,
    select_asset,
)

PAYLOAD = {
    "tag_name": "v1.73",
    "assets": [
        {
            "name": "GitHubLauncher-v1.73-Linux-X64.zip",
            "browser_download_url": "https://example.invalid/linux-x64.zip",
            "size": 43670781,
        },
        {
            "name": "GitHubLauncher-v1.73-Linux-ARM64.zip",
            "browser_download_url": "https://example.invalid/linux-arm64.zip",
            "size": 38911854,
        },
        {
            "name": "GitHubLauncher-v1.73-Windows.zip",
            "browser_download_url": "https://example.invalid/windows.zip",
            "size": 40119076,
        },
    ],
}


class FakeResponse:
    """Minimal stand-in for an http.client.HTTPResponse."""

    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._stream = io.BytesIO(body)
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size) if size and size > 0 else self._stream.read()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class Recorder:
    """Captures requests and replays canned responses or errors."""

    def __init__(self, *responses) -> None:
        self.requests: list[urllib.request.Request] = []
        self._responses = list(responses)

    def __call__(self, request: urllib.request.Request, timeout: float):
        self.requests.append(request)
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def http_error(code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.github.com", code, "err", headers or {}, None
    )


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


# -- pure logic --------------------------------------------------------


def test_parse_release_reads_tag_and_assets():
    release = parse_release(PAYLOAD)
    assert release.tag == "v1.73"
    assert len(release.assets) == 3
    assert release.assets[0].size == 43670781


def test_parse_release_without_tag_is_an_error():
    with pytest.raises(ReleaseError):
        parse_release({"assets": []})


def test_parse_release_skips_malformed_assets():
    release = parse_release(
        {"tag_name": "v1", "assets": ["nope", {"name": "x"}, {"browser_download_url": "u"}]}
    )
    assert release.assets == ()


def test_select_asset_picks_the_single_match():
    asset = select_asset(parse_release(PAYLOAD), r"linux-x64\.zip$")
    assert asset.name == "GitHubLauncher-v1.73-Linux-X64.zip"


def test_select_asset_is_case_insensitive():
    """Projects capitalise platform tags inconsistently (SPEC.md §4.4)."""
    asset = select_asset(parse_release(PAYLOAD), r"LINUX-X64\.ZIP$")
    assert asset.name.endswith("Linux-X64.zip")


def test_select_asset_with_no_match_names_the_available_files():
    with pytest.raises(ReleaseError) as excinfo:
        select_asset(parse_release(PAYLOAD), r"\.AppImage$")
    message = str(excinfo.value)
    assert "No file" in message
    assert "GitHubLauncher-v1.73-Windows.zip" in message


def test_select_asset_with_several_matches_is_an_error():
    """An ambiguous pattern is a catalog bug and must be loud."""
    with pytest.raises(ReleaseError) as excinfo:
        select_asset(parse_release(PAYLOAD), r"linux.*\.zip$")
    message = str(excinfo.value)
    assert "exactly one" in message
    assert "ARM64" in message


# -- client ------------------------------------------------------------


def test_fetch_stores_the_etag_and_payload(state):
    opener = Recorder(FakeResponse(json.dumps(PAYLOAD).encode(), {"ETag": 'W/"abc"'}))
    release = GithubClient(state, opener).latest_release("Owner/Repo")

    assert release.tag == "v1.73"
    entry = state.cache("Owner/Repo")
    assert entry is not None
    assert entry.etag == 'W/"abc"'


def test_second_fetch_sends_if_none_match(state):
    opener = Recorder(
        FakeResponse(json.dumps(PAYLOAD).encode(), {"ETag": 'W/"abc"'}),
        http_error(304),
    )
    client = GithubClient(state, opener)
    client.latest_release("Owner/Repo")
    release = client.latest_release("Owner/Repo")

    assert release.tag == "v1.73"
    assert opener.requests[1].get_header("If-none-match") == 'W/"abc"'


def test_304_without_a_cached_payload_is_an_error(state):
    """Never silently succeed with nothing to return."""
    opener = Recorder(http_error(304))
    with pytest.raises(ReleaseError):
        GithubClient(state, opener).latest_release("Owner/Repo")


def test_rate_limit_suggests_a_token(state):
    opener = Recorder(http_error(403, {"X-RateLimit-Remaining": "0"}))
    with pytest.raises(RateLimitError) as excinfo:
        GithubClient(state, opener).latest_release("Owner/Repo")
    assert "token" in str(excinfo.value).lower()


def test_plain_403_is_not_reported_as_a_rate_limit(state):
    opener = Recorder(http_error(403, {"X-RateLimit-Remaining": "58"}))
    with pytest.raises(ReleaseError) as excinfo:
        GithubClient(state, opener).latest_release("Owner/Repo")
    assert not isinstance(excinfo.value, RateLimitError)


def test_404_explains_there_are_no_releases(state):
    opener = Recorder(http_error(404))
    with pytest.raises(ReleaseError) as excinfo:
        GithubClient(state, opener).latest_release("Owner/Repo")
    assert "no published releases" in str(excinfo.value)


def test_network_failure_is_reported_not_crashed(state):
    opener = Recorder(urllib.error.URLError("no route to host"))
    with pytest.raises(ReleaseError) as excinfo:
        GithubClient(state, opener).latest_release("Owner/Repo")
    assert "Could not reach GitHub" in str(excinfo.value)


def test_unreadable_json_is_reported(state):
    opener = Recorder(FakeResponse(b"<html>not json</html>", {"ETag": "x"}))
    with pytest.raises(ReleaseError):
        GithubClient(state, opener).latest_release("Owner/Repo")


def test_token_is_sent_when_set(state):
    state.github_pat = "ghp_secret"
    opener = Recorder(FakeResponse(json.dumps(PAYLOAD).encode()))
    GithubClient(state, opener).latest_release("Owner/Repo")
    assert opener.requests[0].get_header("Authorization") == "Bearer ghp_secret"


def test_no_authorization_header_without_a_token(state):
    opener = Recorder(FakeResponse(json.dumps(PAYLOAD).encode()))
    GithubClient(state, opener).latest_release("Owner/Repo")
    assert opener.requests[0].get_header("Authorization") is None


def test_cached_release_needs_no_network(state):
    state.set_cache("Owner/Repo", "etag", PAYLOAD)
    client = GithubClient(state, Recorder())  # would IndexError if called
    assert client.cached_release("Owner/Repo").tag == "v1.73"


def test_cached_release_is_none_when_empty(state):
    assert GithubClient(state, Recorder()).cached_release("Owner/Repo") is None


# -- download ----------------------------------------------------------


def test_download_writes_the_file_and_leaves_no_part(tmp_path):
    asset = Asset(name="x.zip", download_url="https://example.invalid/x.zip", size=4)
    opener = Recorder(FakeResponse(b"data"))
    target = tmp_path / "x.zip"

    download_asset(asset, target, lambda _l: None, opener=opener)

    assert target.read_bytes() == b"data"
    assert list(tmp_path.iterdir()) == [target]


def test_download_never_sends_an_authorization_header(tmp_path):
    """browser_download_url redirects to S3, and urllib forwards headers
    through redirects; S3 rejects a signed URL arriving with an Authorization
    header (HTTP 400). So even with a token configured for API calls, the
    download request itself must carry no auth."""
    asset = Asset(name="x.zip", download_url="https://example.invalid/x.zip", size=4)
    opener = Recorder(FakeResponse(b"data"))

    download_asset(asset, tmp_path / "x.zip", lambda _l: None, opener=opener)

    assert opener.requests[0].get_header("Authorization") is None


def test_failed_download_leaves_no_partial_file(tmp_path):
    """An interrupted download must never leave something that looks complete."""
    asset = Asset(name="x.zip", download_url="https://example.invalid/x.zip")
    opener = Recorder(urllib.error.URLError("connection reset"))
    target = tmp_path / "x.zip"

    with pytest.raises(ReleaseError):
        download_asset(asset, target, lambda _l: None, opener=opener)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
