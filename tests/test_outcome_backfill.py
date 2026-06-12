"""Tests for open_prep.outcome_backfill — post-open PnL backfill pipeline."""
from __future__ import annotations

import json
from datetime import date, datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo as _ZoneInfo

import pandas as pd
import pytest

from open_prep.outcome_backfill import (
    _DEFAULT_DATASET,
    DATA_NOT_YET_PUBLISHED,
    _fetch_bars,
    _load_outcome_file,
    _load_pending_dates,
    _save_outcome_file,
    _write_backfill_run_log,
    backfill_feature_importance,
    backfill_outcomes,
    build_parser,
    compute_pnl_from_bars,
    main,
)

_ET = _ZoneInfo("America/New_York")

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_outcome_file(
    tmp_path: Path,
    run_date: date,
    records: list[dict[str, Any]],
) -> Path:
    """Write an outcome JSON file in the expected directory structure."""
    out_dir = tmp_path / "artifacts" / "open_prep" / "outcomes"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"outcomes_{run_date.isoformat()}.json"
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return path


def _make_bars_df(
    symbol: str,
    run_date: date,
    open_price: float = 100.0,
    close_price: float = 102.0,
) -> pd.DataFrame:
    """Build a minimal 1-min OHLCV DataFrame for the 09:30–10:00 window."""
    rows = []
    for minute in range(30):
        ts = datetime.combine(
            run_date,
            dt_time(9, 30 + minute),
            tzinfo=_ET,
        ).astimezone(_ZoneInfo("UTC"))
        # Linear interpolation between open and close
        frac = minute / 29 if minute < 29 else 1.0
        price = open_price + (close_price - open_price) * frac
        rows.append({
            "symbol": symbol,
            "ts_event": ts,
            "open": open_price if minute == 0 else price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price if minute < 29 else close_price,
            "volume": 1000,
        })
    return pd.DataFrame(rows)


# ── compute_pnl_from_bars ──────────────────────────────────────────────────


class TestComputePnlFromBars:
    def test_positive_pnl(self) -> None:
        d = date(2026, 4, 17)
        df = _make_bars_df("NVDA", d, open_price=100.0, close_price=103.0)
        result = compute_pnl_from_bars(df, "NVDA", d)
        assert result is not None
        assert result["profitable_30m"] is True
        assert result["pnl_30m_pct"] == pytest.approx(3.0, abs=0.01)

    def test_negative_pnl(self) -> None:
        d = date(2026, 4, 17)
        df = _make_bars_df("TSLA", d, open_price=200.0, close_price=194.0)
        result = compute_pnl_from_bars(df, "TSLA", d)
        assert result is not None
        assert result["profitable_30m"] is False
        assert result["pnl_30m_pct"] == pytest.approx(-3.0, abs=0.01)

    def test_zero_pnl_is_not_profitable(self) -> None:
        d = date(2026, 4, 17)
        df = _make_bars_df("FLAT", d, open_price=50.0, close_price=50.0)
        result = compute_pnl_from_bars(df, "FLAT", d)
        assert result is not None
        assert result["profitable_30m"] is False
        assert result["pnl_30m_pct"] == 0.0

    def test_empty_df_returns_none(self) -> None:
        assert compute_pnl_from_bars(pd.DataFrame(), "X", date(2026, 1, 1)) is None

    def test_none_df_returns_none(self) -> None:
        assert compute_pnl_from_bars(None, "X", date(2026, 1, 1)) is None

    def test_wrong_symbol_returns_none(self) -> None:
        d = date(2026, 4, 17)
        df = _make_bars_df("AAPL", d)
        assert compute_pnl_from_bars(df, "MISSING", d) is None

    def test_no_timestamp_column_returns_none(self) -> None:
        d = date(2026, 4, 17)
        df = pd.DataFrame({"symbol": ["X"], "open": [100], "close": [101]})
        assert compute_pnl_from_bars(df, "X", d) is None

    def test_datetime_index_fallback(self) -> None:
        """When bars use a DatetimeIndex instead of a ts_event column."""
        d = date(2026, 4, 17)
        df = _make_bars_df("IDX", d, open_price=100.0, close_price=105.0)
        df = df.set_index(pd.to_datetime(df["ts_event"], utc=True))
        df = df.drop(columns=["ts_event"])
        result = compute_pnl_from_bars(df, "IDX", d)
        assert result is not None
        assert result["profitable_30m"] is True


# ── File operations ─────────────────────────────────────────────────────────


class TestFileOperations:
    def test_save_and_load(self, tmp_path: Path) -> None:
        records = [
            {"symbol": "AAPL", "profitable_30m": None, "pnl_30m_pct": None},
        ]
        path = tmp_path / "test_outcomes.json"
        _save_outcome_file(path, records)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded == records

    def test_load_outcome_file_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "open_prep.outcome_backfill.OUTCOMES_DIR",
            tmp_path / "nonexistent",
        )
        _, records = _load_outcome_file(date(2026, 4, 17))
        assert records == []


# ── _load_pending_dates ─────────────────────────────────────────────────────


class TestLoadPendingDates:
    def test_finds_unresolved_dates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        out_dir = tmp_path / "outcomes"
        out_dir.mkdir()
        monkeypatch.setattr("open_prep.outcome_backfill.OUTCOMES_DIR", out_dir)

        # Resolved file — should NOT appear.
        (out_dir / "outcomes_2026-04-16.json").write_text(
            json.dumps([{"profitable_30m": True}]),
        )
        # Unresolved file — should appear.
        (out_dir / "outcomes_2026-04-17.json").write_text(
            json.dumps([{"profitable_30m": None}]),
        )

        pending = _load_pending_dates(lookback_days=5)
        assert date(2026, 4, 17) in pending
        assert date(2026, 4, 16) not in pending

    def test_empty_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "open_prep.outcome_backfill.OUTCOMES_DIR",
            tmp_path / "missing",
        )
        assert _load_pending_dates() == []


# ── backfill_outcomes ───────────────────────────────────────────────────────


class TestBackfillOutcomes:
    def test_resolves_pending_records(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        d = date(2026, 4, 17)
        records = [
            {
                "date": d.isoformat(),
                "symbol": "NVDA",
                "gap_pct": 3.0,
                "rvol": 2.0,
                "score": 4.5,
                "profitable_30m": None,
                "pnl_30m_pct": None,
            },
        ]
        out_dir = tmp_path / "artifacts" / "open_prep" / "outcomes"
        out_dir.mkdir(parents=True)
        outcome_path = out_dir / f"outcomes_{d.isoformat()}.json"
        outcome_path.write_text(json.dumps(records, indent=2))

        monkeypatch.setattr("open_prep.outcome_backfill.OUTCOMES_DIR", out_dir)

        # Mock provider
        bars_df = _make_bars_df("NVDA", d, open_price=100.0, close_price=104.0)
        mock_store = MagicMock()
        mock_store.to_df.return_value = bars_df
        mock_provider = MagicMock()
        mock_provider.get_range.return_value = mock_store

        summary = backfill_outcomes(
            target_dates=[d],
            provider=mock_provider,
        )

        assert summary["resolved"] == 1
        assert summary["failed"] == 0
        assert summary["dates_processed"] == 1

        # Verify file was updated.
        updated = json.loads(outcome_path.read_text())
        assert updated[0]["profitable_30m"] is True
        assert updated[0]["pnl_30m_pct"] == pytest.approx(4.0, abs=0.01)

    def test_skips_already_resolved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        d = date(2026, 4, 17)
        records = [
            {
                "symbol": "AAPL",
                "profitable_30m": True,
                "pnl_30m_pct": 2.0,
            },
        ]
        out_dir = tmp_path / "outcomes"
        out_dir.mkdir()
        (out_dir / f"outcomes_{d.isoformat()}.json").write_text(json.dumps(records))
        monkeypatch.setattr("open_prep.outcome_backfill.OUTCOMES_DIR", out_dir)

        mock_provider = MagicMock()
        summary = backfill_outcomes(
            target_dates=[d],
            provider=mock_provider,
        )
        assert summary["resolved"] == 0
        assert summary["skipped"] == 1
        # Should NOT call get_range when nothing is pending.
        mock_provider.get_range.assert_not_called()

    def test_dry_run_does_not_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        d = date(2026, 4, 17)
        records = [
            {"symbol": "TSLA", "profitable_30m": None, "pnl_30m_pct": None},
        ]
        out_dir = tmp_path / "outcomes"
        out_dir.mkdir()
        path = out_dir / f"outcomes_{d.isoformat()}.json"
        path.write_text(json.dumps(records))
        monkeypatch.setattr("open_prep.outcome_backfill.OUTCOMES_DIR", out_dir)

        bars_df = _make_bars_df("TSLA", d, open_price=50.0, close_price=48.0)
        mock_store = MagicMock()
        mock_store.to_df.return_value = bars_df
        mock_provider = MagicMock()
        mock_provider.get_range.return_value = mock_store

        summary = backfill_outcomes(
            target_dates=[d],
            provider=mock_provider,
            dry_run=True,
        )
        assert summary["resolved"] == 1

        # File should still have null values (dry run).
        raw = json.loads(path.read_text())
        assert raw[0]["profitable_30m"] is None

    def test_no_pending_dates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "open_prep.outcome_backfill._load_pending_dates",
            lambda lookback_days: [],
        )
        summary = backfill_outcomes(provider=MagicMock())
        assert summary["resolved"] == 0
        assert summary["dates_processed"] == 0

    def test_fetch_failure_counts_as_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        d = date(2026, 4, 17)
        records = [
            {"symbol": "FAIL", "profitable_30m": None, "pnl_30m_pct": None},
        ]
        out_dir = tmp_path / "outcomes"
        out_dir.mkdir()
        (out_dir / f"outcomes_{d.isoformat()}.json").write_text(json.dumps(records))
        monkeypatch.setattr("open_prep.outcome_backfill.OUTCOMES_DIR", out_dir)

        # Provider raises on get_range
        mock_provider = MagicMock()
        mock_provider.get_range.side_effect = RuntimeError("API down")

        summary = backfill_outcomes(
            target_dates=[d],
            provider=mock_provider,
        )
        # _fetch_bars catches the error and returns None → failed
        assert summary["failed"] == 1
        assert summary["resolved"] == 0

    def test_unpublished_window_defers_not_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Regression for GH run 27313823758: the late-evening scheduled
        # run hit Databento 422 data_start_after_available_end (day's
        # bars not yet published) and exited 2. That transient case must
        # be classified as deferred, not failed.
        d = date(2026, 6, 10)
        records = [
            {"symbol": "NVDA", "profitable_30m": None, "pnl_30m_pct": None},
            {"symbol": "TSLA", "profitable_30m": None, "pnl_30m_pct": None},
        ]
        out_dir = tmp_path / "outcomes"
        out_dir.mkdir()
        path = out_dir / f"outcomes_{d.isoformat()}.json"
        path.write_text(json.dumps(records))
        monkeypatch.setattr("open_prep.outcome_backfill.OUTCOMES_DIR", out_dir)

        mock_provider = MagicMock()
        mock_provider.get_range.side_effect = RuntimeError(
            "422 data_start_after_available_end: timeseries.get_range "
            "`start` was after the available end"
        )

        summary = backfill_outcomes(target_dates=[d], provider=mock_provider)
        assert summary["deferred"] == 2
        assert summary["failed"] == 0
        assert summary["resolved"] == 0

        # Records stay unresolved so the next scheduled run retries them.
        raw = json.loads(path.read_text())
        assert all(r["profitable_30m"] is None for r in raw)

    def test_multi_symbol_batch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        d = date(2026, 4, 17)
        records = [
            {"symbol": "A", "profitable_30m": None, "pnl_30m_pct": None},
            {"symbol": "B", "profitable_30m": None, "pnl_30m_pct": None},
            {"symbol": "C", "profitable_30m": True, "pnl_30m_pct": 1.0},  # already resolved
        ]
        out_dir = tmp_path / "outcomes"
        out_dir.mkdir()
        (out_dir / f"outcomes_{d.isoformat()}.json").write_text(json.dumps(records))
        monkeypatch.setattr("open_prep.outcome_backfill.OUTCOMES_DIR", out_dir)

        bars_a = _make_bars_df("A", d, open_price=10.0, close_price=11.0)
        bars_b = _make_bars_df("B", d, open_price=20.0, close_price=19.0)
        bars_df = pd.concat([bars_a, bars_b], ignore_index=True)

        mock_store = MagicMock()
        mock_store.to_df.return_value = bars_df
        mock_provider = MagicMock()
        mock_provider.get_range.return_value = mock_store

        summary = backfill_outcomes(target_dates=[d], provider=mock_provider)
        assert summary["resolved"] == 2
        assert summary["skipped"] == 1  # symbol C

        updated = json.loads(
            (out_dir / f"outcomes_{d.isoformat()}.json").read_text(),
        )
        assert updated[0]["profitable_30m"] is True   # A: 10→11
        assert updated[1]["profitable_30m"] is False   # B: 20→19


# ── _fetch_bars ─────────────────────────────────────────────────────────────


class TestFetchBars:
    def test_success(self) -> None:
        d = date(2026, 4, 17)
        mock_df = pd.DataFrame({"x": [1]})
        mock_store = MagicMock()
        mock_store.to_df.return_value = mock_df
        mock_provider = MagicMock()
        mock_provider.get_range.return_value = mock_store

        result = _fetch_bars(mock_provider, ["NVDA"], d)
        assert result is not None
        mock_provider.get_range.assert_called_once()

    def test_failure_returns_none(self) -> None:
        mock_provider = MagicMock()
        mock_provider.get_range.side_effect = RuntimeError("boom")
        result = _fetch_bars(mock_provider, ["X"], date(2026, 4, 17))
        assert result is None

    def test_unpublished_window_returns_sentinel(self) -> None:
        mock_provider = MagicMock()
        mock_provider.get_range.side_effect = RuntimeError(
            "422 data_start_after_available_end"
        )
        result = _fetch_bars(mock_provider, ["X"], date(2026, 6, 10))
        assert result is DATA_NOT_YET_PUBLISHED


# ── CLI parser ──────────────────────────────────────────────────────────────


class TestCLI:
    def test_parser_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.date is None
        assert args.lookback == 5
        assert args.dataset == _DEFAULT_DATASET
        assert args.dry_run is False
        assert args.feature_importance is False

    def test_parser_with_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "--date", "2026-04-18",
            "--lookback", "10",
            "--dry-run",
            "--feature-importance",
        ])
        assert args.date == "2026-04-18"
        assert args.lookback == 10
        assert args.dry_run is True
        assert args.feature_importance is True

    def test_main_invokes_backfill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_backfill = MagicMock(return_value={
            "resolved": 3, "skipped": 1, "failed": 0, "dates_processed": 1,
        })
        monkeypatch.setattr(
            "open_prep.outcome_backfill.backfill_outcomes",
            mock_backfill,
        )
        main(["--date", "2026-04-18", "--dry-run"])
        mock_backfill.assert_called_once()
        call_kwargs = mock_backfill.call_args[1]
        assert call_kwargs["target_dates"] == [date(2026, 4, 18)]
        assert call_kwargs["dry_run"] is True

    def test_main_partial_failure_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: a backfill that resolved most rows but failed on a
        # few legacy data gaps must NOT turn the workflow permanently
        # red. The failed count is preserved in the JSON run log.
        monkeypatch.setattr(
            "open_prep.outcome_backfill.backfill_outcomes",
            MagicMock(return_value={
                "resolved": 18, "skipped": 0, "failed": 3, "dates_processed": 3,
            }),
        )
        assert main(["--date", "2026-04-18", "--dry-run"]) == 0

    def test_main_no_progress_with_failures_exits_two(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Real failure mode: nothing resolved AND at least one failure.
        monkeypatch.setattr(
            "open_prep.outcome_backfill.backfill_outcomes",
            MagicMock(return_value={
                "resolved": 0, "skipped": 0, "failed": 5, "dates_processed": 1,
            }),
        )
        assert main(["--date", "2026-04-18", "--dry-run"]) == 2

    def test_main_deferred_only_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Bars not yet published upstream → deferred, not failed → the
        # scheduled workflow stays green and retries on the next run.
        monkeypatch.setattr(
            "open_prep.outcome_backfill.backfill_outcomes",
            MagicMock(return_value={
                "resolved": 0, "skipped": 17, "failed": 0, "deferred": 13,
                "dates_processed": 3,
            }),
        )
        assert main(["--date", "2026-06-10", "--dry-run"]) == 0

    def test_main_deferred_counts_as_progress_for_require_progress(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "open_prep.outcome_backfill.backfill_outcomes",
            MagicMock(return_value={
                "resolved": 0, "skipped": 0, "failed": 0, "deferred": 4,
                "dates_processed": 1,
            }),
        )
        assert main(
            ["--date", "2026-06-10", "--dry-run", "--require-progress"]
        ) == 0

    def test_main_clean_run_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "open_prep.outcome_backfill.backfill_outcomes",
            MagicMock(return_value={
                "resolved": 5, "skipped": 0, "failed": 0, "dates_processed": 1,
            }),
        )
        assert main(["--date", "2026-04-18", "--dry-run"]) == 0


class TestRunLogStatusDerivation:
    """Audit D-3 (2026-06-12): the workflow's failed-streak alert step
    consumes the run log's ``status`` field, so its derivation rules are
    load-bearing: any failed > 0 → "failed" (even with progress),
    deferred-only → "deferred", otherwise "ok".
    """

    @pytest.mark.parametrize(
        ("summary", "expected"),
        [
            ({"resolved": 18, "failed": 3}, "failed"),
            ({"resolved": 0, "failed": 5}, "failed"),
            ({"resolved": 0, "deferred": 4, "failed": 0}, "deferred"),
            ({"resolved": 5, "deferred": 2, "failed": 0}, "deferred"),
            ({"resolved": 5, "failed": 0}, "ok"),
            ({}, "ok"),
        ],
    )
    def test_status_derivation(
        self, tmp_path: Path, summary: dict[str, Any], expected: str
    ) -> None:
        out_path = _write_backfill_run_log(
            summary=summary,
            feature_importance_samples=None,
            cli_args={},
            log_dir=tmp_path,
        )
        record = json.loads(out_path.read_text(encoding="utf-8"))
        assert record["status"] == expected
        latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
        assert latest["status"] == expected


# ── Feature importance backfill ─────────────────────────────────────────────


class TestFeatureImportanceBackfill:
    def test_no_labeled_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "open_prep.outcomes._load_outcomes_range",
            lambda lookback_days: [{"profitable_30m": None}],
        )
        assert backfill_feature_importance(lookback_days=1) == 0

    def test_labeled_records_flushed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from open_prep.outcomes import FEATURE_TO_WEIGHT_KEY

        # c10b fix: records now carry the FULL component schema (as the
        # fixed prepare_outcome_snapshot persists it); partial-schema
        # records are legacy and skipped by the era-gate (separate test).
        records = [
            {
                "symbol": "NVDA",
                "date": "2026-04-17",
                "score": 4.5,
                "confidence_tier": "HIGH_CONVICTION",
                "profitable_30m": True,
                "pnl_30m_pct": 2.5,
                **{key: 0.5 for key in FEATURE_TO_WEIGHT_KEY},
                "gap_component": 1.0,
                "rvol_component": 0.8,
            },
        ]
        monkeypatch.setattr(
            "open_prep.outcomes._load_outcomes_range",
            lambda lookback_days: records,
        )
        fi_dir = tmp_path / "fi"
        fi_dir.mkdir()
        monkeypatch.setattr(
            "open_prep.outcomes.FEATURE_IMPORTANCE_DIR",
            fi_dir,
        )
        n = backfill_feature_importance(lookback_days=1)
        assert n == 1
        # Should have written a JSONL file.
        files = list(fi_dir.glob("fi_samples_*.jsonl"))
        assert len(files) == 1

    def test_legacy_records_without_components_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """c10b era-gate: pre-fix outcome records (no *_component keys)
        must NOT be turned into all-zero feature vectors."""
        records = [
            {
                "symbol": "NVDA",
                "date": "2026-04-17",
                "score": 4.5,
                "profitable_30m": True,
                "pnl_30m_pct": 2.5,
                # legacy schema: no component keys at all
            },
        ]
        monkeypatch.setattr(
            "open_prep.outcomes._load_outcomes_range",
            lambda lookback_days: records,
        )
        fi_dir = tmp_path / "fi"
        fi_dir.mkdir()
        monkeypatch.setattr(
            "open_prep.outcomes.FEATURE_IMPORTANCE_DIR",
            fi_dir,
        )
        assert backfill_feature_importance(lookback_days=1) == 0
        assert list(fi_dir.glob("fi_samples_*.jsonl")) == []


# ── Zone Priority → Outcome snapshot wiring ────────────────────────────────


class TestZonePriorityOutcomeWiring:
    """Verify zone_priority_rank/score flow through outcome records."""

    def test_prepare_outcome_snapshot_includes_zone_priority_fields(self) -> None:
        from open_prep.outcomes import prepare_outcome_snapshot

        ranked = [
            {
                "symbol": "AAPL",
                "gap_pct": 2.5,
                "volume": 1_000_000,
                "avg_volume": 500_000,
                "score": 78.0,
                "confidence_tier": "HIGH_CONVICTION",
                "regime": "RISK_ON",
                "zone_priority_rank": "A",
                "zone_priority_score": 82,
            },
        ]
        records = prepare_outcome_snapshot(ranked, date(2026, 4, 20))
        assert len(records) == 1
        rec = records[0]
        assert rec["zone_priority_rank"] == "A"
        assert rec["zone_priority_score"] == 82
        assert rec["profitable_30m"] is None  # still pending
        # Sprint C1: regime_at_entry alias must mirror legacy `regime`
        # so C5 stratification + C9 drift watchdog can read the same key.
        assert rec["regime"] == "RISK_ON"
        assert rec["regime_at_entry"] == "RISK_ON"

    def test_prepare_outcome_snapshot_zone_priority_none_when_absent(self) -> None:
        from open_prep.outcomes import prepare_outcome_snapshot

        ranked = [
            {
                "symbol": "MSFT",
                "gap_pct": 1.0,
                "volume": 200_000,
                "avg_volume": 200_000,
                "score": 55.0,
            },
        ]
        records = prepare_outcome_snapshot(ranked, date(2026, 4, 20))
        rec = records[0]
        assert rec["zone_priority_rank"] is None
        assert rec["zone_priority_score"] is None

    def test_zone_priority_survives_backfill_rewrite(self, tmp_path: Path) -> None:
        """Extra zone_priority fields must survive the atomic rewrite in backfill."""
        records = [
            {
                "date": "2026-04-18",
                "symbol": "AAPL",
                "gap_pct": 2.5,
                "rvol": 2.0,
                "score": 78.0,
                "confidence_tier": "HIGH_CONVICTION",
                "regime": "RISK_ON",
                "zone_priority_rank": "B",
                "zone_priority_score": 65,
                "profitable_30m": None,
                "pnl_30m_pct": None,
            },
        ]
        path = tmp_path / "outcomes_2026-04-18.json"
        _save_outcome_file(path, records)

        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded[0]["zone_priority_rank"] == "B"
        assert loaded[0]["zone_priority_score"] == 65

    def test_feature_keys_includes_zone_priority_score(self) -> None:
        from open_prep.outcomes import FEATURE_KEYS

        assert "zone_priority_score" in FEATURE_KEYS

    def test_enrich_zone_priority_populates_rows(self) -> None:
        from open_prep.run_open_prep import _enrich_zone_priority

        class FakeRegime:
            regime = "RISK_ON"

        rows = [
            {"symbol": "AAPL", "score": 80.0},
            {"symbol": "MSFT", "score": 40.0},
        ]
        _enrich_zone_priority(rows, FakeRegime(), {"AAPL": 0.8, "MSFT": 0.1})
        for row in rows:
            assert "zone_priority_rank" in row
            assert "zone_priority_score" in row
            assert row["zone_priority_rank"] in ("A", "B", "C", "D")
            assert isinstance(row["zone_priority_score"], (int, float))

    def test_enrich_zone_priority_handles_none_regime(self) -> None:
        from open_prep.run_open_prep import _enrich_zone_priority

        rows = [{"symbol": "TSLA", "score": 50.0}]
        _enrich_zone_priority(rows, None, {})
        assert rows[0]["zone_priority_rank"] in ("A", "B", "C", "D")
