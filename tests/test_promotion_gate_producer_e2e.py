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


# ---- ADR-0023 Stage-1 magnitude shadow-ledger -> bundle wiring -----------
#
# Handover §5 item 2: the daily shadow runner appends graded rows to the
# move-size ledger; the bundle builder must fold the latest candidate-family
# rows into magnitude_resolution_pass / magnitude_auc so the gate's
# ok_magnitude branch actually sees them (previously always None => dormant).


def _ledger_row(
    *, date: str, family: str, status: str, auc: float | None = 0.63
) -> dict[str, object]:
    return {
        "date": date,
        "family": family,
        "status": status,
        "magnitude_auc": auc,
    }


def _write_ledger(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _build(scoring_root: Path, bundle_path: Path, ledger: Path | str) -> list[dict]:
    rc = build_bundle_main(
        [
            "--scoring-root",
            str(scoring_root),
            "--output",
            str(bundle_path),
            "--date",
            "2026-06-11",
            "--magnitude-ledger",
            str(ledger),
        ]
    )
    assert rc == 0
    return json.loads(bundle_path.read_text(encoding="utf-8"))


def test_bundle_folds_latest_candidate_ledger_rows(tmp_path: Path) -> None:
    scoring_root = tmp_path / "scoring"
    _write_rollup(scoring_root)
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(
        ledger,
        [
            # Stale row first — latest-date-wins must pick 06-11.
            _ledger_row(date="2026-06-10", family="BOS", status="FAIL", auc=0.51),
            _ledger_row(date="2026-06-11", family="BOS", status="PASS", auc=0.64),
            _ledger_row(date="2026-06-11", family="SWEEP", status="FAIL", auc=0.52),
        ],
    )
    bundle = _build(scoring_root, tmp_path / "bundle.json", ledger)
    by_family = {e["family"]: e for e in bundle}
    assert by_family["BOS"]["magnitude_resolution_pass"] is True
    assert by_family["BOS"]["magnitude_auc"] == 0.64
    assert by_family["BOS"]["provenance"]["magnitude_status"] == "PASS"
    assert by_family["BOS"]["provenance"]["magnitude_ledger_date"] == "2026-06-11"
    assert by_family["SWEEP"]["magnitude_resolution_pass"] is False
    assert by_family["SWEEP"]["magnitude_auc"] == 0.52


def test_bundle_never_feeds_control_families(tmp_path: Path) -> None:
    """FVG/OB FAIL by construction — their False must never reach the gate."""
    scoring_root = tmp_path / "scoring"
    _write_rollup(scoring_root)
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(
        ledger,
        [
            _ledger_row(date="2026-06-11", family="FVG", status="FAIL"),
            _ledger_row(date="2026-06-11", family="OB", status="FAIL"),
        ],
    )
    bundle = _build(scoring_root, tmp_path / "bundle.json", ledger)
    for entry in bundle:
        assert "magnitude_resolution_pass" not in entry, entry["family"]
        assert "magnitude_auc" not in entry, entry["family"]


def test_bundle_missing_ledger_stays_dormant(tmp_path: Path) -> None:
    scoring_root = tmp_path / "scoring"
    _write_rollup(scoring_root)
    bundle = _build(
        scoring_root, tmp_path / "bundle.json", tmp_path / "does_not_exist.jsonl"
    )
    for entry in bundle:
        assert "magnitude_resolution_pass" not in entry
        assert "magnitude_auc" not in entry


def test_bundle_inconclusive_maps_to_unmeasured(tmp_path: Path) -> None:
    """INCONCLUSIVE => pass=None (3-state 'not measured'), AUC still carried."""
    scoring_root = tmp_path / "scoring"
    _write_rollup(scoring_root)
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(
        ledger,
        [_ledger_row(date="2026-06-11", family="BOS", status="INCONCLUSIVE")],
    )
    bundle = _build(scoring_root, tmp_path / "bundle.json", ledger)
    by_family = {e["family"]: e for e in bundle}
    assert by_family["BOS"]["magnitude_resolution_pass"] is None
    assert by_family["BOS"]["magnitude_auc"] == 0.63


def test_ledger_verdicts_reach_gate_decision_metrics(tmp_path: Path) -> None:
    """Full chain: ledger row -> bundle -> run_promotion_gate -> decision.

    The gate records magnitude_resolution_pass=1.0 (+ AUC) in the decision
    metrics for a measured PASS — proof the wiring un-dormants ok_magnitude.
    """
    scoring_root = tmp_path / "scoring"
    _write_rollup(scoring_root)
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(
        ledger,
        [_ledger_row(date="2026-06-11", family="BOS", status="PASS", auc=0.66)],
    )
    bundle_path = tmp_path / "bundle.json"
    report_path = tmp_path / "promotion_decisions.json"
    _build(scoring_root, bundle_path, ledger)
    rc_gate = run_gate_main(
        ["--metrics", str(bundle_path), "--output", str(report_path)]
    )
    assert rc_gate == 2  # other W1 metrics still unmeasured => blocked
    report = json.loads(report_path.read_text(encoding="utf-8"))
    bos = next(d for d in report["decisions"] if d["family"] == "BOS")
    assert bos["metrics"]["magnitude_resolution_pass"] == 1.0
    assert bos["metrics"]["magnitude_auc"] == 0.66


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
