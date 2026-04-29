"""Sprint C12.1 — RL risk extensions: CVaR reward, adversarial replay, walk-forward, audit log.

Four cohesive helpers that extend the C12 RL execution layer without
breaking the existing rl/simulator/execution_env contract:

1. cvar_reward(returns, alpha=0.05) — CVaR-penalised reward.
   Conditional Value-at-Risk (a.k.a. Expected Shortfall) on the worst
   alpha tail of bar-returns. Variance-only penalties bruise the upside;
   CVaR is the standard tail-risk objective used by every modern
   execution paper.

2. adversarial_bar_replay(bars, n_worst=10, statistic=...) — Worst-Case
   bar replay used in stress evaluation. Picks the n_worst bars by an
   arbitrary statistic (default = signed return) and returns a synthetic
   bar stream where those bars are interleaved at uniform spacing; the
   simulator then runs against the stressed stream to expose worst-case
   IS / max-DD.

3. RLWalkForwardConfig + walk_forward_episodes(config) —
   Wraps ml.walkforward with episode-aware semantics (each "sample" is
   one full RL episode). Embargoes between train/val episode blocks.

4. ConstraintHitLog — Append-only NDJSON-shard log of HardConstraintLayer
   clamps. Replaces the silent rejection in rl/safety so the operator
   can see "your reward function asked for size > cap 23 times this run"
   = reward-mis-specification signal.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c121
"""
from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# ---------------------------------------------------------------------------
# 1. CVaR reward
# ---------------------------------------------------------------------------

RiskMetric = Literal["variance", "cvar5", "cvar1"]


def cvar(returns: Sequence[float], alpha: float = 0.05) -> float:
    """Mean of the worst ``alpha`` fraction of returns (Expected Shortfall).

    Returns 0.0 for empty input. The worst-tail mean is reported as a
    *signed* value (negative for adverse tails) so downstream callers
    can subtract it from a mean-reward without sign juggling.
    """
    if not (0.0 < alpha <= 1.0):
        raise ValueError(f"alpha must be in (0, 1], got {alpha}")
    if not returns:
        return 0.0
    sorted_r = sorted(returns)
    # Monotone tail size in alpha: ceil avoids bankers-rounding flips.
    n_tail = max(1, math.ceil(alpha * len(sorted_r)))
    tail = sorted_r[:n_tail]
    return sum(tail) / len(tail)


def cvar_reward(
    returns: Sequence[float],
    *,
    alpha: float = 0.05,
    risk_aversion: float = 1.0,
) -> float:
    """Mean return - risk_aversion * |CVaR_alpha(returns)|.

    Adverse tails (CVaR < 0) raise the penalty; favourable tails leave
    it unchanged. The absolute value is used so a positive-only series
    cannot "earn" extra reward by avoiding negative tails it never had.
    """
    if not returns:
        return 0.0
    mean_r = sum(returns) / len(returns)
    tail_loss = abs(min(0.0, cvar(returns, alpha=alpha)))
    return mean_r - risk_aversion * tail_loss


# ---------------------------------------------------------------------------
# 2. Adversarial bar replay
# ---------------------------------------------------------------------------


def adversarial_bar_replay(
    bars: Sequence[Any],
    *,
    n_worst: int = 10,
    statistic: Callable[[Any], float] | None = None,
) -> list[Any]:
    """Build a stressed bar stream by interleaving the worst-N bars.

    Parameters
    ----------
    bars:
        Original bar stream (any objects; the helper is data-agnostic).
    n_worst:
        Number of worst bars to copy in. ``min(n_worst, len(bars))``
        is used so passing 100 against a 50-bar stream is safe.
    statistic:
        ``bar -> float``. Smaller values are "worse". When ``None``,
        the helper expects each bar to expose a ``.return_pct`` or
        ``["return_pct"]`` field; raises if neither is present.

    The returned stream preserves the original bar order and inserts
    copies of the worst bars back into the stream at approximately
    evenly-spaced insertion points, increasing apparent stress without
    altering the population mean too aggressively.
    """
    if n_worst < 0:
        raise ValueError(f"n_worst must be >= 0, got {n_worst}")
    n = len(bars)
    if n == 0 or n_worst == 0:
        return list(bars)

    if statistic is None:
        def _default(b: Any) -> float:
            if hasattr(b, "return_pct"):
                return float(b.return_pct)
            if isinstance(b, dict) and "return_pct" in b:
                return float(b["return_pct"])
            raise ValueError(
                "adversarial_bar_replay: bar lacks 'return_pct'; pass statistic=..."
            )
        statistic = _default

    scored = sorted(range(n), key=lambda i: statistic(bars[i]))
    take = min(n_worst, n)
    worst_bars = [bars[i] for i in scored[:take]]

    # Insert each worst bar at uniformly-spaced positions among the originals.
    out: list[Any] = list(bars)
    if take == 0:
        return out
    step = max(1, n // take)
    insertion_points = [min(n, (i + 1) * step) for i in range(take)]
    # Insert from the end so earlier indices stay valid.
    for pos, bar in zip(reversed(insertion_points), reversed(worst_bars), strict=False):
        out.insert(pos, bar)
    return out


# ---------------------------------------------------------------------------
# 3. Walk-forward over RL episodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RLWalkForwardConfig:
    """Config for episode-level walk-forward of an RL training loop."""

    n_episodes: int
    n_folds: int = 5
    embargo_episodes: int = 1
    scheme: Literal["expanding", "rolling"] = "expanding"
    train_episodes: int | None = None  # required for scheme='rolling'

    def __post_init__(self) -> None:
        if self.n_folds < 1:
            raise ValueError(f"n_folds must be >= 1, got {self.n_folds}")
        if self.n_episodes < self.n_folds + 1:
            raise ValueError(
                f"need n_episodes >= n_folds+1, got {self.n_episodes}/{self.n_folds}"
            )
        if self.embargo_episodes < 0:
            raise ValueError("embargo_episodes must be >= 0")
        if self.scheme == "rolling" and (
            self.train_episodes is None or self.train_episodes < 1
        ):
            raise ValueError("scheme='rolling' requires train_episodes >= 1")


@dataclass(frozen=True)
class RLFold:
    fold_idx: int
    train_episodes: list[int]
    val_episodes: list[int]


def walk_forward_episodes(config: RLWalkForwardConfig) -> list[RLFold]:
    """Generate purged train/val splits over RL episode IDs."""
    n = config.n_episodes
    val_size = max(1, n // (config.n_folds + 1))
    folds: list[RLFold] = []
    for k in range(config.n_folds):
        val_start = n - (config.n_folds - k) * val_size
        val_end = val_start + val_size
        train_end = max(0, val_start - config.embargo_episodes)
        if train_end <= 0:
            continue
        if config.scheme == "rolling":
            if config.train_episodes is None:
                raise RuntimeError("rolling scheme requires config.train_episodes")
            train_start = max(0, train_end - config.train_episodes)
        else:
            train_start = 0
        folds.append(
            RLFold(
                fold_idx=k,
                train_episodes=list(range(train_start, train_end)),
                val_episodes=list(range(val_start, val_end)),
            )
        )
    if not folds:
        raise ValueError("no folds produced; relax n_folds or n_episodes")
    return folds


# ---------------------------------------------------------------------------
# 4. Constraint-hit audit log
# ---------------------------------------------------------------------------


@dataclass
class ConstraintHit:
    timestamp: float
    constraint: str
    requested: float
    enforced: float
    reason: str
    extras: dict[str, Any] = field(default_factory=dict)


class ConstraintHitLog:
    """Append-only NDJSON log of HardConstraintLayer clamps.

    Designed to live next to the RL run artifacts (``artifacts/rl/``)
    so the operator can post-hoc count constraint hits per session and
    surface reward-mis-specification (e.g. "size > cap fired 23x today
    => the agent's reward is rewarding sizes it can't deploy").

    Per-line writes are flushed and ``os.fsync()``'d so a process crash
    cannot drop a successfully-recorded hit. ``read_all()`` tolerates a
    truncated last line (a crash mid-append) without losing earlier
    valid records.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, hit: ConstraintHit) -> None:
        payload = {
            "timestamp": hit.timestamp,
            "constraint": hit.constraint,
            "requested": hit.requested,
            "enforced": hit.enforced,
            "reason": hit.reason,
            "extras": hit.extras,
        }
        line = json.dumps(payload, sort_keys=True) + "\n"
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    def record_clamp(
        self,
        *,
        constraint: str,
        requested: float,
        enforced: float,
        reason: str = "",
        extras: dict[str, Any] | None = None,
    ) -> None:
        """Convenience wrapper that timestamps with ``time.time()``."""
        self.record(
            ConstraintHit(
                timestamp=time.time(),
                constraint=constraint,
                requested=float(requested),
                enforced=float(enforced),
                reason=reason,
                extras=extras or {},
            )
        )

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        nonblank_idx = [i for i, ln in enumerate(lines) if ln.strip()]
        last_nonblank = nonblank_idx[-1] if nonblank_idx else -1
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Tolerate a truncated final line from a crash mid-append;
                # earlier records remain readable.
                if i == last_nonblank:
                    break
                raise
        return out

    def __len__(self) -> int:
        return len(self.read_all())


__all__ = [
    "ConstraintHit",
    "ConstraintHitLog",
    "RLFold",
    "RLWalkForwardConfig",
    "RiskMetric",
    "adversarial_bar_replay",
    "cvar",
    "cvar_reward",
    "walk_forward_episodes",
]
