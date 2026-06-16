"""Tests for scripts/collect_drift_calibration_corpus.py (issue #2798).

Covers:
- happy path: rows appended from a valid drift JSON
- duplicate guard: same (computed_at, variant) not written twice
- dry-run: rows printed but corpus file not created
- missing p0/p1 analogue: invalid drift JSON exits non-zero
- missing file: non-existent --drift-json exits non-zero
- no-variants: empty variants list emits warning, exits 0
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.collect_drift_calibration_corpus import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DRIFT_PAYLOAD = {
    "schema_version": "1.3.0",
    "computed_at": "2026-06-16T07:00:00+00:00",
    "live_window_days": 90,
    "variants": [
        {
            "variant": "smc_breaker_btc",
            "n_live_trades": 24,
            "live_sharpe": 0.71,
            "backtest_sharpe": 0.93,
            "drift_score": 0.76,
            "slippage_ks_p": 0.32,
            "slippage_ks_reference": "backtest_samples",
            "hr_in_bootstrap_ci": True,
            "overperformance_capped": False,
            "trades_per_year_live": 97.3,
            "trades_per_year_backtest": 142.1,
            "verdict": "acceptable",
        },
        {
            "variant": "smc_breaker_eth",
            "n_live_trades": 18,
            "live_sharpe": 0.55,
            "backtest_sharpe": 0.90,
            "drift_score": 0.61,
            "slippage_ks_p": None,
            "slippage_ks_reference": "unavailable",
            "hr_in_bootstrap_ci": None,
            "overperformance_capped": False,
            "trades_per_year_live": 73.0,
            "trades_per_year_backtest": 130.0,
            "verdict": "concerning",
        },
    ],
}


def _write_drift(tmp_path: Path, payload: dict | None = None) -> Path:
    p = tmp_path / "drift.json"
    p.write_text(json.dumps(payload or _DRIFT_PAYLOAD), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_writes_one_row_per_variant(self, tmp_path: Path) -> None:
        drift = _write_drift(tmp_path)
        corpus = tmp_path / "corpus.jsonl"
        rc = main(["--drift-json", str(drift), "--corpus", str(corpus)])
        assert rc == 0
        rows = [json.loads(line) for line in corpus.read_text().splitlines()]
        assert len(rows) == 2  # two variants

    def test_row_fields_present(self, tmp_path: Path) -> None:
        drift = _write_drift(tmp_path)
        corpus = tmp_path / "corpus.jsonl"
        main(["--drift-json", str(drift), "--corpus", str(corpus)])
        row = json.loads(corpus.read_text().splitlines()[0])
        required = {
            "collected_at", "computed_at", "live_window_days",
            "variant", "n_live_trades", "live_sharpe", "backtest_sharpe",
            "drift_score", "verdict", "slippage_ks_p", "hr_in_bootstrap_ci",
            "overperformance_capped", "trades_per_year_live",
            "trades_per_year_backtest", "slippage_ks_reference_type",
            "human_label",
        }
        assert required <= row.keys()

    def test_human_label_is_null(self, tmp_path: Path) -> None:
        drift = _write_drift(tmp_path)
        corpus = tmp_path / "corpus.jsonl"
        main(["--drift-json", str(drift), "--corpus", str(corpus)])
        for line in corpus.read_text().splitlines():
            assert json.loads(line)["human_label"] is None

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        drift = _write_drift(tmp_path)
        corpus = tmp_path / "a" / "b" / "corpus.jsonl"
        rc = main(["--drift-json", str(drift), "--corpus", str(corpus)])
        assert rc == 0
        assert corpus.exists()


class TestDuplicateGuard:
    def test_second_run_writes_zero_rows(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        drift = _write_drift(tmp_path)
        corpus = tmp_path / "corpus.jsonl"
        main(["--drift-json", str(drift), "--corpus", str(corpus)])
        rc = main(["--drift-json", str(drift), "--corpus", str(corpus)])
        assert rc == 0
        rows = corpus.read_text().splitlines()
        assert len(rows) == 2  # still only 2 rows from first run
        out = capsys.readouterr().out
        assert "skipped 2" in out

    def test_new_variant_appended_to_existing_corpus(self, tmp_path: Path) -> None:
        drift1 = _write_drift(tmp_path)
        corpus = tmp_path / "corpus.jsonl"
        main(["--drift-json", str(drift1), "--corpus", str(corpus)])

        payload2 = {
            **_DRIFT_PAYLOAD,
            "computed_at": "2026-06-17T07:00:00+00:00",
        }
        drift2 = tmp_path / "drift2.json"
        drift2.write_text(json.dumps(payload2), encoding="utf-8")
        rc = main(["--drift-json", str(drift2), "--corpus", str(corpus)])
        assert rc == 0
        assert len(corpus.read_text().splitlines()) == 4


class TestDryRun:
    def test_dry_run_prints_rows(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        drift = _write_drift(tmp_path)
        rc = main(["--drift-json", str(drift), "--dry-run"])
        assert rc == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["variant"] == "smc_breaker_btc"

    def test_dry_run_does_not_create_corpus(self, tmp_path: Path) -> None:
        drift = _write_drift(tmp_path)
        corpus = tmp_path / "corpus.jsonl"
        main(["--drift-json", str(drift), "--dry-run", "--corpus", str(corpus)])
        assert not corpus.exists()


class TestErrorPaths:
    def test_missing_drift_file_exits_1(self, tmp_path: Path) -> None:
        rc = main(["--drift-json", str(tmp_path / "nonexistent.json")])
        assert rc == 1

    def test_invalid_json_exits_1(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        rc = main(["--drift-json", str(bad)])
        assert rc == 1

    def test_empty_variants_exits_0(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text(json.dumps({**_DRIFT_PAYLOAD, "variants": []}), encoding="utf-8")
        corpus = tmp_path / "corpus.jsonl"
        rc = main(["--drift-json", str(empty), "--corpus", str(corpus)])
        assert rc == 0
        assert not corpus.exists()
        assert "warning" in capsys.readouterr().err.lower()
