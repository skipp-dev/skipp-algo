"""Generate the SMC context golden-vector file (Phase 2 of the context bus-v3 track).

This is the cross-language semantic contract for the context library
(`SMC++/smc_context_engine_private.pine`, not yet written). It pins the *exact
scoring / rule-layer parity* that the Pine port must reproduce, by running the
authoritative Python reference builders over canonical fixtures and freezing
their outputs to ``tests/fixtures/smc_context_golden.json``.

Only the rule layer with a real Python source of truth is frozen here:

- **imbalance** — ``scripts.smc_imbalance_lifecycle.build_imbalance_lifecycle``
  (FVG create/partial/full mitigation, BPR overlap, liquidity-void >= 2% of mid)
- **sweeps** — ``scripts.smc_liquidity_sweeps.build_liquidity_sweeps``
  (sweep type classification + 0-5 quality score)
- **pools** — ``scripts.smc_liquidity_pools.build_liquidity_pools``
  (pool imbalance, +/-0.3 magnet direction, 0-5 quality score)

Structure (BOS/CHoCH), live candidate *detection*, and any field whose truth is
the Pine engine (``smc_engine_private.detect_structure`` / ``fvgs_objects``) are
deliberately NOT frozen here — they carry no Python source of truth and are
validated in the Pine compile/golden harness instead. See
``docs/smc-context-semantics.md`` for the full parity split.

Run ``python -m scripts.gen_smc_context_golden`` to regenerate. The companion
test ``tests/test_smc_context_golden.py`` fails if the live builders drift from
the frozen file, so regeneration is a deliberate, reviewed act.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.smc_imbalance_lifecycle import (
    FULL_MIT_PCT,
    LIQ_VOID_MIN_SIZE_PCT,
    PARTIAL_MIT_PCT,
    build_imbalance_lifecycle,
)
from scripts.smc_liquidity_pools import (
    IMBALANCE_SIG_THRESHOLD,
    build_liquidity_pools,
)
from scripts.smc_liquidity_sweeps import (
    SWEEP_DEPTH_MIN_PCT,
    SWEEP_RECLAIM_MAX_BARS,
    SWEEP_VOLUME_RATIO_MIN,
    build_liquidity_sweeps,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "tests" / "fixtures" / "smc_context_golden.json"

# Column order for the imbalance OHLC fixtures.
_OHLC_COLS = ("open", "high", "low", "close")


# --- Imbalance fixtures (OHLC bar sequences that exercise each rule branch) ---
# Each fixture is a list of (open, high, low, close) bars. The builder detects
# 3-bar FVGs (bar[i].low > bar[i-2].high = bull; bar[i].high < bar[i-2].low =
# bear), tracks mitigation vs the last bar, forms a BPR on overlapping active
# bull+bear FVGs, and flags a liquidity void when a gap >= 2% of mid-price.
_IMBALANCE_FIXTURES: dict[str, list[tuple[float, float, float, float]]] = {
    # No gaps -> all defaults / IMBALANCE_STATE NONE.
    "flat_no_imbalance": [
        (100.0, 100.5, 99.5, 100.0),
        (100.0, 100.6, 99.6, 100.1),
        (100.1, 100.7, 99.7, 100.2),
    ],
    # Single unmitigated bullish FVG, gap < 2% of mid -> FVG_BULL.
    "bull_fvg_active": [
        (100.0, 101.0, 99.0, 100.5),
        (101.0, 103.0, 100.8, 102.5),
        (103.0, 105.0, 102.0, 104.0),
    ],
    # Large bullish gap (>= 2% of mid) -> liquidity void takes precedence.
    "bull_liquidity_void": [
        (100.0, 100.0, 98.0, 99.5),
        (100.0, 108.0, 100.0, 107.0),
        (107.0, 110.0, 105.0, 109.0),
    ],
    # Overlapping active bull + bear FVG -> BPR active.
    "bpr_overlap": [
        (100.0, 102.0, 99.0, 101.0),
        (101.0, 106.0, 101.0, 105.0),
        (105.0, 108.0, 104.0, 107.0),
        (106.0, 107.0, 103.5, 104.0),
        (105.0, 106.0, 104.5, 105.0),
        (103.0, 103.0, 102.5, 102.8),
    ],
    # Bullish FVG that price fully retraces through -> full mitigation.
    "bull_fvg_full_mitigation": [
        (100.0, 101.0, 99.0, 100.5),
        (101.0, 103.0, 100.8, 102.5),
        (103.0, 105.0, 102.0, 104.0),
        (104.0, 104.5, 100.5, 101.0),
    ],
}


# --- Sweep fixtures (pre-computed microstructure rows the scorer classifies) ---
_SWEEP_FIXTURES: dict[str, dict[str, Any]] = {
    "no_sweep": {},
    "stop_hunt_max_quality": {
        "recent_bull_sweep": True,
        "sweep_depth_pct": 0.4,          # >= 3 * 0.1 -> deep
        "sweep_volume_ratio": 1.5,       # >= 1.2
        "sweep_reclaim_active": True,
        "sweep_zone_top": 101.0,
        "sweep_zone_bottom": 100.0,
    },
    "liquidity_grab": {
        "recent_bear_sweep": True,
        "sweep_depth_pct": 0.15,         # >= 0.1 but < 0.3
        "sweep_volume_ratio": 1.3,       # >= 1.2 -> grab (not stop-hunt)
        "sweep_reclaim_active": False,
    },
    "inducement_low_quality": {
        "recent_bull_sweep": True,
        "sweep_depth_pct": 0.05,         # < 0.1
        "sweep_volume_ratio": 1.0,       # < 1.2 -> inducement
        "sweep_reclaim_active": False,
    },
    "both_sides_ambiguous": {
        "recent_bull_sweep": True,
        "recent_bear_sweep": True,       # no sweep_bias_bull -> direction NONE
        "sweep_depth_pct": 0.2,
        "sweep_volume_ratio": 1.3,
    },
}


# --- Pool fixtures (pre-computed pool rows the scorer aggregates) -------------
_POOL_FIXTURES: dict[str, dict[str, Any]] = {
    "no_pools": {},
    "buy_side_magnet": {
        "buy_side_pool_level": 100.0,
        "buy_side_pool_strength": 4,
        "untested_buy_pools": 2,
        "sell_side_pool_strength": 1,
        "untested_sell_pools": 0,
        "pool_proximity_pct": 0.5,       # <= 1.0 near
        "pool_cluster_density": 3,       # >= 3 dense
    },
    "sell_side_magnet": {
        "sell_side_pool_level": 100.0,
        "sell_side_pool_strength": 4,
        "untested_sell_pools": 2,
        "buy_side_pool_strength": 1,
        "untested_buy_pools": 0,
        "pool_proximity_pct": 0.8,
        "pool_cluster_density": 3,
    },
    "balanced_no_magnet": {
        "buy_side_pool_strength": 2,
        "untested_buy_pools": 1,
        "sell_side_pool_strength": 2,
        "untested_sell_pools": 1,
    },
}


def _imbalance_expected(bars: list[tuple[float, float, float, float]]) -> dict[str, Any]:
    df = pd.DataFrame(bars, columns=list(_OHLC_COLS))
    return build_imbalance_lifecycle(snapshot=df)


def _sweep_expected(row: dict[str, Any]) -> dict[str, Any]:
    df = pd.DataFrame([row]) if row else pd.DataFrame([{"_placeholder": 0}])
    return build_liquidity_sweeps(snapshot=df)


def _pool_expected(row: dict[str, Any]) -> dict[str, Any]:
    df = pd.DataFrame([row]) if row else pd.DataFrame([{"_placeholder": 0}])
    return build_liquidity_pools(snapshot=df)


def build_golden() -> dict[str, Any]:
    return {
        "_meta": {
            "generated_by": "scripts/gen_smc_context_golden.py",
            "purpose": "cross-language scoring/rule parity contract for smc_context_engine_private.pine",
            "sources": [
                "scripts/smc_imbalance_lifecycle.py",
                "scripts/smc_liquidity_sweeps.py",
                "scripts/smc_liquidity_pools.py",
            ],
            "thresholds": {
                "imbalance": {
                    "PARTIAL_MIT_PCT": PARTIAL_MIT_PCT,
                    "FULL_MIT_PCT": FULL_MIT_PCT,
                    "LIQ_VOID_MIN_SIZE_PCT": LIQ_VOID_MIN_SIZE_PCT,
                },
                "sweeps": {
                    "SWEEP_DEPTH_MIN_PCT": SWEEP_DEPTH_MIN_PCT,
                    "SWEEP_RECLAIM_MAX_BARS": SWEEP_RECLAIM_MAX_BARS,
                    "SWEEP_VOLUME_RATIO_MIN": SWEEP_VOLUME_RATIO_MIN,
                },
                "pools": {
                    "IMBALANCE_SIG_THRESHOLD": IMBALANCE_SIG_THRESHOLD,
                },
            },
        },
        "imbalance_lifecycle": {
            name: {"bars": [list(b) for b in bars], "expected": _imbalance_expected(bars)}
            for name, bars in _IMBALANCE_FIXTURES.items()
        },
        "liquidity_sweeps": {
            name: {"row": row, "expected": _sweep_expected(row)}
            for name, row in _SWEEP_FIXTURES.items()
        },
        "liquidity_pools": {
            name: {"row": row, "expected": _pool_expected(row)}
            for name, row in _POOL_FIXTURES.items()
        },
    }


def main() -> None:
    golden = build_golden()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
