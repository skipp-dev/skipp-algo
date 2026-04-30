"""Tests for ``scripts/run_drift_watchdog.py`` (Sprint C9 / T3)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from scripts.run_drift_watchdog import (
    INSUFFICIENT_LIVE_TRADES,
    build_report,
    extract_metric_pairs,
    load_baseline,
    load_live_outcomes,
    load_live_outcomes_with_coverage,
    main,
    write_report,
)

# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _write_outcomes(dir_: Path, day: date, records: list[dict]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"outcomes_{day.isoformat()}.json").write_text(
        json.dumps(records), encoding="utf-8"
    )


def test_load_live_outcomes_filters_by_window(tmp_path: Path) -> None:
    today = date(2026, 4, 26)
    _write_outcomes(tmp_path, today, [{"pnl_30m_pct": 0.5}])
    _write_outcomes(tmp_path, today - timedelta(days=10), [{"pnl_30m_pct": 0.4}])
    _write_outcomes(tmp_path, today - timedelta(days=40), [{"pnl_30m_pct": -1.0}])
    _write_outcomes(tmp_path, today + timedelta(days=5), [{"pnl_30m_pct": 99.0}])
    out = load_live_outcomes(tmp_path, window_days=30, today=today)
    assert len(out) == 2
    assert {-1.0, 99.0}.isdisjoint({o["pnl_30m_pct"] for o in out})


def test_load_live_outcomes_returns_empty_on_missing_dir(tmp_path: Path) -> None:
    assert load_live_outcomes(tmp_path / "missing", window_days=30, today=date.today()) == []


def test_load_live_outcomes_skips_malformed_files(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "outcomes_2026-04-25.json").write_text("not-json", encoding="utf-8")
    (tmp_path / "outcomes_garbage.json").write_text("[]", encoding="utf-8")
    out = load_live_outcomes(tmp_path, window_days=30, today=date(2026, 4, 26))
    assert out == []


def test_load_baseline_returns_empty_on_missing(tmp_path: Path) -> None:
    assert load_baseline(tmp_path / "no.json") == {}


def test_load_baseline_returns_empty_on_invalid(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    assert load_baseline(p) == {}


# ---------------------------------------------------------------------------
# extract_metric_pairs
# ---------------------------------------------------------------------------


def test_extract_metric_pairs_pnl_only() -> None:
    live = [{"pnl_30m_pct": 0.1}, {"pnl_30m_pct": -0.2}, {"pnl_30m_pct": None}]
    baseline = {
        "per_setup": {
            "fvg_long": {"oos_pnl_returns": [0.1, 0.05, -0.1]},
            "fvg_short": {"oos_pnl_returns": [-0.05, 0.0]},
        }
    }
    out = extract_metric_pairs(live_outcomes=live, baseline=baseline)
    assert "pnl_per_trade" in out
    base, live_p = out["pnl_per_trade"]
    assert sorted(base) == [-0.1, -0.05, 0.0, 0.05, 0.1]
    assert sorted(live_p) == [-0.2, 0.1]  # None filtered


def test_extract_metric_pairs_handles_missing_baseline_keys() -> None:
    out = extract_metric_pairs(
        live_outcomes=[{"pnl_30m_pct": 0.1}],
        baseline={},
    )
    assert out["pnl_per_trade"] == ([], [0.1])


# ---------------------------------------------------------------------------
# build_report — orchestration
# ---------------------------------------------------------------------------


def test_build_report_returns_yellow_when_n_below_floor(tmp_path: Path) -> None:
    today = date(2026, 4, 26)
    _write_outcomes(tmp_path, today, [{"pnl_30m_pct": 0.1}] * 5)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"x": {"oos_pnl_returns": [0.1] * 100}}}),
        encoding="utf-8",
    )

    rep = build_report(
        outcomes_dir=tmp_path,
        baseline_json=baseline_path,
        window_days=30,
        today=today,
    )
    assert rep["aggregate_severity"] == "yellow"
    assert rep["reason"] == "insufficient_n"
    assert rep["n_live_trades"] == 5
    assert rep["min_required"] == INSUFFICIENT_LIVE_TRADES


def test_build_report_returns_green_when_distributions_match(tmp_path: Path) -> None:
    today = date(2026, 4, 26)
    rng = np.random.default_rng(0)
    samples = rng.normal(0.001, 0.01, size=200).tolist()
    _write_outcomes(tmp_path, today, [{"pnl_30m_pct": s} for s in samples[:60]])

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"x": {"oos_pnl_returns": samples}}}),
        encoding="utf-8",
    )
    rep = build_report(
        outcomes_dir=tmp_path,
        baseline_json=baseline_path,
        window_days=30,
        today=today,
    )
    assert rep["aggregate_severity"] in ("green", "yellow")
    assert rep["n_live_trades"] == 60
    assert rep["window_days"] == 30


def test_build_report_returns_red_when_live_drifts(tmp_path: Path) -> None:
    today = date(2026, 4, 26)
    rng = np.random.default_rng(0)
    baseline_samples = rng.normal(0.001, 0.01, size=400).tolist()
    live_samples = rng.normal(0.05, 0.01, size=80).tolist()  # large mean shift

    _write_outcomes(tmp_path, today, [{"pnl_30m_pct": s} for s in live_samples])
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"x": {"oos_pnl_returns": baseline_samples}}}),
        encoding="utf-8",
    )
    rep = build_report(
        outcomes_dir=tmp_path,
        baseline_json=baseline_path,
        window_days=30,
        today=today,
    )
    assert rep["aggregate_severity"] == "red"


def test_build_report_softens_green_to_yellow_on_incomplete_window(
    tmp_path: Path,
) -> None:
    """C9 deep-review: incomplete date coverage must not look "green"."""
    today = date(2026, 4, 26)
    rng = np.random.default_rng(0)
    samples = rng.normal(0.001, 0.01, size=200).tolist()
    # Write live outcomes for ONLY 1 of the 30 expected days.
    _write_outcomes(tmp_path, today, [{"pnl_30m_pct": s} for s in samples[:60]])
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"x": {"oos_pnl_returns": samples}}}),
        encoding="utf-8",
    )
    rep = build_report(
        outcomes_dir=tmp_path,
        baseline_json=baseline_path,
        window_days=30,
        today=today,
    )
    assert rep["window_complete"] is False
    cov = rep["window_coverage"]
    assert cov["days_present"] == 1
    assert cov["days_expected"] == 30
    assert len(cov["missing_dates"]) == 29
    # If the underlying KS/PSI verdict was green, it must now be yellow.
    if rep.get("reason") == "incomplete_window":
        assert rep["aggregate_severity"] == "yellow"


def test_load_live_outcomes_with_coverage_complete(tmp_path: Path) -> None:
    today = date(2026, 4, 26)
    for offset in range(3):
        _write_outcomes(
            tmp_path,
            today - timedelta(days=offset),
            [{"pnl_30m_pct": 0.01 * offset}],
        )
    _, cov = load_live_outcomes_with_coverage(tmp_path, window_days=3, today=today)
    assert cov["window_complete"] is True
    assert cov["days_present"] == 3
    assert cov["missing_dates"] == []


def test_load_live_outcomes_with_coverage_does_not_admit_dates_outside_window(
    tmp_path: Path,
) -> None:
    """Regression for Copilot review on PR #304: an off-by-one between
    the cutoff filter (``file_date < today - timedelta(days=window_days)``)
    and the expected window (last ``window_days`` calendar days from
    ``today``) previously admitted one extra older date, inflating
    ``days_present`` past ``days_expected``.
    """
    today = date(2026, 4, 26)
    # Write 3 in-window dates + 1 older outlier exactly on the
    # previous boundary (today - window_days).
    for offset in range(3):
        _write_outcomes(tmp_path, today - timedelta(days=offset), [{"pnl_30m_pct": 0.01}])
    _write_outcomes(tmp_path, today - timedelta(days=3), [{"pnl_30m_pct": 0.99}])
    out, cov = load_live_outcomes_with_coverage(tmp_path, window_days=3, today=today)
    assert cov["days_present"] == 3
    assert cov["days_expected"] == 3
    assert cov["window_complete"] is True
    # Outlier value 0.99 must NOT have been loaded.
    assert all(rec["pnl_30m_pct"] != 0.99 for rec in out)


# ---------------------------------------------------------------------------
# write_report — atomic write
# ---------------------------------------------------------------------------


def test_write_report_creates_atomic_json(tmp_path: Path) -> None:
    rep = {"aggregate_severity": "green", "findings": []}
    target = write_report(rep, output_dir=tmp_path, run_date=date(2026, 4, 26))
    assert target.exists()
    assert target.name == "drift_report_2026-04-26.json"
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed["aggregate_severity"] == "green"
    # No leftover .tmp files from the atomic-write helper.
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_main_writes_report_and_returns_zero(tmp_path: Path, capsys) -> None:
    today = date(2026, 4, 26)
    _write_outcomes(tmp_path, today, [{"pnl_30m_pct": 0.01}] * 50)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"x": {"oos_pnl_returns": [0.01] * 200}}}),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--outcomes-dir",
            str(tmp_path),
            "--baseline-json",
            str(baseline_path),
            "--output-dir",
            str(out_dir),
            "--today",
            today.isoformat(),
        ]
    )
    assert rc == 0
    assert (out_dir / f"drift_report_{today.isoformat()}.json").exists()
    captured = capsys.readouterr().out
    assert "aggregate_severity" in captured


def test_main_exit_nonzero_on_red(tmp_path: Path) -> None:
    today = date(2026, 4, 26)
    rng = np.random.default_rng(0)
    baseline = rng.normal(0.001, 0.01, size=400).tolist()
    live = rng.normal(0.1, 0.01, size=60).tolist()
    _write_outcomes(tmp_path, today, [{"pnl_30m_pct": s} for s in live])
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"x": {"oos_pnl_returns": baseline}}}),
        encoding="utf-8",
    )

    rc = main(
        [
            "--outcomes-dir",
            str(tmp_path),
            "--baseline-json",
            str(baseline_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--today",
            today.isoformat(),
            "--exit-nonzero-on-red",
        ]
    )
    assert rc == 2
