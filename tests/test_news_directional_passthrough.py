"""Tests for the signed news score (observe-only, no scorer weight).

``news_directional_score`` = mention intensity × average article sentiment.
The weighted ``news`` component stays direction-blind by contract until the
c10b experiment concludes (see news.py); this pass-through column collects
the feature-importance evidence for a directional variant BEFORE any weight
moves.

Covers:
  - ``build_news_scores`` sign behavior (bullish / bearish / no coverage)
  - scorer ranked-row pass-through + score neutrality
  - ``prepare_outcome_snapshot`` pass-through
  - ``FEATURE_KEYS`` / ``PASS_THROUGH_FEATURE_KEYS`` / ``FEATURE_TO_WEIGHT_KEY``
    consistency
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from open_prep.news import build_news_scores

_NOW = datetime(2026, 7, 7, 13, 0, 0, tzinfo=UTC)


def _article(title: str, tickers: str = "NASDAQ:NVDA") -> dict:
    # 15 minutes before _NOW — safely inside the 2h recency window.
    return {
        "tickers": tickers,
        "title": title,
        "content": "",
        "date": "2026-07-07 12:45:00",
    }


class TestDirectionalScoreSign:
    def test_bullish_coverage_is_positive(self) -> None:
        articles = [
            _article("NVIDIA record quarter, raises guidance, bullish momentum"),
            _article("NVIDIA beats estimates, strong buy"),
        ]
        _, metrics = build_news_scores(symbols=["NVDA"], articles=articles, now_utc=_NOW)
        row = metrics["NVDA"]
        assert row["sentiment_label"] == "bullish"
        assert row["news_directional_score"] > 0
        # Magnitude never exceeds the undirected intensity score.
        assert abs(row["news_directional_score"]) <= row["news_catalyst_score"] + 1e-9

    def test_bearish_coverage_is_negative(self) -> None:
        articles = [
            _article("NVIDIA lawsuit and selloff, bearish downgrade, losses mount"),
            _article("NVIDIA declining demand, sell rating, weak outlook"),
        ]
        _, metrics = build_news_scores(symbols=["NVDA"], articles=articles, now_utc=_NOW)
        row = metrics["NVDA"]
        assert row["sentiment_label"] == "bearish"
        assert row["news_directional_score"] < 0

    def test_no_coverage_is_zero(self) -> None:
        _, metrics = build_news_scores(symbols=["NVDA"], articles=[], now_utc=_NOW)
        assert metrics["NVDA"]["news_directional_score"] == 0.0


class TestScorerPassThrough:
    def test_ranked_row_carries_directional_score_without_moving_the_score(self) -> None:
        from open_prep import scorer as sc
        from tests.test_open_prep_scorer_uplift import _make_passing_quote

        quote = _make_passing_quote("NVDA")
        nm = {"news_directional_score": -1.25, "sentiment_emoji": "🔴",
              "sentiment_label": "bearish", "sentiment_score": -0.5}
        ranked_with, _ = sc.rank_candidates_v2(
            [quote], bias=0.5, top_n=5,
            news_metrics={"NVDA": nm},
        )
        ranked_without, _ = sc.rank_candidates_v2(
            [_make_passing_quote("NVDA")], bias=0.5, top_n=5,
        )
        assert ranked_with[0]["news_directional_score"] == -1.25
        assert ranked_without[0]["news_directional_score"] == 0.0
        # Observe-only: identical score with and without the field.
        assert ranked_with[0]["score"] == ranked_without[0]["score"]


class TestOutcomeSnapshotPassThrough:
    def test_snapshot_includes_directional_score(self) -> None:
        from open_prep.outcomes import prepare_outcome_snapshot

        ranked = [{
            "symbol": "NVDA",
            "gap_pct": 2.0,
            "volume": 1_000_000,
            "avg_volume": 500_000,
            "score": 3.2,
            "news_directional_score": -0.75,
        }]
        records = prepare_outcome_snapshot(ranked, date(2026, 7, 7))
        assert records[0]["news_directional_score"] == -0.75

    def test_snapshot_none_when_absent(self) -> None:
        from open_prep.outcomes import prepare_outcome_snapshot

        records = prepare_outcome_snapshot(
            [{"symbol": "MSFT", "gap_pct": 1.0, "volume": 1, "avg_volume": 1, "score": 0.5}],
            date(2026, 7, 7),
        )
        assert records[0]["news_directional_score"] is None


class TestFeatureKeyConsistency:
    def test_directional_score_is_pass_through_not_weighted(self) -> None:
        from open_prep.outcomes import (
            FEATURE_KEYS,
            FEATURE_TO_WEIGHT_KEY,
            PASS_THROUGH_FEATURE_KEYS,
        )

        assert "news_directional_score" in FEATURE_KEYS
        assert "news_directional_score" in PASS_THROUGH_FEATURE_KEYS
        assert "news_directional_score" not in FEATURE_TO_WEIGHT_KEY
