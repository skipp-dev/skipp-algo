"""Order-slicing execution environment (optionally a real gymnasium env).

Provides ``reset(seed=None) -> (obs, info)`` and
``step(action) -> (obs, reward, terminated, truncated, info)`` so a future
``stable_baselines3.PPO`` can be plugged in without an interface adapter.
When ``gymnasium`` is installed the class also exposes real
``action_space`` / ``observation_space`` metadata and accepts continuous
actions directly, making it consumable by SB3 without a shim. Without the
optional dependency it keeps the same numpy-only interface.

Reward = -ImplementationShortfall (in bps) - lambda_var * realized_variance,
matching the Almgren-Chriss mean-variance objective.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from rl.slippage import AlmgrenChrissCalibrator
from rl.types import ExecutionAction, OrderType

try:  # pragma: no cover - exercised only in RL research environments
    import gymnasium as gym  # type: ignore
    from gymnasium import spaces  # type: ignore

    _HAS_GYM = True
    _EnvBase = gym.Env  # type: ignore[misc]
except Exception:  # pragma: no cover - absence is the common CI path
    gym = None  # type: ignore
    spaces = None  # type: ignore
    _HAS_GYM = False

    class _EnvBase:  # pragma: no cover - trivial fallback base class
        pass


@dataclass
class EnvConfig:
    parent_qty: float = 10_000.0
    side: int = 1                         # +1 buy, -1 sell
    horizon_steps: int = 20
    seconds_per_step: float = 30.0
    starting_mid: float = 100.0
    lambda_var: float = 0.01
    base_volatility_bps: float = 5.0
    base_volume_per_step: float = 5_000.0
    default_order_type: OrderType = "limit_at_mid"
    seed: int = 0


@dataclass
class ExecutionEnv(_EnvBase):
    """Order-slicing environment for a single parent order.

    The slippage model is supplied by the caller; if absent, a deterministic
    zero-impact stub is used so the env can be exercised end-to-end without
    fitting a calibrator first.
    """

    cfg: EnvConfig = field(default_factory=EnvConfig)
    slippage: AlmgrenChrissCalibrator | None = None

    metadata = {"render_modes": []}

    def __post_init__(self) -> None:
        super_init = getattr(super(), "__init__", None)
        if callable(super_init):
            super_init()
        self._rng = np.random.default_rng(self.cfg.seed)
        self.action_space = None
        self.observation_space = None
        if _HAS_GYM:
            self.action_space = spaces.Box(
                low=np.asarray([0.0], dtype=np.float32),
                high=np.asarray([1.0], dtype=np.float32),
                dtype=np.float32,
            )
            obs_low = np.asarray([0.0, 0.0, 0.0, 0.0, -1.0], dtype=np.float32)
            obs_high = np.asarray(
                [1.0, 1.0, np.finfo(np.float32).max, np.finfo(np.float32).max, 1.0],
                dtype=np.float32,
            )
            self.observation_space = spaces.Box(low=obs_low, high=obs_high, dtype=np.float32)
        self._reset_state()

    # gymnasium-compatible -------------------------------------------------
    def reset(self, *, seed: int | None = None, options: dict | None = None):
        del options
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        self._reset_state()
        return self._obs(), self._info()

    def step(self, action: ExecutionAction | np.ndarray | list[float] | tuple[float, ...] | float | int):
        if self._done:
            raise RuntimeError("step() called after termination; call reset()")
        action = self._coerce_action(action)
        slice_qty = float(action.slice_size) * self._remaining_qty
        # Final step forces full liquidation regardless of action.
        if self._step_idx >= self.cfg.horizon_steps - 1:
            slice_qty = self._remaining_qty
        # Volume + price evolution
        vol_step = self.cfg.base_volume_per_step * float(np.exp(self._rng.normal(0.0, 0.2)))
        # Deep-Review 2026-04-27: vol_bps must use a lognormal multiplier
        # (mean=base, no folded-normal up-bias). The previous
        # ``abs(normal(1.0, 0.2))`` introduced an upward shift in mean
        # volatility (E[|N(1, 0.2)|] != 1), and gave the simulator an
        # unphysical asymmetric tail. ``exp(normal(0, 0.2))`` matches
        # the lognormal model already used for ``vol_step`` above.
        vol_bps = self.cfg.base_volatility_bps * float(np.exp(self._rng.normal(0.0, 0.2)))
        price_drift_bps = self._rng.normal(0.0, vol_bps)
        self._mid *= (1.0 + price_drift_bps / 1e4)
        # Slippage estimate (in bps, signed adverse for the trader).
        if self.slippage is not None and slice_qty > 0:
            spct = (self.cfg.side * slice_qty) / max(vol_step, 1.0)
            x = np.array([spct, self.cfg.seconds_per_step**0.5, abs(spct)])
            est = self.slippage.predict_bps(x)
            slip_bps = max(0.0, est.expected_bps)
        else:
            slip_bps = 0.0
        # Aggressive market orders pay an extra spread cost.
        if action.order_type == "market":
            slip_bps += 1.5
        elif action.order_type == "limit_aggressive":
            slip_bps += 0.5
        fill_price = self._mid * (1.0 + self.cfg.side * slip_bps / 1e4)
        # Update accounting
        self._filled_qty += slice_qty
        self._remaining_qty -= slice_qty
        notional_bps = (fill_price / self._anchor_mid - 1.0) * 1e4 * self.cfg.side
        # Implementation shortfall contribution = (fill - anchor) * qty
        is_contrib = notional_bps * slice_qty
        self._is_accum += is_contrib
        # Per-step variance share (matched 1:1 with the reward variance penalty
        # below so internal accounting and the optimised objective coincide).
        share = slice_qty / max(self.cfg.parent_qty, 1.0)
        var_step = (price_drift_bps ** 2) * share
        self._var_accum += var_step
        # Reward = -ImpactShortfall - lambda * variance (per-step)
        reward = -(notional_bps * share)
        reward -= self.cfg.lambda_var * var_step
        self._step_idx += 1
        terminated = self._remaining_qty <= 1e-9
        truncated = self._step_idx >= self.cfg.horizon_steps and not terminated
        if terminated or truncated:
            self._done = True
        info = self._info()
        info.update(
            {
                "slice_qty": slice_qty,
                "fill_price": fill_price,
                "slippage_bps": slip_bps,
                "implementation_shortfall_bps": is_contrib / max(self.cfg.parent_qty, 1.0),
            }
        )
        return self._obs(), float(reward), bool(terminated), bool(truncated), info

    # introspection --------------------------------------------------------
    @property
    def total_implementation_shortfall_bps(self) -> float:
        # Quantum-sweep L4: ``max(parent_qty, 1.0)`` floors the divisor at
        # 1.0 to avoid div-by-zero. For fractional-share parents
        # (``parent_qty < 1.0``) this *understates* the bps figure since
        # the true shortfall would be divided by the smaller fractional
        # quantity. Revisit if/when the simulator supports fractional
        # parents — switch to ``max(parent_qty, 1e-9)`` and document the
        # numerical-stability tradeoff in the strategy docstring.
        return self._is_accum / max(self.cfg.parent_qty, 1.0)

    @property
    def realized_variance(self) -> float:
        """Sum of per-step variance contributions consumed by the reward."""
        return float(self._var_accum)

    def render(self):
        return None

    def close(self) -> None:
        return None

    # internals ------------------------------------------------------------
    def _coerce_action(
        self,
        action: ExecutionAction | np.ndarray | list[float] | tuple[float, ...] | float | int,
    ) -> ExecutionAction:
        if isinstance(action, ExecutionAction):
            return action
        arr = np.asarray(action, dtype=float).reshape(-1)
        raw = float(arr[0]) if arr.size else 0.0
        slice_size = float(np.clip(raw, 0.0, 1.0))
        return ExecutionAction(slice_size=slice_size, order_type=self.cfg.default_order_type)

    def _reset_state(self) -> None:
        self._mid = float(self.cfg.starting_mid)
        self._anchor_mid = float(self.cfg.starting_mid)
        self._remaining_qty = float(self.cfg.parent_qty)
        self._filled_qty = 0.0
        self._step_idx = 0
        self._is_accum = 0.0
        self._var_accum = 0.0
        self._done = False

    def _obs(self) -> np.ndarray:
        return np.array(
            [
                self._remaining_qty / max(self.cfg.parent_qty, 1.0),
                1.0 - self._step_idx / max(self.cfg.horizon_steps, 1),
                self.cfg.base_volatility_bps / 100.0,
                self.cfg.base_volume_per_step / max(self.cfg.parent_qty, 1.0),
                float(self.cfg.side),
            ],
            dtype=float,
        )

    def _info(self) -> dict:
        return {
            "step": self._step_idx,
            "remaining_qty": self._remaining_qty,
            "filled_qty": self._filled_qty,
            "mid": self._mid,
            "is_bps": self.total_implementation_shortfall_bps,
        }


__all__ = ["EnvConfig", "ExecutionEnv"]
