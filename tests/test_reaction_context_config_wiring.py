"""Truth pins for the reaction-context config surface (findings 6 + 7).

F6 — ``SMC_REACTION_ZONE_*`` was renamed ``SMC_REACTION_CONTEXT_*`` because the
config only drives the ``detect_reaction_zone`` context detector, NOT the
canonical ``compute_reaction_zone`` geometry (which is hard-coded). The renamed
env vars must actually change the detector output, and the old names must be
dead (clean cutover).

F7 — reaction context is observe-only: enabling it must not move
``SIGNAL_QUALITY_SCORE``.
"""

from __future__ import annotations

import pytest

from scripts.smc_signal_quality import build_signal_quality
from smc_core.reaction_zone import detect_reaction_zone

# Bias-aligned bullish context (OB within the 3% default distance).
_CTX_ENR = {
    "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
    "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 1.5, "PRIMARY_OB_SIDE": "BULL"},
    "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
}


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "ENABLE_REACTION_CONTEXT",
        "SIGNAL_QUALITY_MODEL",
        "SMC_REACTION_CONTEXT_BIAS_ALIGNED_CONFIDENCE",
        "SMC_REACTION_ZONE_BIAS_ALIGNED_CONFIDENCE",
    ):
        monkeypatch.delenv(k, raising=False)


# --- F6: renamed env var drives the detector -------------------------------- #

def test_new_context_confidence_env_changes_detector_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_REACTION_CONTEXT", "1")
    monkeypatch.setenv("SMC_REACTION_CONTEXT_BIAS_ALIGNED_CONFIDENCE", "77")
    result = detect_reaction_zone(enrichment=_CTX_ENR)
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 77  # renamed env var is wired


def test_old_reaction_zone_config_name_is_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REACTION_CONTEXT", "1")
    # Old pre-rename env var must have NO effect (default 60 stands).
    monkeypatch.setenv("SMC_REACTION_ZONE_BIAS_ALIGNED_CONFIDENCE", "77")
    result = detect_reaction_zone(enrichment=_CTX_ENR)
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 60


# --- F7: reaction context is observe-only ----------------------------------- #

def test_reaction_context_does_not_move_the_score(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_QUALITY_MODEL", "v2")
    monkeypatch.delenv("ENABLE_REACTION_CONTEXT", raising=False)
    score_off = build_signal_quality(enrichment=_CTX_ENR)["SIGNAL_QUALITY_SCORE"]

    monkeypatch.setenv("ENABLE_REACTION_CONTEXT", "1")
    out_on = build_signal_quality(enrichment=_CTX_ENR)
    # The detector fired (fields appended) …
    assert out_on["REACTION_CONTEXT_DETECTED"] is True
    # … but the score is byte-identical: observe-only, no weight.
    assert out_on["SIGNAL_QUALITY_SCORE"] == score_off
