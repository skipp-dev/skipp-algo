"""Tests for ``scripts.build_promotion_gate_dashboard`` (closes #2354)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts.build_promotion_gate_dashboard import (
    DASHBOARD_SCHEMA_VERSION,
    METRIC_KEYS,
    build,
    main,
)

FAMILIES = ("BOS", "OB", "FVG")
REFERENCE = date(2026, 5, 25)  # Monday, ISO week 2026-W22.


def _synthetic_report(generated_at: datetime, week_index: int) -> dict[str, object]:
    """Build a minimal report matching ``REPORT_SCHEMA_VERSION=1`` shape."""
    decisions = []
    for family in FAMILIES:
        decisions.append(
            {
                "schema_version": 2,
                "family": family,
                "promoted": True,
                "posture": "live",
                "blockers": [],
                "metrics": {
                    "brier": 0.10 + 0.001 * week_index,
                    "ece": 0.02 + 0.001 * week_index,
                    "fdr_pvalue": 0.01 + 0.001 * week_index,
                    "psr": 0.97 - 0.001 * week_index,
                    "psi": 0.05 + 0.001 * week_index,
                },
                "provenance": {},
            }
        )
    return {
        "schema_version": 1,
        "gate_schema_version": 2,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "strict_provenance": False,
        "decisions": decisions,
    }


def _seed_archive(source_dir: Path, weeks: int) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    anchor = datetime.combine(REFERENCE, datetime.min.time(), tzinfo=UTC)
    for offset in range(weeks):
        moment = anchor - timedelta(weeks=offset)
        report = _synthetic_report(moment, week_index=offset)
        (source_dir / f"promotion_decisions_{moment.date().isoformat()}.json").write_text(
            json.dumps(report) + "\n", encoding="utf-8"
        )


def test_build_aggregates_full_window(tmp_path: Path) -> None:
    source_dir = tmp_path / "promotion_decisions"
    output_dir = tmp_path / "out"
    _seed_archive(source_dir, weeks=12)

    written = build(
        source_dir=source_dir,
        output_dir=output_dir,
        lookback_weeks=12,
        reference_date=REFERENCE,
        render_png=False,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    assert payload["schema_version"] == DASHBOARD_SCHEMA_VERSION
    assert payload["lookback_weeks"] == 12
    assert payload["reference_date"] == REFERENCE.isoformat()
    points = payload["points"]
    # 3 families × 12 weeks = 36 aggregated weekly points.
    assert len(points) == len(FAMILIES) * 12
    families = {p["family"] for p in points}
    assert families == set(FAMILIES)
    for point in points:
        for key in METRIC_KEYS:
            assert key in point
            assert point[key] is not None
    assert payload["gate_thresholds"]["brier_max"] > 0.0


def test_build_handles_empty_source_dir(tmp_path: Path) -> None:
    source_dir = tmp_path / "missing"
    output_dir = tmp_path / "out"

    written = build(
        source_dir=source_dir,
        output_dir=output_dir,
        lookback_weeks=4,
        reference_date=REFERENCE,
        render_png=False,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    assert payload["points"] == []
    assert payload["lookback_weeks"] == 4


def test_build_drops_reports_outside_window(tmp_path: Path) -> None:
    source_dir = tmp_path / "promotion_decisions"
    output_dir = tmp_path / "out"
    _seed_archive(source_dir, weeks=20)

    written = build(
        source_dir=source_dir,
        output_dir=output_dir,
        lookback_weeks=4,
        reference_date=REFERENCE,
        render_png=False,
    )
    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    assert len(payload["points"]) == len(FAMILIES) * 4


def test_build_renders_png(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    source_dir = tmp_path / "promotion_decisions"
    output_dir = tmp_path / "out"
    _seed_archive(source_dir, weeks=6)

    written = build(
        source_dir=source_dir,
        output_dir=output_dir,
        lookback_weeks=6,
        reference_date=REFERENCE,
        render_png=True,
    )
    png_path = written["png"]
    assert png_path.exists()
    assert png_path.stat().st_size > 5_000


def test_cli_exit_code_zero_on_empty(tmp_path: Path) -> None:
    rc = main(
        [
            "--source-dir",
            str(tmp_path / "empty"),
            "--output-dir",
            str(tmp_path / "out"),
            "--lookback-weeks",
            "2",
            "--reference-date",
            REFERENCE.isoformat(),
            "--no-png",
        ]
    )
    assert rc == 0
