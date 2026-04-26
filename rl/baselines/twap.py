"""Time-Weighted Average Price slicer."""
from __future__ import annotations

from rl.simulator import ExecutionEnv
from rl.types import ExecutionAction, ExecutionState


class TWAPSlicer:
    """Equal slice across the remaining horizon, posted as ``limit_at_mid``."""

    name = "twap"

    def act(self, state: ExecutionState) -> ExecutionAction:
        """Return a 1/steps_left slice using ``state.recent_volume_profile``
        as the remaining-step proxy.
        """
        steps_left = max(1, len(getattr(state, "recent_volume_profile", ())))
        return ExecutionAction(
            slice_size=1.0 / steps_left,
            order_type="limit_at_mid",
        )

    def run(self, env: ExecutionEnv) -> dict:
        env.reset()
        total_reward = 0.0
        for k in range(env.cfg.horizon_steps):
            steps_left = env.cfg.horizon_steps - k
            slice_frac = 1.0 / steps_left
            _, r, terminated, truncated, _ = env.step(
                ExecutionAction(slice_size=slice_frac, order_type="limit_at_mid")
            )
            total_reward += r
            if terminated or truncated:
                break
        return {
            "implementation_shortfall_bps": env.total_implementation_shortfall_bps,
            "total_reward": total_reward,
        }
