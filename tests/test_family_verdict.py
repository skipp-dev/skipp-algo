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
