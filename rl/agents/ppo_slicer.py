"""PPO-based order slicer (optional ``stable_baselines3`` dependency).

Wraps ``stable_baselines3.PPO`` over the now real-gym ``ExecutionEnv``
(or, for pinned order-type overrides, ``rl.simulator.SB3ExecutionEnv``).
When sb3/gymnasium are absent, the class
exposes ``available = False`` and instantiating raises a clear
``RuntimeError``. Callers should branch on ``PPOSlicer.available`` and use
``EpsilonGreedyTwapAgent`` otherwise.

.. warning::
   **EXPERIMENTAL** — Deep-Review 2026-04-27. This agent is **not**
   exercised by the C12 trigger gate or any production promotion
   path; it ships for offline research only. The C12 / Phase-B
   pipelines route through :class:`EpsilonGreedyTwapAgent` and the
   deterministic TWAP baseline. Promotion of PPO outputs to live
   requires a separate sign-off; see ``docs/c12_trigger_runbook.md``.
"""
from __future__ import annotations

from typing import Any

try:  # pragma: no cover - exercised only in environments with sb3
    import gymnasium as gym  # type: ignore
    from stable_baselines3 import PPO  # type: ignore

    _HAS_DEPS = True
except Exception:  # pragma: no cover - the absence is the locally tested path
    gym = None  # type: ignore
    PPO = None  # type: ignore
    _HAS_DEPS = False


class PPOSlicer:
    """Production wrapper around ``sb3.PPO`` (EXPERIMENTAL — see module docstring)."""

    #: Marks this agent as research-only; production gates assert that
    #: no EXPERIMENTAL agent backs a Phase-B promotion (Deep-Review
    #: 2026-04-27). Do not flip without sign-off.
    EXPERIMENTAL: bool = True
    available: bool = _HAS_DEPS
    name = "ppo"

    def __init__(
        self,
        *,
        learning_rate: float = 3e-4,
        n_steps: int = 512,
        seed: int = 0,
        device: str = "auto",
        order_type: str = "limit_at_mid",
        verbose: int = 0,
    ) -> None:
        if not _HAS_DEPS:
            raise RuntimeError(
                "stable-baselines3 / gymnasium are not installed. Install via "
                "'pip install -r requirements-rl.txt' or use "
                "rl.agents.EpsilonGreedyTwapAgent."
            )
        self.learning_rate = float(learning_rate)
        self.n_steps = int(n_steps)
        self.seed = int(seed)
        self.device = str(device)
        self.order_type = str(order_type)
        self.verbose = int(verbose)
        self._model: Any = None
        self._training_env: Any = None
        self.resolved_device: str | None = None

    def _wrap_env(self, env: Any) -> Any:
        if hasattr(env, "action_space") and hasattr(env, "observation_space"):
            return env
        from rl.simulator.sb3_execution_env import SB3ExecutionEnv

        return SB3ExecutionEnv(execution_env=env, order_type=self.order_type)

    def fit(self, env: Any, total_timesteps: int = 50_000) -> PPOSlicer:  # pragma: no cover
        sb3_env = self._wrap_env(env)
        self._training_env = sb3_env
        self._model = PPO(
            "MlpPolicy",
            sb3_env,
            learning_rate=self.learning_rate,
            n_steps=self.n_steps,
            seed=self.seed,
            device=self.device,
            verbose=self.verbose,
        )
        self._model.learn(total_timesteps=total_timesteps)
        self.resolved_device = str(getattr(self._model, "device", self.device))
        return self

    def predict(self, obs):  # pragma: no cover
        if self._model is None:
            raise RuntimeError("PPOSlicer.fit(...) must be called first")
        action, _ = self._model.predict(obs, deterministic=True)
        return action


__all__ = ["PPOSlicer"]
