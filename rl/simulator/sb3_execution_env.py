"""Gymnasium / SB3-compatible wrapper around ``ExecutionEnv``.

The core execution simulator intentionally stays dependency-light. This wrapper
is now mostly a thin adapter that pins ``order_type`` over the real
``ExecutionEnv`` gym contract, keeping older call sites working while the
core env itself became SB3-compatible.
"""
from __future__ import annotations

import numpy as np

from rl.simulator.execution_env import EnvConfig, ExecutionEnv
from rl.slippage import AlmgrenChrissCalibrator
from rl.types import OrderType

try:  # pragma: no cover - exercised only in RL research environments
    import gymnasium as gym  # type: ignore
    from gymnasium import spaces  # type: ignore

    _HAS_GYM = True
except Exception:  # pragma: no cover - absence is the common CI path
    gym = None  # type: ignore
    spaces = None  # type: ignore
    _HAS_GYM = False


if _HAS_GYM:  # pragma: no cover - requires optional gymnasium dependency
    class SB3ExecutionEnv(gym.Env):  # type: ignore[misc]
        """Continuous-action wrapper suitable for PPO / SAC research.

        Actions are a single scalar in ``[0, 1]`` representing the fraction of
        remaining quantity to execute this step. ``order_type`` is held fixed by
        the wrapper so the current research loop stays simple and deterministic.
        """

        metadata = {"render_modes": []}  # noqa: RUF012

        def __init__(
            self,
            *,
            execution_env: ExecutionEnv | None = None,
            cfg: EnvConfig | None = None,
            slippage: AlmgrenChrissCalibrator | None = None,
            order_type: OrderType = "limit_at_mid",
        ) -> None:
            super().__init__()
            base_env = execution_env or ExecutionEnv(
                cfg=cfg or EnvConfig(default_order_type=order_type),
                slippage=slippage,
            )
            base_env.cfg.default_order_type = order_type
            self.execution_env = base_env
            self.order_type = order_type
            self.action_space = self.execution_env.action_space
            self.observation_space = self.execution_env.observation_space

        def reset(self, *, seed: int | None = None, options: dict | None = None):
            obs, info = self.execution_env.reset(seed=seed, options=options)
            return np.asarray(obs, dtype=np.float32), info

        def step(self, action):
            obs, reward, terminated, truncated, info = self.execution_env.step(action)
            return (
                np.asarray(obs, dtype=np.float32),
                float(reward),
                bool(terminated),
                bool(truncated),
                info,
            )

        def render(self):
            return None

        def close(self) -> None:
            return None


else:
    class SB3ExecutionEnv:  # pragma: no cover - trivial dependency guard
        def __init__(self, **_: object) -> None:
            raise RuntimeError(
                "gymnasium is not installed. Install via 'pip install -r requirements-rl.txt' "
                "to use rl.simulator.SB3ExecutionEnv."
            )


__all__ = ["SB3ExecutionEnv"]
