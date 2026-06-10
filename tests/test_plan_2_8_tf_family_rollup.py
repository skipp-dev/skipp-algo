"""Tests for scripts/plan_2_8_tf_family_rollup.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.plan_2_8_tf_family_rollup import (
    build_rollup,
    main,
    render_markdown,
)


def _write_scoring(
    root: Path, symbol: str, tf: str, *, n: int, hr: float,
    families: dict[str, tuple[int, float]] | None = None,
) -> None:
    d = root / symbol / tf
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "symbol": symbol,
        "timeframe": tf,
        "n_events": n,
        "hit_rate": hr,
        "family_metrics": {
            fam: {"n_events": fn, "hit_rate": fhr}
            for fam, (fn, fhr) in (families or {}).items()
        },
    }
    (d / f"scoring_{symbol}_{tf}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_rollup_aggregates_per_tf(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "5m", n=100, hr=0.6,
                   families={"FVG": (50, 0.55), "OB": (50, 0.65)})
    _write_scoring(tmp_path, "MSFT", "5m", n=200, hr=0.7,
                   families={"FVG": (100, 0.65), "OB": (100, 0.75)})
    rollup = build_rollup(scoring_root=tmp_path, timeframes=("5m",))
    slot = rollup["per_tf"]["5m"]
    assert slot["n_events"] == 300
    # Weighted HR: (0.6*100 + 0.7*200) / 300 = 200/300 = 0.6667
    assert round(slot["hit_rate"], 4) == round((60 + 140) / 300, 4)
    assert set(slot["symbols"]) == {"AAPL", "MSFT"}
    fvg = slot["families"]["FVG"]
    assert fvg["n_events"] == 150
    assert round(fvg["hit_rate"], 4) == round((0.55 * 50 + 0.65 * 100) / 150, 4)


def test_rollup_partitions_multiple_tfs(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "5m", n=100, hr=0.5)
    _write_scoring(tmp_path, "AAPL", "1H", n=50, hr=0.8)
    rollup = build_rollup(scoring_root=tmp_path)
    assert rollup["per_tf"]["5m"]["n_events"] == 100
    assert rollup["per_tf"]["1H"]["n_events"] == 50
    assert rollup["per_tf"]["15m"]["n_events"] == 0
    assert rollup["per_tf"]["4H"]["n_events"] == 0


def test_rollup_phase_e2_verdict_measured(tmp_path: Path) -> None:
    # FVG 5m (n=200, hr=0.65) vs merged 15m+1H baseline (n=150, hr=0.58)
    _write_scoring(tmp_path, "AAPL", "5m", n=200, hr=0.65,
                   families={"FVG": (200, 0.65)})
    _write_scoring(tmp_path, "AAPL", "15m", n=100, hr=0.60,
                   families={"FVG": (100, 0.60)})
    _write_scoring(tmp_path, "AAPL", "1H", n=50, hr=0.55,
                   families={"FVG": (50, 0.55)})
    # BOS 4H (n=80, hr=0.92) vs baseline (n=100, hr=0.88)
    _write_scoring(tmp_path, "AAPL", "4H", n=80, hr=0.92,
                   families={"BOS": (80, 0.92)})
    _write_scoring(tmp_path, "MSFT", "15m", n=60, hr=0.87,
                   families={"BOS": (60, 0.87)})
    _write_scoring(tmp_path, "MSFT", "1H", n=40, hr=0.89,
                   families={"BOS": (40, 0.89)})
    rollup = build_rollup(scoring_root=tmp_path)
    fvg = rollup["phase_e2_verdict"]["fvg_ttf_5m_vs_baseline"]
    assert fvg["status"] == "measured"
    assert fvg["n_a"] == 200
    assert fvg["n_b"] == 150
    assert round(fvg["delta_hr"], 4) == round(0.65 - ((0.60 * 100 + 0.55 * 50) / 150), 4)
    bos = rollup["phase_e2_verdict"]["bos_stability_4h_vs_baseline"]
    assert bos["status"] == "measured"
    assert bos["n_a"] == 80


def test_rollup_insufficient_data_when_under_threshold(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "5m", n=10, hr=0.5,
                   families={"FVG": (10, 0.5)})
    _write_scoring(tmp_path, "AAPL", "15m", n=10, hr=0.5,
                   families={"FVG": (10, 0.5)})
    rollup = build_rollup(scoring_root=tmp_path)
    verdict = rollup["phase_e2_verdict"]["fvg_ttf_5m_vs_baseline"]
    assert verdict["status"] == "insufficient_data"


def test_rollup_phase_e2_verdict_degenerate_when_slices_aliased(tmp_path: Path) -> None:
    # Cross-TF aliasing guard (2026-06-10 ADR): the legacy structure
    # artifact served one timeframe's events to every TF, so all
    # TF/family slices became identical clones and delta_hr compared an
    # arm against itself. Fixture mirrors the real production shape.
    for tf in ("5m", "15m", "1H", "4H"):
        _write_scoring(tmp_path, "AAPL", tf, n=367, hr=0.5516,
                       families={"FVG": (320, 0.571875),
                                 "BOS": (47, 0.7659553191489361)})
    rollup = build_rollup(scoring_root=tmp_path)
    fvg = rollup["phase_e2_verdict"]["fvg_ttf_5m_vs_baseline"]
    assert fvg["status"] == "degenerate_aliased_input"
    assert fvg["n_a"] == 320
    assert fvg["n_b"] == 640
    assert fvg["hr_a"] == fvg["hr_b"]
    assert "reason" in fvg
    assert "delta_hr" not in fvg
    bos = rollup["phase_e2_verdict"]["bos_stability_4h_vs_baseline"]
    assert bos["status"] == "degenerate_aliased_input"
    assert bos["n_a"] == 47


def test_rollup_phase_e2_verdict_not_degenerate_when_any_slice_differs(tmp_path: Path) -> None:
    # One honest baseline slice with a different hit rate must keep the
    # verdict "measured" — the guard only fires on full pairwise identity.
    _write_scoring(tmp_path, "AAPL", "5m", n=320, hr=0.571875,
                   families={"FVG": (320, 0.571875)})
    _write_scoring(tmp_path, "AAPL", "15m", n=320, hr=0.571875,
                   families={"FVG": (320, 0.571875)})
    _write_scoring(tmp_path, "AAPL", "1H", n=320, hr=0.60,
                   families={"FVG": (320, 0.60)})
    rollup = build_rollup(scoring_root=tmp_path)
    fvg = rollup["phase_e2_verdict"]["fvg_ttf_5m_vs_baseline"]
    assert fvg["status"] == "measured"
    assert "delta_hr" in fvg


def test_rollup_missing_family_reports_missing(tmp_path: Path) -> None:
    rollup = build_rollup(scoring_root=tmp_path)
    assert rollup["phase_e2_verdict"]["fvg_ttf_5m_vs_baseline"]["status"] == "missing"
    assert rollup["phase_e2_verdict"]["bos_stability_4h_vs_baseline"]["status"] == "missing"


def test_rollup_flags_unknown_timeframe(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "3m", n=10, hr=0.5)
    rollup = build_rollup(scoring_root=tmp_path)
    assert rollup["unknown_timeframes"] == {"3m": 1}


def test_rollup_tolerates_unreadable_file(tmp_path: Path) -> None:
    d = tmp_path / "AAPL" / "5m"
    d.mkdir(parents=True)
    (d / "scoring_AAPL_5m.json").write_text("{ not valid json", encoding="utf-8")
    rollup = build_rollup(scoring_root=tmp_path)
    assert rollup["files_scanned"] == 1
    assert rollup["per_tf"]["5m"]["n_events"] == 0
    # Stat-review F9: unreadable files are counted, not silently dropped.
    assert rollup["n_skipped_malformed"] == 1
    assert "scoring_AAPL_5m.json" in rollup["skipped_malformed"][0]


# ── Stat-review F9: malformed-row skip-and-count ─────────────────────


def test_rollup_skips_and_counts_null_hit_rate(tmp_path: Path) -> None:
    # The old `float(payload.get("hit_rate") or 0.0)` laundered
    # hit_rate: null into 40 events at 0.0 HR, dragging the aggregate
    # down (kills a good variant). It must be skipped and counted.
    d = tmp_path / "AAPL" / "5m"
    d.mkdir(parents=True)
    (d / "scoring_AAPL_5m.json").write_text(
        json.dumps({"n_events": 40, "hit_rate": None}), encoding="utf-8"
    )
    _write_scoring(tmp_path, "MSFT", "5m", n=100, hr=0.6)
    rollup = build_rollup(scoring_root=tmp_path)
    slot = rollup["per_tf"]["5m"]
    assert slot["n_events"] == 100
    assert slot["hit_rate"] == pytest.approx(0.6)
    assert rollup["n_skipped_malformed"] == 1
    assert "scoring_AAPL_5m.json" in rollup["skipped_malformed"][0]


def test_rollup_skips_and_counts_malformed_family_row(tmp_path: Path) -> None:
    d = tmp_path / "AAPL" / "5m"
    d.mkdir(parents=True)
    (d / "scoring_AAPL_5m.json").write_text(
        json.dumps({
            "n_events": 100,
            "hit_rate": 0.6,
            "family_metrics": {
                "FVG": {"n_events": 50, "hit_rate": None},
                "OB": {"n_events": 50, "hit_rate": 0.7},
            },
        }),
        encoding="utf-8",
    )
    rollup = build_rollup(scoring_root=tmp_path)
    slot = rollup["per_tf"]["5m"]
    # File-level metrics still aggregate; only the malformed family row
    # is skipped and counted.
    assert slot["n_events"] == 100
    assert "FVG" not in slot["families"]
    assert slot["families"]["OB"]["n_events"] == 50
    assert rollup["n_skipped_malformed"] == 1
    assert "family=FVG" in rollup["skipped_malformed"][0]


def test_rollup_well_formed_inputs_report_zero_skipped(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "5m", n=100, hr=0.6)
    rollup = build_rollup(scoring_root=tmp_path)
    assert rollup["n_skipped_malformed"] == 0
    assert rollup["skipped_malformed"] == []


# ── Stat-review F8: uncertainty on "measured" verdicts ──────────────


def test_rollup_measured_verdict_carries_p_value(tmp_path: Path) -> None:
    # Large delta at large n → small two-sided p-value.
    _write_scoring(tmp_path, "AAPL", "5m", n=500, hr=0.80,
                   families={"FVG": (500, 0.80)})
    _write_scoring(tmp_path, "AAPL", "15m", n=500, hr=0.50,
                   families={"FVG": (500, 0.50)})
    rollup = build_rollup(scoring_root=tmp_path)
    fvg = rollup["phase_e2_verdict"]["fvg_ttf_5m_vs_baseline"]
    assert fvg["status"] == "measured"
    assert fvg["delta_hr_p_value"] is not None
    assert fvg["delta_hr_p_value"] < 0.001


def test_rollup_small_delta_at_floor_has_large_p_value(tmp_path: Path) -> None:
    # The finding's example: a 5pp delta at the n=30 floor is
    # indistinguishable from noise — the p-value must say so.
    _write_scoring(tmp_path, "AAPL", "5m", n=30, hr=0.55,
                   families={"FVG": (30, 0.55)})
    _write_scoring(tmp_path, "AAPL", "15m", n=30, hr=0.50,
                   families={"FVG": (30, 0.50)})
    rollup = build_rollup(scoring_root=tmp_path)
    fvg = rollup["phase_e2_verdict"]["fvg_ttf_5m_vs_baseline"]
    assert fvg["status"] == "measured"
    assert fvg["delta_hr_p_value"] > 0.3


def test_rollup_degenerate_proportions_yield_none_p_value(tmp_path: Path) -> None:
    # All-hit on both arms → pooled variance degenerate → p None, not 0/1.
    _write_scoring(tmp_path, "AAPL", "5m", n=40, hr=1.0,
                   families={"FVG": (40, 1.0)})
    _write_scoring(tmp_path, "AAPL", "15m", n=35, hr=1.0,
                   families={"FVG": (35, 1.0)})
    rollup = build_rollup(scoring_root=tmp_path)
    fvg = rollup["phase_e2_verdict"]["fvg_ttf_5m_vs_baseline"]
    # n differs so the aliasing guard does not fire; hit rates identical.
    assert fvg["status"] == "measured"
    assert fvg["delta_hr_p_value"] is None


def test_render_markdown_includes_sections(tmp_path: Path) -> None:
    _write_scoring(tmp_path, "AAPL", "5m", n=100, hr=0.6)
    rollup = build_rollup(scoring_root=tmp_path)
    md = render_markdown(rollup)
    assert "# Chart-TF rollup" in md
    assert "## Per-TF aggregate" in md
    assert "## Phase E2 verdicts" in md
    assert "`5m`" in md


def test_cli_writes_output_and_prints_md(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_scoring(tmp_path, "AAPL", "5m", n=100, hr=0.6)
    out = tmp_path / "rollup.json"
    rc = main([
        "--scoring-root", str(tmp_path),
        "--output", str(out),
    ])
    assert rc == 0
    stdout = capsys.readouterr().out
    assert "Chart-TF rollup" in stdout
    assert json.loads(out.read_text(encoding="utf-8"))["schema_version"] == 1


def test_cli_json_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_scoring(tmp_path, "AAPL", "5m", n=10, hr=0.5)
    rc = main([
        "--scoring-root", str(tmp_path),
        "--format", "json",
    ])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["schema_version"] == 1


def test_cli_quiet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_scoring(tmp_path, "AAPL", "5m", n=10, hr=0.5)
    out = tmp_path / "r.json"
    rc = main([
        "--scoring-root", str(tmp_path),
        "--output", str(out),
        "--quiet",
    ])
    assert rc == 0
    assert capsys.readouterr().out == ""
    assert out.exists()


def test_cli_custom_timeframes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_scoring(tmp_path, "AAPL", "5m", n=10, hr=0.5)
    _write_scoring(tmp_path, "AAPL", "3m", n=10, hr=0.5)
    rc = main([
        "--scoring-root", str(tmp_path),
        "--timeframes", "5m,3m",
        "--format", "json",
    ])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert set(parsed["per_tf"].keys()) == {"5m", "3m"}
