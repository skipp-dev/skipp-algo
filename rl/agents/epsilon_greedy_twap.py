"""Pure-numpy ε-greedy TWAP agent (always-on fallback)."""
from __future__ import annotations

import numpy as np

from rl.types import ExecutionAction


class EpsilonGreedyTwapAgent:
    """Posts equal slices most of the time; with probability ε, posts a
    larger aggressive slice to capture sudden volume.

    Deterministic given a seed; serves as the always-on fallback when
    stable-baselines3 is unavailable.
    """

    name = "eps_greedy_twap"

    def __init__(
        self, *, epsilon: float = 0.1, seed: int = 0, horizon_steps: int = 20
    ) -> None:
        self.epsilon = float(epsilon)
        self.rng = np.random.default_rng(seed)
        self.horizon_steps = max(1.0, float(horizon_steps))

    def act(self, obs: np.ndarray) -> ExecutionAction:
        time_pct_left = float(obs[1])
        steps_left = max(1.0, time_pct_left * self.horizon_steps)
        twap_frac = 1.0 / steps_left
        if self.rng.uniform() < self.epsilon:
            return ExecutionAction(
                slice_size=min(1.0, twap_frac * 2.0),
                order_type="limit_aggressive",
            )
        return ExecutionAction(slice_size=min(1.0, twap_frac), order_type="limit_at_mid")


__all__ = ["EpsilonGreedyTwapAgent"]
