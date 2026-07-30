"""Release-tag comparison for update checks."""

from __future__ import annotations

import pytest

from ignis.core.version import is_newer, parse_version


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.1.2", (0, 1, 2)),
        ("v0.1.2", (0, 1, 2)),
        ("V1.0", (1, 0)),
        ("1.2.3.4", (1, 2, 3, 4)),
        ("2", (2,)),
        ("1.2.0-beta1", (1, 2, 0)),
        ("v1.73", (1, 73)),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "latest", "v", "nightly"])
def test_unparseable_versions_are_empty(text):
    assert parse_version(text) == ()


def test_detects_a_newer_release():
    assert is_newer("v0.1.3", "0.1.2")
    assert is_newer("v0.2.0", "0.1.9")
    assert is_newer("v1.0.0", "0.9.9")


def test_same_version_is_not_newer():
    assert not is_newer("v0.1.2", "0.1.2")


def test_older_release_is_not_newer():
    assert not is_newer("v0.1.1", "0.1.2")


def test_shorter_tag_compares_correctly():
    assert is_newer("v1.1", "1.0.9")
    assert not is_newer("v1.0", "1.0.1")


@pytest.mark.parametrize(
    ("candidate", "current"), [("latest", "0.1.2"), ("v0.1.3", "unknown")]
)
def test_unparseable_never_claims_an_update(candidate, current):
    """A tag we don't understand must not produce a spurious update prompt."""
    assert not is_newer(candidate, current)
