"""Independent, fail-closed rollout controls for A0-Fast and PRE-A0.

2026-08-18 (Verdrahtungs-Sweep C1): ``fmp_a0_enabled`` (hartes True-Literal
ohne jeden Leser) und ``evaluate_promotion``/``PromotionEvidence`` (null
Aufrufer; die Promotion-Checkliste lebt im Runbook und ist ein manueller
Operator-Akt) wurden entfernt. Die Runbook-Invariante "FMP A0 bleibt in
jedem Modus unabhängig aktiv" ist STRUKTURELL (der FMP-Pfad kennt diese
Config nicht), kein Flag. Die eigentliche shadow-only-Erzwingung für
A0-Fast sitzt fail-closed in services/a0_fast_detector/worker.py; das
Parsing hier degradiert nur und protokolliert ``issues``."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class A0FastMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    OBSERVE = "observe"
    ACTIVE = "active"


class PreA0Mode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    OBSERVE = "observe"
    NOTIFY = "notify"


@dataclass(frozen=True, slots=True)
class RolloutConfig:
    a0_fast_mode: A0FastMode
    a0_fast_max_data_age_ms: int
    pre_a0_mode: PreA0Mode
    pre_a0_model_path: Path | None
    pre_a0_allowed_horizons: tuple[int, ...]
    pre_a0_max_alerts_per_hour: int
    issues: tuple[str, ...]


def load_rollout_config(env: Mapping[str, str]) -> RolloutConfig:
    """Parse configuration; any unsafe value disables only its new capability."""
    issues: list[str] = []
    try:
        fast_mode = A0FastMode(env.get("RT_A0_FAST_MODE", "off").strip().lower())
    except ValueError:
        fast_mode = A0FastMode.OFF
        issues.append("invalid_a0_fast_mode")
    try:
        max_age = int(env.get("RT_A0_FAST_MAX_DATA_AGE_MS", "5000"))
        if max_age <= 0:
            raise ValueError
    except ValueError:
        max_age = 5_000
        fast_mode = A0FastMode.OFF
        issues.append("invalid_a0_fast_max_data_age_ms")
    if fast_mode is A0FastMode.ACTIVE and env.get("RT_A0_FAST_DEPLOYMENT_APPROVED") != "1":
        fast_mode = A0FastMode.OFF
        issues.append("a0_fast_active_missing_deployment_approval")

    try:
        pre_mode = PreA0Mode(env.get("RT_PRE_A0_MODE", "off").strip().lower())
    except ValueError:
        pre_mode = PreA0Mode.OFF
        issues.append("invalid_pre_a0_mode")
    raw_path = env.get("RT_PRE_A0_MODEL_PATH", "").strip()
    model_path = Path(raw_path) if raw_path else None
    if pre_mode is not PreA0Mode.OFF and model_path is None:
        pre_mode = PreA0Mode.OFF
        issues.append("pre_a0_model_path_missing")
    if pre_mode is PreA0Mode.NOTIFY and env.get("RT_PRE_A0_DEPLOYMENT_APPROVED") != "1":
        pre_mode = PreA0Mode.OFF
        issues.append("pre_a0_notify_missing_deployment_approval")
    try:
        horizons = tuple(
            sorted({int(value.strip()) for value in env.get("RT_PRE_A0_ALLOWED_HORIZONS", "30,60,180").split(",")})
        )
        if not horizons or any(value not in {30, 60, 180} for value in horizons):
            raise ValueError
    except ValueError:
        horizons = (30, 60, 180)
        pre_mode = PreA0Mode.OFF
        issues.append("invalid_pre_a0_allowed_horizons")
    try:
        max_alerts = int(env.get("RT_PRE_A0_MAX_ALERTS_PER_HOUR", "20"))
        if max_alerts <= 0:
            raise ValueError
    except ValueError:
        max_alerts = 20
        pre_mode = PreA0Mode.OFF
        issues.append("invalid_pre_a0_alert_budget")
    return RolloutConfig(
        fast_mode,
        max_age,
        pre_mode,
        model_path,
        horizons,
        max_alerts,
        tuple(issues),
    )


class AlertBudget:
    def __init__(self, max_per_hour: int) -> None:
        if max_per_hour <= 0:
            raise ValueError("max_per_hour must be positive")
        self.max_per_hour = max_per_hour
        self._sent_at: deque[float] = deque()

    def allow(self, *, now: float) -> bool:
        boundary = now - 3600
        while self._sent_at and self._sent_at[0] <= boundary:
            self._sent_at.popleft()
        if len(self._sent_at) >= self.max_per_hour:
            return False
        self._sent_at.append(now)
        return True
