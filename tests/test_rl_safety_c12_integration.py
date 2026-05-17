"""Sprint C12 regression tests: HardConstraintLayer audit sink + CVaR risk metric."""
from __future__ import annotations

from pathlib import Path

from rl.extensions import ConstraintHitLog
from rl.safety import HardConstraintLayer
from rl.simulator.execution_env import EnvConfig, ExecutionEnv
from rl.types import ExecutionAction


# ---------------------------------------------------------------------------
# HardConstraintLayer.hit_log audit sink
# ---------------------------------------------------------------------------


def test_layer_without_hit_log_keeps_legacy_behaviour() -> None:
    layer = HardConstraintLayer(max_size_fraction=0.01)
    fraction, decision, _ = layer.guard_size_fraction(0.05)
    assert decision == "clamped"
    assert fraction == 0.01


def test_layer_records_drawdown_rejection(tmp_path: Path) -> None:
    log = ConstraintHitLog(tmp_path / "hits.ndjson")
    layer = HardConstraintLayer(hit_log=log)
    layer.guard_action(
        ExecutionAction(slice_size=0.001, order_type="limit_at_mid"),
        drawdown_pct=0.50,
    )
    rows = log.read_all()
    assert len(rows) == 1
    assert rows[0]["constraint"] == "drawdown"
    assert rows[0]["requested"] == 0.50


def test_layer_records_size_fraction_clamp(tmp_path: Path) -> None:
    log = ConstraintHitLog(tmp_path / "hits.ndjson")
    layer = HardConstraintLayer(max_size_fraction=0.01, hit_log=log)
    fraction, decision, _ = layer.guard_size_fraction(0.05)
    assert decision == "clamped"
    assert fraction == 0.01
    rows = log.read_all()
    assert len(rows) == 1
    assert rows[0]["constraint"] == "size_fraction"


def test_layer_records_negative_size_rejection(tmp_path: Path) -> None:
    log = ConstraintHitLog(tmp_path / "hits.ndjson")
    layer = HardConstraintLayer(hit_log=log)
    fraction, decision, _ = layer.guard_size_fraction(-0.1)
    assert decision == "rejected"
    assert fraction == 0.0
    rows = log.read_all()
    assert len(rows) == 1
    assert rows[0]["enforced"] == 0.0


def test_layer_audit_failure_does_not_block_decision() -> None:
    class _BrokenLog:
        def record_clamp(self, **_kw: object) -> None:
            raise RuntimeError("disk full")

    layer = HardConstraintLayer(max_size_fraction=0.01, hit_log=_BrokenLog())  # type: ignore[arg-type]
    # Must still return clamped result, not raise.
    fraction, decision, _ = layer.guard_size_fraction(0.05)
    assert decision == "clamped"
    assert fraction == 0.01


# ---------------------------------------------------------------------------
# ExecutionEnv.risk_metric (variance / cvar5 / cvar1)
# ---------------------------------------------------------------------------


def _run_episode(env: ExecutionEnv) -> float:
    env.reset()
    total = 0.0
    while True:
        _obs, reward, terminated, truncated, _info = env.step(
            ExecutionAction(slice_size=0.5, order_type="limit_at_mid")
        )
        total += float(reward)
        if terminated or truncated:
            break
    return total


def test_execution_env_default_risk_metric_is_variance() -> None:
    cfg = EnvConfig()
    assert cfg.risk_metric == "variance"


def test_execution_env_cvar5_runs_to_completion() -> None:
    cfg = EnvConfig(risk_metric="cvar5")
    env = ExecutionEnv(cfg)
    total = _run_episode(env)
    # Pure smoke: episode completes and produces a finite reward.
    assert total == total  # not NaN


def test_execution_env_cvar1_runs_to_completion() -> None:
    cfg = EnvConfig(risk_metric="cvar1")
    env = ExecutionEnv(cfg)
    total = _run_episode(env)
    assert total == total
