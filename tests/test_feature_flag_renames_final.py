"""Post-migration contract: the 2026-07-13 flag renames are FINAL.

The deprecation window closed the same day (the old names/keys were verified
unset in every Railway service and had no consumer), so the back-compat aliases
were dropped. This pins that:

- the OLD env names (``ENABLE_FRESHNESS_V2``, ``ENABLE_REACTION_ZONE``) are no
  longer honored — setting them enables nothing;
- the NEW names work across all three flag layers;
- study vs context stay independently gated;
- ``detect_reaction_zone`` emits ONLY ``REACTION_CONTEXT_*`` (the legacy
  ``REACTION_ZONE_*`` dual-emit is gone).
"""

from __future__ import annotations

import pytest

from open_prep.feature_flags import (
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


# --- Old names are no longer honored --------------------------------------- #

def test_old_freshness_name_is_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_FRESHNESS_V2", "1")  # deprecated → ignored
    assert is_freshness_v2_enabled() is False
    assert v2_features.freshness_v2_enabled() is False
    assert me.is_freshness_v2_enabled() is False


def test_old_reaction_zone_name_is_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_ZONE", "1")  # deprecated → ignored
    assert is_reaction_zone_study_enabled() is False
    assert is_reaction_context_enabled() is False
    assert is_reaction_zone_enabled() is False
    assert v2_features.reaction_zone_study_enabled() is False
    assert v2_features.reaction_context_enabled() is False
    assert me.is_reaction_zone_enabled() is False
    # And it no longer arms the detector.
    assert detect_reaction_zone(enrichment=_BULL_ENR)["REACTION_CONTEXT_DETECTED"] is False


# --- New names work across all three layers -------------------------------- #

def test_new_freshness_name_enables_across_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_FRESHNESS_V2_SCORE", "1")
    assert is_freshness_v2_enabled() is True
    assert v2_features.freshness_v2_enabled() is True
    assert me.is_freshness_v2_enabled() is True


def test_study_flag_enables_only_study(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_ZONE_STUDY", "1")
    assert is_reaction_zone_study_enabled() is True
    assert is_reaction_context_enabled() is False
    assert v2_features.reaction_zone_study_enabled() is True
    assert v2_features.reaction_context_enabled() is False
    assert me.is_reaction_zone_enabled() is True  # measurement study gate
    # Study alone must NOT arm the context detector.
    assert detect_reaction_zone(enrichment=_BULL_ENR)["REACTION_CONTEXT_DETECTED"] is False


def test_context_flag_enables_only_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_CONTEXT", "1")
    assert is_reaction_context_enabled() is True
    assert is_reaction_zone_study_enabled() is False
    assert me.is_reaction_zone_enabled() is False  # study must not run on context-only
    assert detect_reaction_zone(enrichment=_BULL_ENR)["REACTION_CONTEXT_DETECTED"] is True


# --- Legacy field keys are gone -------------------------------------------- #

def test_detector_emits_only_context_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_CONTEXT", "1")
    result = detect_reaction_zone(enrichment=_BULL_ENR)
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_DIRECTION"] == "bull"
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 60
    # The legacy dual-emit is gone.
    for suffix in ("DETECTED", "CONFIDENCE", "DIRECTION"):
        assert f"REACTION_ZONE_{suffix}" not in result


def test_detector_neutral_has_only_context_keys() -> None:
    result = detect_reaction_zone(enrichment=_BULL_ENR)  # flag off → neutral
    assert result["REACTION_CONTEXT_DETECTED"] is False
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 0
    assert result["REACTION_CONTEXT_DIRECTION"] == "neutral"
    for suffix in ("DETECTED", "CONFIDENCE", "DIRECTION"):
        assert f"REACTION_ZONE_{suffix}" not in result
