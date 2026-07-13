"""Truth pins for dead / inert v2 config surfaces (2026-07-13 audit).

- ``SMC_CONFLUENCE_POINTS_PER_SIGNAL`` / ``ConfluenceScoreConfig`` was removed
  (RESERVED/UNWIRED — read nowhere).
- ``SIGNAL_QUALITY_MODEL=v2.1`` is an alias for ``v2`` (no distinct model).
- ``ENABLE_SMT_DIVERGENCE`` / ``SMC_SMT_DIVERGENCE_CONFIDENCE`` are productively
  inert: the detector returns neutral for every production event because no
  producer builds ``correlated_context``.
"""

from __future__ import annotations

import pytest

from scripts.smc_signal_quality import build_signal_quality
from smc_core import smt_divergence, v2_config

_ENR = {
    "structure_state_light": {
        "STRUCTURE_LAST_EVENT": "BOS_BULL",
        "STRUCTURE_FRESH": True,
        "STRUCTURE_EVENT_AGE_BARS": 0,
    },
    "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
    "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 1.5, "PRIMARY_OB_SIDE": "BULL"},
}


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("SIGNAL_QUALITY_MODEL", "ENABLE_SMT_DIVERGENCE", "SMC_SMT_DIVERGENCE_CONFIDENCE"):
        monkeypatch.delenv(k, raising=False)


# --- F1: dead confluence knob removed -------------------------------------- #

def test_confluence_points_per_signal_config_is_gone() -> None:
    assert not hasattr(v2_config, "confluence_score_config")
    assert not hasattr(v2_config, "ConfluenceScoreConfig")


# --- F4: v2.1 is a byte-identical alias for v2 ----------------------------- #

def test_v2_1_is_alias_for_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_QUALITY_MODEL", "v2")
    out_v2 = build_signal_quality(enrichment=_ENR)
    monkeypatch.setenv("SIGNAL_QUALITY_MODEL", "v2.1")
    out_v21 = build_signal_quality(enrichment=_ENR)
    assert out_v21 == out_v2, "v2.1 must be identical to v2 (it is an alias, not a distinct model)"


def test_router_docstring_flags_v2_1_as_alias() -> None:
    doc = build_signal_quality.__doc__ or ""
    assert "alias for" in doc and "v2.1" in doc


# --- F5: SMT is productively inert (no correlated_context producer) --------- #

def test_smt_neutral_without_correlated_context_even_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_SMT_DIVERGENCE", "1")
    monkeypatch.setenv("SMC_SMT_DIVERGENCE_CONFIDENCE", "99")
    # Production-shaped enrichment: NO correlated_context block.
    result = smt_divergence.detect_smt_divergence(enrichment=_ENR)
    assert result["SMT_DIVERGENCE_DETECTED"] is False


def test_smt_config_and_flag_document_inertness() -> None:
    from open_prep.feature_flags import is_smt_divergence_enabled

    assert "INERT" in (v2_config.SmtDivergenceConfig.__doc__ or "").upper()
    assert "correlated_context" in (is_smt_divergence_enabled.__doc__ or "")
    assert "INERT" in (is_smt_divergence_enabled.__doc__ or "").upper()
