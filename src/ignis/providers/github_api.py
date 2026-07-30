"""GitHub releases API: fetching, ETag caching, and asset selection.

Pure logic (parsing, asset selection) is deliberately separated from I/O so
it can be unit-tested without touching the network. The HTTP entry points
take an injectable ``opener`` for the same reason (CLAUDE.md testing rules).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ignis import __version__
from ignis.core.state import State
from ignis.providers.base import LineCallback, ProviderError

log = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
USER_AGENT = f"Ignis/{__version__} (+https://github.com/rgbcoder001/ignis)"
API_VERSION = "2022-11-28"
REQUEST_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 900
CHUNK_BYTES = 256 * 1024
PROGRESS_STEP_BYTES = 8 * 1024 * 1024


class ReleaseError(ProviderError):
    """A release could not be fetched or understood."""


class RateLimitError(ReleaseError):
    """GitHub's API rate limit was reached."""


@dataclass(frozen=True)
class Asset:
    """One downloadable file attached to a release."""

    name: str
    download_url: str
    size: int = 0


@dataclass(frozen=True)
class Release:
    """A published GitHub release."""

    tag: str
    assets: tuple[Asset, ...] = ()


def parse_release(payload: dict[str, Any]) -> Release:
    """Turn a releases/latest JSON payload into a :class:`Release`."""
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise ReleaseError("GitHub's response contained no release tag")

    assets: list[Asset] = []
    for raw in payload.get("assets") or []:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        url = raw.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        size = raw.get("size")
        assets.append(Asset(name=name, download_url=url, size=size if isinstance(size, int) else 0))

    return Release(tag=tag.strip(), assets=tuple(assets))


def select_asset(release: Release, pattern: str) -> Asset:
    """Pick the one asset matching ``pattern``.

    Zero or multiple matches is a catalog bug, so the error names every
    asset in the release — that is what makes the pattern fixable without
    having to go read the releases page (SPEC.md §4.4).
    """
    matches = [a for a in release.assets if re.search(pattern, a.name, re.IGNORECASE)]
    if len(matches) == 1:
        return matches[0]

    available = ", ".join(a.name for a in release.assets) or "none"
    if not matches:
        raise ReleaseError(
            f"No file in release {release.tag} matches the pattern /{pattern}/. "
            f"Available files: {available}"
        )
    matched = ", ".join(a.name for a in matches)
    raise ReleaseError(
        f"{len(matches)} files in release {release.tag} match the pattern "
        f"/{pattern}/, but it must match exactly one. Matched: {matched}"
    )


def _request(url: str, *, pat: str = "", accept: str) -> urllib.request.Request:
    """Build a GitHub request with the standard headers."""
    request = urllib.request.Request(url)
    request.add_header("Accept", accept)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("X-GitHub-Api-Version", API_VERSION)
    if pat:
        request.add_header("Authorization", f"Bearer {pat}")
    return request


def _default_opener(request: urllib.request.Request, timeout: float):
    """Real network call. Swapped out in tests."""
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https only


Opener = Callable[[urllib.request.Request, float], Any]


class GithubClient:
    """Fetches release metadata, caching responses by ETag in state.json."""

    def __init__(self, state: State, opener: Opener | None = None) -> None:
        self._state = state
        self._opener = opener or _default_opener

    def cached_release(self, repo: str) -> Release | None:
        """The last known release for ``repo`` without touching the network."""
        entry = self._state.cache(repo)
        if entry is None or not entry.payload:
            return None
        try:
            return parse_release(entry.payload)
        except ReleaseError:
            log.warning("cached release for %s is unusable", repo, exc_info=True)
            return None

    def latest_release(self, repo: str) -> Release:
        """Fetch the latest release, reusing the cache when GitHub says 304."""
        entry = self._state.cache(repo)
        request = _request(
            f"{API_ROOT}/repos/{repo}/releases/latest",
            pat=self._state.github_pat,
            accept="application/vnd.github+json",
        )
        if entry is not None and entry.etag:
            request.add_header("If-None-Match", entry.etag)

        try:
            with self._opener(request, REQUEST_TIMEOUT) as response:
                body = response.read()
                etag = response.headers.get("ETag", "") if response.headers else ""
        except urllib.error.HTTPError as exc:
            return self._handle_http_error(exc, repo, entry)
        except urllib.error.URLError as exc:
            raise ReleaseError(f"Could not reach GitHub: {exc.reason}") from exc
        except OSError as exc:
            raise ReleaseError(f"Could not reach GitHub: {exc}") from exc

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ReleaseError(f"GitHub returned an unreadable response for {repo}") from exc
        if not isinstance(payload, dict):
            raise ReleaseError(f"GitHub returned an unexpected response for {repo}")

        release = parse_release(payload)
        if etag:
            self._store_cache(repo, etag, payload)
        return release

    def _handle_http_error(self, exc: urllib.error.HTTPError, repo: str, entry) -> Release:
        """Map an HTTP failure onto a cache hit or a readable error."""
        if exc.code == 304:
            # A 304 body is empty by definition — the cache *is* the response.
            if entry is not None and entry.payload:
                return parse_release(entry.payload)
            raise ReleaseError(
                f"GitHub reported no change for {repo} but nothing was cached"
            ) from exc

        if exc.code in (403, 429) and _is_rate_limited(exc):
            raise RateLimitError(
                "GitHub's API rate limit has been reached. Add a personal access "
                "token in Settings to raise the limit, or try again in a while."
            ) from exc

        if exc.code == 404:
            raise ReleaseError(
                f"{repo} has no published releases, or the repository is private."
            ) from exc

        raise ReleaseError(f"GitHub returned HTTP {exc.code} for {repo}") from exc

    def _store_cache(self, repo: str, etag: str, payload: dict[str, Any]) -> None:
        """Persist the response. A cache write failure must not fail the fetch."""
        self._state.set_cache(repo, etag, payload)
        try:
            self._state.save()
        except OSError:
            log.warning("could not persist the release cache for %s", repo, exc_info=True)


def _is_rate_limited(exc: urllib.error.HTTPError) -> bool:
    """True when a 403/429 is GitHub's rate limiter rather than a permission error."""
    headers = exc.headers
    if headers is None:
        return False
    if headers.get("X-RateLimit-Remaining") == "0":
        return True
    return headers.get("Retry-After") is not None


def download_asset(
    asset: Asset,
    destination: Path,
    on_line: LineCallback,
    *,
    opener: Opener | None = None,
) -> Path:
    """Stream ``asset`` to ``destination`` via a .part file.

    An interrupted download leaves only the .part file behind, never a
    truncated file that looks complete (CLAUDE.md hard rule 7).

    Deliberately sends NO Authorization header, even when the user has set a
    token: browser_download_url redirects to S3, urllib forwards headers
    through redirects, and S3 rejects a request carrying both a signed URL
    and an Authorization header with HTTP 400. Public release downloads need
    no auth; the token exists only to raise the API rate limit.
    """
    open_url = opener or _default_opener
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")

    request = _request(asset.download_url, accept="application/octet-stream")
    total_mb = asset.size / (1024 * 1024) if asset.size else 0

    try:
        with open_url(request, DOWNLOAD_TIMEOUT) as response, partial.open("wb") as handle:
            downloaded = 0
            next_report = PROGRESS_STEP_BYTES
            while True:
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_report:
                    next_report += PROGRESS_STEP_BYTES
                    done_mb = downloaded / (1024 * 1024)
                    suffix = f" of {total_mb:.0f} MB" if total_mb else ""
                    on_line(f"[ignis] downloaded {done_mb:.0f} MB{suffix}")
            handle.flush()
            os.fsync(handle.fileno())
    except (urllib.error.URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise ReleaseError(f"Could not download {asset.name}: {exc}") from exc

    os.replace(partial, destination)
    return destination
