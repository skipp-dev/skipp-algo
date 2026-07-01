"""Coverage uplift for `open_prep.scorer` (baseline 78%).

Focuses on small, discrete uncovered branches identified from the
missing-line report (78% → target ≥90%):

- `load_weight_set` / `save_weight_set` round-trip + fallback paths
- `freshness_decay_score` edge cases (None / non-positive elapsed / ATR-aware)
- `compute_sector_relative_gap` known-sector path
- `compute_vwap_distance_pct` happy path
- `_compute_ewma_feature` neutral fallback + happy path
- `classify_confidence_tier` <5 samples + HIGH_CONVICTION + STANDARD + WATCHLIST
- `rank_candidates_v2` empty-symbol skip + below-cutoff overflow + VIX-adaptive
  warning path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from open_prep import scorer as sc

# ---------------------------------------------------------------------------
# load_weight_set / save_weight_set
# ---------------------------------------------------------------------------


def test_load_weight_set_default_returns_default_copy() -> None:
    out = sc.load_weight_set("default")
    assert out == sc.DEFAULT_WEIGHTS
    # must be a copy
    out["gap"] = -999.0
    assert sc.DEFAULT_WEIGHTS["gap"] != -999.0


def test_load_weight_set_missing_label_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sc, "OUTCOMES_DIR", tmp_path)
    out = sc.load_weight_set("nonexistent_label")
    assert out == sc.DEFAULT_WEIGHTS


def test_load_weight_set_existing_file_merges_with_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sc, "OUTCOMES_DIR", tmp_path)
    (tmp_path / "weights_custom.json").write_text(json.dumps({"gap": 9.99, "extra": 2.5}))
    out = sc.load_weight_set("custom")
    assert out["gap"] == 9.99
    assert out["extra"] == 2.5
    # defaults preserved
    assert out["rvol"] == sc.DEFAULT_WEIGHTS["rvol"]


def test_load_weight_set_invalid_json_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sc, "OUTCOMES_DIR", tmp_path)
    (tmp_path / "weights_bad.json").write_text("{not valid json")
    out = sc.load_weight_set("bad")
    assert out == sc.DEFAULT_WEIGHTS


def test_load_weight_set_non_dict_payload_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sc, "OUTCOMES_DIR", tmp_path)
    (tmp_path / "weights_list.json").write_text(json.dumps([1, 2, 3]))
    out = sc.load_weight_set("list")
    assert out == sc.DEFAULT_WEIGHTS


def test_save_weight_set_roundtrips_via_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sc, "OUTCOMES_DIR", tmp_path)
    weights = dict(sc.DEFAULT_WEIGHTS)
    weights["gap"] = 1.234
    sc.save_weight_set("rt", weights)
    out = sc.load_weight_set("rt")
    assert out["gap"] == 1.234


def test_save_weight_set_cleans_up_tmp_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sc, "OUTCOMES_DIR", tmp_path)

    def boom_replace(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom_replace)
    with pytest.raises(OSError, match="disk full"):
        sc.save_weight_set("fail", dict(sc.DEFAULT_WEIGHTS))
    # No leftover .tmp files
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


# ---------------------------------------------------------------------------
# freshness_decay_score
# ---------------------------------------------------------------------------


def test_freshness_decay_score_none_elapsed_returns_zero() -> None:
    assert sc.freshness_decay_score(None) == 0.0


def test_freshness_decay_score_zero_or_negative_returns_one() -> None:
    assert sc.freshness_decay_score(0.0) == 1.0
    assert sc.freshness_decay_score(-1.0) == 1.0


def test_freshness_decay_score_default_half_life() -> None:
    out = sc.freshness_decay_score(sc.FRESHNESS_HALF_LIFE_SECONDS)
    assert out == pytest.approx(0.5, abs=1e-6)


def test_freshness_decay_score_uses_atr_aware_half_life() -> None:
    out = sc.freshness_decay_score(60.0, atr_pct=2.5)
    assert 0.0 < out <= 1.0


# ---------------------------------------------------------------------------
# compute_sector_relative_gap
# ---------------------------------------------------------------------------


def test_compute_sector_relative_gap_unknown_sector_returns_zero() -> None:
    assert sc.compute_sector_relative_gap(5.0, None, {"Tech": 1.0}) == 0.0
    assert sc.compute_sector_relative_gap(5.0, "Tech", {}) == 0.0


def test_compute_sector_relative_gap_subtracts_sector_avg() -> None:
    assert sc.compute_sector_relative_gap(5.0, "Tech", {"Tech": 1.5}) == pytest.approx(3.5)
    # missing sector key → defaults to 0
    assert sc.compute_sector_relative_gap(5.0, "NotPresent", {"Tech": 1.5}) == 5.0


# ---------------------------------------------------------------------------
# compute_vwap_distance_pct
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("vwap", "prev_close", "expected"),
    [
        (None, 100.0, 0.0),
        (100.0, None, 0.0),
        (100.0, 0.0, 0.0),
        (0.0, 100.0, 0.0),
        (110.0, 100.0, 10.0),
        (90.0, 100.0, -10.0),
    ],
)
def test_compute_vwap_distance_pct(
    vwap: float | None, prev_close: float | None, expected: float
) -> None:
    assert sc.compute_vwap_distance_pct(vwap, prev_close) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# _compute_ewma_feature
# ---------------------------------------------------------------------------


def test_compute_ewma_feature_no_bars_returns_neutral() -> None:
    assert sc._compute_ewma_feature({}, price=100.0) == 0.5


def test_compute_ewma_feature_short_bars_returns_neutral() -> None:
    assert sc._compute_ewma_feature({"daily_bars": [{"close": 1.0}] * 3}, price=100.0) == 0.5


def test_compute_ewma_feature_non_list_bars_returns_neutral() -> None:
    assert sc._compute_ewma_feature({"daily_bars": "not_a_list"}, price=100.0) == 0.5


def test_compute_ewma_feature_with_full_bars_returns_score() -> None:
    bars = [{"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100 + i, "volume": 1000}
            for i in range(20)]
    out = sc._compute_ewma_feature({"daily_bars": bars}, price=120.0)
    assert 0.0 <= out <= 1.0


def test_compute_ewma_feature_returns_neutral_when_calculate_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sc, "calculate_ewma", lambda *args, **kwargs: None)
    bars = [{"close": 1.0}] * 20
    assert sc._compute_ewma_feature({"daily_bars": bars}, price=100.0) == 0.5


# ---------------------------------------------------------------------------
# classify_confidence_tier
# ---------------------------------------------------------------------------


def test_classify_confidence_tier_few_samples_returns_standard() -> None:
    assert sc.classify_confidence_tier(10.0, [1.0, 2.0, 3.0]) == "STANDARD"


def test_classify_confidence_tier_high_conviction() -> None:
    # mean=5, std≈3.16 → mean+2σ ≈ 11.32. score=20 > threshold and no warn flags
    scores = [1.0, 3.0, 5.0, 7.0, 9.0]
    assert sc.classify_confidence_tier(20.0, scores, warn_flags="") == "HIGH_CONVICTION"


def test_classify_confidence_tier_high_conviction_demoted_by_warn_flags() -> None:
    scores = [1.0, 3.0, 5.0, 7.0, 9.0]
    # Same score that would be HIGH_CONVICTION, but warn_flags present → STANDARD
    out = sc.classify_confidence_tier(20.0, scores, warn_flags="something")
    assert out == "STANDARD"


def test_classify_confidence_tier_standard() -> None:
    scores = [1.0, 3.0, 5.0, 7.0, 9.0]
    # mean+1σ ≈ 8.16 → score=10 falls between 1σ and 2σ
    assert sc.classify_confidence_tier(10.0, scores) == "STANDARD"


def test_classify_confidence_tier_watchlist() -> None:
    scores = [1.0, 3.0, 5.0, 7.0, 9.0]
    assert sc.classify_confidence_tier(2.0, scores) == "WATCHLIST"


def test_classify_confidence_tier_zero_variance_uses_floor() -> None:
    # All identical scores → variance 0 → std defaults to 0.001
    # mean+2σ = 5.002 → 5.01 clears the bar
    out = sc.classify_confidence_tier(5.01, [5.0, 5.0, 5.0, 5.0, 5.0], warn_flags="")
    assert out == "HIGH_CONVICTION"


# ---------------------------------------------------------------------------
# rank_candidates_v2 — light end-to-end
# ---------------------------------------------------------------------------


def _make_passing_quote(symbol: str, gap_pct: float = 5.0) -> dict[str, Any]:
    """Build a minimal quote that survives filter_candidate hard blocks."""
    return {
        "symbol": symbol,
        "price": 50.0,
        "gap_pct": gap_pct,
        "gap_available": True,
        "volume": 1_000_000,
        "avgVolume": 800_000,
        "atr": 1.5,
        "momentum_z_score": 1.0,
        "volume_ratio": 1.5,
        "rsi": 55.0,
        "premarket_stale": False,
        "premarket_spread_bps": 50.0,
        "earnings_today": False,
        "earnings_risk_window": False,
        "split_today": False,
        "ipo_window": False,
        "previousClose": 47.5,
        "vwap": 49.0,
        "ext_hours_score": 0.5,
        "is_hvb": False,
        "premarket_change_pct": 5.0,
        "premarket_freshness_sec": 30.0,
    }


def test_rank_candidates_v2_skips_empty_symbol() -> None:
    quotes = [_make_passing_quote("AAPL"), {"symbol": ""}]
    ranked, _filtered = sc.rank_candidates_v2(quotes, bias=0.5, top_n=10)
    assert all(r["symbol"] != "" for r in ranked)


def test_rank_candidates_v2_overflow_goes_to_filtered_out() -> None:
    quotes = [_make_passing_quote(f"S{i}", gap_pct=5.0 - 0.1 * i) for i in range(5)]
    ranked, filtered = sc.rank_candidates_v2(quotes, bias=0.5, top_n=2)
    assert len(ranked) == 2
    overflow = [f for f in filtered if "below_top_n_cutoff" in f.get("filter_reasons", [])]
    assert len(overflow) >= 1


def test_rank_candidates_v2_assigns_confidence_tier() -> None:
    quotes = [_make_passing_quote(f"S{i}") for i in range(6)]
    ranked, _ = sc.rank_candidates_v2(quotes, bias=0.5, top_n=10)
    assert all("confidence_tier" in r for r in ranked)


def test_rank_candidates_v2_with_vix_adds_adaptive_gates() -> None:
    quotes = [_make_passing_quote("AAPL"), _make_passing_quote("MSFT")]
    ranked, _ = sc.rank_candidates_v2(quotes, bias=0.5, top_n=10, vix_level=20.0)
    for row in ranked:
        assert "adaptive_gates" in row
        assert "adaptive_gate_warning" in row


def test_rank_candidates_v2_handles_non_finite_scores_deterministically(monkeypatch: pytest.MonkeyPatch) -> None:
    quotes = [_make_passing_quote("AAPL"), _make_passing_quote("MSFT")]
    original = sc.score_candidate

    def _fake_score_candidate(fr, bias, weights):  # type: ignore[no-untyped-def]
        row = original(fr, bias, weights)
        if row["symbol"] == "AAPL":
            row["score"] = float("nan")
        return row

    monkeypatch.setattr(sc, "score_candidate", _fake_score_candidate)

    ranked, _ = sc.rank_candidates_v2(quotes, bias=0.5, top_n=10, vix_level=20.0)

    # Non-finite score is sanitized to a deterministic low finite value.
    aapl = next(r for r in ranked if r["symbol"] == "AAPL")
    assert aapl["score"] == -1_000_000_000.0
    assert "non_finite_score" in aapl.get("warn_flags", "")
    assert [r["symbol"] for r in ranked][-1] == "AAPL"


def test_rank_candidates_v2_filters_hard_block_to_filtered_out() -> None:
    bad = _make_passing_quote("BAD")
    bad["price"] = 1.0  # below MIN_PRICE_THRESHOLD → hard-block
    ranked, filtered = sc.rank_candidates_v2([bad], bias=0.5, top_n=10)
    assert ranked == []
    assert any(f["symbol"] == "BAD" for f in filtered)
    bad_filter = next(f for f in filtered if f["symbol"] == "BAD")
    assert "price_below_5" in bad_filter["filter_reasons"]


def test_rank_candidates_v2_passes_news_and_sector_data() -> None:
    quotes = [_make_passing_quote("AAPL")]
    news = {"AAPL": 0.7}
    metrics = {"AAPL": {"sentiment_label": "bullish", "sentiment_emoji": "🟢"}}
    ranked, _ = sc.rank_candidates_v2(
        quotes,
        bias=0.5,
        news_scores=news,
        news_metrics=metrics,
        symbol_sectors={"AAPL": "Tech"},
        sector_changes={"Tech": 1.0},
        institutional_scores={"AAPL": 0.6},
        estimate_revisions={"AAPL": 0.3},
    )
    assert len(ranked) == 1
    row = ranked[0]
    assert row["symbol"] == "AAPL"
    assert row["news_catalyst_score"] == pytest.approx(0.7, abs=0.01)
    assert row["institutional_quality"] == pytest.approx(0.6, abs=0.01)
