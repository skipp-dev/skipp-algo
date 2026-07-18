from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from open_prep.a0_contract import A0ThresholdContext, build_market_snapshot
from open_prep.a0_stream_state import A0StreamFeatureSnapshot, GapState
from open_prep.pre_a0_model import (
    fit_platt_calibration,
    make_artifact,
    train_logistic_regression,
)
from open_prep.pre_a0_telemetry import PreA0Telemetry
from services.a0_fast_detector.pre_a0_runtime import build_pre_a0_runtime

_OPEN = datetime(2026, 7, 20, 9, 30, tzinfo=ZoneInfo("America/New_York"))
_THRESHOLDS = A0ThresholdContext(3.0, 1.0, 0.6, 2.0, 1.0, 0.5)


def _artifact(path, *, horizons=(30, 60, 180), offline_evaluated=True) -> None:
    rows = [
        {"price_progress": index / 39, "volume_progress": index / 39}
        for index in range(40)
    ]
    labels = [int(index >= 20) for index in range(40)]
    model = train_logistic_regression(rows, labels, ("price_progress", "volume_progress"))
    raw = [model.raw_score(row) for row in rows]
    artifact = make_artifact(
        model,
        fit_platt_calibration(raw, labels),
        schema_version="pre-a0-snapshot-v1",
        feature_version="pre-a0-features-v1",
        split_manifest_sha256="sealed",
        trained_window=("2026-06-01", "2026-06-30"),
        calibrated_window=("2026-07-01", "2026-07-10"),
        review_after="2099-01-01T00:00:00Z",
        horizons=horizons,
        metrics={"brier": 0.1},
        gates={"offline_evaluated": offline_evaluated},
    )
    path.write_text(json.dumps(artifact.to_dict()), encoding="utf-8")


def _snapshot(second: int, progress: float) -> A0StreamFeatureSnapshot:
    event = (_OPEN + timedelta(seconds=second)).timestamp()
    change = 2.0 * progress
    pace = 3.0 * progress
    market = build_market_snapshot(
        symbol="NVDA",
        price=100 * (1 + change / 100),
        prev_close=100,
        change_pct=change,
        raw_daily_volume_ratio=0.02 * pace,
        expected_volume_fraction=0.02,
        normalized_volume_pace=pace,
        source="databento:live",
        raw_ts_event=event,
        raw_ts_recv=event + 0.05,
        observed_at=event + 0.05,
    )
    return A0StreamFeatureSnapshot(
        market=market,
        cumulative_regular_volume=10_000 + second * 1_000,
        gap_state=GapState.COMPLETE,
        reference_source="databento:daily",
        reference_as_of_session="2026-07-17",
        reference_version="daily-v1",
        corporate_action_version="corp-v1",
    )


def test_observe_runtime_scores_and_persists_without_confirming_a0(tmp_path) -> None:
    model_path = tmp_path / "model.json"
    output = tmp_path / "snapshots"
    _artifact(model_path)
    telemetry = PreA0Telemetry()
    runtime = build_pre_a0_runtime(
        {
            "RT_A0_FAST_MODE": "shadow",
            "RT_PRE_A0_MODE": "observe",
            "RT_PRE_A0_MODEL_PATH": str(model_path),
            "RT_PRE_A0_SNAPSHOT_DIR": str(output),
            "RT_PRE_A0_SNAPSHOT_FLUSH_ROWS": "100",
            "RT_PRE_A0_CODE_REVISION": "test",
        },
        thresholds=_THRESHOLDS,
        telemetry=telemetry,
    )
    assert runtime is not None
    result = None
    for second in range(21):
        result = runtime.process(_snapshot(second, 0.45 + second * 0.02))
    assert result is not None
    assert result.operator_payload is not None
    assert result.operator_payload["kind"] == "PRE_A0"
    assert result.operator_payload["level"] is None
    assert result.operator_payload["confirmed"] is False
    assert result.operator_payload["is_calibrated"] is True
    assert set(result.operator_payload["calibrated_probability_by_horizon"]) == {"30", "60", "180"}
    assert runtime.flush() > 0
    manifests = list(output.rglob("*.manifest.json"))
    parquet = list(output.rglob("*.parquet"))
    assert manifests and parquet
    frame = pd.concat(pd.read_parquet(path) for path in parquet)
    assert set(frame["selection_reason"]) == {"base_5s", "warm_1s"}
    assert frame["episode_id"].notna().any()
    metrics = telemetry.render_prometheus()
    assert "pre_a0_model_ready 1" in metrics
    assert "pre_a0_snapshots_recorded_total" in metrics


def test_missing_model_disables_only_pre_a0(tmp_path) -> None:
    telemetry = PreA0Telemetry()
    runtime = build_pre_a0_runtime(
        {
            "RT_A0_FAST_MODE": "shadow",
            "RT_PRE_A0_MODE": "shadow",
            "RT_PRE_A0_MODEL_PATH": str(tmp_path / "missing.json"),
            "RT_PRE_A0_SNAPSHOT_DIR": str(tmp_path / "snapshots"),
        },
        thresholds=_THRESHOLDS,
        telemetry=telemetry,
    )
    assert runtime is None
    snapshot = telemetry.snapshot()
    assert snapshot["model_status"] == "missing"
    assert snapshot["disabled_reasons"] == ("artifact_missing",)


def test_observe_rejects_unsupported_horizon_and_unreviewed_artifact(tmp_path) -> None:
    model_path = tmp_path / "model.json"
    _artifact(model_path, horizons=(60,), offline_evaluated=False)
    base_env = {
        "RT_A0_FAST_MODE": "shadow",
        "RT_PRE_A0_MODE": "observe",
        "RT_PRE_A0_MODEL_PATH": str(model_path),
        "RT_PRE_A0_SNAPSHOT_DIR": str(tmp_path / "snapshots"),
    }
    telemetry = PreA0Telemetry()
    assert build_pre_a0_runtime(base_env, thresholds=_THRESHOLDS, telemetry=telemetry) is None
    assert telemetry.snapshot()["disabled_reasons"] == ("configured_horizon_not_supported",)

    telemetry = PreA0Telemetry()
    only_60 = {**base_env, "RT_PRE_A0_ALLOWED_HORIZONS": "60"}
    assert build_pre_a0_runtime(only_60, thresholds=_THRESHOLDS, telemetry=telemetry) is None
    assert telemetry.snapshot()["disabled_reasons"] == ("observe_requires_offline_evaluation_gate",)
