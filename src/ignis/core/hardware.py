"""GPU vendor detection by reading sysfs.

Detection failure is never fatal: an empty result means "show everything"
rather than hiding the catalog.
"""

from __future__ import annotations

import logging
import re
from enum import StrEnum
from pathlib import Path

log = logging.getLogger(__name__)

DRM_PATH = "sys/class/drm"

#: PCI vendor id -> vendor name used in catalog `hardware` lists.
VENDOR_IDS = {
    "0x1002": "amd",
    "0x1022": "amd",
    "0x10de": "nvidia",
    "0x8086": "intel",
}

# Only card devices; cardN-HDMI-A-1 and friends are connectors, not GPUs.
CARD_PATTERN = re.compile(r"card\d+")

#: Human-readable labels for badges.
VENDOR_LABELS = {"amd": "AMD", "nvidia": "NVIDIA", "intel": "Intel"}


def detect_gpu_vendors(root: Path | None = None) -> frozenset[str]:
    """Return the set of GPU vendors present, e.g. ``{"amd", "intel"}``.

    ``root`` overrides the filesystem root (for tests). Returns an empty set
    if nothing could be detected.
    """
    drm_dir = (root or Path("/")) / DRM_PATH
    vendors: set[str] = set()
    try:
        cards = sorted(drm_dir.iterdir())
    except OSError:
        log.info("no DRM devices found at %s — skipping GPU detection", drm_dir)
        return frozenset()

    for card in cards:
        if not CARD_PATTERN.fullmatch(card.name):
            continue
        vendor_id = _read_vendor_id(card / "device" / "vendor")
        if vendor_id is None:
            continue
        vendor = VENDOR_IDS.get(vendor_id)
        if vendor is None:
            log.info("unrecognised GPU vendor id %s at %s", vendor_id, card)
            continue
        vendors.add(vendor)

    log.info("detected GPU vendors: %s", ", ".join(sorted(vendors)) or "none")
    return frozenset(vendors)


def _read_vendor_id(path: Path) -> str | None:
    """Read a sysfs PCI vendor id, or None if unreadable."""
    try:
        return path.read_text(encoding="utf-8").strip().lower()
    except (OSError, UnicodeDecodeError):
        log.debug("could not read vendor id at %s", path, exc_info=True)
        return None


def label(vendor: str) -> str:
    """Human-readable label for a vendor key."""
    return VENDOR_LABELS.get(vendor, vendor.upper())


class BadgeState(StrEnum):
    """How a hardware badge relates to the machine Ignis is running on."""

    MATCHED = "matched"
    UNMATCHED = "unmatched"
    UNKNOWN = "unknown"


#: libadwaita style class per badge state.
BADGE_STYLES = {
    BadgeState.MATCHED: "accent",
    BadgeState.UNMATCHED: "warning",
    BadgeState.UNKNOWN: "dim-label",
}


def badge_state(vendor: str, vendors: frozenset[str]) -> BadgeState:
    """Whether ``vendor`` matches the detected GPUs.

    An empty ``vendors`` means detection failed rather than "no match" — the
    badge is shown neutrally instead of warning about hardware we never
    actually looked at.
    """
    if not vendors:
        return BadgeState.UNKNOWN
    return BadgeState.MATCHED if vendor in vendors else BadgeState.UNMATCHED


def badge_tooltip(vendor: str, state: BadgeState) -> str:
    """Plain-language explanation of a hardware badge.

    Never says "incompatible": detection can be wrong, and the app stays
    installable either way (SPEC.md §4.5).
    """
    name = label(vendor)
    if state is BadgeState.MATCHED:
        return f"Made for {name} graphics, which is what this system has."
    if state is BadgeState.UNMATCHED:
        return (
            f"Made for {name} graphics, which wasn't detected on this system. "
            "You can still install it."
        )
    return f"Made for {name} graphics. Ignis couldn't detect your graphics card."
