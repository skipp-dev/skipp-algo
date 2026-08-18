"""Tests for the local-only commercial shadow campaign controller."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.run_commercial_shadow_campaign import (
    CampaignObservationError,
    build_campaign_report,
    main,
    run_campaign_observation,
)

_ANCHOR = 1_800_000_000.0
_NOW = datetime.fromtimestamp(_ANCHOR, UTC)


def _payload() -> dict:
    return {
        "as_of": _ANCHOR,
        "bars": [
            {
                "timestamp": _ANCHOR,
                "open": 100.0,
                "high": 103.0,
                "low": 98.0,
                "close": 102.0,
            }
        ],
        "structure": {
            "bos": [
                {
                    "id": "bos-1",
                    "time": _ANCHOR,
                    "price": 102.0,
                    "dir": "UP",
                }
            ],
            "orderblocks": [
                {
                    "id": "ob-1",
                    "anchor_ts": _ANCHOR,
                    "low": 98.0,
                    "high": 100.0,
                    "dir": "BULL",
                    "valid": True,
                }
            ],
            "fvg": [
                {
                    "id": "fvg-1",
                    "anchor_ts": _ANCHOR,
                    "low": 100.0,
                    "high": 101.0,
                    "dir": "BULL",
                    "valid": True,
                }
            ],
            "liquidity_sweeps": [
                {
                    "id": "sweep-1",
                    "time": _ANCHOR,
                    "price": 99.0,
                    "side": "SELL_SIDE",
                }
            ],
        },
        "provenance": {
            "symbol": "AAPL",
            "timeframe": "15m",
            "source": "databento",
            "dataset": "XNAS.ITCH",
        },
    }


def _shift_payload(payload: dict, seconds: float) -> dict:
    shifted = deepcopy(payload)
    shifted["as_of"] += seconds
    shifted["bars"][0]["timestamp"] += seconds
    shifted["structure"]["bos"][0].update(id="bos-2", time=shifted["structure"]["bos"][0]["time"] + seconds)
    shifted["structure"]["orderblocks"][0].update(
        id="ob-2",
        anchor_ts=(shifted["structure"]["orderblocks"][0]["anchor_ts"] + seconds),
    )
    shifted["structure"]["fvg"][0].update(
        id="fvg-2",
        anchor_ts=shifted["structure"]["fvg"][0]["anchor_ts"] + seconds,
    )
    shifted["structure"]["liquidity_sweeps"][0].update(
        id="sweep-2",
        time=(shifted["structure"]["liquidity_sweeps"][0]["time"] + seconds),
    )
    return shifted


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_campaign_accumulates_unique_snapshots_and_passes_observation_gate(
    tmp_path: Path,
) -> None:
    campaign_dir = tmp_path / "campaign"

    first_attempt, first_report = run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=2,
    )
    second_payload = _shift_payload(_payload(), 60.0)
    second_attempt, report = run_campaign_observation(
        payload=second_payload,
        campaign_dir=campaign_dir,
        now=datetime.fromtimestamp(_ANCHOR + 60.0, UTC),
        min_unique_snapshots=2,
    )

    assert first_attempt["status"] == "COMPLETED"
    assert first_report["observation_gate"]["verdict"] == "PENDING"
    assert second_attempt["status"] == "COMPLETED"
    assert report["observation_gate"]["verdict"] == "PASS"
    assert report["audit_integrity"] == {
        "audit_rows": 8,
        "valid_audit_rows": 8,
        "invalid_audit_rows": 0,
        "duplicate_snapshot_intent_rows": 0,
        "unique_audited_snapshots": 2,
        "unique_audited_intents": 8,
    }
    assert report["family_snapshot_counts"] == {
        "BOS": 2,
        "FVG": 2,
        "OB": 2,
        "SWEEP": 2,
    }
    assert report["promotion_gate"]["verdict"] == "NO_GO"
    assert report["broker_io"] is False
    assert report["network_io"] is False
    assert report["paper_orders_placed"] == 0


def test_campaign_replay_records_attempt_without_duplicate_audit(
    tmp_path: Path,
) -> None:
    campaign_dir = tmp_path / "campaign"
    run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=1,
    )

    attempt, report = run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=datetime.fromtimestamp(_ANCHOR + 1.0, UTC),
        min_unique_snapshots=1,
    )

    assert attempt["status"] == "REPLAY_SKIPPED"
    assert report["attempt_status_counts"] == {
        "COMPLETED": 1,
        "REPLAY_SKIPPED": 1,
    }
    assert report["substantive_attempts_total"] == 1
    assert report["source_age_seconds"]["count"] == 1
    assert report["audit_integrity"]["audit_rows"] == 4
    assert report["audit_integrity"]["duplicate_snapshot_intent_rows"] == 0


def test_no_setup_observation_is_valid_but_cannot_pass_coverage(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["structure"] = {
        "bos": [],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }

    attempt, report = run_campaign_observation(
        payload=payload,
        campaign_dir=tmp_path / "campaign",
        now=_NOW,
        min_unique_snapshots=1,
    )

    assert attempt["status"] == "NO_SETUPS"
    assert attempt["families"] == []
    assert report["observation_gate"]["verdict"] == "PENDING"
    assert report["audit_integrity"]["unique_audited_snapshots"] == 0


def test_failed_observation_is_durable_and_keeps_promotion_blocked(
    tmp_path: Path,
) -> None:
    campaign_dir = tmp_path / "campaign"

    with pytest.raises(CampaignObservationError, match="is stale"):
        run_campaign_observation(
            payload=_payload(),
            campaign_dir=campaign_dir,
            now=datetime.fromtimestamp(_ANCHOR + 301.0, UTC),
            min_unique_snapshots=1,
        )

    [attempt] = [json.loads(path.read_text(encoding="utf-8")) for path in (campaign_dir / "attempts").glob("*.json")]
    report = json.loads((campaign_dir / "campaign_report.json").read_text(encoding="utf-8"))
    assert attempt["status"] == "FAILED"
    assert attempt["error_type"] == "ValueError"
    assert report["attempt_status_counts"] == {"FAILED": 1}
    assert report["failure_rate"] == 1.0
    assert report["promotion_gate"]["verdict"] == "NO_GO"


def test_failure_before_source_age_is_known_still_rebuilds_report(
    tmp_path: Path,
) -> None:
    campaign_dir = tmp_path / "campaign"
    payload = _payload()
    payload["as_of"] = None

    with pytest.raises(CampaignObservationError, match=r"input\.as_of"):
        run_campaign_observation(
            payload=payload,
            campaign_dir=campaign_dir,
            now=_NOW,
            min_unique_snapshots=1,
        )

    report = json.loads((campaign_dir / "campaign_report.json").read_text(encoding="utf-8"))
    assert report["attempt_status_counts"] == {"FAILED": 1}
    assert report["source_age_seconds"]["count"] == 0
    assert "source_age_p95_unknown" in report["observation_gate"]["current_threshold_warnings"]


def test_duplicate_audit_row_fails_observation_integrity_gate(
    tmp_path: Path,
) -> None:
    campaign_dir = tmp_path / "campaign"
    run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=1,
    )
    audit_path = campaign_dir / "audit" / "incubation_audit.jsonl"
    [first, *_] = _read_jsonl(audit_path)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(first) + "\n")

    report = build_campaign_report(
        campaign_dir,
        generated_at=_NOW,
        min_unique_snapshots=1,
    )

    assert report["observation_gate"]["verdict"] == "FAIL"
    assert report["observation_gate"]["reasons"] == ["duplicate_snapshot_intent_rows"]


def test_corrupt_attempt_file_fails_report_rebuild_closed(tmp_path: Path) -> None:
    attempt_path = tmp_path / "campaign" / "attempts" / "broken.json"
    attempt_path.parent.mkdir(parents=True)
    attempt_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid campaign attempt JSON"):
        build_campaign_report(tmp_path / "campaign")


def test_tampered_attempt_file_fails_report_rebuild_closed(tmp_path: Path) -> None:
    campaign_dir = tmp_path / "campaign"
    attempt, _report = run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=1,
    )
    attempt_path = campaign_dir / "attempts" / f"{attempt['attempt_id']}.json"
    tampered = json.loads(attempt_path.read_text(encoding="utf-8"))
    tampered["broker_io"] = True
    attempt_path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValueError, match="violates broker-free contract"):
        build_campaign_report(campaign_dir, min_unique_snapshots=1)


def test_attempt_records_are_never_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.run_commercial_shadow_campaign.secrets.token_hex",
        lambda _bytes: "fixed-attempt",
    )
    campaign_dir = tmp_path / "campaign"
    first_attempt, _report = run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=1,
    )

    with pytest.raises(RuntimeError, match="campaign attempt already exists"):
        run_campaign_observation(
            payload=_payload(),
            campaign_dir=campaign_dir,
            now=_NOW,
            min_unique_snapshots=1,
        )

    attempt_path = campaign_dir / "attempts" / f"{first_attempt['attempt_id']}.json"
    assert json.loads(attempt_path.read_text(encoding="utf-8")) == first_attempt
    assert len(_read_jsonl(campaign_dir / "audit" / "incubation_audit.jsonl")) == 4


def test_campaign_contract_blocks_decision_and_threshold_drift(
    tmp_path: Path,
) -> None:
    campaign_dir = tmp_path / "campaign"
    run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=1,
    )
    contract_path = campaign_dir / "campaign_contract.json"
    original_contract = json.loads(contract_path.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="campaign contract drift"):
        run_campaign_observation(
            payload=_shift_payload(_payload(), 60.0),
            campaign_dir=campaign_dir,
            now=datetime.fromtimestamp(_ANCHOR + 60.0, UTC),
            rr_target=3.0,
            min_unique_snapshots=1,
        )
    with pytest.raises(ValueError, match="campaign contract drift"):
        run_campaign_observation(
            payload=_shift_payload(_payload(), 60.0),
            campaign_dir=campaign_dir,
            now=datetime.fromtimestamp(_ANCHOR + 60.0, UTC),
            min_unique_snapshots=2,
        )

    assert json.loads(contract_path.read_text(encoding="utf-8")) == original_contract
    assert len(list((campaign_dir / "attempts").glob("*.json"))) == 1
    assert len(_read_jsonl(campaign_dir / "audit" / "incubation_audit.jsonl")) == 4


def test_report_rebuild_rejects_threshold_drift(tmp_path: Path) -> None:
    campaign_dir = tmp_path / "campaign"
    run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=1,
    )

    with pytest.raises(ValueError, match="thresholds differ"):
        build_campaign_report(campaign_dir, min_unique_snapshots=2)


def test_missing_campaign_contract_fails_existing_campaign_closed(
    tmp_path: Path,
) -> None:
    campaign_dir = tmp_path / "campaign"
    run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=1,
    )
    (campaign_dir / "campaign_contract.json").unlink()

    with pytest.raises(ValueError, match="contract is missing"):
        build_campaign_report(campaign_dir, min_unique_snapshots=1)
    with pytest.raises(ValueError, match="contract is missing"):
        run_campaign_observation(
            payload=_shift_payload(_payload(), 60.0),
            campaign_dir=campaign_dir,
            now=datetime.fromtimestamp(_ANCHOR + 60.0, UTC),
            min_unique_snapshots=1,
        )

    assert not (campaign_dir / "campaign_contract.json").exists()
    assert len(list((campaign_dir / "attempts").glob("*.json"))) == 1


def test_future_source_timestamp_is_visible_in_observation_gate(
    tmp_path: Path,
) -> None:
    campaign_dir = tmp_path / "campaign"

    with pytest.raises(CampaignObservationError, match="in the future"):
        run_campaign_observation(
            payload=_payload(),
            campaign_dir=campaign_dir,
            now=datetime.fromtimestamp(_ANCHOR - 1.0, UTC),
            min_unique_snapshots=1,
        )

    report = json.loads((campaign_dir / "campaign_report.json").read_text(encoding="utf-8"))
    assert report["source_age_seconds"]["min"] == -1.0
    assert "future_source_timestamp_observed" in report["observation_gate"]["current_threshold_warnings"]


def test_campaign_never_invokes_broker_order_placement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_broker_call(*_args, **_kwargs):
        raise AssertionError("broker placement must be unreachable from shadow mode")

    monkeypatch.setattr(
        "scripts.run_smc_live_incubation.place_order_intents",
        forbidden_broker_call,
    )

    attempt, _report = run_campaign_observation(
        payload=_payload(),
        campaign_dir=tmp_path / "campaign",
        now=_NOW,
        min_unique_snapshots=1,
    )

    assert attempt["status"] == "COMPLETED"
    assert attempt["paper_orders_placed"] == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_unique_snapshots": 0}, "min_unique_snapshots"),
        ({"max_failure_rate": 1.1}, "max_failure_rate"),
        ({"max_source_age_p95_seconds": -1.0}, "max_source_age_p95_seconds"),
    ],
)
def test_campaign_thresholds_fail_closed(
    tmp_path: Path,
    kwargs: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_campaign_report(tmp_path / "campaign", **kwargs)


def test_cli_is_local_only_and_writes_campaign_report(tmp_path: Path) -> None:
    current_anchor = datetime.now(UTC).timestamp() - 1.0
    payload = _shift_payload(_payload(), current_anchor - _ANCHOR)
    source = tmp_path / "input.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    campaign_dir = tmp_path / "campaign"

    rc = main(
        [
            "--input",
            str(source),
            "--campaign-dir",
            str(campaign_dir),
            "--min-unique-snapshots",
            "1",
        ]
    )

    assert rc == 0
    report = json.loads((campaign_dir / "campaign_report.json").read_text(encoding="utf-8"))
    assert report["observation_gate"]["verdict"] == "PASS"
    assert report["promotion_gate"]["verdict"] == "NO_GO"
    assert report["network_io"] is False
    assert report["broker_io"] is False


def test_partial_family_coverage_attempt_does_not_poison_the_campaign(
    tmp_path: Path,
) -> None:
    # 2026-08-18 Verdrahtungs-Sweep K2: partial coverage is the setup
    # producer's NORMAL output (a family without a valid event is skipped),
    # but the attempt loader pinned strict equality against all four
    # variants. The immutable partial attempt file then made every later
    # report rebuild raise — one honest thin snapshot poisoned the campaign
    # forever and the 20-unique-snapshot gate became unreachable.
    campaign_dir = tmp_path / "campaign"
    partial = _payload()
    partial["structure"]["fvg"] = []
    partial["structure"]["liquidity_sweeps"] = []

    first_attempt, first_report = run_campaign_observation(
        payload=partial,
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=2,
    )
    assert first_attempt["status"] == "COMPLETED"
    assert first_attempt["families"] == ["BOS", "OB"]
    assert first_report["family_snapshot_counts"]["FVG"] == 0

    # The poison path: rebuilding the report re-reads the immutable partial
    # attempt from disk — this raised before the fix.
    rebuilt = build_campaign_report(campaign_dir, min_unique_snapshots=2)
    assert rebuilt["observation_gate"]["verdict"] == "PENDING"

    # And the campaign keeps accepting attempts after the partial one.
    second_attempt, report = run_campaign_observation(
        payload=_shift_payload(_payload(), 60.0),
        campaign_dir=campaign_dir,
        now=datetime.fromtimestamp(_ANCHOR + 60.0, UTC),
        min_unique_snapshots=2,
    )
    assert second_attempt["status"] == "COMPLETED"
    assert second_attempt["families"] == ["BOS", "OB", "FVG", "SWEEP"]
    assert report["family_snapshot_counts"]["BOS"] == 2
    assert report["family_snapshot_counts"]["FVG"] == 1


def test_tampered_families_shapes_still_fail_closed(tmp_path: Path) -> None:
    # The relaxation accepts exactly one shape: a non-empty, duplicate-free
    # subsequence of FAMILY_VARIANTS in canonical order. Everything else
    # keeps failing the rebuild closed.
    campaign_dir = tmp_path / "campaign"
    attempt, _report = run_campaign_observation(
        payload=_payload(),
        campaign_dir=campaign_dir,
        now=_NOW,
        min_unique_snapshots=1,
    )
    attempt_path = campaign_dir / "attempts" / f"{attempt['attempt_id']}.json"
    original = attempt_path.read_text(encoding="utf-8")

    for bad_families in (
        ["BOS", "BOS"],  # duplicate
        ["BOS", "UNKNOWN"],  # unknown family
        ["OB", "BOS"],  # non-canonical order
        [],  # empty despite COMPLETED
        "BOS",  # not a list
    ):
        tampered = json.loads(original)
        tampered["families"] = bad_families
        attempt_path.write_text(json.dumps(tampered), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid families"):
            build_campaign_report(campaign_dir, min_unique_snapshots=1)

    attempt_path.write_text(original, encoding="utf-8")
    assert build_campaign_report(campaign_dir, min_unique_snapshots=1)
