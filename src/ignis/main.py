"""Entry point: ``python -m ignis``.

``gi`` is imported lazily so that ``--self-check`` still works on a machine
where the GTK stack is missing or broken.
"""

from __future__ import annotations

import argparse
import logging
import sys

from ignis import __version__
from ignis.core import paths
from ignis.core.catalog import App, CatalogError, load_catalog
from ignis.core.hardware import detect_gpu_vendors
from ignis.core.host import HostBridge
from ignis.core.log import setup_logging

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Run Ignis. Returns a process exit code."""
    args = _parse_args(argv)
    log_path = setup_logging(
        paths.log_file(), level=logging.DEBUG if args.debug else logging.INFO
    )
    log.info("Ignis %s starting (flatpak=%s)", __version__, HostBridge.in_flatpak())
    if log_path:
        log.info("logging to %s", log_path)

    apps = _load_apps()
    vendors = detect_gpu_vendors()
    bridge = HostBridge()

    if args.self_check:
        return _self_check(apps, vendors, bridge)

    try:
        from ignis.app import IgnisApplication
    except ImportError:
        log.exception("could not import the GTK stack")
        print(
            "Ignis could not start because GTK 4 / libadwaita Python bindings "
            "(PyGObject) are not available.\n"
            "This is expected on Windows — Ignis is a Linux application.\n"
            "Run 'python -m ignis --self-check' to verify the non-GUI parts.",
            file=sys.stderr,
        )
        return 1

    return IgnisApplication(apps, bridge, vendors).run([])


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(prog="ignis", description="App installer for Bazzite")
    parser.add_argument("--version", action="version", version=f"Ignis {__version__}")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="print environment diagnostics without starting the GUI",
    )
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    return parser.parse_args(argv)


def _load_apps() -> list[App]:
    """Load the catalog, degrading to an empty list on failure."""
    try:
        return load_catalog(paths.catalog_path())
    except CatalogError:
        log.exception("could not load the catalog")
        return []


def _self_check(apps: list[App], vendors: frozenset[str], bridge: HostBridge) -> int:
    """Print diagnostics — the fastest way to triage a machine."""
    print(f"Ignis {__version__}")
    print(f"  data dir:      {paths.data_dir()}")
    print(f"  catalog:       {len(apps)} apps loaded from {paths.catalog_path()}")
    print(f"  GPU vendors:   {', '.join(sorted(vendors)) or 'none detected'}")
    print(f"  in flatpak:    {HostBridge.in_flatpak()}")
    print(f"  host spawn:    {bridge.uses_host_spawn}")

    result = bridge.run(["flatpak", "--version"], check=False)
    status = "OK" if result.ok else f"FAILED (exit {result.returncode})"
    print(f"  host command:  {status} — {result.command}")
    for line in result.output.splitlines():
        print(f"      {line}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
