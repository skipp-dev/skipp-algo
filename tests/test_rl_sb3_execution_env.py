from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from rl.simulator import EnvConfig, ExecutionEnv, SB3ExecutionEnv


def test_execution_env_is_directly_sb3_compatible() -> None:
    env = ExecutionEnv(cfg=EnvConfig(parent_qty=1_000.0, horizon_steps=4, seed=2))
    obs, info = env.reset(seed=2)
    assert env.action_space is not None
    assert env.observation_space is not None
    assert env.action_space.shape == (1,)
    assert env.observation_space.shape == (5,)
    assert obs.shape == (5,)
    obs, reward, terminated, truncated, info = env.step(np.asarray([0.25], dtype=np.float32))
    assert obs.shape == (5,)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)


def test_sb3_execution_env_exposes_spaces_and_clamps_actions() -> None:
    env = SB3ExecutionEnv(
        execution_env=ExecutionEnv(cfg=EnvConfig(parent_qty=1_000.0, horizon_steps=4, seed=3)),
        order_type="market",
    )
    obs, info = env.reset(seed=3)
    assert env.action_space.shape == (1,)
    assert env.observation_space.shape == (5,)
    assert obs.shape == (5,)
    obs, reward, terminated, truncated, info = env.step(np.asarray([2.0], dtype=np.float32))
    assert obs.shape == (5,)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert 0.0 <= float(info["slice_qty"]) <= 1_000.0


def test_execution_env_non_finite_action_is_safely_neutralized() -> None:
    env = ExecutionEnv(cfg=EnvConfig(parent_qty=1_000.0, horizon_steps=4, seed=7))
    env.reset(seed=7)
    _obs, _reward, _terminated, _truncated, info = env.step(np.asarray([np.nan], dtype=np.float32))
    assert float(info["slice_qty"]) == 0.0
