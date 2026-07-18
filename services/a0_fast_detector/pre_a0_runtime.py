"""PRE-A0 shadow/observe runtime isolated from confirmed A0 decisions."""

from __future__ import annotations

import hashlib
import logging
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from open_prep.a0_contract import A0ThresholdContext
from open_prep.a0_rollout import PreA0Mode, RolloutConfig, load_rollout_config
from open_prep.a0_stream_state import A0StreamFeatureSnapshot, GapState
from open_prep.pre_a0 import (
    PRE_A0_FEATURE_VERSION,
    PreA0Estimate,
    PreA0Features,
    PreA0Machine,
    PreA0Observation,
    PreA0State,
    build_pre_a0_features,
)
from open_prep.pre_a0_events import PreA0SnapshotBuffer, snapshot_row
from open_prep.pre_a0_model import (
    ModelStatus,
    PreA0ShadowScorer,
    ShadowScore,
    load_artifact,
)
from open_prep.pre_a0_schema import PRE_A0_SCHEMA_VERSION
from open_prep.pre_a0_telemetry import PreA0Telemetry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreA0RuntimeResult:
    estimate: PreA0Estimate
    scores: tuple[ShadowScore, ...]
    operator_payload: dict[str, Any] | None
    snapshot_recorded: bool


class PreA0Runtime:
    """Consume complete A0 stream snapshots without influencing A0 output."""

    def __init__(
        self,
        *,
        thresholds: A0ThresholdContext,
        config: RolloutConfig,
        scorer: PreA0ShadowScorer,
        store: PreA0SnapshotBuffer,
        telemetry: PreA0Telemetry,
    ) -> None:
        if config.pre_a0_mode not in {PreA0Mode.SHADOW, PreA0Mode.OBSERVE}:
            raise ValueError("runtime supports shadow or observe only")
        self.thresholds = thresholds
        self.config = config
        self.scorer = scorer
        self.store = store
        self.telemetry = telemetry
        self._history: dict[str, deque[PreA0Observation]] = {}
        self._machines: dict[str, PreA0Machine] = {}
        self._episodes: dict[str, str] = {}

    def reset(self, symbol: str) -> None:
        normalized = symbol.strip().upper()
        self._history.pop(normalized, None)
        self._machines.pop(normalized, None)
        self._episodes.pop(normalized, None)

    def process(self, snapshot: A0StreamFeatureSnapshot) -> PreA0RuntimeResult:
        if snapshot.gap_state is not GapState.COMPLETE:
            self.reset(snapshot.market.symbol)
            raise ValueError("PRE-A0 requires complete stream state")
        symbol = snapshot.market.symbol
        history = self._history.setdefault(symbol, deque())
        observation = PreA0Observation(
            snapshot.market,
            snapshot.cumulative_regular_volume,
            gap_complete=True,
        )
        history.append(observation)
        cutoff = snapshot.market.observed_at - 30.0
        while history and history[0].market.observed_at < cutoff:
            history.popleft()
        features = build_pre_a0_features(tuple(history), self.thresholds)
        machine = self._machines.setdefault(
            symbol,
            PreA0Machine(max_data_age_ms=self.config.a0_fast_max_data_age_ms),
        )
        estimate = machine.evaluate(features)
        self.telemetry.record_estimate(estimate.state.name)
        scores = tuple(
            self.scorer.score(_model_features(features, horizon), horizon_s=horizon)
            for horizon in self.config.pre_a0_allowed_horizons
        )
        for score in scores:
            self.telemetry.record_score(score)

        episode_id = self._episode_id(estimate)
        selection = _selection(estimate)
        recorded = False
        if selection is not None:
            reason, weight = selection
            row = snapshot_row(
                snapshot,
                estimate,
                selection_reason=reason,
                sample_weight=weight,
                episode_id=episode_id,
                scores=scores,
            )
            before = self.store.pending_rows
            flushed = self.store.add(row)
            recorded = self.store.pending_rows > before or flushed is not None
            self.telemetry.record_snapshot(recorded=recorded, flushed=flushed.rows if flushed else 0)
        payload = self._operator_payload(estimate, scores)
        return PreA0RuntimeResult(estimate, scores, payload, recorded)

    def flush(self) -> int:
        flushed = self.store.flush()
        self.telemetry.record_snapshot(recorded=False, flushed=flushed.rows)
        return flushed.rows

    def _episode_id(self, estimate: PreA0Estimate) -> str | None:
        symbol = estimate.features.symbol
        if estimate.state is PreA0State.NONE:
            self._episodes.pop(symbol, None)
            return None
        existing = self._episodes.get(symbol)
        if existing is not None:
            return existing
        identity = (
            f"{estimate.features.session_date}:{symbol}:{estimate.direction}:"
            f"{estimate.features.observed_at:.6f}"
        )
        episode_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        self._episodes[symbol] = episode_id
        return episode_id

    def _operator_payload(
        self,
        estimate: PreA0Estimate,
        scores: tuple[ShadowScore, ...],
    ) -> dict[str, Any] | None:
        if self.config.pre_a0_mode is not PreA0Mode.OBSERVE or estimate.state is PreA0State.NONE:
            return None
        payload = estimate.to_operator_payload()
        valid = [
            score
            for score in scores
            if score.status is ModelStatus.READY
            and score.is_calibrated
            and score.probability is not None
            and not score.out_of_range_features
        ]
        if len(valid) == len(scores):
            payload["is_calibrated"] = True
            payload["calibrated_probability_by_horizon"] = {
                str(score.horizon_s): score.probability for score in valid
            }
            payload["model_artifact_id"] = valid[0].artifact_id if valid else None
        return payload


def build_pre_a0_runtime(
    env: Mapping[str, str],
    *,
    thresholds: A0ThresholdContext,
    telemetry: PreA0Telemetry,
) -> PreA0Runtime | None:
    config = load_rollout_config(env)
    if config.pre_a0_mode is PreA0Mode.OFF:
        telemetry.set_disabled(config.issues)
        return None
    if config.pre_a0_mode is PreA0Mode.NOTIFY:
        telemetry.set_disabled(("notify_not_supported_by_shadow_worker",))
        return None
    output_raw = env.get("RT_PRE_A0_SNAPSHOT_DIR", "").strip()
    if not output_raw or config.pre_a0_model_path is None:
        telemetry.set_disabled(("snapshot_or_model_path_missing",))
        return None
    status, artifact, reason = load_artifact(
        config.pre_a0_model_path,
        expected_schema=PRE_A0_SCHEMA_VERSION,
        expected_feature_version=PRE_A0_FEATURE_VERSION,
    )
    telemetry.set_model(status, artifact, reason)
    if status is not ModelStatus.READY or artifact is None:
        return None
    if not set(config.pre_a0_allowed_horizons).issubset(artifact.horizons):
        telemetry.set_disabled(("configured_horizon_not_supported",))
        return None
    if config.pre_a0_mode is PreA0Mode.OBSERVE and not artifact.gates.get(
        "offline_evaluated", False
    ):
        telemetry.set_disabled(("observe_requires_offline_evaluation_gate",))
        return None
    try:
        max_rows = int(env.get("RT_PRE_A0_SNAPSHOT_FLUSH_ROWS", "500"))
    except ValueError:
        telemetry.set_disabled(("invalid_snapshot_flush_rows",))
        return None
    revision = env.get("RAILWAY_GIT_COMMIT_SHA", env.get("RT_PRE_A0_CODE_REVISION", "unknown"))
    store = PreA0SnapshotBuffer(Path(output_raw), code_revision=revision, max_rows=max_rows)
    return PreA0Runtime(
        thresholds=thresholds,
        config=config,
        scorer=PreA0ShadowScorer(status, artifact, reason),
        store=store,
        telemetry=telemetry,
    )


def _selection(estimate: PreA0Estimate) -> tuple[str, float] | None:
    if estimate.state is not PreA0State.NONE:
        return "warm_1s", 1.0
    if int(estimate.features.observed_at) % 5 == 0:
        return "base_5s", 5.0
    return None


def _model_features(features: PreA0Features, horizon: int) -> dict[str, float]:
    direction = 1.0 if features.direction == "up" else -1.0 if features.direction == "down" else 0.0
    values: dict[str, float | None] = {
        "price_progress": features.price_progress,
        "volume_progress": features.volume_progress,
        "price_distance_pct": features.price_distance_pct,
        "volume_distance_pace": features.volume_distance_pace,
        "price_slope_5s": features.slope("price", 5),
        "price_slope_15s": features.slope("price", 15),
        "price_slope_30s": features.slope("price", 30),
        "volume_slope_5s": features.slope("volume", 5),
        "volume_slope_15s": features.slope("volume", 15),
        "volume_slope_30s": features.slope("volume", 30),
        "price_acceleration": features.price_acceleration,
        "volume_acceleration": features.volume_acceleration,
        "direction_stability": features.direction_stability,
        "direction": direction,
        "horizon_s": float(horizon),
    }
    return {name: float(value) for name, value in values.items() if value is not None}
