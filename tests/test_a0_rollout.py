from __future__ import annotations

from open_prep.a0_rollout import (
    A0FastMode,
    AlertBudget,
    PreA0Mode,
    load_rollout_config,
)
from open_prep.pre_a0_model import ModelStatus, ShadowScore
from open_prep.pre_a0_telemetry import PreA0Telemetry


def test_defaults_and_unsafe_modes_fail_closed() -> None:  # 2026-08-18 (C1): fmp-Flag entfernt
    defaults = load_rollout_config({})
    assert defaults.a0_fast_mode is A0FastMode.OFF
    assert defaults.pre_a0_mode is PreA0Mode.OFF
    unsafe = load_rollout_config(
        {
            "RT_A0_FAST_MODE": "active",
            "RT_PRE_A0_MODE": "notify",
            "RT_PRE_A0_MODEL_PATH": "/tmp/model.json",
        }
    )
    assert unsafe.a0_fast_mode is A0FastMode.OFF
    assert unsafe.pre_a0_mode is PreA0Mode.OFF
    assert len(unsafe.issues) == 2


def test_shadow_and_observe_are_independent_and_budget_is_hard() -> None:
    config = load_rollout_config(
        {
            "RT_A0_FAST_MODE": "shadow",
            "RT_PRE_A0_MODE": "observe",
            "RT_PRE_A0_MODEL_PATH": "/models/pre-a0.json",
            "RT_PRE_A0_MAX_ALERTS_PER_HOUR": "2",
        }
    )
    assert config.a0_fast_mode is A0FastMode.SHADOW
    assert config.pre_a0_mode is PreA0Mode.OBSERVE
    budget = AlertBudget(2)
    assert [budget.allow(now=value) for value in (1, 2, 3)] == [True, True, False]
    assert budget.allow(now=3602) is True


def test_pre_a0_telemetry_covers_runtime_gates() -> None:
    telemetry = PreA0Telemetry()
    telemetry.set_model(ModelStatus.READY, None, None)
    telemetry.record_score(
        ShadowScore(ModelStatus.READY, 0.7, False, 60, 1.5, (), (), "model", None)
    )
    telemetry.record_alert(60, "up")
    text = telemetry.render_prometheus()
    assert "pre_a0_enabled 1" in text
    assert "pre_a0_model_ready 1" in text
    assert "pre_a0_calibration_valid 0" in text
    assert 'pre_a0_alerts_total{horizon="60",direction="up"} 1' in text
