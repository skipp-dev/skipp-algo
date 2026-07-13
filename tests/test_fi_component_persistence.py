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
from datetime import date, timedelta
from pathlib import Path

import pytest

from open_prep.outcomes import (
    _DIRECTIONAL_LABEL_ERA_CUTOFF,
    _SCORE_FORMULA_ERA_CUTOFF,
    FEATURE_KEYS,
    FEATURE_TO_WEIGHT_KEY,
    compute_feature_importance,
    prepare_outcome_snapshot,
)

# Bound at import time — the module-level autouse fixture below monkeypatches
# the module attribute, so a later read would see the neutralized value.
_DIRECTIONAL_CUTOFF_REAL = _DIRECTIONAL_LABEL_ERA_CUTOFF

# Derive every formula-era fixture date from the production cutoff constant so
# the next cutoff bump can't silently re-break these fixtures the way this suite
# had to be repaired for the 2026-07-02 cutoff.
_CUTOFF = _SCORE_FORMULA_ERA_CUTOFF
_AT_CUTOFF = _CUTOFF.isoformat()  # kept: formula-era gate is strict `<`
_POST_CUTOFF_1 = (_CUTOFF + timedelta(days=1)).isoformat()
_POST_CUTOFF_2 = (_CUTOFF + timedelta(days=2)).isoformat()
_PRE_CUTOFF = (_CUTOFF - timedelta(days=1)).isoformat()  # dropped by formula-era gate
_LEGACY_DATE = (_CUTOFF - timedelta(days=31)).isoformat()  # pre-fix all-zero rows


@pytest.fixture(autouse=True)
def _directional_era_gate_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    # These fixtures pin the D-2 all-zero / formula-era / dedup gates with
    # dates derived from the FORMULA cutoff, which predate the (newer)
    # directional-label cutover — neutralize that gate here so each test keeps
    # pinning exactly one gate. The directional gate has its own dedicated
    # tests (TestDirectionalEraGate below).
    monkeypatch.setattr("open_prep.outcomes._DIRECTIONAL_LABEL_ERA_CUTOFF", date(2020, 1, 1))


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
        # fill starts at 0.1 (not 0.0): an all-zero weighted vector would
        # be era-gated as a legacy row (audit D-2) and skew the count.
        rows = [
            _fi_sample(f"SYM{i}", _AT_CUTOFF, win=bool(i % 2), fill=0.1 * (i + 1))
            for i in range(12)
        ]
        for fname in (
            f"fi_samples_{_AT_CUTOFF}.jsonl",
            f"fi_samples_{_POST_CUTOFF_1}.jsonl",
            f"fi_samples_{_POST_CUTOFF_2}.jsonl",
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
        (tmp_path / f"fi_samples_{_LEGACY_DATE}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8",
        )
        report = compute_feature_importance(lookback_days=30)
        assert "error" not in report
        assert report["labeled_samples"] == 12
        assert report["duplicate_samples_dropped"] == 0


# ── 4. Reader-side era-gate (audit D-2, 2026-06-12) ───────────────────────────


def _legacy_zero_sample(symbol: str, run_date: str, *, win: bool) -> str:
    """A pre-2026-06-11 row: all weighted components literal 0.0."""
    row = {key: 0.0 for key in FEATURE_KEYS}
    row["zone_priority_score"] = 0.7  # pass-through key was always real
    row["symbol"] = symbol
    row["date"] = run_date
    row["profitable_30m"] = win
    return json.dumps(row)


class TestReaderEraGate:
    """The 2026-06-11 fix era-gated only the writer; legacy all-zero rows
    still on disk must not poison the report matrix (audit D-2)."""

    def test_mixed_eras_drops_legacy_zero_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path)
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")
        legacy = [
            _legacy_zero_sample(f"OLD{i}", _LEGACY_DATE, win=bool(i % 2))
            for i in range(8)
        ]
        clean = [
            _fi_sample(f"NEW{i}", _AT_CUTOFF, win=bool(i % 2), fill=0.1 * (i + 1))
            for i in range(12)
        ]
        (tmp_path / f"fi_samples_{_LEGACY_DATE}.jsonl").write_text(
            "\n".join(legacy) + "\n", encoding="utf-8",
        )
        (tmp_path / f"fi_samples_{_AT_CUTOFF}.jsonl").write_text(
            "\n".join(clean) + "\n", encoding="utf-8",
        )

        report = compute_feature_importance(lookback_days=30)
        assert "error" not in report
        assert report["era_gated_samples_dropped"] == 8
        assert report["labeled_samples"] == 12, (
            "legacy all-zero rows must not enter the feature matrix — "
            "they flatten every importance to 0.00 (audit D-2)"
        )

    def test_all_legacy_yields_insufficient_not_vacuous(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Only-legacy input must surface as 'insufficient', never as a
        confident all-zero-importance report."""
        monkeypatch.setattr("open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path)
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")
        legacy = [
            _legacy_zero_sample(f"OLD{i}", _LEGACY_DATE, win=bool(i % 2))
            for i in range(20)
        ]
        (tmp_path / f"fi_samples_{_LEGACY_DATE}.jsonl").write_text(
            "\n".join(legacy) + "\n", encoding="utf-8",
        )

        report = compute_feature_importance(lookback_days=30)
        assert report.get("error") == "insufficient labeled samples"
        assert report["era_gated_samples_dropped"] == 20
        assert report["labeled_samples"] == 0

    def test_genuine_zero_in_some_components_survives(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A clean row where SOME weighted components are genuinely 0.0
        must NOT be era-gated — only the all-zero vector is poisoned."""
        monkeypatch.setattr("open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path)
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")
        rows = []
        for i in range(12):
            row = json.loads(
                _fi_sample(f"SYM{i}", _AT_CUTOFF, win=bool(i % 2), fill=0.0)
            )
            row["gap_component"] = 0.5 + 0.1 * i  # one real non-zero component
            rows.append(json.dumps(row))
        (tmp_path / f"fi_samples_{_AT_CUTOFF}.jsonl").write_text(
            "\n".join(rows) + "\n", encoding="utf-8",
        )

        report = compute_feature_importance(lookback_days=30)
        assert "error" not in report
        assert report["era_gated_samples_dropped"] == 0
        assert report["labeled_samples"] == 12


# ── 5. Formula-era gate (2026-07-02, PR #3114) ────────────────────────────────


class TestFormulaEraGate:
    """Rows scored before the component-cap rewrite live on a different
    feature scale; pooling them with post-rewrite rows poisons the stats.
    The all-zero D-2 gate can't catch a *clean* pre-cutoff row (fill>0), so
    the formula-era date gate is the only thing that drops it — this suite is
    its only coverage (regression for the drop path at outcomes.py)."""

    def test_clean_pre_cutoff_rows_dropped_by_formula_era_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path)
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")
        # Clean pre-cutoff rows: fill>0 so they survive the all-zero D-2 gate
        # and reach the formula-era gate, which must drop them for being
        # scored on the pre-rewrite feature scale.
        pre = [
            _fi_sample(f"PRE{i}", _PRE_CUTOFF, win=bool(i % 2), fill=0.1 * (i + 1))
            for i in range(4)
        ]
        post = [
            _fi_sample(f"NEW{i}", _AT_CUTOFF, win=bool(i % 2), fill=0.1 * (i + 1))
            for i in range(12)
        ]
        (tmp_path / f"fi_samples_{_PRE_CUTOFF}.jsonl").write_text(
            "\n".join(pre) + "\n", encoding="utf-8",
        )
        (tmp_path / f"fi_samples_{_AT_CUTOFF}.jsonl").write_text(
            "\n".join(post) + "\n", encoding="utf-8",
        )

        report = compute_feature_importance(lookback_days=30)
        assert "error" not in report
        assert report["era_gated_samples_dropped"] == 0, (
            "clean fill>0 rows must not be caught by the all-zero D-2 gate"
        )
        assert report["formula_era_samples_dropped"] == 4, (
            "clean rows dated before the cutoff must be dropped by the "
            "formula-era gate — flipping `<` to `<=`/`>` would leak the "
            "pre-rewrite feature scale into the matrix"
        )
        assert report["labeled_samples"] == 12, (
            "pre-cutoff rows must be excluded from the feature matrix"
        )

    def test_row_exactly_at_cutoff_is_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The gate is strict `<`: a row dated exactly on the cutoff is
        post-rewrite and must survive."""
        monkeypatch.setattr("open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path)
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")
        rows = [
            _fi_sample(f"AT{i}", _AT_CUTOFF, win=bool(i % 2), fill=0.1 * (i + 1))
            for i in range(12)
        ]
        (tmp_path / f"fi_samples_{_AT_CUTOFF}.jsonl").write_text(
            "\n".join(rows) + "\n", encoding="utf-8",
        )

        report = compute_feature_importance(lookback_days=30)
        assert "error" not in report
        assert report["formula_era_samples_dropped"] == 0
        assert report["labeled_samples"] == 12


class TestDirectionalEraGate:
    """Directional-label era gate (2026-07-13): pre-cutover fi_samples carry
    the legacy long-only label and must not mix with directional-era rows."""

    @pytest.fixture(autouse=True)
    def _real_directional_cutoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Re-arm the real cutoff (the module-level fixture neutralizes it).
        monkeypatch.setattr(
            "open_prep.outcomes._DIRECTIONAL_LABEL_ERA_CUTOFF", _DIRECTIONAL_CUTOFF_REAL,
        )

    def test_pre_cutover_rows_dropped_post_cutover_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path)
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")
        pre_date = (_DIRECTIONAL_CUTOFF_REAL - timedelta(days=1)).isoformat()
        at_date = _DIRECTIONAL_CUTOFF_REAL.isoformat()  # strict `<`: kept
        pre = [
            _fi_sample(f"OLD{i}", pre_date, win=bool(i % 2), fill=0.1 * (i + 1))
            for i in range(4)
        ]
        post = [
            _fi_sample(f"NEW{i}", at_date, win=bool(i % 2), fill=0.1 * (i + 1))
            for i in range(12)
        ]
        (tmp_path / f"fi_samples_{pre_date}.jsonl").write_text(
            "\n".join(pre) + "\n", encoding="utf-8",
        )
        (tmp_path / f"fi_samples_{at_date}.jsonl").write_text(
            "\n".join(post) + "\n", encoding="utf-8",
        )

        report = compute_feature_importance(lookback_days=30)
        assert "error" not in report
        assert report["directional_era_samples_dropped"] == 4, (
            "rows dated before the directional-label cutover carry the "
            "long-only label and must be excluded from the FI matrix"
        )
        assert report["labeled_samples"] == 12
