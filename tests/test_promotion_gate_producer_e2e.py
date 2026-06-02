"""End-to-end producer-path test for Sprint W1.b.

Covers the full chain:

    synthetic rolling-bench artifacts
        -> scripts.build_promotion_gate_bundle.main
        -> scripts.run_promotion_gate.main
        -> dashboard.decision_first_panel.load_decisions_from_report
        -> dashboard.decision_first_panel.render_panel

The test deliberately uses only the public CLI / loader surfaces — no
internal helpers — so it pins the contract the daily workflow relies on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.decision_first_panel import (
    load_decisions_from_report,
    render_panel,
)
from scripts.build_promotion_gate_bundle import main as build_bundle_main
from scripts.run_promotion_gate import main as run_gate_main


@pytest.fixture(autouse=True)
def _isolate_archive_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_promotion_gate`` archives a timestamped copy to the default
    ``governance/promotion_decisions`` dir resolved *relative to cwd*. Chdir
    into ``tmp_path`` so this end-to-end CLI test never writes into the real
    repo tree."""
    monkeypatch.chdir(tmp_path)


def _write_rollup(scoring_root: Path) -> None:
    scoring_root.mkdir(parents=True, exist_ok=True)
    rollup = {
        "schema_version": 1,
        "scoring_root": str(scoring_root),
        "timeframes": ["5m", "15m", "1H", "4H"],
        "files_scanned": 3,
        "per_tf": {
            "5m": {
                "n_events": 40,
                "families": {
                    "FVG": {"n_events": 25, "hit_rate": 0.6},
                    "BOS": {"n_events": 15, "hit_rate": 0.5},
                },
            },
            "15m": {
                "n_events": 20,
                "families": {
                    "OB": {"n_events": 12, "hit_rate": 0.4},
                    "SWEEP": {"n_events": 8, "hit_rate": 0.55},
                },
            },
        },
        "unknown_timeframes": {},
        "phase_e2_verdict": {},
    }
    (scoring_root / "plan_2_8_tf_family_rollup.json").write_text(
        json.dumps(rollup), encoding="utf-8"
    )


def test_producer_path_end_to_end(tmp_path: Path) -> None:
    scoring_root = tmp_path / "scoring"
    bundle_path = tmp_path / "bundle.json"
    report_path = tmp_path / "promotion_decisions.json"

    _write_rollup(scoring_root)

    # 1. Build the FamilyMetrics bundle from the synthetic rolling-bench output.
    rc_bundle = build_bundle_main(
        [
            "--scoring-root",
            str(scoring_root),
            "--output",
            str(bundle_path),
            "--date",
            "2026-05-17",
        ]
    )
    assert rc_bundle == 0
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert {entry["family"] for entry in bundle} == {"BOS", "OB", "FVG", "SWEEP"}
    # Per-family event totals are aggregated across timeframes.
    totals = {entry["family"]: entry["extras"]["n_events_total"] for entry in bundle}
    assert totals == {"BOS": 15.0, "OB": 12.0, "FVG": 25.0, "SWEEP": 8.0}
    # Provenance carries the source artifact identity.
    for entry in bundle:
        prov = entry["provenance"]
        assert prov["source"] == "smc-measurement-benchmark-rolling"
        assert prov["run_date"] == "2026-05-17"

    # 2. Run the PromotionGate over the bundle in strict-provenance mode.
    rc_gate = run_gate_main(
        [
            "--metrics",
            str(bundle_path),
            "--output",
            str(report_path),
        ]
    )
    # Strict mode + bundle with no real W1 metrics yet => rc=2 (blocked).
    assert rc_gate == 2
    assert report_path.exists()

    # 3. Loader contract: the dashboard reads decisions back from the report.
    decisions = load_decisions_from_report(report_path)
    assert len(decisions) == 4
    families_in_report = {str(d["family"]) for d in decisions}
    assert families_in_report == {"BOS", "OB", "FVG", "SWEEP"}
    # First-cut posture: every family blocked because metrics are missing.
    assert all(d["promoted"] is False for d in decisions)

    # 4. Render the panel from those decisions — must not raise and must
    #    contain a card per family.
    rendered = render_panel(decisions)
    for fam in ("BOS", "OB", "FVG", "SWEEP"):
        assert fam in rendered
    # 4 cards separated by blank lines => 7 lines per card joined by "\n\n".
    blocks = rendered.split("\n\n")
    assert len(blocks) == 4


def test_producer_path_runner_rejects_empty_scoring_root(tmp_path: Path) -> None:
    """Bundler still emits a valid bundle when the rollup is missing;
    the gate then runs and reports zero events per family."""
    empty_scoring = tmp_path / "empty"
    empty_scoring.mkdir()
    bundle_path = tmp_path / "bundle.json"
    report_path = tmp_path / "report.json"

    rc_bundle = build_bundle_main(
        [
            "--scoring-root",
            str(empty_scoring),
            "--output",
            str(bundle_path),
        ]
    )
    assert rc_bundle == 0
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert all(entry["extras"]["n_events_total"] == 0.0 for entry in bundle)

    rc_gate = run_gate_main(
        [
            "--metrics",
            str(bundle_path),
            "--output",
            str(report_path),
        ]
    )
    assert rc_gate == 2  # strict mode: missing metrics => blocked


def test_producer_path_bundler_rejects_unknown_family(tmp_path: Path) -> None:
    rc = build_bundle_main(
        [
            "--scoring-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "bundle.json"),
            "--families",
            "NOT_A_FAMILY",
        ]
    )
    assert rc == 1
    assert not (tmp_path / "bundle.json").exists()
