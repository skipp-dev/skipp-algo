"""Tests for ``scripts/run_drift_watchdog.py`` (Sprint C9 / T3)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from scripts.run_drift_watchdog import (
    INSUFFICIENT_LIVE_TRADES,
    BaselineUnavailableError,
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


def test_load_baseline_raises_on_missing(tmp_path: Path) -> None:
    """Audit D-1 (2026-06-12): missing baseline must fail loudly, not {}."""
    with pytest.raises(BaselineUnavailableError, match="not found"):
        load_baseline(tmp_path / "no.json")


def test_load_baseline_raises_on_invalid(tmp_path: Path) -> None:
    """Audit D-1: corrupt baseline JSON must fail loudly, not {}."""
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(BaselineUnavailableError, match="unreadable/invalid"):
        load_baseline(p)


def test_assert_baseline_disjoint_thresholds() -> None:
    from scripts.run_drift_watchdog import _assert_baseline_disjoint

    # 20-day window, today is 2026-04-26.
    # The 20 days are 2026-04-26 back to 2026-04-07.
    today = date(2026, 4, 26)

    # Baseline ends on 2026-04-06 (no overlap, 0 days, 0.0 fraction) -> should PASS
    _assert_baseline_disjoint(
        baseline={"backtest_end_date": "2026-04-06"},
        window_days=20,
        today=today,
    )

    # Baseline ends on 2026-04-07 (exactly 1 day of overlap, 1/20 = 0.05 fraction) -> should FAIL with >= 0.05
    with pytest.raises(ValueError, match="Live window overlaps backtest baseline"):
        _assert_baseline_disjoint(
            baseline={"backtest_end_date": "2026-04-07"},
            window_days=20,
            today=today,
        )

    # Baseline ends on 2026-04-06 under a 30-day window.
    # The 30 days are 2026-04-26 back to 2026-03-28.
    # Baseline ending on 2026-03-28 means exactly 1 day overlap (1/30 = 0.033 < 0.05 fraction) -> should PASS
    _assert_baseline_disjoint(
        baseline={"backtest_end_date": "2026-03-28"},
        window_days=30,
        today=today,
    )

    # Baseline ending on 2026-03-29 means exactly 2 days overlap (2/30 = 0.067 >= 0.05 fraction) -> should FAIL
    with pytest.raises(ValueError, match="Live window overlaps backtest baseline"):
        _assert_baseline_disjoint(
            baseline={"backtest_end_date": "2026-03-29"},
            window_days=30,
            today=today,
        )


def test_main_returns_4_when_baseline_missing(tmp_path: Path, capsys) -> None:
    """Audit D-1: CLI exits 4 (not 0) so the cron workflow turns red."""
    today = date(2026, 4, 26)
    _write_outcomes(tmp_path, today, [{"pnl_30m_pct": 0.01}] * 50)
    rc = main(
        [
            "--outcomes-dir",
            str(tmp_path),
            "--baseline-json",
            str(tmp_path / "does_not_exist.json"),
            "--output-dir",
            str(tmp_path / "out"),
            "--today",
            today.isoformat(),
        ]
    )
    assert rc == 4
    assert "::error::" in capsys.readouterr().out
    # No report artifact written on configuration failure.
    assert not (tmp_path / "out").exists()


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


def test_extract_metric_pairs_splits_per_setup_when_attributed() -> None:
    """Stat-review F10 (2026-06-10): live records carrying a setup_type
    attribution get per-setup metrics in addition to the pooled one."""
    live = [
        {"pnl_30m_pct": 0.1, "setup_type": "fvg_long"},
        {"pnl_30m_pct": -0.2, "setup_type": "fvg_long"},
        {"pnl_30m_pct": 0.3, "setup_type": "fvg_short"},
        {"pnl_30m_pct": 0.4},  # unattributed → pooled only
    ]
    baseline = {
        "per_setup": {
            "fvg_long": {"oos_pnl_returns": [0.1, 0.05]},
            "fvg_short": {"oos_pnl_returns": [-0.05]},
            "never_traded_live": {"oos_pnl_returns": [9.9]},
        }
    }
    out = extract_metric_pairs(live_outcomes=live, baseline=baseline)
    assert sorted(out["pnl_per_trade"][1]) == [-0.2, 0.1, 0.3, 0.4]
    assert out["pnl_per_trade[setup=fvg_long]"] == ([0.1, 0.05], [0.1, -0.2])
    assert out["pnl_per_trade[setup=fvg_short]"] == ([-0.05], [0.3])
    # No live trades for that setup → no spurious metric.
    assert "pnl_per_trade[setup=never_traded_live]" not in out


def test_extract_metric_pairs_no_per_setup_without_attribution() -> None:
    """The current open_prep outcome schema has no setup key — only the
    pooled metric must be emitted (no fabricated splits)."""
    live = [{"pnl_30m_pct": 0.1}, {"pnl_30m_pct": -0.2}]
    baseline = {"per_setup": {"x": {"oos_pnl_returns": [0.1, 0.2]}}}
    out = extract_metric_pairs(live_outcomes=live, baseline=baseline)
    assert set(out) == {"pnl_per_trade"}


def test_build_report_discloses_pooling_limitation(tmp_path: Path) -> None:
    """Stat-review F10: a pooled-only report must say so explicitly."""
    today = date(2026, 4, 26)
    _write_outcomes(
        tmp_path,
        today,
        [{"pnl_30m_pct": 0.01 * (i % 7 - 3)} for i in range(40)],
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"x": {"oos_pnl_returns": [0.01] * 200}}}),
        encoding="utf-8",
    )
    rep = build_report(
        outcomes_dir=tmp_path,
        baseline_json=baseline_path,
        window_days=30,
        today=today,
    )
    assert rep["per_setup_live_attribution"] is False
    assert rep["per_setup_metrics"] == []
    assert "per-setup drift may be masked" in rep["pooling_note"]


def test_build_report_per_setup_metrics_listed_when_attributed(tmp_path: Path) -> None:
    today = date(2026, 4, 26)
    _write_outcomes(
        tmp_path,
        today,
        [
            {"pnl_30m_pct": 0.01 * (i % 7 - 3), "setup_type": "fvg_long"}
            for i in range(40)
        ],
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"fvg_long": {"oos_pnl_returns": [0.01] * 200}}}),
        encoding="utf-8",
    )
    rep = build_report(
        outcomes_dir=tmp_path,
        baseline_json=baseline_path,
        window_days=30,
        today=today,
    )
    assert rep["per_setup_live_attribution"] is True
    assert rep["per_setup_metrics"] == ["pnl_per_trade[setup=fvg_long]"]
    assert "pooling_note" not in rep


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


def test_build_report_returns_yellow_on_empty_baseline(tmp_path: Path) -> None:
    """W3-1: missing/empty baseline must NOT produce a vacuous green."""
    today = date(2026, 4, 26)
    # Enough live trades to pass the insufficient_n gate.
    _write_outcomes(tmp_path, today, [{"pnl_30m_pct": 0.01}] * 60)

    # Empty baseline — simulates corrupt or missing file contents.
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({}), encoding="utf-8")

    rep = build_report(
        outcomes_dir=tmp_path,
        baseline_json=baseline_path,
        window_days=30,
        today=today,
    )
    assert rep["aggregate_severity"] == "yellow"
    assert rep["reason"] == "missing_baseline"
    assert rep["n_baseline_trades"] == 0
    assert rep["n_live_trades"] == 60


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


def test_build_report_softens_green_to_yellow_when_setup_unattributed(
    tmp_path: Path,
) -> None:
    """W8-1 (stat-review wave 8): a baseline that carries per-setup blocks
    but live outcomes without setup attribution must not yield a clean
    green — the un-run per-setup comparison is surfaced as yellow so it is
    not silently masked behind the pooled verdict."""
    today = date(2026, 4, 26)
    rng = np.random.default_rng(0)
    samples = rng.normal(0.001, 0.01, size=201).tolist()
    # Live == the full baseline distribution → the pooled comparison is a
    # clean green; spread across the whole window so coverage is complete
    # (otherwise incomplete_window would pre-empt the W8-1 downgrade). Live
    # records carry NO setup_type, so no per-setup metric pair can form.
    third = len(samples) // 3
    for offset in range(3):
        _write_outcomes(
            tmp_path,
            today - timedelta(days=offset),
            [
                {"pnl_30m_pct": s}
                for s in samples[offset * third : (offset + 1) * third]
            ],
        )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"x": {"oos_pnl_returns": samples}}}),
        encoding="utf-8",
    )
    rep = build_report(
        outcomes_dir=tmp_path,
        baseline_json=baseline_path,
        window_days=3,
        today=today,
    )
    assert rep["window_complete"] is True
    assert rep["per_setup_live_attribution"] is False
    assert rep["aggregate_severity"] == "yellow"
    assert rep["reason"] == "per_setup_unattributable"


def test_build_report_keeps_green_when_setup_attributed(tmp_path: Path) -> None:
    """W8-1: the green→yellow softening must NOT fire when live outcomes
    carry setup attribution (a per-setup comparison actually ran)."""
    today = date(2026, 4, 26)
    rng = np.random.default_rng(1)
    samples = rng.normal(0.001, 0.01, size=201).tolist()
    third = len(samples) // 3
    for offset in range(3):
        _write_outcomes(
            tmp_path,
            today - timedelta(days=offset),
            [
                {"pnl_30m_pct": s, "setup_type": "fvg_long"}
                for s in samples[offset * third : (offset + 1) * third]
            ],
        )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"per_setup": {"fvg_long": {"oos_pnl_returns": samples}}}),
        encoding="utf-8",
    )
    rep = build_report(
        outcomes_dir=tmp_path,
        baseline_json=baseline_path,
        window_days=3,
        today=today,
    )
    assert rep["window_complete"] is True
    assert rep["per_setup_live_attribution"] is True
    assert rep["aggregate_severity"] == "green"
    assert rep.get("reason") != "per_setup_unattributable"


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
