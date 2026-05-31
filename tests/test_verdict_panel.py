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
    archive_dir: Path, stamp: str, decisions: list[dict[str, object]]
) -> Path:
    path = archive_dir / f"promotion_decisions_{stamp}.json"
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


def test_load_latest_report_picks_lexicographically_last(tmp_path: Path) -> None:
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
    _write_report(
        tmp_path,
        "2026-06-08T00-00-00",
        [_decision("BOS", promoted=False, metrics={"psr": 0.10})],
    )
    panel = render_panel_from_archive(tmp_path)
    assert "BOS" in panel
    assert "no_edge" in panel


def test_render_panel_from_archive_empty_is_notice(tmp_path: Path) -> None:
    assert render_panel_from_archive(tmp_path) == "(no decisions archived yet)"
