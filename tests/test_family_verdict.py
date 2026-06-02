"""Tests for the EV-08 honest family-verdict reporter."""

from __future__ import annotations

import json

from governance.edge_hypotheses import get_hypothesis, list_hypotheses
from governance.family_verdict import (
    _has_contradiction,
    build_verdict_report,
    build_verdicts,
    main,
    verdict_summary,
)


def _decision(
    family: str,
    *,
    promoted: bool,
    metrics: dict | None = None,
    blockers: list | None = None,
) -> dict:
    return {
        "schema_version": 2,
        "family": family,
        "promoted": promoted,
        "posture": "green" if promoted else "red",
        "blockers": blockers or [],
        "metrics": metrics or {},
        "provenance": {},
    }


def _report(decisions: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "gate_schema_version": 2,
        "generated_at": "2026-06-01T00:00:00+00:00",
        "strict_provenance": True,
        "decisions": decisions,
    }


def _psr_family() -> tuple[str, int]:
    hyp = next(h for h in list_hypotheses() if h["primary_metric"] == "psr")
    return hyp["family"], int(hyp["min_sample_n"])


def test_promoted_with_measured_primary_and_adequate_sample_is_edge() -> None:
    family, min_n = _psr_family()
    report = _report([
        _decision(
            family,
            promoted=True,
            metrics={"psr": 0.97, "extra.n_returns": float(min_n)},
        )
    ])

    verdicts = {v["family"]: v for v in build_verdicts(report)}
    v = verdicts[family]

    assert v["verdict"] == "edge_supported"
    assert v["primary_metric_measured"] is True
    assert v["primary_metric_value"] == 0.97
    assert v["sample_adequate"] is True


def test_promoted_but_underpowered_is_inconclusive_not_edge() -> None:
    family, min_n = _psr_family()
    report = _report([
        _decision(
            family,
            promoted=True,
            metrics={"psr": 0.97, "extra.n_returns": float(min_n - 1)},
        )
    ])

    v = next(x for x in build_verdicts(report) if x["family"] == family)

    assert v["verdict"] == "inconclusive"
    assert v["sample_adequate"] is False
    assert any("min_sample_n" in note for note in v["notes"])


def test_promoted_but_primary_unmeasured_is_inconclusive() -> None:
    family, min_n = _psr_family()
    # Gate promoted (hypothetically) yet the primary metric is absent ->
    # the cross-check withholds the edge claim.
    report = _report([
        _decision(family, promoted=True, metrics={"extra.n_returns": float(min_n)})
    ])

    v = next(x for x in build_verdicts(report) if x["family"] == family)

    assert v["verdict"] == "inconclusive"
    assert v["primary_metric_measured"] is False


def test_not_promoted_with_measured_primary_is_no_edge() -> None:
    family, min_n = _psr_family()
    report = _report([
        _decision(
            family,
            promoted=False,
            metrics={"psr": 0.40, "extra.n_returns": float(min_n)},
            blockers=[{"check": "psr_minimum", "severity": "blocker", "observed": 0.40, "threshold": 0.95, "message": "x"}],
        )
    ])

    v = next(x for x in build_verdicts(report) if x["family"] == family)

    assert v["verdict"] == "no_edge"
    assert v["blocker_checks"] == ["psr_minimum"]


def test_not_promoted_measured_but_underpowered_is_inconclusive_not_no_edge() -> None:
    family, min_n = _psr_family()
    # Gate did not promote and the primary metric is measured, but the sample
    # is below the pre-registered minimum -> we cannot honestly claim "no edge"
    # on an underpowered sample; the verdict must be inconclusive.
    report = _report([
        _decision(
            family,
            promoted=False,
            metrics={"psr": 0.40, "extra.n_returns": float(min_n - 1)},
            blockers=[{"check": "psr_minimum", "severity": "blocker", "observed": 0.40, "threshold": 0.95, "message": "x"}],
        )
    ])

    v = next(x for x in build_verdicts(report) if x["family"] == family)

    assert v["verdict"] == "inconclusive"
    assert v["sample_adequate"] is False
    assert any("no_edge claim withheld" in note for note in v["notes"])



def test_not_promoted_unmeasured_primary_is_inconclusive() -> None:
    family, _ = _psr_family()
    report = _report([_decision(family, promoted=False, metrics={})])

    v = next(x for x in build_verdicts(report) if x["family"] == family)

    assert v["verdict"] == "inconclusive"


def test_missing_decision_is_not_evaluated() -> None:
    # Empty report -> every registered family is surfaced as not_evaluated.
    verdicts = build_verdicts(_report([]))

    assert verdicts, "register must yield at least one family"
    assert all(v["verdict"] == "not_evaluated" for v in verdicts)
    assert all(v["promoted"] is None for v in verdicts)


def test_summary_counts_cover_all_families() -> None:
    verdicts = build_verdicts(_report([]))
    summary = verdict_summary(verdicts)

    assert sum(summary.values()) == len(verdicts)
    assert summary["not_evaluated"] == len(verdicts)


def test_contradiction_flag_and_exit_code(tmp_path) -> None:
    family, min_n = _psr_family()
    # Promoted but underpowered -> contradiction the CLI must fail on.
    report = _report([
        _decision(
            family,
            promoted=True,
            metrics={"psr": 0.97, "extra.n_returns": float(min_n - 5)},
        )
    ])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    out_path = tmp_path / "verdicts.json"

    rc = main(["--report", str(report_path), "--output", str(out_path)])

    assert rc == 3
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert _has_contradiction(written["verdicts"]) is True


def test_clean_no_edge_report_exits_zero(tmp_path) -> None:
    family, min_n = _psr_family()
    report = _report([
        _decision(
            family,
            promoted=False,
            metrics={"psr": 0.10, "extra.n_returns": float(min_n)},
        )
    ])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    rc = main(["--report", str(report_path)])

    assert rc == 0


def test_verdict_report_uses_real_register_metric() -> None:
    # The verdict's primary_metric must match the frozen register exactly.
    report = _report([])
    built = build_verdict_report(report)

    for verdict in built["verdicts"]:
        hyp = get_hypothesis(verdict["family"])
        assert verdict["primary_metric"] == hyp["primary_metric"]
        assert verdict["min_sample_n"] == hyp["min_sample_n"]


# --- ADR-0015 two-tier taxonomy -------------------------------------------


def test_calibration_only_block_is_tier1_edge_not_tier2() -> None:
    # Gate did NOT promote, blocked solely by a calibration check
    # (brier_threshold). The edge proof is intact -> tier-1 edge_supported,
    # but tier-2 risk_sizeable is withheld.
    family, min_n = _psr_family()
    report = _report([
        _decision(
            family,
            promoted=False,
            metrics={"psr": 0.97, "extra.n_returns": float(min_n)},
            blockers=[{
                "check": "brier_threshold",
                "severity": "blocker",
                "observed": 0.24,
                "threshold": 0.22,
                "message": "brier above bar",
            }],
        )
    ])

    v = next(x for x in build_verdicts(report) if x["family"] == family)

    assert v["verdict"] == "edge_supported"
    assert v["risk_sizeable"] is False
    assert any("risk_sizeable withheld" in note for note in v["notes"])


def test_fully_promoted_is_tier2_risk_sizeable() -> None:
    family, min_n = _psr_family()
    report = _report([
        _decision(
            family,
            promoted=True,
            metrics={"psr": 0.97, "extra.n_returns": float(min_n)},
        )
    ])

    v = next(x for x in build_verdicts(report) if x["family"] == family)

    assert v["verdict"] == "edge_supported"
    assert v["risk_sizeable"] is True


def test_edge_blocker_stays_no_edge_and_not_sizeable() -> None:
    # A real edge blocker (psr_minimum) keeps the family out of both tiers.
    family, min_n = _psr_family()
    report = _report([
        _decision(
            family,
            promoted=False,
            metrics={"psr": 0.40, "extra.n_returns": float(min_n)},
            blockers=[{
                "check": "psr_minimum",
                "severity": "blocker",
                "observed": 0.40,
                "threshold": 0.95,
                "message": "x",
            }],
        )
    ])

    v = next(x for x in build_verdicts(report) if x["family"] == family)

    assert v["verdict"] == "no_edge"
    assert v["risk_sizeable"] is False


def test_calibration_only_block_is_not_a_contradiction(tmp_path) -> None:
    # A tier-1 edge_supported family the gate did not fully promote (calibration
    # block) must NOT trip the contradiction CI gate (promoted is False).
    family, min_n = _psr_family()
    report = _report([
        _decision(
            family,
            promoted=False,
            metrics={"psr": 0.97, "extra.n_returns": float(min_n)},
            blockers=[{
                "check": "ece_threshold",
                "severity": "blocker",
                "observed": 0.08,
                "threshold": 0.05,
                "message": "ece above bar",
            }],
        )
    ])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    rc = main(["--report", str(report_path)])

    assert rc == 0


def test_edge_metrics_clear_but_integrity_unmeasured_is_inconclusive() -> None:
    # Mirrors the real archive: strong edge metrics, only calibration hard
    # blockers, but integrity/provenance guards are unmeasured (info). The
    # honest verdict is inconclusive (cannot certify the edge), NOT no_edge
    # and NOT edge_supported.
    family, min_n = _psr_family()
    report = _report([
        _decision(
            family,
            promoted=False,
            metrics={"psr": 0.99, "extra.n_returns": float(min_n)},
            blockers=[
                {"check": "brier_threshold", "severity": "blocker",
                 "observed": 0.24, "threshold": 0.22, "message": "x"},
                {"check": "regime_degraded", "severity": "info",
                 "observed": None, "threshold": 0.0, "message": "unmeasured"},
                {"check": "conformal_coverage", "severity": "info",
                 "observed": None, "threshold": 0.0, "message": "unmeasured"},
            ],
        )
    ])

    v = next(x for x in build_verdicts(report) if x["family"] == family)

    assert v["verdict"] == "inconclusive"
    assert v["risk_sizeable"] is False
    assert any("not yet measured" in note for note in v["notes"])


def test_risk_sizeable_count_in_report() -> None:
    family, min_n = _psr_family()
    built = build_verdict_report(
        _report([
            _decision(
                family,
                promoted=True,
                metrics={"psr": 0.97, "extra.n_returns": float(min_n)},
            )
        ])
    )

    assert built["risk_sizeable_count"] == 1

