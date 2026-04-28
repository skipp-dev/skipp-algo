"""Volume-Weighted Average Price slicer.

Slices proportionally to a forecast volume profile. The ``profile`` argument
is normalised to sum to 1.0 across the horizon.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from rl.simulator import ExecutionEnv
from rl.types import ExecutionAction


class VWAPSlicer:
    name = "vwap"

    def __init__(self, profile: Sequence[float]) -> None:
        p = np.asarray(profile, dtype=float)
        if p.size == 0 or p.sum() <= 0:
            raise ValueError("profile must be a positive-sum sequence")
        self.profile = p / p.sum()

    def run(self, env: ExecutionEnv) -> dict:
        env.reset()
        H = env.cfg.horizon_steps
        if self.profile.size != H:
            # Resample profile to env horizon by linear interpolation.
            xs = np.linspace(0.0, 1.0, self.profile.size)
            xt = np.linspace(0.0, 1.0, H)
            p = np.interp(xt, xs, self.profile)
            p = p / p.sum()
        else:
            p = self.profile
        total_reward = 0.0
        remaining_pct = 1.0
        for k in range(H):
            remain_target = max(0.0, 1.0 - p[: k + 1].sum())
            slice_pct = max(0.0, remaining_pct - remain_target)
            slice_frac = slice_pct / remaining_pct if remaining_pct > 0 else 0.0
            slice_frac = float(np.clip(slice_frac, 0.0, 1.0))
            _, r, terminated, truncated, _ = env.step(
                ExecutionAction(slice_size=slice_frac, order_type="limit_at_mid")
            )
            total_reward += r
            remaining_pct -= slice_pct
            if terminated or truncated:
                break
        return {
            "implementation_shortfall_bps": env.total_implementation_shortfall_bps,
            "total_reward": total_reward,
        }
