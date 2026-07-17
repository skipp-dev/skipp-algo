"""Dependency-free Prometheus telemetry for PRE-A0 shadow operation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass(slots=True)
class PreA0Telemetry:
    model_ready: bool = False
    calibration_valid: bool = False
    inference_errors: int = 0
    feature_missing_total: int = 0
    feature_out_of_range_total: int = 0
    alert_budget_exceeded_total: int = 0
    duplicate_decision_ids_total: int = 0
    inference_duration_ms_sum: float = 0.0
    inference_count: int = 0
    alerts: Counter[tuple[int, str]] = field(default_factory=Counter)
    outcomes: Counter[tuple[int, str]] = field(default_factory=Counter)

    def observe_inference(self, duration_ms: float) -> None:
        self.inference_count += 1
        self.inference_duration_ms_sum += max(0.0, duration_ms)

    def render_prometheus(self) -> str:
        rows = [
            f"pre_a0_model_ready {int(self.model_ready)}",
            f"pre_a0_calibration_valid {int(self.calibration_valid)}",
            f"pre_a0_inference_errors_total {self.inference_errors}",
            f"pre_a0_feature_missing_total {self.feature_missing_total}",
            f"pre_a0_feature_out_of_range_total {self.feature_out_of_range_total}",
            f"pre_a0_alert_budget_exceeded_total {self.alert_budget_exceeded_total}",
            f"pre_a0_duplicate_decision_ids_total {self.duplicate_decision_ids_total}",
            f"pre_a0_inference_duration_ms_sum {self.inference_duration_ms_sum:.6f}",
            f"pre_a0_inference_duration_ms_count {self.inference_count}",
        ]
        rows.extend(
            f'pre_a0_alerts_total{{horizon="{horizon}",direction="{direction}"}} {count}'
            for (horizon, direction), count in sorted(self.alerts.items())
        )
        rows.extend(
            f'pre_a0_outcomes_total{{horizon="{horizon}",outcome="{outcome}"}} {count}'
            for (horizon, outcome), count in sorted(self.outcomes.items())
        )
        return "\n".join(rows) + "\n"
