"""Catalog loading: parses data/catalog.toml into validated dataclasses.

A malformed entry is logged and skipped — one bad entry must never take
down the app (CLAUDE.md hard rule 8).
"""

from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

log = logging.getLogger(__name__)

ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REPO_PATTERN = re.compile(r"[\w.-]+/[\w.-]+")

#: GPU vendors an app may be restricted to.
VENDORS = frozenset({"amd", "nvidia", "intel"})


class Category(StrEnum):
    """Catalog categories, in display order."""

    GAMING = "gaming"
    EMULATION = "emulation"
    MEDIA = "media"
    STREAMING = "streaming"
    COMMUNICATION = "communication"
    SYSTEM = "system"


class InstallKind(StrEnum):
    """How a GitHub release asset is installed."""

    APPIMAGE = "appimage"
    TARBALL = "tarball"
    ZIP = "zip"


class CatalogError(Exception):
    """The catalog file itself could not be read or parsed."""


class EntryError(Exception):
    """A single catalog entry is invalid and will be skipped."""


@dataclass(frozen=True)
class FlathubSource:
    """Installs a Flatpak from Flathub."""

    ref: str
    type: str = "flathub"


@dataclass(frozen=True)
class UjustSource:
    """Runs one of Bazzite's built-in ujust recipes.

    Bazzite recipes take an action argument (``status | install | uninstall``,
    or for some recipes ``enable | disable``). Called with no argument they
    drop into an interactive menu that needs a terminal, which Ignis cannot
    answer — so ``args`` is how a catalog entry stays unattended.
    """

    recipe: str
    args: tuple[str, ...] = ()
    uninstall_args: tuple[str, ...] | None = None
    check_cmd: tuple[str, ...] | None = None
    type: str = "ujust"


@dataclass(frozen=True)
class GithubSource:
    """Installs an asset from a GitHub release."""

    repo: str
    asset_pattern: str
    install_kind: InstallKind
    type: str = "github"

    def matches(self, asset_name: str) -> bool:
        """True if ``asset_name`` matches this source's asset pattern.

        Case-insensitive per SPEC.md §4.4 — release asset names capitalise
        platform tags inconsistently between projects and even between
        releases of the same project.
        """
        return re.search(self.asset_pattern, asset_name, re.IGNORECASE) is not None


@dataclass(frozen=True)
class ScriptSource:
    """Runs a vetted shell script bundled with Ignis."""

    file: str
    check_cmd: tuple[str, ...] | None = None
    type: str = "script"


Source = FlathubSource | UjustSource | GithubSource | ScriptSource


@dataclass(frozen=True)
class App:
    """One installable entry in the catalog."""

    id: str
    name: str
    summary: str
    source: Source
    description: str = ""
    category: Category = Category.SYSTEM
    hardware: frozenset[str] = field(default_factory=frozenset)
    icon: str | None = None
    post_install: str | None = None

    def supports(self, vendors: frozenset[str]) -> bool:
        """True if this app applies to the detected GPU vendors.

        An app with no hardware restriction always applies; so does any app
        when detection found nothing (never hide the catalog).
        """
        if not self.hardware or not vendors:
            return True
        return bool(self.hardware & vendors)


def load_catalog(path: Path) -> list[App]:
    """Read and validate a catalog file. Raises :class:`CatalogError`."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CatalogError(f"Could not read catalog at {path}: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise CatalogError(f"Could not parse catalog at {path}: {exc}") from exc
    return parse_catalog(data)


def parse_catalog(data: dict[str, Any]) -> list[App]:
    """Validate parsed TOML into apps, skipping (and logging) bad entries."""
    entries = data.get("apps")
    if not isinstance(entries, list):
        raise CatalogError("Catalog has no [[apps]] entries")

    apps: list[App] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        try:
            app = _parse_app(entry)
        except EntryError as exc:
            log.warning("skipping catalog entry %d: %s", index, exc)
            continue
        if app.id in seen:
            log.warning("skipping catalog entry %d: duplicate id %r", index, app.id)
            continue
        seen.add(app.id)
        apps.append(app)

    log.info("loaded %d apps (%d entries in file)", len(apps), len(entries))
    return apps


def _parse_app(entry: Any) -> App:
    """Validate one [[apps]] table."""
    if not isinstance(entry, dict):
        raise EntryError("entry is not a table")

    app_id = _require_str(entry, "id")
    if not ID_PATTERN.fullmatch(app_id):
        raise EntryError(f"id {app_id!r} is not kebab-case")

    category_value = _require_str(entry, "category")
    try:
        category = Category(category_value)
    except ValueError:
        raise EntryError(f"unknown category {category_value!r}") from None

    hardware = _parse_hardware(entry.get("hardware", []))
    source = _parse_source(entry.get("source"))

    return App(
        id=app_id,
        name=_require_str(entry, "name"),
        summary=_require_str(entry, "summary"),
        description=_optional_str(entry, "description") or "",
        category=category,
        hardware=hardware,
        icon=_optional_str(entry, "icon"),
        post_install=_optional_str(entry, "post_install"),
        source=source,
    )


def _parse_hardware(value: Any) -> frozenset[str]:
    """Validate the hardware vendor restriction list."""
    if not isinstance(value, list):
        raise EntryError("hardware must be a list")
    vendors = set()
    for item in value:
        if not isinstance(item, str) or item not in VENDORS:
            raise EntryError(f"unknown hardware vendor {item!r}")
        vendors.add(item)
    return frozenset(vendors)


def _parse_source(value: Any) -> Source:
    """Validate the [apps.source] table."""
    if not isinstance(value, dict):
        raise EntryError("missing [apps.source] table")
    source_type = _require_str(value, "type")

    if source_type == "flathub":
        return FlathubSource(ref=_require_str(value, "ref"))

    if source_type == "ujust":
        return UjustSource(
            recipe=_require_str(value, "recipe"),
            args=_parse_args(value.get("args")),
            uninstall_args=_parse_check_cmd(value.get("uninstall_args")),
            check_cmd=_parse_check_cmd(value.get("check_cmd")),
        )

    if source_type == "github":
        repo = _require_str(value, "repo")
        if not REPO_PATTERN.fullmatch(repo):
            raise EntryError(f"repo {repo!r} is not in owner/name form")
        pattern = _require_str(value, "asset_pattern")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise EntryError(f"asset_pattern is not a valid regex: {exc}") from None
        kind_value = _require_str(value, "install_kind")
        try:
            kind = InstallKind(kind_value)
        except ValueError:
            raise EntryError(f"unknown install_kind {kind_value!r}") from None
        return GithubSource(repo=repo, asset_pattern=pattern, install_kind=kind)

    if source_type == "script":
        script = _require_str(value, "file")
        # Catalog paths are always POSIX, whatever OS is doing the validating —
        # Path("/x").is_absolute() is False on Windows and would let this through.
        script_path = PurePosixPath(script)
        if script_path.is_absolute() or ".." in script_path.parts or "\\" in script:
            raise EntryError(f"script file {script!r} must be a bundled relative path")
        return ScriptSource(
            file=script, check_cmd=_parse_check_cmd(value.get("check_cmd"))
        )

    raise EntryError(f"unknown source type {source_type!r}")


def _parse_args(value: Any) -> tuple[str, ...]:
    """Validate an optional argument list, defaulting to no arguments."""
    if value is None:
        return ()
    return _parse_check_cmd(value) or ()


def _parse_check_cmd(value: Any) -> tuple[str, ...] | None:
    """Validate an optional status-probe command."""
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise EntryError("check_cmd must be a non-empty list")
    if not all(isinstance(item, str) for item in value):
        raise EntryError("check_cmd must contain only strings")
    return tuple(value)


def _require_str(entry: dict[str, Any], key: str) -> str:
    """Fetch a required non-empty string field."""
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EntryError(f"missing or empty {key!r}")
    return value.strip()


def _optional_str(entry: dict[str, Any], key: str) -> str | None:
    """Fetch an optional string field."""
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise EntryError(f"{key!r} must be a string")
    return value.strip() or None
