"""Hardware badge state and wording (SPEC.md §4.5)."""

from __future__ import annotations

import pytest

from ignis.core.hardware import BADGE_STYLES, BadgeState, badge_state, badge_tooltip

AMD = frozenset({"amd"})
HYBRID = frozenset({"intel", "nvidia"})
NONE = frozenset()


def test_badge_matches_detected_vendor():
    assert badge_state("amd", AMD) is BadgeState.MATCHED


def test_badge_warns_when_vendor_is_absent():
    assert badge_state("amd", HYBRID) is BadgeState.UNMATCHED


def test_badge_matches_either_gpu_on_a_hybrid_machine():
    assert badge_state("intel", HYBRID) is BadgeState.MATCHED
    assert badge_state("nvidia", HYBRID) is BadgeState.MATCHED


def test_failed_detection_is_unknown_not_a_mismatch():
    """An empty set means we never looked, so don't warn about hardware."""
    assert badge_state("amd", NONE) is BadgeState.UNKNOWN


@pytest.mark.parametrize("state", list(BadgeState))
def test_every_state_has_a_style_and_tooltip(state):
    assert BADGE_STYLES[state]
    assert badge_tooltip("amd", state)


def test_mismatch_wording_stays_installable_not_incompatible():
    """Detection can be wrong, so the app must never be described as blocked."""
    text = badge_tooltip("amd", BadgeState.UNMATCHED)
    assert "still install" in text
    assert "incompatible" not in text.lower()


def test_tooltips_use_friendly_vendor_names():
    assert "NVIDIA" in badge_tooltip("nvidia", BadgeState.MATCHED)
