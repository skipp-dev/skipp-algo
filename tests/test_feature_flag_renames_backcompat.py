"""Back-compat contract for the 2026-07-13 feature-flag renames.

Renames (all with deprecated aliases honored for a migration window):
- ``ENABLE_FRESHNESS_V2``  → ``ENABLE_FRESHNESS_V2_SCORE``
- ``ENABLE_REACTION_ZONE`` → split into ``ENABLE_REACTION_ZONE_STUDY``
  (the ``compute_reaction_zone`` reclaim/band study) and
  ``ENABLE_REACTION_CONTEXT`` (the ``detect_reaction_zone`` context detector);
  the old flag still arms BOTH.
- ``REACTION_ZONE_*`` live-dict keys → ``REACTION_CONTEXT_*`` (old keys
  dual-emitted).

Verified across all three flag layers (canonical + the two dependency-neutral
mirrors) so they cannot drift apart.
"""

from __future__ import annotations

import pytest

from open_prep.feature_flags import (
    DEPRECATED_FLAG_ALIASES,
    is_freshness_v2_enabled,
    is_reaction_context_enabled,
    is_reaction_zone_enabled,
    is_reaction_zone_study_enabled,
)
from smc_core import v2_features
from smc_core.reaction_zone import detect_reaction_zone
from smc_integration import measurement_evidence as me

_ALL_FLAGS = (
    "ENABLE_FRESHNESS_V2",
    "ENABLE_FRESHNESS_V2_SCORE",
    "ENABLE_REACTION_ZONE",
    "ENABLE_REACTION_ZONE_STUDY",
    "ENABLE_REACTION_CONTEXT",
)

_BULL_ENR = {
    "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
    "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 1.5, "PRIMARY_OB_SIDE": "BULL"},
    "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in _ALL_FLAGS:
        monkeypatch.delenv(flag, raising=False)


# --- Freshness alias ------------------------------------------------------- #

@pytest.mark.parametrize("flag", ["ENABLE_FRESHNESS_V2_SCORE", "ENABLE_FRESHNESS_V2"])
def test_freshness_new_and_old_names_enable_across_all_layers(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    assert is_freshness_v2_enabled() is False  # baseline (both unset)
    monkeypatch.setenv(flag, "1")
    assert is_freshness_v2_enabled() is True                 # canonical
    assert v2_features.freshness_v2_enabled() is True        # smc_core mirror
    assert me.is_freshness_v2_enabled() is True              # measurement mirror


# --- Reaction split -------------------------------------------------------- #

def test_study_flag_enables_only_study(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_ZONE_STUDY", "1")
    assert is_reaction_zone_study_enabled() is True
    assert is_reaction_context_enabled() is False
    assert v2_features.reaction_zone_study_enabled() is True
    assert v2_features.reaction_context_enabled() is False
    assert me.is_reaction_zone_enabled() is True  # measurement study gate


def test_context_flag_enables_only_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_CONTEXT", "1")
    assert is_reaction_context_enabled() is True
    assert is_reaction_zone_study_enabled() is False
    assert v2_features.reaction_context_enabled() is True
    assert v2_features.reaction_zone_study_enabled() is False
    assert me.is_reaction_zone_enabled() is False  # study must NOT run on context-only


def test_old_flag_arms_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_ZONE", "1")
    assert is_reaction_zone_study_enabled() is True
    assert is_reaction_context_enabled() is True
    assert is_reaction_zone_enabled() is True  # deprecated shim
    assert v2_features.reaction_zone_study_enabled() is True
    assert v2_features.reaction_context_enabled() is True
    assert me.is_reaction_zone_enabled() is True


def test_all_reaction_flags_off_is_neutral() -> None:
    assert is_reaction_zone_study_enabled() is False
    assert is_reaction_context_enabled() is False
    assert is_reaction_zone_enabled() is False
    assert me.is_reaction_zone_enabled() is False


# --- Context detector gating + field dual-emit ----------------------------- #

def test_detector_gated_by_context_not_study(monkeypatch: pytest.MonkeyPatch) -> None:
    # Study flag alone must NOT arm the context detector.
    monkeypatch.setenv("ENABLE_REACTION_ZONE_STUDY", "1")
    assert detect_reaction_zone(enrichment=_BULL_ENR)["REACTION_CONTEXT_DETECTED"] is False


def test_detector_dual_emits_context_and_legacy_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_CONTEXT", "1")
    result = detect_reaction_zone(enrichment=_BULL_ENR)
    # Canonical keys present and detected.
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_DIRECTION"] == "bull"
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 60
    # Legacy keys dual-emitted with identical values.
    for suffix in ("DETECTED", "CONFIDENCE", "DIRECTION"):
        assert result[f"REACTION_ZONE_{suffix}"] == result[f"REACTION_CONTEXT_{suffix}"]


def test_detector_neutral_dual_emits_both_key_families() -> None:
    # Flag off → neutral, both families present.
    result = detect_reaction_zone(enrichment=_BULL_ENR)
    for family in ("REACTION_CONTEXT", "REACTION_ZONE"):
        assert result[f"{family}_DETECTED"] is False
        assert result[f"{family}_CONFIDENCE"] == 0
        assert result[f"{family}_DIRECTION"] == "neutral"


def test_old_flag_also_arms_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_ZONE", "1")
    assert detect_reaction_zone(enrichment=_BULL_ENR)["REACTION_CONTEXT_DETECTED"] is True


# --- Alias registry -------------------------------------------------------- #

def test_deprecated_alias_registry_lists_the_renames() -> None:
    assert DEPRECATED_FLAG_ALIASES["ENABLE_FRESHNESS_V2"] == "ENABLE_FRESHNESS_V2_SCORE"
    assert "ENABLE_REACTION_ZONE" in DEPRECATED_FLAG_ALIASES
