"""Wald SPRT stop-rule for A/B promotion gates (F2 contextual / G3 auto-tuner).

Plan reference: ``smc_improvement_plan_q3_q4_2026-04-20.md`` §2.4 G3 — *"30-Tage
A/B mit sauberer Stoppregel (SPRT oder fixes N), keine ad-hoc Entscheidung."*

Design
------
One-sided two-hypothesis SPRT on a *single* arm's binary outcomes (hit / miss).
We test whether the treatment arm's hit rate ``p`` exceeds a fixed baseline
``p0`` by at least the minimum-detectable effect ``p1 - p0``:

* ``H0: p = p0``  (no improvement → reject treatment, keep static weights)
* ``H1: p = p1``  (effect ≥ delta → promote treatment weights)

Wald's boundaries with type-I error ``alpha`` and type-II error ``beta``:

* ``A = ln((1 - beta) / alpha)``  → upper boundary (accept H1)
* ``B = ln(beta / (1 - alpha))``  → lower boundary (accept H0)
* ``B < LLR < A`` → continue sampling

Per Bernoulli observation ``x ∈ {0, 1}`` the log-likelihood-ratio increment is::

    delta_llr = x * ln(p1/p0) + (1 - x) * ln((1 - p1)/(1 - p0))

The state accumulates ``n`` (count), ``k`` (hits), ``llr`` (running sum).

Why a single-arm SPRT (not paired two-arm)?
-------------------------------------------
For F2/G3 the *baseline* is the in-production calibration's known hit rate
(measured over the lifetime corpus); only the treatment arm is sampled
sequentially. This matches Wald's classical formulation exactly and avoids
the variance inflation of paired two-arm tests when control is fully observed.

If callers need a paired test instead they can call :func:`evaluate_paired`,
which collapses paired (control, treatment) outcomes to ``+1 / 0 / -1`` deltas
and runs SPRT on the marginal sign — useful when control drifts.

Determinism / fail-soft
-----------------------
* Pure Python (``math.log`` only); no numpy/scipy.
* Returns explicit ``Decision`` enum strings; never raises on degenerate input
  except parameter validation in :class:`SPRTConfig`.
* ``max_n`` clamp degrades to ``"max_n_reached"`` decision so the gate cannot
  loop forever in CI.

Decision sentinel semantics (SPRT-1)
------------------------------------
The :data:`Decision` literal carries five disjoint outcomes:

* ``"accept_h1"``     — promote treatment (LLR crossed Wald upper bound).
* ``"accept_h0"``     — reject treatment (LLR crossed Wald lower bound).
* ``"continue"``      — streaming evaluator only; LLR still inside bounds
                        and ``max_n`` (if any) not yet reached. Never
                        emitted by :func:`terminal_decision`.
* ``"max_n_reached"`` — streaming evaluator hit the hard observation cap
                        before crossing a Wald bound. Distinct from
                        ``"inconclusive"`` because it indicates the test
                        was *truncated* — additional data could change
                        the verdict.
* ``"inconclusive"``  — closed-form / post-hoc evaluator: at the supplied
                        sample size ``n`` the LLR sits strictly between
                        the Wald bounds. Distinct from ``"max_n_reached"``
                        because no streaming cap was involved; the test
                        ran to completion at fixed n. Both downstream
                        gates (g23_ab_watchdog promotion-ready, F2
                        rollback) treat ``"inconclusive"`` and
                        ``"max_n_reached"`` identically (= no action),
                        but reports preserve the distinction so
                        operators can tell *why* the test did not
                        conclude.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scripts.smc_atomic_write import atomic_write_text

Decision = Literal[
    "accept_h0",
    "accept_h1",
    "continue",
    "max_n_reached",
    "inconclusive",
]

# Both sentinels mean "no promotion, no rejection" for downstream gates.
# Kept as a tuple so consumers can iterate without re-listing the strings.
INCONCLUSIVE_DECISIONS: tuple[Decision, ...] = ("max_n_reached", "inconclusive")


@dataclass(frozen=True)
class SPRTConfig:
    """Wald SPRT parameters.

    Parameters
    ----------
    p0:
        Null-hypothesis hit rate (baseline / current production).
    p1:
        Alternative hit-rate to detect (must satisfy ``p1 > p0``).
    alpha:
        Type-I error: probability of falsely accepting H1 when H0 is true.
    beta:
        Type-II error: probability of falsely accepting H0 when H1 is true.
    max_n:
        Hard cap on observations. ``None`` = unlimited. Recommended: 30 days
        worth of data points (e.g. ~600 events for a 20-event/day arm).
    """

    p0: float
    p1: float
    alpha: float = 0.05
    beta: float = 0.20
    max_n: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 < self.p0 < 1.0:
            raise ValueError(f"p0 must be in (0, 1), got {self.p0}")
        if not 0.0 < self.p1 < 1.0:
            raise ValueError(f"p1 must be in (0, 1), got {self.p1}")
        if self.p1 <= self.p0:
            raise ValueError(
                f"p1 ({self.p1}) must exceed p0 ({self.p0}) for one-sided test"
            )
        if not 0.0 < self.alpha < 0.5:
            raise ValueError(f"alpha must be in (0, 0.5), got {self.alpha}")
        if not 0.0 < self.beta < 0.5:
            raise ValueError(f"beta must be in (0, 0.5), got {self.beta}")
        if self.max_n is not None and self.max_n < 1:
            raise ValueError(f"max_n must be >= 1 or None, got {self.max_n}")

    @property
    def upper_bound(self) -> float:
        """Wald A = ln((1 - beta) / alpha) — accept H1 when LLR >= A."""
        return math.log((1.0 - self.beta) / self.alpha)

    @property
    def lower_bound(self) -> float:
        """Wald B = ln(beta / (1 - alpha)) — accept H0 when LLR <= B."""
        return math.log(self.beta / (1.0 - self.alpha))


@dataclass(frozen=True)
class SPRTState:
    """Running SPRT state after ``n`` observations."""

    n: int = 0
    k: int = 0
    llr: float = 0.0

    @property
    def hit_rate(self) -> float:
        return self.k / self.n if self.n > 0 else 0.0


def update(state: SPRTState, outcome: bool, config: SPRTConfig) -> SPRTState:
    """Apply a single Bernoulli observation and return the new state.

    ``outcome`` is coerced to 0/1; non-bool truthy/falsy values are accepted.
    """
    x = 1 if outcome else 0
    if x == 1:
        increment = math.log(config.p1 / config.p0)
    else:
        increment = math.log((1.0 - config.p1) / (1.0 - config.p0))
    return SPRTState(n=state.n + 1, k=state.k + x, llr=state.llr + increment)


def decide(state: SPRTState, config: SPRTConfig) -> Decision:
    """Return the SPRT decision for the current state."""
    if state.llr >= config.upper_bound:
        return "accept_h1"
    if state.llr <= config.lower_bound:
        return "accept_h0"
    if config.max_n is not None and state.n >= config.max_n:
        return "max_n_reached"
    return "continue"


def evaluate(outcomes: Iterable[bool], config: SPRTConfig) -> tuple[SPRTState, Decision]:
    """Run SPRT over ``outcomes`` and stop at first terminal decision.

    Honours ``config.max_n``: if reached without hitting Wald bounds the
    decision is ``"max_n_reached"`` and the state reflects all observations
    consumed up to the cap.
    """
    state = SPRTState()
    for outcome in outcomes:
        state = update(state, outcome, config)
        d = decide(state, config)
        if d != "continue":
            return state, d
    # Exhausted iterator without terminal decision.
    return state, decide(state, config)


def evaluate_paired(
    pairs: Iterable[tuple[bool, bool]], config: SPRTConfig
) -> tuple[SPRTState, Decision]:
    """Paired-arm SPRT: collapses (control, treatment) pairs to marginal sign.

    Pairs where both arms agree (both hit or both miss) are *discarded* —
    this is the classical paired-binary test (McNemar-style sufficient
    statistic). Only discordant pairs contribute to the LLR, with treatment-
    only-hit counted as ``outcome=True`` and control-only-hit as ``False``.
    """
    discordant = (
        treatment and not control
        for control, treatment in pairs
        if control != treatment
    )
    return evaluate(discordant, config)


def terminal_decision(
    n: int, k: int, config: SPRTConfig
) -> tuple[SPRTState, Decision]:
    """Compute the SPRT decision from aggregated totals (order-independent).

    The terminal LLR after consuming ``n`` Bernoulli observations with ``k``
    hits is the closed-form sum::

        llr = k * ln(p1/p0) + (n - k) * ln((1 - p1)/(1 - p0))

    This bypasses the per-step early-stop logic and reports the decision
    that *would* have been reached if the test had been allowed to run to
    completion at sample size ``n``. This is the right call site for
    post-hoc analysis of fixed-window A/B benchmarks (plan §2.4 G3:
    "SPRT *or* fixes N").

    Returns ``"inconclusive"`` (SPRT-1) when the LLR is strictly inside both
    Wald bounds at terminal n — the gate cannot promote (accept_h1) or
    reject (accept_h0) on inconclusive evidence. This sentinel is distinct
    from the streaming-only ``"max_n_reached"`` because no observation cap
    was involved; the test simply ran to completion at fixed n with
    insufficient evidence either way. Downstream gates treat both as
    no-action (see :data:`INCONCLUSIVE_DECISIONS`).
    """
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"invalid totals: n={n}, k={k}")
    if n == 0:
        return SPRTState(), "inconclusive"
    llr = (
        k * math.log(config.p1 / config.p0)
        + (n - k) * math.log((1.0 - config.p1) / (1.0 - config.p0))
    )
    state = SPRTState(n=n, k=k, llr=llr)
    if llr >= config.upper_bound:
        return state, "accept_h1"
    if llr <= config.lower_bound:
        return state, "accept_h0"
    return state, "inconclusive"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _read_outcomes_jsonl(path: Path) -> list[bool]:
    out: list[bool] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if "hit" not in rec:
            raise ValueError(f"{path}: row missing 'hit': {rec!r}")
        out.append(bool(rec["hit"]))
    return out


def _emit_report(state: SPRTState, decision: Decision, config: SPRTConfig) -> dict:
    return {
        "schema_version": 1,
        "decision": decision,
        "n": state.n,
        "k": state.k,
        "hit_rate": round(state.hit_rate, 4),
        "llr": round(state.llr, 4),
        "wald_upper": round(config.upper_bound, 4),
        "wald_lower": round(config.lower_bound, 4),
        "config": {
            "p0": config.p0,
            "p1": config.p1,
            "alpha": config.alpha,
            "beta": config.beta,
            "max_n": config.max_n,
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Wald SPRT for A/B promotion gates")
    parser.add_argument("--outcomes", type=Path, required=True,
                        help="JSONL file with rows {'hit': bool, ...}")
    parser.add_argument("--p0", type=float, required=True, help="Baseline hit rate")
    parser.add_argument("--p1", type=float, required=True, help="Target hit rate")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--beta", type=float, default=0.20)
    parser.add_argument("--max-n", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional path for the JSON report; default stdout only")
    args = parser.parse_args(argv)

    config = SPRTConfig(
        p0=args.p0,
        p1=args.p1,
        alpha=args.alpha,
        beta=args.beta,
        max_n=args.max_n,
    )
    outcomes = _read_outcomes_jsonl(args.outcomes)
    state, decision = evaluate(outcomes, config)
    report = _emit_report(state, decision, config)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(report, indent=2) + "\n", args.output)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
