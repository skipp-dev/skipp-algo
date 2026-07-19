"""Thread-safe Prometheus telemetry for PRE-A0 shadow operation."""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any

from .pre_a0_model import ModelStatus, PreA0ModelArtifact, ShadowScore


class PreA0Telemetry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model_status = "off"
        self._enabled = False
        self._model_artifact_id = "none"
        self._calibration_version = "none"
        self._disabled_reasons: tuple[str, ...] = ()
        self._inference_errors = 0
        self._feature_missing = 0
        self._feature_out_of_range = 0
        self._alert_budget_exceeded = 0
        self._duplicate_decision_ids = 0
        self._inference_duration_ms_sum = 0.0
        self._inference_count = 0
        self._snapshots_recorded = 0
        self._snapshot_rows_flushed = 0
        self._persistence_errors = 0
        self._states: Counter[str] = Counter()
        self._scores: Counter[tuple[int, str]] = Counter()
        self._alerts: Counter[tuple[int, str]] = Counter()
        self._outcomes: Counter[tuple[int, str]] = Counter()

    def set_disabled(self, reasons: tuple[str, ...]) -> None:
        with self._lock:
            self._enabled = False
            self._model_status = "off"
            self._disabled_reasons = tuple(reasons)

    def set_model(
        self,
        status: ModelStatus,
        artifact: PreA0ModelArtifact | None,
        reason: str | None,
    ) -> None:
        with self._lock:
            self._enabled = True
            self._model_status = str(status)
            self._model_artifact_id = artifact.artifact_id if artifact else "none"
            self._calibration_version = (
                artifact.calibration.version
                if artifact and artifact.calibration
                else "none"
            )
            self._disabled_reasons = (reason,) if reason else ()

    def record_estimate(self, state: str) -> None:
        with self._lock:
            self._states[state.strip().lower() or "unknown"] += 1

    def record_score(self, score: ShadowScore) -> None:
        with self._lock:
            self._inference_count += 1
            self._inference_duration_ms_sum += max(0.0, score.inference_ms)
            self._feature_missing += len(score.missing_features)
            self._feature_out_of_range += len(score.out_of_range_features)
            if score.probability is None:
                self._inference_errors += 1
                bucket = "unavailable"
            else:
                bucket = f"{min(9, int(score.probability * 10)) * 10:02d}"
            self._scores[(score.horizon_s, bucket)] += 1

    def record_snapshot(self, *, recorded: bool, flushed: int) -> None:
        with self._lock:
            self._snapshots_recorded += int(recorded)
            self._snapshot_rows_flushed += max(0, int(flushed))

    def record_persistence_error(self) -> None:
        with self._lock:
            self._persistence_errors += 1

    def record_runtime_error(self) -> None:
        with self._lock:
            self._inference_errors += 1

    def record_alert(self, horizon: int, direction: str) -> None:
        with self._lock:
            self._alerts[(int(horizon), direction.strip().lower())] += 1

    def record_alert_budget_exceeded(self) -> None:
        with self._lock:
            self._alert_budget_exceeded += 1

    def record_outcome(self, horizon: int, outcome: str) -> None:
        with self._lock:
            self._outcomes[(int(horizon), outcome.strip().lower())] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "model_status": self._model_status,
                "model_artifact_id": self._model_artifact_id,
                "calibration_version": self._calibration_version,
                "disabled_reasons": self._disabled_reasons,
                "inference_errors": self._inference_errors,
                "feature_missing": self._feature_missing,
                "feature_out_of_range": self._feature_out_of_range,
                "alert_budget_exceeded": self._alert_budget_exceeded,
                "duplicate_decision_ids": self._duplicate_decision_ids,
                "inference_duration_ms_sum": self._inference_duration_ms_sum,
                "inference_count": self._inference_count,
                "snapshots_recorded": self._snapshots_recorded,
                "snapshot_rows_flushed": self._snapshot_rows_flushed,
                "persistence_errors": self._persistence_errors,
                "states": dict(self._states),
                "scores": dict(self._scores),
                "alerts": dict(self._alerts),
                "outcomes": dict(self._outcomes),
            }

    def render_prometheus(self) -> str:
        snapshot = self.snapshot()
        ready = int(snapshot["model_status"] == str(ModelStatus.READY))
        calibrated = int(snapshot["calibration_version"] != "none")
        rows = [
            f"pre_a0_enabled {int(snapshot['enabled'])}",
            f"pre_a0_model_ready {ready}",
            f"pre_a0_calibration_valid {calibrated}",
            f"pre_a0_inference_errors_total {snapshot['inference_errors']}",
            f"pre_a0_feature_missing_total {snapshot['feature_missing']}",
            f"pre_a0_feature_out_of_range_total {snapshot['feature_out_of_range']}",
            f"pre_a0_alert_budget_exceeded_total {snapshot['alert_budget_exceeded']}",
            f"pre_a0_duplicate_decision_ids_total {snapshot['duplicate_decision_ids']}",
            f"pre_a0_inference_duration_ms_sum {snapshot['inference_duration_ms_sum']:.6f}",
            f"pre_a0_inference_duration_ms_count {snapshot['inference_count']}",
            f"pre_a0_snapshots_recorded_total {snapshot['snapshots_recorded']}",
            f"pre_a0_snapshot_rows_flushed_total {snapshot['snapshot_rows_flushed']}",
            f"pre_a0_persistence_errors_total {snapshot['persistence_errors']}",
            "pre_a0_model_info"
            f'{{status="{snapshot["model_status"]}",artifact_id="{snapshot["model_artifact_id"]}",'
            f'calibration_version="{snapshot["calibration_version"]}"}} 1',
        ]
        rows.extend(
            f'pre_a0_estimates_total{{state="{state}"}} {count}'
            for state, count in sorted(snapshot["states"].items())
        )
        rows.extend(
            f'pre_a0_scores_total{{horizon="{horizon}",bucket="{bucket}"}} {count}'
            for (horizon, bucket), count in sorted(snapshot["scores"].items())
        )
        rows.extend(
            f'pre_a0_alerts_total{{horizon="{horizon}",direction="{direction}"}} {count}'
            for (horizon, direction), count in sorted(snapshot["alerts"].items())
        )
        rows.extend(
            f'pre_a0_outcomes_total{{horizon="{horizon}",outcome="{outcome}"}} {count}'
            for (horizon, outcome), count in sorted(snapshot["outcomes"].items())
        )
        return "\n".join(rows) + "\n"
