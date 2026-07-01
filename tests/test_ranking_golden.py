"""Golden-file regression test for ``open_prep.scorer.rank_candidates_v2``.

Why this test exists
--------------------
``rank_candidates_v2`` is the production ranking boundary: a list of quote
dicts plus side-channel metadata enters, and a ranked list of trade ideas
exits. It is fully deterministic (no ``time.time()``, no ``random``, no
module-level mutable state) when called with ``dirty_manager=None`` and
``weight_label="default"``, so it is the ideal target for a behavioural
regression anchor.

The fixture in ``tests/fixtures/ranking_archetypes_input.json`` contains
twelve quote archetypes that exercise distinct branches of the pipeline:

    MEGA_CAP_EARNINGS, SECTOR_LEADER, SECTOR_LAGGARD,
    NEWS_PUMP, ENERGY_RISK_OFF, PENNY_REJECT, SEVERE_GAP_DOWN_REJECT,
    TIER_2_NEWS, COUNTER_TREND,
    EARNINGS_AMC, STALE_PREMARKET, EARNINGS_RISK_WINDOW

The expected output is captured in
``tests/fixtures/ranking_archetypes_golden.json``. Any change to scoring
weights, filter thresholds, freshness decay, or component formulas will
produce a visible diff in that golden file. That diff IS the contract:
review it during PR, accept it by re-running with ``REGEN_RANKING_GOLDEN=1``.

Workflow when intentionally changing weights/thresholds:

    REGEN_RANKING_GOLDEN=1 .venv/bin/python -m pytest \\
        tests/test_ranking_golden.py -p no:cacheprovider

Then ``git diff tests/fixtures/ranking_archetypes_golden.json`` shows exactly
what behaviour shifted. Commit both the source change and the golden update
in the same PR.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import pytest

from open_prep.scorer import rank_candidates_v2

FIXTURE_DIR = Path(__file__).parent / "fixtures"
INPUT_PATH = FIXTURE_DIR / "ranking_archetypes_input.json"
GOLDEN_PATH = FIXTURE_DIR / "ranking_archetypes_golden.json"

# Float rounding precision for stable cross-platform comparison.
# 6 decimals is tight enough to catch real weight changes (≥1e-4 in score)
# and loose enough to absorb the last-bit FP noise across architectures.
FLOAT_PLACES = 6


# Fields that are pure passthroughs from the input quote and add noise to
# the golden diff without contributing signal. Stripped from output before
# comparison so the golden focuses on COMPUTED values.
_PASSTHROUGH_NOISE_KEYS = frozenset({
    "name",
    "previousClose",
    "changesPercentage",
    "premarket_spread_bps",
    "premarket_stale",
    "is_premarket_mover",
    "rsi14",
    "adx",
    "bb_width_pct",
    "earnings_timing",
    "earnings_risk_window",
})


def _round_floats(obj: Any, places: int = FLOAT_PLACES) -> Any:
    """Recursively round all floats so the golden is byte-stable."""
    if isinstance(obj, float):
        # Normalise -0.0 and tiny FP residue.
        rounded = round(obj, places)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(obj, dict):
        return {k: _round_floats(v, places) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, places) for v in obj]
    return obj


def _strip_passthrough_noise(row: dict[str, Any]) -> dict[str, Any]:
    """Remove fields that just echo input back out."""
    return {k: v for k, v in row.items() if k not in _PASSTHROUGH_NOISE_KEYS}


def _normalise_ranked(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round floats + strip noise, preserving rank order."""
    return [_round_floats(_strip_passthrough_noise(r)) for r in rows]


def _normalise_filtered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtered-out rows have a tiny shape; sort by symbol for stability."""
    cleaned = [_round_floats(r) for r in rows]
    return sorted(cleaned, key=lambda r: str(r.get("symbol", "")))


def _load_input() -> dict[str, Any]:
    with INPUT_PATH.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    # Strip _doc / _archetype annotations from quotes so they don't influence
    # the scorer (they wouldn't anyway, but keeps the call surface clean).
    quotes = [
        {k: v for k, v in q.items() if not k.startswith("_")}
        for q in payload["quotes"]
    ]
    return {
        "params": payload["params"],
        "side_channels": payload["side_channels"],
        "quotes": quotes,
    }


def _run_pipeline() -> dict[str, Any]:
    data = _load_input()
    params = data["params"]
    sc = data["side_channels"]

    ranked, filtered_out = rank_candidates_v2(
        quotes=data["quotes"],
        bias=float(params["bias"]),
        top_n=int(params["top_n"]),
        news_scores=sc.get("news_scores"),
        news_metrics=sc.get("news_metrics"),
        sector_changes=sc.get("sector_changes"),
        symbol_sectors=sc.get("symbol_sectors"),
        institutional_scores=sc.get("institutional_scores"),
        estimate_revisions=sc.get("estimate_revisions"),
        weight_label=str(params["weight_label"]),
        vix_level=params.get("vix_level"),
        gate_tracker=None,
        dirty_manager=None,
    )
    return {
        "ranked": _normalise_ranked(ranked),
        "filtered_out": _normalise_filtered(filtered_out),
    }


def _write_golden(payload: dict[str, Any]) -> None:
    GOLDEN_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_golden() -> dict[str, Any]:
    with GOLDEN_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ranking_archetypes_golden_matches() -> None:
    """Full-pipeline regression: ranked + filtered_out must match the golden.

    Set ``REGEN_RANKING_GOLDEN=1`` to overwrite the golden when an
    intentional scoring change is being made.
    """
    actual = _run_pipeline()

    if os.environ.get("REGEN_RANKING_GOLDEN") == "1":
        _write_golden(actual)
        pytest.skip("Regenerated golden; rerun without REGEN_RANKING_GOLDEN to assert.")

    if not GOLDEN_PATH.exists():
        _write_golden(actual)
        pytest.fail(
            f"Golden file did not exist; created {GOLDEN_PATH.name}. "
            "Review the diff and re-run."
        )

    expected = _load_golden()
    assert actual == expected, (
        "Ranking output drifted from golden.\n"
        "  - If this drift is INTENTIONAL (weight tweak, threshold change, "
        "new component): re-run with REGEN_RANKING_GOLDEN=1 and commit the "
        "updated golden alongside the source change.\n"
        "  - If this drift is UNEXPECTED: a refactor changed scoring "
        "behaviour. Diff actual vs expected to find the regression."
    )


def test_ranking_pipeline_is_deterministic() -> None:
    """Two runs of the pipeline on the same fixture must produce identical output."""
    first = _run_pipeline()
    second = _run_pipeline()
    assert first == second, "rank_candidates_v2 produced non-deterministic output"


def test_infinite_analyst_catalyst_score_cannot_dominate_ranking() -> None:
    """Non-finite input fields must not propagate into final scores."""
    data = _load_input()
    params = data["params"]
    sc = data["side_channels"]
    quotes = data["quotes"]
    target_symbol = quotes[0]["symbol"]
    quotes[0]["analyst_catalyst_score"] = float("inf")

    ranked, _filtered_out = rank_candidates_v2(
        quotes=quotes,
        bias=float(params["bias"]),
        top_n=int(params["top_n"]),
        news_scores=sc.get("news_scores"),
        news_metrics=sc.get("news_metrics"),
        sector_changes=sc.get("sector_changes"),
        symbol_sectors=sc.get("symbol_sectors"),
        institutional_scores=sc.get("institutional_scores"),
        estimate_revisions=sc.get("estimate_revisions"),
        weight_label=str(params["weight_label"]),
        vix_level=params.get("vix_level"),
        gate_tracker=None,
        dirty_manager=None,
    )

    assert ranked, "fixture should produce ranked candidates"
    assert all(math.isfinite(row["score"]) for row in ranked)
    by_symbol = {row["symbol"]: row for row in ranked}
    assert math.isfinite(by_symbol[target_symbol]["score"])
    assert by_symbol[target_symbol]["analyst_catalyst_score"] == 0.0


def test_known_archetype_filter_decisions() -> None:
    """Sanity contracts that must hold regardless of weight tuning.

    These are the invariants the golden alone cannot guard if a refactor
    accidentally re-routes everything through the same branch.
    """
    actual = _run_pipeline()
    ranked_symbols = {r["symbol"] for r in actual["ranked"]}
    filtered_symbols = {r["symbol"] for r in actual["filtered_out"]}

    # Penny stock and severe-gap-down must always be filtered out.
    assert "PNNY" in filtered_symbols, "Penny-stock filter regressed"
    assert "CRSH" in filtered_symbols, "Severe-gap-down filter regressed"

    # Filtered symbols must not also appear in ranked output.
    assert ranked_symbols.isdisjoint(filtered_symbols), (
        "A symbol cannot be both ranked and filtered_out"
    )

    # Ranked output must be sorted by score descending.
    scores = [r["score"] for r in actual["ranked"]]
    assert scores == sorted(scores, reverse=True), (
        "Ranked output is not sorted by score descending"
    )


def test_counter_trend_and_rumor_penalties_stack() -> None:
    """CTRD archetype triggers BOTH multiplicative final-score penalties.

    momentum_z_score = -3.5  → counter_trend_penalty > 0 (gap is positive
        but momentum is strongly negative).
    news_source_tier = TIER_3 with news_score = 0.6 ≥ 0.5
        → low_tier_news_rumor_penalty > 0.

    Both penalties must show up in the score_breakdown for the same row,
    proving they compose multiplicatively rather than one masking the other.
    """
    actual = _run_pipeline()
    ctrd_rows = [r for r in actual["ranked"] if r["symbol"] == "CTRD"]
    assert len(ctrd_rows) == 1, "CTRD archetype missing from ranked output"
    breakdown = ctrd_rows[0].get("score_breakdown", {})
    assert breakdown.get("counter_trend_penalty", 0.0) > 0.0, (
        "counter_trend_penalty did not fire on CTRD (expected momentum_z=-3.5 "
        "to trigger penalty)"
    )
    assert breakdown.get("low_tier_news_rumor_penalty", 0.0) > 0.0, (
        "low_tier_news_rumor_penalty did not fire on CTRD (expected TIER_3 "
        "news with score 0.6 to trigger penalty)"
    )


def test_amc_earnings_has_no_bmo_bonus() -> None:
    """AMCS reports earnings AFTER market close (timing='amc').

    earnings_bmo_component must be 0 — the +1.5 weight bonus only applies
    to BMO timing. Compare against NVDA (timing='bmo') where the component
    is non-zero. This pins the AMC-vs-BMO branch in score_candidate.
    """
    actual = _run_pipeline()
    by_symbol = {r["symbol"]: r for r in actual["ranked"]}
    assert "AMCS" in by_symbol, "AMCS archetype missing from ranked output"
    assert "NVDA" in by_symbol, "NVDA archetype missing from ranked output"
    amcs_bmo = by_symbol["AMCS"].get("score_breakdown", {}).get(
        "earnings_bmo_component", 0.0
    )
    nvda_bmo = by_symbol["NVDA"].get("score_breakdown", {}).get(
        "earnings_bmo_component", 0.0
    )
    assert amcs_bmo == 0.0, (
        f"AMCS (earnings_timing='amc') must have earnings_bmo_component=0, "
        f"got {amcs_bmo}"
    )
    assert nvda_bmo > 0.0, (
        f"NVDA (earnings_timing='bmo') must have earnings_bmo_component>0, "
        f"got {nvda_bmo}"
    )


def test_stale_premarket_is_soft_filter() -> None:
    """STAL has premarket_stale=true but is NOT a hard block.

    The candidate must still appear in ``ranked`` (not ``filtered_out``)
    with ``premarket_stale`` annotated in score_breakdown.filter_reasons.
    """
    actual = _run_pipeline()
    ranked_syms = {r["symbol"] for r in actual["ranked"]}
    filtered_syms = {r["symbol"] for r in actual["filtered_out"]}
    assert "STAL" in ranked_syms, "STAL must pass (soft filter, not hard block)"
    assert "STAL" not in filtered_syms, "STAL must not be hard-filtered"
    stal_row = next(r for r in actual["ranked"] if r["symbol"] == "STAL")
    reasons = stal_row.get("no_trade_reason", [])
    assert "premarket_stale" in reasons, (
        f"STAL must have 'premarket_stale' in no_trade_reason, got {reasons}"
    )


def test_earnings_risk_window_is_soft_filter() -> None:
    """ERWN has earnings_risk_window=true but is NOT a hard block.

    The candidate must still appear in ``ranked`` (not ``filtered_out``)
    with ``earnings_risk_window`` annotated in
    score_breakdown.filter_reasons.
    """
    actual = _run_pipeline()
    ranked_syms = {r["symbol"] for r in actual["ranked"]}
    filtered_syms = {r["symbol"] for r in actual["filtered_out"]}
    assert "ERWN" in ranked_syms, (
        "ERWN must pass (soft filter, not hard block)"
    )
    assert "ERWN" not in filtered_syms, "ERWN must not be hard-filtered"
    erwn_row = next(r for r in actual["ranked"] if r["symbol"] == "ERWN")
    reasons = erwn_row.get("no_trade_reason", [])
    assert "earnings_risk_window" in reasons, (
        f"ERWN must have 'earnings_risk_window' in no_trade_reason, "
        f"got {reasons}"
    )


def _run_with_overrides(**overrides: Any) -> dict[str, Any]:
    """Run the pipeline with the same fixture but specific param overrides.

    Used for branches that depend on global parameters (bias, vix_level)
    rather than per-quote fields, so they cannot be expressed as fixture
    archetypes.
    """
    data = _load_input()
    params = dict(data["params"])
    params.update(overrides)
    sc = data["side_channels"]
    ranked, filtered_out = rank_candidates_v2(
        quotes=data["quotes"],
        bias=float(params["bias"]),
        top_n=int(params["top_n"]),
        news_scores=sc.get("news_scores"),
        news_metrics=sc.get("news_metrics"),
        sector_changes=sc.get("sector_changes"),
        symbol_sectors=sc.get("symbol_sectors"),
        institutional_scores=sc.get("institutional_scores"),
        estimate_revisions=sc.get("estimate_revisions"),
        weight_label=str(params["weight_label"]),
        vix_level=params.get("vix_level"),
        gate_tracker=None,
        dirty_manager=None,
    )
    return {
        "ranked": _normalise_ranked(ranked),
        "filtered_out": _normalise_filtered(filtered_out),
    }


def test_macro_risk_off_extreme_hard_filters_all() -> None:
    """When bias <= -0.75, every candidate must be hard-filtered.

    This is the global-macro kill switch — bias is a global parameter
    (not a per-quote field), so it cannot be expressed as a fixture
    archetype. ``macro_risk_off_extreme`` is in the hard_blocks set;
    no symbol should reach ``ranked``.
    """
    actual = _run_with_overrides(bias=-0.85)
    assert actual["ranked"] == [], (
        f"With bias=-0.85, ranked must be empty (macro risk-off extreme), "
        f"got {[r['symbol'] for r in actual['ranked']]}"
    )
    assert actual["filtered_out"], "filtered_out must be non-empty"
    for row in actual["filtered_out"]:
        reasons = row.get("filter_reasons") or row.get(
            "score_breakdown", {}
        ).get("filter_reasons", [])
        assert "macro_risk_off_extreme" in reasons, (
            f"Symbol {row.get('symbol')} filtered without "
            f"'macro_risk_off_extreme' reason: {reasons}"
        )


def test_high_vix_regime_relaxes_adaptive_gates() -> None:
    """vix_level changes adaptive_gates['score_min'] thresholds on rows.

    vix_level is a global parameter (not per-quote), so it cannot be a
    fixture archetype. The contract: a HIGH vix (>30) relaxes score_min
    by 15 %, a LOW vix (<15) tightens it by 15 %. We assert the gate
    threshold attached to a row actually responds to vix changes — this
    pins the macro-regime → adaptive-gate plumbing.
    """
    high = _run_with_overrides(vix_level=35.0)
    low = _run_with_overrides(vix_level=10.0)
    assert high["ranked"] and low["ranked"], "Expected non-empty ranked output"
    high_score_min = high["ranked"][0]["adaptive_gates"]["score_min"]
    low_score_min = low["ranked"][0]["adaptive_gates"]["score_min"]
    assert high_score_min < low_score_min, (
        f"HIGH vix (35) must RELAX score_min vs LOW vix (10): "
        f"high={high_score_min} low={low_score_min}"
    )
