"""Tests for the recent-earnings-surprise PEAD feature (observe-only, no weight).

``recent_eps_surprise_pct`` = eps surprise of the most-recent REPORTED earnings.
Today's ``eps_surprise_pct`` is always 0 at pre-open scoring time (unreported);
this recent variant + ``days_since_last_earnings`` collect the post-earnings-drift
(PEAD) evidence BEFORE any weight moves (eval C2b, 2026-07-10).

Covers:
  - _fetch_earnings_distance_features recent-surprise computation (beat/miss/
    unreported/most-recent-past selection)
  - prepare_outcome_snapshot pass-through (present + None-when-absent)
  - FEATURE_KEYS / PASS_THROUGH_FEATURE_KEYS / FEATURE_TO_WEIGHT_KEY consistency
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

_TODAY = date(2026, 7, 10)


class TestRecentSurpriseComputation:
    def _run(self, report_rows: list[dict]) -> dict:
        from open_prep.run_open_prep import _fetch_earnings_distance_features

        client = MagicMock()
        client.get_earnings_report.return_value = report_rows
        out = _fetch_earnings_distance_features(
            client=client, symbols=["AAPL"], today=_TODAY,
        )
        return out.get("AAPL", {})

    def test_beat_is_positive(self) -> None:
        d = self._run([{"date": "2026-04-30", "epsActual": 2.01, "epsEstimated": 1.95}])
        assert d["recent_eps_surprise_pct"] == pytest.approx((2.01 - 1.95) / 1.95 * 100)
        assert d["recent_eps_surprise_pct"] > 0
        assert d["days_since_last_earnings"] == (_TODAY - date(2026, 4, 30)).days

    def test_miss_is_negative(self) -> None:
        d = self._run([{"date": "2026-04-30", "epsActual": 1.80, "epsEstimated": 2.00}])
        assert d["recent_eps_surprise_pct"] < 0

    def test_unreported_last_is_none(self) -> None:
        d = self._run([{"date": "2026-04-30", "epsActual": None, "epsEstimated": 2.00}])
        assert d["recent_eps_surprise_pct"] is None

    def test_uses_most_recent_past_not_future_or_older(self) -> None:
        d = self._run([
            {"date": "2026-07-30", "epsActual": None, "epsEstimated": 1.88},   # future
            {"date": "2026-04-30", "epsActual": 2.01, "epsEstimated": 1.95},   # most-recent past
            {"date": "2026-01-29", "epsActual": 2.85, "epsEstimated": 2.67},   # older
        ])
        assert d["recent_eps_surprise_pct"] == pytest.approx((2.01 - 1.95) / 1.95 * 100)


class TestOutcomeSnapshotPassThrough:
    def test_snapshot_includes_recent_surprise(self) -> None:
        from open_prep.outcomes import prepare_outcome_snapshot

        ranked = [{
            "symbol": "AAPL", "gap_pct": 2.0, "volume": 1_000_000, "avg_volume": 500_000,
            "score": 3.0, "recent_eps_surprise_pct": 3.08, "days_since_last_earnings": 71,
        }]
        rec = prepare_outcome_snapshot(ranked, _TODAY)[0]
        assert rec["recent_eps_surprise_pct"] == 3.08
        assert rec["days_since_last_earnings"] == 71

    def test_snapshot_none_when_absent(self) -> None:
        from open_prep.outcomes import prepare_outcome_snapshot

        rec = prepare_outcome_snapshot(
            [{"symbol": "MSFT", "gap_pct": 1.0, "volume": 1, "avg_volume": 1, "score": 0.5}],
            _TODAY,
        )[0]
        assert rec["recent_eps_surprise_pct"] is None
        assert rec["days_since_last_earnings"] is None


class TestFeatureKeyConsistency:
    def test_recent_surprise_is_pass_through_not_weighted(self) -> None:
        from open_prep.outcomes import (
            FEATURE_KEYS,
            FEATURE_TO_WEIGHT_KEY,
            PASS_THROUGH_FEATURE_KEYS,
        )

        for k in ("recent_eps_surprise_pct", "days_since_last_earnings"):
            assert k in FEATURE_KEYS
            assert k in PASS_THROUGH_FEATURE_KEYS
            assert k not in FEATURE_TO_WEIGHT_KEY
