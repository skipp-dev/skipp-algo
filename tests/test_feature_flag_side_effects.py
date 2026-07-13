"""Truth pins for feature-flag side effects documented in the flag docstrings.

A flag-semantics audit found docstrings that undersold live side effects:

- ``ENABLE_FRESHNESS_V2_SCORE`` is not a scoped freshness toggle — being a member of
  ``any_v2_score_feature_enabled`` it routes ``build_signal_quality`` from the
  v1 to the v2 budget, so the numeric score moves even with neutral freshness.
- ``ENABLE_REACTION_CONTEXT`` also gates ``detect_reaction_zone`` (a semantically
  different "reaction context" detector), not only the reclaim/band study.
- ``smc_integration.measurement_evidence.signal_quality_model`` must normalise
  ``SIGNAL_QUALITY_MODEL`` identically to the canonical
  ``open_prep.feature_flags.signal_quality_model`` (it previously only
  ``.strip()``-ed, so ``"V2"`` diverged).

These fail if a docstring reverts or the mirrors drift apart.
"""

from __future__ import annotations

import pytest

from open_prep.feature_flags import (
    any_v2_score_feature_enabled,
    is_freshness_v2_enabled,
    is_reaction_context_enabled,
    is_reaction_zone_enabled,
    is_reaction_zone_study_enabled,
)
from open_prep.feature_flags import (
    signal_quality_model as canonical_model,
)
from scripts.smc_signal_quality import (
    build_signal_quality,
    build_signal_quality_v1,
    build_signal_quality_v2,
)
from smc_integration.measurement_evidence import (
    signal_quality_model as measurement_model,
)

_RAW = "SIGNAL_QUALITY_SCORE"
# Structure-only enrichment: NO freshness fields (freshness is neutral), so any
# score difference between the models is purely the budget re-weight.
_ENR = {
    "structure_state_light": {
        "STRUCTURE_LAST_EVENT": "BOS_BULL",
        "STRUCTURE_FRESH": True,
        "STRUCTURE_EVENT_AGE_BARS": 0,
    }
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from a known-off flag state for every test."""
    monkeypatch.delenv("SIGNAL_QUALITY_MODEL", raising=False)
    for flag in (
        "ENABLE_FRESHNESS_V2_SCORE",
        "ENABLE_CONFLUENCE_SCORE",
        "ENABLE_SWEEP_TRAP",
        "ENABLE_REACTION_CONTEXT",
        "ENABLE_SMT_DIVERGENCE",
    ):
        monkeypatch.delenv(flag, raising=False)


# --- F1: ENABLE_FRESHNESS_V2_SCORE is a v2 score-model cutover -------------------- #

def test_freshness_v2_flag_routes_model_and_moves_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With all flags off the router picks v1.
    assert any_v2_score_feature_enabled() is False
    v1 = build_signal_quality_v1(enrichment=_ENR)[_RAW]
    v2 = build_signal_quality_v2(enrichment=_ENR)[_RAW]
    assert v1 != v2, "v1/v2 budgets must differ for this enrichment to be a valid probe"
    assert build_signal_quality(enrichment=_ENR)[_RAW] == v1

    # Turning ONLY freshness on (SIGNAL_QUALITY_MODEL still 'v1') flips the model.
    monkeypatch.setenv("ENABLE_FRESHNESS_V2_SCORE", "1")
    assert any_v2_score_feature_enabled() is True
    routed = build_signal_quality(enrichment=_ENR)
    assert routed[_RAW] == v2, "freshness flag must route build_signal_quality to the v2 budget"
    assert routed[_RAW] != v1, "the numeric score must change even with neutral freshness data"


def test_freshness_v2_docstring_discloses_model_cutover() -> None:
    doc = is_freshness_v2_enabled.__doc__ or ""
    assert "score-model" in doc
    assert "any_v2_score_feature_enabled" in doc
    # Names the re-weight so the side effect is unambiguous.
    assert "20→18" in doc or "15→12" in doc


# --- F2: reaction zone split into study + context -------------------------- #

def test_reaction_zone_flag_is_split_into_study_and_context() -> None:
    # The dual-feature is resolved: two distinct canonical flags, and the
    # old convenience reader delegates to them.
    study_doc = is_reaction_zone_study_enabled.__doc__ or ""
    ctx_doc = is_reaction_context_enabled.__doc__ or ""
    assert "ENABLE_REACTION_ZONE_STUDY" in study_doc
    assert "compute_reaction_zone" in study_doc
    assert "ENABLE_REACTION_CONTEXT" in ctx_doc
    assert "detect_reaction_zone" in ctx_doc
    # The old single reader is now a thin convenience over the two split readers.
    shim_doc = is_reaction_zone_enabled.__doc__ or ""
    assert "is_reaction_zone_study_enabled" in shim_doc
    assert "is_reaction_context_enabled" in shim_doc


# --- F4: measurement mirror normalises SIGNAL_QUALITY_MODEL like canonical -- #

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("v1", "v1"),
        ("v2", "v2"),
        ("v2.1", "v2.1"),
        ("V2", "v2"),          # uppercase — previously diverged (only .strip())
        (" v2.1 ", "v2.1"),    # surrounding whitespace
        ("V1", "v1"),
        ("garbage", "v1"),     # invalid → validated fallback
        ("", "v1"),            # empty → default
    ],
)
def test_measurement_model_matches_canonical(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("SIGNAL_QUALITY_MODEL", raw)
    assert measurement_model() == expected
    assert measurement_model() == canonical_model()


def test_measurement_model_defaults_to_v1_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SIGNAL_QUALITY_MODEL", raising=False)
    assert measurement_model() == "v1"
    assert measurement_model() == canonical_model()
