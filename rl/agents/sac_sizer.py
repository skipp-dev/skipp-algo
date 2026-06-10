"""SAC-based position sizer (optional ``stable_baselines3`` dependency).

Mirrors ``PPOSlicer`` for the continuous-action sizing problem. When sb3 is
absent, exposes ``available = False`` and raises a clear ``RuntimeError`` at
instantiation. Callers should branch on ``SACSizer.available`` and use a
fixed-fraction sizer protected by ``rl.safety.HardConstraintLayer``
otherwise.

.. warning::
   **EXPERIMENTAL** — Deep-Review 2026-04-27. This sizer is **not**
   exercised by the C12 trigger gate or any production promotion
   path; it ships for offline research only. The C12 / Phase-B
   pipelines route sizing through ``rl.safety.HardConstraintLayer``
   over a deterministic fixed-fraction sizer. Promotion of SAC
   outputs to live requires a separate sign-off; see
   ``docs/c12_trigger_runbook.md``.
"""
from __future__ import annotations

import logging
from typing import Any

try:  # pragma: no cover
    from stable_baselines3 import SAC  # type: ignore

    _HAS_SB3 = True
except Exception:  # pragma: no cover
    SAC = None  # type: ignore
    _HAS_SB3 = False


logger = logging.getLogger(__name__)


class SACSizer:
    #: Marks this sizer as research-only; production gates assert that
    #: no EXPERIMENTAL agent backs a Phase-B promotion (Deep-Review
    #: 2026-04-27). Do not flip without sign-off.
    EXPERIMENTAL: bool = True
    available: bool = _HAS_SB3
    name = "sac"

    def __init__(
        self,
        *,
        learning_rate: float = 3e-4,
        batch_size: int = 256,
        seed: int = 0,
        device: str = "auto",
        order_type: str = "limit_at_mid",
        verbose: int = 0,
    ) -> None:
        if not _HAS_SB3:
            raise RuntimeError(
                "stable-baselines3 is not installed. Install via "
                "'pip install -r requirements-rl.txt' or use a fixed-fraction "
                "sizer guarded by rl.safety.HardConstraintLayer."
            )
        self.learning_rate = float(learning_rate)
        self.batch_size = int(batch_size)
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

    def fit(self, env: Any, total_timesteps: int = 100_000) -> SACSizer:  # pragma: no cover
        sb3_env = self._wrap_env(env)
        self._training_env = sb3_env
        self._model = SAC(
            "MlpPolicy",
            sb3_env,
            learning_rate=self.learning_rate,
            batch_size=self.batch_size,
            seed=self.seed,
            device=self.device,
            verbose=self.verbose,
        )
        self._model.learn(total_timesteps=total_timesteps)
        self.resolved_device = str(getattr(self._model, "device", self.device))
        requested = str(self.device).strip().lower()
        resolved = str(self.resolved_device or "").strip().lower()
        if requested in {"cuda", "gpu"} and resolved and "cuda" not in resolved:
            logger.warning(
                "SAC requested device '%s' but resolved to '%s' (fallback to CPU-like backend)",
                self.device,
                self.resolved_device,
            )
        return self

    def predict(self, obs):  # pragma: no cover
        if self._model is None:
            raise RuntimeError("SACSizer.fit(...) must be called first")
        action, _ = self._model.predict(obs, deterministic=True)
        return action


__all__ = ["SACSizer"]
