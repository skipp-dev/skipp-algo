"""Time-Weighted Average Price slicer."""
from __future__ import annotations

from rl.simulator import ExecutionEnv
from rl.types import ExecutionAction, ExecutionState


class TWAPSlicer:
    """Equal slice across the remaining horizon, posted as ``limit_at_mid``."""

    name = "twap"

    def act(self, state: ExecutionState) -> ExecutionAction:
        # remaining_time/total_time approximated by recent_volume_profile length;
        # in env we know it via obs[1] but here we use a simple 1/k schedule.
        return ExecutionAction(slice_size=0.0, order_type="limit_at_mid")

    def run(self, env: ExecutionEnv) -> dict:
        env.reset()
        total_reward = 0.0
        for k in range(env.cfg.horizon_steps):
            steps_left = env.cfg.horizon_steps - k
            slice_frac = 1.0 / steps_left
            obs, r, terminated, truncated, info = env.step(
                ExecutionAction(slice_size=slice_frac, order_type="limit_at_mid")
            )
            total_reward += r
            if terminated or truncated:
                break
        return {
            "implementation_shortfall_bps": env.total_implementation_shortfall_bps,
            "total_reward": total_reward,
        }
