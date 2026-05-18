"""C12 RL-Execution end-to-end smoke test on synthetic data.

Exercises the full pipeline:
    blotter -> Almgren-Chriss calibrator -> ExecutionEnv -> TWAP/VWAP/eps-greedy
    -> HardConstraintLayer guard -> reward summary.

Pure numpy + stdlib. Optional sb3/gymnasium are not required.
"""
from __future__ import annotations

import numpy as np
import pytest

from rl.agents import EpsilonGreedyTwapAgent, PPOSlicer, SACSizer
from rl.baselines import TWAPSlicer, VWAPSlicer
from rl.drift import RLDriftDetector
from rl.safety import HardConstraintLayer
from rl.simulator import EnvConfig, ExecutionEnv
from rl.slippage import AlmgrenChrissCalibrator
from rl.types import ExecutionAction, ExecutionState, TradeBlotter, TradeRecord


def _make_synthetic_blotter(n: int = 200, seed: int = 7) -> TradeBlotter:
    rng = np.random.default_rng(seed)
    bl = TradeBlotter()
    for i in range(n):
        side = 1 if rng.uniform() < 0.5 else -1
        qty = float(rng.uniform(100, 1000))
        vol = float(rng.uniform(5_000, 50_000))
        dur = float(rng.uniform(5, 60))
        # ground-truth slippage: 8 bps * |signed_pct| + 0.4 * sqrt(dur) + noise
        spct = (side * qty) / vol
        slip_bps = 8.0 * abs(spct) + 0.4 * dur**0.5 + float(rng.normal(0.0, 1.0))
        mid = 100.0
        fill = mid * (1.0 + side * slip_bps / 1e4)
        bl.add(
            TradeRecord(
                order_id=f"o{i}",
                family="BOS",
                side=side,
                quantity=qty,
                mid_at_signal=mid,
                fill_price=fill,
                volume_at_signal=vol,
                duration_s=dur,
            )
        )
    return bl


def test_almgren_chriss_calibrator_recovers_signal():
    bl = _make_synthetic_blotter(n=400, seed=11)
    X, y = bl.to_features_targets()
    cal = AlmgrenChrissCalibrator(prior_precision=0.01, noise_variance=4.0).fit(X, y)
    assert cal.fitted
    # Coefficients should all be non-negative (half-normal prior).
    assert np.all(cal.mean_ >= 0.0)  # type: ignore[arg-type]
    # Predictions should be close to ground truth in MAE.
    assert cal.mae(X, y) < 3.0
    assert cal.rmse(X, y) < 4.0
    est = cal.predict_bps(X[0])
    assert est.confidence_low_bps <= est.expected_bps <= est.confidence_high_bps


def test_calibrator_raises_before_fit():
    cal = AlmgrenChrissCalibrator()
    with pytest.raises(RuntimeError):
        cal.predict_bps(np.array([0.01, 4.0, 0.01]))


def test_execution_env_determinism_under_same_seed():
    cfg = EnvConfig(parent_qty=5_000.0, horizon_steps=10, seed=3)
    env_a = ExecutionEnv(cfg=cfg)
    env_b = ExecutionEnv(cfg=cfg)
    rewards_a, rewards_b = [], []
    for env, rw in ((env_a, rewards_a), (env_b, rewards_b)):
        env.reset(seed=cfg.seed)
        for _ in range(cfg.horizon_steps):
            _, r, term, trunc, _ = env.step(
                ExecutionAction(slice_size=0.1, order_type="limit_at_mid")
            )
            rw.append(r)
            if term or trunc:
                break
    assert np.allclose(rewards_a, rewards_b)


def test_execution_env_terminates_with_zero_remaining_qty():
    env = ExecutionEnv(cfg=EnvConfig(parent_qty=1_000.0, horizon_steps=5, seed=0))
    env.reset()
    last_info = None
    for _ in range(5):
        _, _, term, trunc, info = env.step(
            ExecutionAction(slice_size=0.5, order_type="market")
        )
        last_info = info
        if term or trunc:
            break
    assert last_info is not None
    assert last_info["remaining_qty"] == pytest.approx(0.0, abs=1e-6)


def test_twap_baseline_completes_and_reports_shortfall():
    cal = AlmgrenChrissCalibrator(prior_precision=0.01).fit(
        *_make_synthetic_blotter(n=200, seed=4).to_features_targets()
    )
    env = ExecutionEnv(cfg=EnvConfig(parent_qty=10_000.0, horizon_steps=20, seed=1), slippage=cal)
    res = TWAPSlicer().run(env)
    assert "implementation_shortfall_bps" in res
    assert np.isfinite(res["implementation_shortfall_bps"])
    # Parent order must be fully filled.
    assert env._remaining_qty == pytest.approx(0.0, abs=1e-6)


def test_vwap_baseline_against_uniform_profile_matches_twap_within_noise():
    cal = AlmgrenChrissCalibrator(prior_precision=0.01).fit(
        *_make_synthetic_blotter(n=200, seed=5).to_features_targets()
    )
    cfg = EnvConfig(parent_qty=10_000.0, horizon_steps=20, seed=2)
    env_t = ExecutionEnv(cfg=cfg, slippage=cal)
    env_v = ExecutionEnv(cfg=cfg, slippage=cal)
    twap = TWAPSlicer().run(env_t)
    vwap = VWAPSlicer(profile=np.ones(20)).run(env_v)
    assert abs(twap["implementation_shortfall_bps"] - vwap["implementation_shortfall_bps"]) < 5.0


def test_eps_greedy_agent_runs_through_env():
    env = ExecutionEnv(cfg=EnvConfig(parent_qty=2_000.0, horizon_steps=10, seed=1))
    obs, _ = env.reset()
    agent = EpsilonGreedyTwapAgent(epsilon=0.1, seed=0)
    for _ in range(10):
        action = agent.act(obs)
        obs, _, term, trunc, _ = env.step(action)
        if term or trunc:
            break
    assert env._remaining_qty == pytest.approx(0.0, abs=1e-6)


def test_hard_constraint_layer_clamps_oversized_action():
    layer = HardConstraintLayer(max_size_fraction=0.01, max_drawdown_pct=0.10)
    # ExecutionAction.__post_init__ validates inputs, so use a duck-typed
    # adversarial object to simulate upstream RL agent producing garbage.
    bad = type("X", (), {"slice_size": 5.0, "order_type": "panic"})()
    res = layer.guard_action(bad, drawdown_pct=0.0)  # type: ignore[arg-type]
    assert res.action.slice_size == 1.0
    assert res.action.order_type == "limit_at_mid"
    assert res.decision == "clamped"


def test_hard_constraint_layer_rejects_on_drawdown():
    layer = HardConstraintLayer(max_drawdown_pct=0.05)
    res = layer.guard_action(
        ExecutionAction(slice_size=0.5, order_type="market"), drawdown_pct=0.1
    )
    assert res.decision == "rejected"
    assert res.action.slice_size == 0.0


def test_hard_constraint_layer_clamps_size_fraction():
    layer = HardConstraintLayer(max_size_fraction=0.01)
    val, dec, _ = layer.guard_size_fraction(0.5)
    assert val == 0.01 and dec == "clamped"
    val, dec, _ = layer.guard_size_fraction(-0.01)
    assert val == 0.0 and dec == "rejected"
    val, dec, _ = layer.guard_size_fraction(0.005)
    assert val == 0.005 and dec == "accept"


def test_optional_agent_dep_contract():
    if not PPOSlicer.available:
        with pytest.raises(RuntimeError, match="stable-baselines3 / gymnasium"):
            PPOSlicer()
    if not SACSizer.available:
        with pytest.raises(RuntimeError, match="stable-baselines3"):
            SACSizer()


def test_execution_state_typed_contract():
    s = ExecutionState(
        remaining_qty=1000.0,
        remaining_time=120.0,
        current_volatility=0.2,
        current_spread=2.0,
        recent_volume_profile=(1.0, 2.0, 3.0),
        signal_strength=0.6,
    )
    assert s.signal_strength == 0.6
    assert len(s.recent_volume_profile) == 3


def test_rl_drift_detector_flags_action_distribution_shift():
    rng = np.random.default_rng(0)
    ref = rng.uniform(0.0, 0.2, size=2000)
    live_ok = rng.uniform(0.0, 0.2, size=500)
    live_shift = rng.uniform(0.6, 1.0, size=500)
    det = RLDriftDetector(warn=0.15, alarm=0.20)
    a_ok = det.check(ref, live_ok)
    a_bad = det.check(ref, live_shift)
    assert a_ok.severity in ("ok", "warn")
    assert a_bad.severity == "alarm"
    assert a_bad.psi > a_ok.psi


def test_blotter_drops_records_with_invalid_mid_at_signal():
    bl = TradeBlotter()
    bl.add(TradeRecord(order_id="bad-zero", family="BOS", side=1, quantity=100.0,
                       mid_at_signal=0.0, fill_price=100.5, volume_at_signal=1000.0, duration_s=10.0))
    bl.add(TradeRecord(order_id="bad-neg", family="BOS", side=1, quantity=100.0,
                       mid_at_signal=-1.0, fill_price=100.5, volume_at_signal=1000.0, duration_s=10.0))
    bl.add(TradeRecord(order_id="bad-nan", family="BOS", side=1, quantity=100.0,
                       mid_at_signal=float("nan"), fill_price=100.5, volume_at_signal=1000.0, duration_s=10.0))
    bl.add(TradeRecord(order_id="bad-fill", family="BOS", side=1, quantity=100.0,
                       mid_at_signal=100.0, fill_price=float("inf"), volume_at_signal=1000.0, duration_s=10.0))
    bl.add(TradeRecord(order_id="ok", family="BOS", side=1, quantity=100.0,
                       mid_at_signal=100.0, fill_price=100.05, volume_at_signal=1000.0, duration_s=10.0))
    with pytest.warns(RuntimeWarning, match="dropped 4/5"):
        X, y = bl.to_features_targets()
    assert X.shape[0] == 1
    assert y.shape[0] == 1


def test_blotter_raises_when_all_records_invalid():
    bl = TradeBlotter()
    bl.add(TradeRecord(order_id="x", family="BOS", side=1, quantity=100.0,
                       mid_at_signal=0.0, fill_price=100.5, volume_at_signal=1000.0, duration_s=10.0))
    with pytest.warns(RuntimeWarning):
        with pytest.raises(ValueError, match="all 1 blotter records dropped"):
            bl.to_features_targets()


def test_almgren_chriss_rejects_zero_noise_variance():
    bl = _make_synthetic_blotter(n=50, seed=3)
    X, y = bl.to_features_targets()
    with pytest.raises(ValueError, match="noise_variance must be > 0"):
        AlmgrenChrissCalibrator(prior_precision=0.01, noise_variance=0.0).fit(X, y)
    with pytest.raises(ValueError, match="noise_variance must be > 0"):
        AlmgrenChrissCalibrator(prior_precision=0.01, noise_variance=-1.0).fit(X, y)
