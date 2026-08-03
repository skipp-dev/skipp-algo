from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from open_prep.pre_a0_model import fit_platt_calibration, make_artifact, train_logistic_regression
from open_prep.pre_a0_schema import PreA0SnapshotRow, write_snapshot_partition
from scripts import evaluate_pre_a0_shadow, prepare_pre_a0_training_data


def _artifact(path: Path):
    features = [{"price_progress": index / 39} for index in range(40)]
    labels = [int(index >= 20) for index in range(40)]
    model = train_logistic_regression(features, labels, ("price_progress",))
    raw = [model.raw_score(row) for row in features]
    artifact = make_artifact(
        model,
        fit_platt_calibration(raw, labels),
        schema_version="pre-a0-snapshot-v1",
        feature_version="pre-a0-features-v1",
        split_manifest_sha256="sealed",
        trained_window=("2026-06-01", "2026-06-30"),
        calibrated_window=("2026-07-01", "2026-07-02"),
        review_after="2099-01-01T00:00:00Z",
        horizons=(60, 180),
        metrics={"test_rows": 200.0},
        gates={"offline_evaluated": True, "shadow_evaluated": False},
    )
    path.write_text(json.dumps(artifact.to_dict()), encoding="utf-8")
    return artifact


def _row(
    day: int,
    second: int,
    *,
    probability: float,
    artifact_id: str,
    symbol: str = "XYZ",
) -> PreA0SnapshotRow:
    timestamp = 1_800_000_000 + day * 86_400 + second
    return PreA0SnapshotRow.create(
        feature_version="pre-a0-features-v1",
        session_date=f"2026-07-{day:02d}",
        source="databento:live",
        market_session="regular",
        symbol=symbol,
        prediction_time=timestamp,
        max_feature_time=timestamp,
        direction="up",
        state="WATCH",
        price_progress=0.6,
        volume_progress=0.7,
        price_distance_pct=0.4,
        volume_distance_pace=0.3,
        price_slope_15s=0.01,
        volume_slope_15s=0.02,
        direction_stability=1.0,
        data_age_ms=10,
        gap_complete=True,
        selection_reason="warm_1s",
        sample_weight=1.0,
        model_artifact_id=artifact_id,
        probability_60=probability,
        probability_180=probability,
        score_status_60="ready",
        score_status_180="ready",
    )


def _fixture(
    tmp_path: Path,
    *,
    positive_probability: float = 0.9,
    negative_probability: float = 0.1,
    extra_positive: bool = False,
):
    artifact_path = tmp_path / "artifact.json"
    artifact = _artifact(artifact_path)
    offline = tmp_path / "offline.json"
    offline.write_text(
        json.dumps(
            {
                "artifact_id": artifact.artifact_id,
                "split_sha256": artifact.split_manifest_sha256,
                "metrics": artifact.metrics,
                "offline_gate_passed": True,
            }
        ),
        encoding="utf-8",
    )
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "shadow": {
                    "max_brier_ratio": 1.0,
                    "max_ece": 0.5,
                    "min_average_precision_lift": 2.0,
                    "min_labeled_rows_per_horizon": 5,
                    "min_positive_rows_per_horizon": 5,
                    "min_score_coverage": 1.0,
                    "min_sessions": 5,
                    "require_single_artifact": True,
                    "require_zero_audit_findings": True,
                }
            }
        ),
        encoding="utf-8",
    )
    snapshots = tmp_path / "snapshots"
    journal = tmp_path / "a0.jsonl"
    journal_rows = []
    for day in range(1, 6):
        positive = _row(
            day, 0, probability=positive_probability, artifact_id=artifact.artifact_id
        )
        negative = _row(
            day, 10, probability=negative_probability, artifact_id=artifact.artifact_id, symbol="ABC"
        )
        sentinel = _row(
            day, 300, probability=negative_probability, artifact_id=artifact.artifact_id
        )
        day_rows = [positive, negative, sentinel]
        if extra_positive:
            second = _row(
                day, 5, probability=positive_probability,
                artifact_id=artifact.artifact_id, symbol="DEF",
            )
            day_rows.append(second)
            journal_rows.append(
                json.dumps(
                    {
                        "decision_id": f"a0-def-{day}",
                        "symbol": "DEF",
                        "direction": "LONG",
                        "source": "databento",
                        "final_level": "A0",
                        "decision_at": second.prediction_time + 30,
                        "session_date": second.session_date,
                        "reason_codes": ["core_a0_thresholds"],
                    }
                )
            )
        write_snapshot_partition(
            day_rows, snapshots, build_id=f"b{day}", code_revision="abc"
        )
        journal_rows.append(
            json.dumps(
                {
                    "decision_id": f"a0-{day}",
                    "symbol": "XYZ",
                    "direction": "LONG",
                    "source": "databento",
                    "final_level": "A0",
                    "decision_at": positive.prediction_time + 30,
                    "session_date": positive.session_date,
                    "reason_codes": ["core_a0_thresholds"],
                }
            )
        )
    journal.write_text("\n".join(journal_rows) + "\n", encoding="utf-8")
    return artifact_path, offline, policy, snapshots, journal, artifact


def test_shadow_evaluation_passes_with_scored_multisession_evidence(tmp_path: Path) -> None:
    artifact_path, offline, policy, snapshots, journal, artifact = _fixture(tmp_path)
    report, validated = evaluate_pre_a0_shadow.evaluate(
        artifact_path=artifact_path,
        offline_report_path=offline,
        policy_path=policy,
        snapshot_root=snapshots,
        journal_paths=[journal],
    )

    assert report["shadow_gate_passed"] is True
    assert report["shadow_evaluation"]["sessions"] == 5
    assert report["shadow_evaluation"]["horizons"]["60"]["score_coverage"] == 1.0
    assert validated.artifact_id == artifact.artifact_id
    assert validated.gates["shadow_evaluated"] is True


def test_shadow_gate_blocks_when_ap_lift_is_below_minimum(tmp_path: Path) -> None:
    """Policy v2: the AP floor per horizon is min(1.0, lift * base_rate).

    Inverted probabilities (positives scored LOW) rank worse than the base
    rate — the gate must name the lift reason, not pass on an absolute floor
    tuned to a different base-rate regime.
    """
    artifact_path, offline, policy, snapshots, journal, _artifact = _fixture(
        tmp_path, positive_probability=0.1, negative_probability=0.9
    )
    report, _ = evaluate_pre_a0_shadow.evaluate(
        artifact_path=artifact_path,
        offline_report_path=offline,
        policy_path=policy,
        snapshot_root=snapshots,
        journal_paths=[journal],
    )
    assert report["shadow_gate_passed"] is False
    assert any(
        reason.endswith("_average_precision_lift_below_minimum")
        for reason in report["shadow_evaluation"]["reasons"]
    ), report["shadow_evaluation"]["reasons"]


def test_lift_floor_is_capped_so_perfect_ranking_stays_attainable(tmp_path: Path) -> None:
    """At base rates above 1/lift the uncapped floor exceeds the maximum
    possible AP (1.0) — a perfectly ranked horizon would be blocked by
    construction. The floor must degrade to 1.0, not to impossible."""
    artifact_path, offline, policy, snapshots, journal, _artifact = _fixture(
        tmp_path, extra_positive=True  # 2 positives / 1 negative scored -> base rate 2/3
    )
    report, _ = evaluate_pre_a0_shadow.evaluate(
        artifact_path=artifact_path,
        offline_report_path=offline,
        policy_path=policy,
        snapshot_root=snapshots,
        journal_paths=[journal],
    )
    assert not any(
        reason.endswith("_average_precision_lift_below_minimum")
        for reason in report["shadow_evaluation"]["reasons"]
    ), report["shadow_evaluation"]["reasons"]


def test_shadow_evaluation_rejects_mixed_artifact_identity(tmp_path: Path) -> None:
    artifact_path, offline, policy, snapshots, journal, _artifact_value = _fixture(tmp_path)
    first = next(snapshots.rglob("*.parquet"))
    import pandas as pd

    frame = pd.read_parquet(first)
    frame.loc[0, "model_artifact_id"] = "another-artifact"
    frame.to_parquet(first, index=False)
    manifest = first.with_suffix(".manifest.json")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["row_count"] = len(frame)
    rows = evaluate_pre_a0_shadow._rows(frame)
    payload["rows_sha256"] = hashlib.sha256(
        json.dumps(
            [asdict(row) for row in sorted(rows, key=lambda item: item.record_id)],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    report, validated = evaluate_pre_a0_shadow.evaluate(
        artifact_path=artifact_path,
        offline_report_path=offline,
        policy_path=policy,
        snapshot_root=snapshots,
        journal_paths=[journal],
    )
    assert report["shadow_gate_passed"] is False
    assert "shadow_artifact_identity_mismatch" in report["shadow_evaluation"]["reasons"]
    assert validated.gates["shadow_evaluated"] is False


def test_prepare_training_data_is_walk_forward_and_reproducible(tmp_path: Path) -> None:
    artifact_path, _offline, _policy, snapshots, journal, artifact = _fixture(tmp_path)
    training, test, provenance = prepare_pre_a0_training_data.prepare(
        artifact_path=artifact_path,
        snapshot_root=snapshots,
        journal_paths=[journal],
        code_revision="abc123",
    )

    assert training["feature_names"] == list(artifact.model.feature_names)
    assert {row["session_date"] for row in training["train"]} == {
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
    }
    assert {row["session_date"] for row in training["calibration"]} == {"2026-07-04"}
    assert {row["session_date"] for row in test["rows"]} == {"2026-07-05"}
    assert test["split_sha256"] == provenance["split_manifest"]["split_sha256"]
    assert provenance["audit"]["passed"] is True
    assert provenance["reproducible"] is True


def test_load_snapshots_collapses_byte_identical_duplicate_records(tmp_path: Path) -> None:
    # A mid-session restart / duplicate producer re-emits byte-identical rows
    # (record_id is content-addressed) into a fresh part file. The loader must
    # collapse them idempotently instead of failing closed (observed 2026-07-23).
    snapshots = tmp_path / "snapshots"
    shared = _row(1, 0, probability=0.9, artifact_id="art-1")
    other = _row(1, 10, probability=0.1, artifact_id="art-1", symbol="ABC")
    write_snapshot_partition([shared, other], snapshots, build_id="b1", code_revision="rev")
    write_snapshot_partition([shared], snapshots, build_id="b2", code_revision="rev")

    frame, paths = evaluate_pre_a0_shadow._load_snapshots(snapshots)

    assert len(paths) == 2  # both part files were read and manifest-validated
    assert not frame["record_id"].duplicated().any()
    assert set(frame["record_id"]) == {shared.record_id, other.record_id}
    assert len(frame) == 2


def test_load_snapshots_rejects_conflicting_feature_records(tmp_path: Path) -> None:
    # Same record_id but a differing identity/FEATURE field is real corruption,
    # not a benign hysteresis re-emit, and must still fail closed.
    snapshots = tmp_path / "snapshots"
    original = _row(1, 0, probability=0.9, artifact_id="art-1")
    conflicting = replace(original, price_progress=0.99)
    assert original.record_id == conflicting.record_id
    write_snapshot_partition([original], snapshots, build_id="b1", code_revision="rev")
    write_snapshot_partition([conflicting], snapshots, build_id="b2", code_revision="rev")

    with pytest.raises(ValueError, match="conflicting duplicate record_id"):
        evaluate_pre_a0_shadow._load_snapshots(snapshots)


def test_load_snapshots_drops_benign_hysteresis_only_conflicts(tmp_path: Path) -> None:
    # Same record_id and identical FEATURES, but a different hysteresis-derived
    # state (a replay rebuilds PreA0Machine state from session open and diverges
    # from the live run at boundary bars, 2026-07-23/24). Unresolvable — the load
    # DROPS the record instead of guessing its state, and does not fail closed.
    snapshots = tmp_path / "snapshots"
    live = _row(1, 0, probability=0.9, artifact_id="art-1")
    other = _row(1, 10, probability=0.1, artifact_id="art-1", symbol="ABC")
    replayed = replace(
        live,
        state="NONE",
        selection_reason="base_5s",
        sample_weight=5.0,
        probability_60=None,
        probability_180=None,
        score_status_60=None,
        score_status_180=None,
    )
    assert replayed.record_id == live.record_id
    assert asdict(replayed) != asdict(live)  # differ only in decision fields
    write_snapshot_partition([live, other], snapshots, build_id="b1", code_revision="rev")
    write_snapshot_partition([replayed], snapshots, build_id="b2", code_revision="rev")

    frame, _paths = evaluate_pre_a0_shadow._load_snapshots(snapshots)

    assert live.record_id not in set(frame["record_id"])  # the ambiguous record is dropped
    assert other.record_id in set(frame["record_id"])  # unaffected records survive
    assert not frame["record_id"].duplicated().any()


def test_load_snapshots_collapses_episode_id_only_conflicts(tmp_path: Path) -> None:
    # Same record_id and identical features/state, differing ONLY in episode_id
    # (a pre-#4023 re-emit relabel). That is a benign relabel, not an ambiguous
    # state, so the copies COLLAPSE to one row rather than being dropped.
    snapshots = tmp_path / "snapshots"
    live = _row(1, 0, probability=0.9, artifact_id="art-1")
    relabelled = replace(live, episode_id="episode-relabelled")
    assert relabelled.record_id == live.record_id
    write_snapshot_partition([live], snapshots, build_id="b1", code_revision="rev")
    write_snapshot_partition([relabelled], snapshots, build_id="b2", code_revision="rev")

    frame, _paths = evaluate_pre_a0_shadow._load_snapshots(snapshots)

    assert list(frame["record_id"]) == [live.record_id]  # collapsed, not dropped
