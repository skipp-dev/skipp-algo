"""EV-09 tests: verdict panel over the real promotion-decision archive."""

from __future__ import annotations

import json
from pathlib import Path

from dashboard.verdict_panel import (
    load_latest_report,
    render_panel_from_archive,
    render_verdict_panel,
    walkforward_histories,
)


def _decision(
    family: str,
    *,
    promoted: bool,
    metrics: dict[str, float],
    posture: str = "green",
    blockers: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "family": family,
        "promoted": promoted,
        "posture": posture,
        "blockers": blockers or [],
        "metrics": metrics,
        "provenance": {},
    }


def _write_report(
    archive_dir: Path,
    stamp: str,
    decisions: list[dict[str, object]],
    *,
    label: str | None = None,
) -> Path:
    """Write a fixture report using the REAL producer filename format.

    ``run_promotion_gate._archive_report`` embeds a compact UTC stamp
    (``YYYYMMDDTHHMMSSZ``) and an optional label:
    ``promotion_decisions_[<LABEL>_]<stamp>.json``. Mirroring it here keeps
    these fixtures honest about what the archive actually contains.
    """
    compact = (
        stamp.split("+", 1)[0].split(".", 1)[0].rstrip("Z").replace("-", "").replace(":", "")
        + "Z"
    )
    name = (
        f"promotion_decisions_{label}_{compact}.json"
        if label
        else f"promotion_decisions_{compact}.json"
    )
    path = archive_dir / name
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": f"{stamp}Z",
                "decisions": decisions,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_load_latest_report_empty_archive_returns_none(tmp_path: Path) -> None:
    assert load_latest_report(tmp_path) is None


def test_render_verdict_panel_none_report_is_honest_notice() -> None:
    assert render_verdict_panel(None) == "(no decisions archived yet)"


def test_load_latest_report_picks_latest_stamp(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        "2026-06-01T00-00-00",
        [_decision("BOS", promoted=False, metrics={"psr": 0.10})],
    )
    _write_report(
        tmp_path,
        "2026-06-08T00-00-00",
        [_decision("BOS", promoted=True, metrics={"psr": 0.99})],
    )
    report = load_latest_report(tmp_path)
    assert report is not None
    decisions = report["decisions"]
    assert decisions[0]["metrics"]["psr"] == 0.99


def test_load_latest_report_labeled_archive_does_not_outrank_newer_daily(
    tmp_path: Path,
) -> None:
    """Regression: digits sort before letters, so a whole-filename sort would
    let an OLD ``promotion_decisions_TSLA_<stamp>.json`` permanently outrank
    every newer unlabelled daily report. The stamp must decide.
    """
    _write_report(
        tmp_path,
        "2026-06-03T19-05-35",
        [_decision("BOS", promoted=True, metrics={"psr": 0.99})],
        label="TSLA",
    )
    _write_report(
        tmp_path,
        "2026-06-10T12-00-00",
        [_decision("BOS", promoted=False, metrics={"psr": 0.10})],
    )
    report = load_latest_report(tmp_path)
    assert report is not None
    assert report["decisions"][0]["metrics"]["psr"] == 0.10


def test_walkforward_histories_chronological_per_family(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        "2026-06-01T00-00-00",
        [_decision("BOS", promoted=False, metrics={"walkforward_brier": 0.20})],
    )
    _write_report(
        tmp_path,
        "2026-06-08T00-00-00",
        [_decision("BOS", promoted=False, metrics={"walkforward_brier": 0.18})],
    )
    histories = walkforward_histories(tmp_path)
    assert histories["BOS"] == [0.20, 0.18]


def test_walkforward_histories_order_survives_labeled_filenames(
    tmp_path: Path,
) -> None:
    """Labelled archives must slot into the series by stamp, not filename."""
    _write_report(
        tmp_path,
        "2026-06-01T00-00-00",
        [_decision("BOS", promoted=False, metrics={"walkforward_brier": 0.20})],
    )
    _write_report(
        tmp_path,
        "2026-06-04T00-00-00",
        [_decision("BOS", promoted=False, metrics={"walkforward_brier": 0.19})],
        label="TSLA",
    )
    _write_report(
        tmp_path,
        "2026-06-08T00-00-00",
        [_decision("BOS", promoted=False, metrics={"walkforward_brier": 0.18})],
    )
    histories = walkforward_histories(tmp_path)
    assert histories["BOS"] == [0.20, 0.19, 0.18]


def test_walkforward_histories_skips_unmeasured_no_fabricated_points(
    tmp_path: Path,
) -> None:
    _write_report(
        tmp_path,
        "2026-06-01T00-00-00",
        [_decision("BOS", promoted=False, metrics={"psr": 0.10})],
    )
    histories = walkforward_histories(tmp_path)
    assert histories == {}


def test_render_verdict_panel_promoted_measured_adequate_is_edge_supported(
    tmp_path: Path,
) -> None:
    _write_report(
        tmp_path,
        "2026-06-08T00-00-00",
        [
            _decision(
                "BOS",
                promoted=True,
                metrics={
                    "psr": 0.97,
                    "extra.n_returns": 250,
                    "walkforward_brier": 0.18,
                },
            )
        ],
    )
    report = load_latest_report(tmp_path)
    panel = render_verdict_panel(report, archive_dir=tmp_path)
    assert "[EDGE] edge_supported" in panel
    assert "PROMOTED" in panel
    assert "n=250/200" in panel


def test_render_verdict_panel_promoted_underpowered_is_inconclusive(
    tmp_path: Path,
) -> None:
    _write_report(
        tmp_path,
        "2026-06-08T00-00-00",
        [
            _decision(
                "BOS",
                promoted=True,
                metrics={"psr": 0.97, "extra.n_returns": 10},
            )
        ],
    )
    report = load_latest_report(tmp_path)
    panel = render_verdict_panel(report, archive_dir=tmp_path)
    # Promoted flag is shown, but the honest verdict withholds the edge.
    assert "PROMOTED" in panel
    assert "[INCONCLUSIVE] inconclusive" in panel
    assert "[EDGE]" not in panel


def test_render_verdict_panel_missing_decision_is_not_evaluated(
    tmp_path: Path,
) -> None:
    # Only BOS is decided; the other registered families have no decision.
    _write_report(
        tmp_path,
        "2026-06-08T00-00-00",
        [_decision("BOS", promoted=False, metrics={"psr": 0.10})],
    )
    report = load_latest_report(tmp_path)
    panel = render_verdict_panel(report, archive_dir=tmp_path)
    assert "NOT EVALUATED" in panel
    assert "[N/A] not_evaluated" in panel


def test_render_panel_from_archive_end_to_end(tmp_path: Path) -> None:
    # A no_edge verdict is an affirmative claim ("measured enough samples,
    # found no edge"), so it requires an adequate observed sample size
    # (extra.n_returns >= min_sample_n). Without it the honest verdict is
    # inconclusive, not no_edge. Per ADR-0015 it also requires a genuine
    # *edge* blocker (here psr_minimum on psr=0.10) — a calibration-only
    # block would instead clear tier-1 edge_supported.
    _write_report(
        tmp_path,
        "2026-06-08T00-00-00",
        [
            _decision(
                "BOS",
                promoted=False,
                metrics={"psr": 0.10, "extra.n_returns": 250},
                posture="red",
                blockers=[{
                    "check": "psr_minimum",
                    "severity": "blocker",
                    "observed": 0.10,
                    "threshold": 0.95,
                    "message": "psr below floor",
                }],
            )
        ],
    )
    panel = render_panel_from_archive(tmp_path)
    assert "BOS" in panel
    assert "no_edge" in panel


def test_render_panel_from_archive_empty_is_notice(tmp_path: Path) -> None:
    assert render_panel_from_archive(tmp_path) == "(no decisions archived yet)"
