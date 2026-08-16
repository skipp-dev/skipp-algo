"""The family-claim tier is bound to the pre-registered sample, not to prose.

2026-08-16, weekly commercial review (P1, operator decision): FVG leaves the
four-family claim — one modeled OOS outcome against a pre-registered minimum
of 150, and governance has classified FVG as a control family since ADR-0023.
The decision lives in ``docs/commercial/family_claim_status.json`` and rides
into the public report as ``commercial_claim`` per family row.

The mechanism this file owns: the ``claimable`` tier — the only tier that may
appear in commercial claims as "a family WITH evidence" — requires the
family's own pre-registered ``min_sample_n`` from
``governance/edge_hypotheses.json`` across closed outcomes. Editing the
decision record alone can therefore never silently restore an equal-family
rendering; the sample has to exist first. Both directions of the rule are
executed below, against the real committed evidence and against synthetic
states, so neither branch is vacuous.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_families_telemetry import (
    EVENT_FAMILIES,
    FAMILY_CLAIM_STATUS_PATH,
    build_payload,
    load_family_claim_statuses,
)

ROOT = Path(__file__).resolve().parents[1]
EDGE_HYPOTHESES_PATH = ROOT / "governance" / "edge_hypotheses.json"


def _preregistered_minimums() -> dict[str, int]:
    payload = json.loads(EDGE_HYPOTHESES_PATH.read_text(encoding="utf-8"))
    minimums = {
        entry["family"]: int(entry["min_sample_n"]) for entry in payload
    }
    assert set(minimums) == set(EVENT_FAMILIES)
    return minimums


def _closed_outcome_totals() -> dict[str, int]:
    """Per-family closed outcomes across ALL evidence classes, measured.

    Built by the same producer the daily cron runs, over the committed
    audit/drift/returns artifacts — not re-derived counting logic.
    """
    payload = build_payload(
        audit_glob=str(ROOT / "cache" / "live" / "incubation_*.jsonl"),
        drift_glob=str(ROOT / "cache" / "live" / "drift_*.json"),
        variant_family_map=ROOT / "configs" / "c13" / "variant_family_map.json",
        modeled_returns_glob=str(
            ROOT / "docs" / "calibration" / "gates" / "returns_series_*.json"
        ),
    )
    totals: dict[str, int] = {}
    for row in payload["families"]:
        evidence = row["evidence"]
        totals[row["name"]] = (
            int(evidence["MODELED_OOS"]["n_outcomes"])
            + int(evidence["PAPER"]["n_closed_outcomes"])
            + int(evidence["LIVE"]["n_closed_outcomes"])
        )
    return totals


def _verify_claim_tiers(
    statuses: dict[str, str],
    totals: dict[str, int],
    minimums: dict[str, int],
) -> None:
    for family, status in statuses.items():
        if status != "claimable":
            continue
        if totals[family] < minimums[family]:
            raise AssertionError(
                f"{family} is recorded as claimable with {totals[family]} "
                f"closed outcomes against its pre-registered minimum of "
                f"{minimums[family]} -- the claim tier cannot be reached by "
                "editing the decision record; build the sample first"
            )


def test_the_repository_state_holds() -> None:
    _verify_claim_tiers(
        load_family_claim_statuses(),
        _closed_outcome_totals(),
        _preregistered_minimums(),
    )


def test_the_recorded_decision_is_the_2026_08_16_one() -> None:
    """Flipping the record is a visible two-file change, not a quiet edit."""
    statuses = load_family_claim_statuses()

    assert statuses["FVG"] == "incubation"
    assert statuses["BOS"] == "evidence_building"
    assert statuses["OB"] == "evidence_building"
    assert statuses["SWEEP"] == "evidence_building"


def test_an_unearned_claimable_tier_is_refused() -> None:
    minimums = _preregistered_minimums()
    statuses = dict.fromkeys(EVENT_FAMILIES, "evidence_building")
    statuses["FVG"] = "claimable"
    totals = {family: minimums[family] - 1 for family in EVENT_FAMILIES}

    with pytest.raises(AssertionError, match="build the sample first"):
        _verify_claim_tiers(statuses, totals, minimums)


def test_an_earned_claimable_tier_passes() -> None:
    minimums = _preregistered_minimums()
    statuses = dict.fromkeys(EVENT_FAMILIES, "claimable")
    totals = dict(minimums)

    _verify_claim_tiers(statuses, totals, minimums)


def test_the_loader_fails_closed(tmp_path: Path) -> None:
    record = json.loads(FAMILY_CLAIM_STATUS_PATH.read_text(encoding="utf-8"))

    missing = {**record, "families": {
        k: v for k, v in record["families"].items() if k != "FVG"
    }}
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(ValueError, match=r"families\.FVG\.status"):
        load_family_claim_statuses(path)

    unknown = {**record, "families": {
        **record["families"],
        "MOMO": {"status": "incubation", "basis": "synthetic"},
    }}
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(unknown), encoding="utf-8")
    with pytest.raises(ValueError, match=r"unknown families \['MOMO'\]"):
        load_family_claim_statuses(path)

    bad_status = {**record, "families": {
        **record["families"],
        "BOS": {"status": "totally_claimable", "basis": "synthetic"},
    }}
    path = tmp_path / "bad_status.json"
    path.write_text(json.dumps(bad_status), encoding="utf-8")
    with pytest.raises(ValueError, match=r"families\.BOS\.status"):
        load_family_claim_statuses(path)
