from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from open_prep.a0_contract import A0ThresholdContext, build_market_snapshot
from open_prep.a0_stream_state import A0StreamFeatureSnapshot, GapState
from open_prep.pre_a0 import PreA0State
from open_prep.pre_a0_model import (
    fit_platt_calibration,
    make_artifact,
    train_logistic_regression,
)
from open_prep.pre_a0_telemetry import PreA0Telemetry
from services.a0_fast_detector.pre_a0_runtime import PreA0Runtime, build_pre_a0_runtime

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
    scored = frame[frame["state"] != "NONE"]
    quiet = frame[frame["state"] == "NONE"]
    assert len(scored) > 0
    assert scored["model_artifact_id"].eq(json.loads(model_path.read_text())["artifact_id"]).all()
    assert scored["probability_30"].between(0, 1).all()
    assert scored["probability_60"].between(0, 1).all()
    assert scored["probability_180"].between(0, 1).all()
    assert scored["score_status_60"].eq("ready").all()
    assert quiet["probability_60"].isna().all()
    assert quiet["score_status_60"].isna().all()
    metrics = telemetry.render_prometheus()
    assert "pre_a0_model_ready 1" in metrics
    assert "pre_a0_snapshots_recorded_total" in metrics


def test_state_none_snapshots_record_without_scoring(tmp_path) -> None:
    model_path = tmp_path / "model.json"
    output = tmp_path / "snapshots"
    _artifact(model_path)
    telemetry = PreA0Telemetry()
    runtime = build_pre_a0_runtime(
        {
            "RT_A0_FAST_MODE": "shadow",
            "RT_PRE_A0_MODE": "shadow",
            "RT_PRE_A0_MODEL_PATH": str(model_path),
            "RT_PRE_A0_SNAPSHOT_DIR": str(output),
            "RT_PRE_A0_SNAPSHOT_FLUSH_ROWS": "100",
            "RT_PRE_A0_CODE_REVISION": "test",
        },
        thresholds=_THRESHOLDS,
        telemetry=telemetry,
    )
    assert runtime is not None
    results = [runtime.process(_snapshot(second, 0.1)) for second in range(11)]
    assert all(result.estimate.state.name == "NONE" for result in results)
    assert all(result.scores == () for result in results)
    snapshot = telemetry.snapshot()
    assert snapshot["inference_count"] == 0
    assert snapshot["feature_missing"] == 0
    assert snapshot["feature_out_of_range"] == 0
    assert snapshot["states"]["none"] == 11
    assert runtime.flush() > 0


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


def _estimate(state, *, symbol="NVDA", session_date="2026-07-23", direction="up", observed_at=0.0):
    return SimpleNamespace(
        state=state,
        direction=direction,
        features=SimpleNamespace(symbol=symbol, session_date=session_date, observed_at=observed_at),
    )


def test_episode_id_ignores_observation_time() -> None:
    # The id must not depend on observed_at (the field the old in-memory seed used),
    # so the same record hashes identically no matter which bar the process saw first.
    early = PreA0Runtime._episode_id(_estimate(PreA0State.WATCH, observed_at=100.0))
    later = PreA0Runtime._episode_id(_estimate(PreA0State.WATCH, observed_at=987.0))
    assert early is not None
    assert early == later


def test_episode_id_survives_a_mid_episode_restart(tmp_path) -> None:
    # Real regression for the 2026-07-23 conflict: two fresh runtimes (a restart
    # loses the in-memory episode map) see different-length prefixes of the same
    # bar stream. Every record they BOTH emit must carry the same episode_id.
    model_path = tmp_path / "model.json"
    _artifact(model_path)

    def _episode_ids(out, seconds):
        runtime = build_pre_a0_runtime(
            {
                "RT_A0_FAST_MODE": "shadow",
                "RT_PRE_A0_MODE": "observe",
                "RT_PRE_A0_MODEL_PATH": str(model_path),
                "RT_PRE_A0_SNAPSHOT_DIR": str(out),
                "RT_PRE_A0_SNAPSHOT_FLUSH_ROWS": "100",
                "RT_PRE_A0_CODE_REVISION": "test",
            },
            thresholds=_THRESHOLDS,
            telemetry=PreA0Telemetry(),
        )
        assert runtime is not None
        for second in seconds:
            runtime.process(_snapshot(second, 0.45 + second * 0.02))
        runtime.flush()
        frame = pd.concat(pd.read_parquet(path) for path in out.rglob("*.parquet"))
        return frame.set_index("record_id")["episode_id"]

    full = _episode_ids(tmp_path / "full", range(21))
    restarted = _episode_ids(tmp_path / "restarted", range(10, 21))
    shared = [
        rid
        for rid in full.index.intersection(restarted.index)
        if pd.notna(full[rid]) and pd.notna(restarted[rid])
    ]
    assert shared, "no shared scored record between the two runs"
    for rid in shared:
        assert full[rid] == restarted[rid]


def test_episode_id_is_none_for_quiet_state() -> None:
    assert PreA0Runtime._episode_id(_estimate(PreA0State.NONE)) is None


def test_episode_id_distinguishes_symbol_direction_and_session() -> None:
    base = _estimate(PreA0State.WATCH)
    assert PreA0Runtime._episode_id(base) != PreA0Runtime._episode_id(
        _estimate(PreA0State.WATCH, symbol="AMD")
    )
    assert PreA0Runtime._episode_id(base) != PreA0Runtime._episode_id(
        _estimate(PreA0State.WATCH, direction="down")
    )
    assert PreA0Runtime._episode_id(base) != PreA0Runtime._episode_id(
        _estimate(PreA0State.WATCH, session_date="2026-07-24")
    )
