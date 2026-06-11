"""Regression tests — FI component persistence + sample dedup (c10b follow-up).

Covers the 2026-06-11 blast-radius remediation after the FDR-gate wiring
fix:

1. ``prepare_outcome_snapshot()`` persists the weighted ``score_breakdown``
   components flat on every outcome record (previously absent → the
   backfill defaulted every component to 0.0 and every FI report since
   2026-04-30 was computed on all-zero feature vectors).
2. ``backfill_feature_importance()`` era-gate: legacy records without the
   component schema are skipped, never laundered into all-zero samples.
3. ``compute_feature_importance()`` deduplicates ``(symbol, date)`` rows
   across overlapping daily fi_samples files (daily backfill re-emits its
   full lookback window → ~3× n-inflation of the Welch t-stats feeding
   the BH-FDR gate).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from open_prep.outcomes import (
    FEATURE_KEYS,
    FEATURE_TO_WEIGHT_KEY,
    compute_feature_importance,
    prepare_outcome_snapshot,
)


def _ranked_row(symbol: str = "NVDA", **overrides) -> dict:
    row = {
        "symbol": symbol,
        "gap_pct": 3.2,
        "volume": 2_000_000,
        "avg_volume": 1_000_000,
        "score": 4.5,
        "confidence_tier": "HIGH_CONVICTION",
        "regime": "risk_on",
        "score_breakdown": {key: 0.25 for key in FEATURE_TO_WEIGHT_KEY},
    }
    row["score_breakdown"]["gap_component"] = 1.5
    row.update(overrides)
    return row


# ── 1. Snapshot persists components ─────────────────────────────────────────


class TestSnapshotComponentPersistence:
    def test_components_flattened_onto_record(self) -> None:
        records = prepare_outcome_snapshot([_ranked_row()], date(2026, 6, 11))
        rec = records[0]
        for key in FEATURE_TO_WEIGHT_KEY:
            assert key in rec, f"{key} missing from outcome record"
        assert rec["gap_component"] == 1.5
        assert rec["rvol_component"] == 0.25

    def test_missing_breakdown_yields_none_not_zero(self) -> None:
        """Absence must stay distinguishable from a genuine zero — the
        backfill era-gate keys off ``None``."""
        row = _ranked_row()
        del row["score_breakdown"]
        rec = prepare_outcome_snapshot([row], date(2026, 6, 11))[0]
        for key in FEATURE_TO_WEIGHT_KEY:
            assert rec[key] is None

    def test_partial_breakdown_missing_keys_are_none(self) -> None:
        row = _ranked_row(score_breakdown={"gap_component": 0.9})
        rec = prepare_outcome_snapshot([row], date(2026, 6, 11))[0]
        assert rec["gap_component"] == 0.9
        assert rec["rvol_component"] is None

    def test_records_json_serializable(self) -> None:
        records = prepare_outcome_snapshot([_ranked_row()], date(2026, 6, 11))
        json.dumps(records, allow_nan=False)


# ── 2. Backfill era-gate ────────────────────────────────────────────────────


class TestBackfillEraGate:
    def _patch_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        fi_dir = tmp_path / "fi"
        fi_dir.mkdir()
        monkeypatch.setattr("open_prep.outcomes.FEATURE_IMPORTANCE_DIR", fi_dir)
        return fi_dir

    def test_post_fix_records_flow_through_e2e(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """E2E: snapshot → label → backfill → non-zero components in
        fi_samples. THE regression for the c10b producer bug."""
        from open_prep.outcome_backfill import backfill_feature_importance

        records = prepare_outcome_snapshot(
            [_ranked_row()], date(2026, 6, 11),
        )
        records[0]["profitable_30m"] = True  # label arrives post-open
        records[0]["pnl_30m_pct"] = 2.0
        monkeypatch.setattr(
            "open_prep.outcomes._load_outcomes_range",
            lambda lookback_days: records,
        )
        fi_dir = self._patch_dirs(tmp_path, monkeypatch)

        assert backfill_feature_importance(lookback_days=1) == 1
        files = list(fi_dir.glob("fi_samples_*.jsonl"))
        assert len(files) == 1
        sample = json.loads(files[0].read_text().strip())
        assert sample["gap_component"] == 1.5, (
            "component value lost between snapshot and fi_sample — "
            "the all-zero producer bug is back"
        )

    def test_mixed_eras_only_complete_records_sampled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from open_prep.outcome_backfill import backfill_feature_importance

        modern = prepare_outcome_snapshot([_ranked_row()], date(2026, 6, 11))[0]
        modern["profitable_30m"] = True
        legacy = {
            "symbol": "TSLA",
            "date": "2026-05-05",
            "score": 3.0,
            "profitable_30m": False,
            "pnl_30m_pct": -1.0,
        }
        monkeypatch.setattr(
            "open_prep.outcomes._load_outcomes_range",
            lambda lookback_days: [modern, legacy],
        )
        fi_dir = self._patch_dirs(tmp_path, monkeypatch)

        assert backfill_feature_importance(lookback_days=7) == 1
        lines = [
            json.loads(line)
            for f in fi_dir.glob("fi_samples_*.jsonl")
            for line in f.read_text().splitlines()
        ]
        assert [s["symbol"] for s in lines] == ["NVDA"]

    def test_all_legacy_returns_zero_without_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from open_prep.outcome_backfill import backfill_feature_importance

        monkeypatch.setattr(
            "open_prep.outcomes._load_outcomes_range",
            lambda lookback_days: [
                {"symbol": "AMD", "date": "2026-05-01", "profitable_30m": True},
            ],
        )
        fi_dir = self._patch_dirs(tmp_path, monkeypatch)
        assert backfill_feature_importance(lookback_days=7) == 0
        assert list(fi_dir.glob("fi_samples_*.jsonl")) == []


# ── 3. (symbol, date) dedup in compute_feature_importance ──────────────────


def _fi_sample(symbol: str, run_date: str, *, win: bool, fill: float = 0.1) -> str:
    row = {key: fill for key in FEATURE_KEYS}
    row["symbol"] = symbol
    row["date"] = run_date
    row["profitable_30m"] = win
    return json.dumps(row)


class TestSampleDedup:
    def test_overlapping_files_counted_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path)
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")
        # 12 unique (symbol, date) rows, re-emitted into 3 overlapping
        # daily files — exactly the production overlap pattern.
        rows = [
            _fi_sample(f"SYM{i}", "2026-06-08", win=bool(i % 2), fill=0.1 * i)
            for i in range(12)
        ]
        for fname in (
            "fi_samples_2026-06-08.jsonl",
            "fi_samples_2026-06-09.jsonl",
            "fi_samples_2026-06-10.jsonl",
        ):
            (tmp_path / fname).write_text("\n".join(rows) + "\n", encoding="utf-8")

        report = compute_feature_importance(lookback_days=30)
        assert "error" not in report
        assert report["labeled_samples"] == 12, (
            f"expected 12 unique samples, got {report['labeled_samples']} — "
            "overlapping backfill windows are inflating n (and the Welch "
            "t-stats feeding the BH-FDR gate)"
        )
        assert report["duplicate_samples_dropped"] == 24

    def test_samples_without_keys_not_deduped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Synthetic/legacy samples lacking symbol+date stay untouched."""
        monkeypatch.setattr("open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path)
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")
        row = {key: 0.5 for key in FEATURE_KEYS}
        row["profitable_30m"] = True
        lines = [json.dumps(row)] * 12
        (tmp_path / "fi_samples_2026-06-10.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8",
        )
        report = compute_feature_importance(lookback_days=30)
        assert "error" not in report
        assert report["labeled_samples"] == 12
        assert report["duplicate_samples_dropped"] == 0
