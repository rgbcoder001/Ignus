"""The catalog we ship must parse with nothing skipped."""

from __future__ import annotations

import tomllib

from ignis.core import paths
from ignis.core.catalog import Category, load_catalog


def test_shipped_catalog_loads_completely():
    path = paths.catalog_path()
    raw_count = len(tomllib.loads(path.read_text(encoding="utf-8"))["apps"])
    apps = load_catalog(path)
    assert len(apps) == raw_count, "some shipped catalog entries were skipped"


def test_shipped_catalog_has_content_in_every_category():
    apps = load_catalog(paths.catalog_path())
    covered = {app.category for app in apps}
    assert covered == set(Category)


def test_shipped_catalog_ids_are_unique():
    apps = load_catalog(paths.catalog_path())
    ids = [app.id for app in apps]
    assert len(ids) == len(set(ids))
