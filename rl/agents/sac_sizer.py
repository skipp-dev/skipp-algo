"""SAC-based position sizer (optional ``stable_baselines3`` dependency).

Mirrors ``PPOSlicer`` for the continuous-action sizing problem. When sb3 is
absent, exposes ``available = False`` and raises a clear ``RuntimeError`` at
instantiation. Callers should branch on ``SACSizer.available`` and use a
fixed-fraction sizer protected by ``rl.safety.HardConstraintLayer``
otherwise.
"""
from __future__ import annotations

from typing import Any

try:  # pragma: no cover
    from stable_baselines3 import SAC  # type: ignore

    _HAS_SB3 = True
except Exception:  # pragma: no cover
    SAC = None  # type: ignore
    _HAS_SB3 = False


class SACSizer:
    available: bool = _HAS_SB3
    name = "sac"

    def __init__(self, *, learning_rate: float = 3e-4, batch_size: int = 256, seed: int = 0) -> None:
        if not _HAS_SB3:
            raise RuntimeError(
                "stable-baselines3 is not installed. Install via "
                "'pip install -r requirements-rl.txt' or use a fixed-fraction "
                "sizer guarded by rl.safety.HardConstraintLayer."
            )
        self.learning_rate = float(learning_rate)
        self.batch_size = int(batch_size)
        self.seed = int(seed)
        self._model: Any = None

    def fit(self, env: Any, total_timesteps: int = 100_000) -> "SACSizer":  # pragma: no cover
        self._model = SAC(
            "MlpPolicy", env, learning_rate=self.learning_rate, batch_size=self.batch_size, seed=self.seed
        )
        self._model.learn(total_timesteps=total_timesteps)
        return self

    def predict(self, obs):  # pragma: no cover
        if self._model is None:
            raise RuntimeError("SACSizer.fit(...) must be called first")
        action, _ = self._model.predict(obs, deterministic=True)
        return action


__all__ = ["SACSizer"]
