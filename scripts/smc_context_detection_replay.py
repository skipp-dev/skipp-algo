"""Repository replay vectors for Pine-only R3 context detection.

The Python golden owns scoring parity.  This module covers the other column:
state transitions around confirmed pivot installation, sweep reclaim/staleness,
pool clustering/removal, and aggregate voting.  It remains repository evidence,
not TradingView execution evidence.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.smc_atomic_write import atomic_write_text
from scripts.smc_liquidity_pools import (
    CLUSTER_STRONG_COUNT,
    IMBALANCE_SIG_THRESHOLD,
    PROXIMITY_NEAR_PCT,
)
from scripts.smc_liquidity_sweeps import (
    SWEEP_DEPTH_MIN_PCT,
    SWEEP_DEPTH_STOP_HUNT_PCT,
    SWEEP_RECLAIM_MAX_BARS,
    SWEEP_VOLUME_RATIO_MIN,
)

ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT: Final = ROOT / "tests" / "fixtures" / "smc_context_detection_replay.json"


@dataclass(frozen=True)
class DetectionBar:
    high: float
    low: float
    close: float
    volume_ratio: float = 0.0
    pivot_high: float | None = None
    pivot_low: float | None = None


class SweepDetector:
    def __init__(self, fresh_max_bars: int = 20) -> None:
        self.fresh_max_bars = fresh_max_bars
        self.reference_high: float | None = None
        self.reference_low: float | None = None
        self.previous_high: float | None = None
        self.previous_low: float | None = None
        self.event: dict | None = None

    def process(self, bar: DetectionBar) -> dict:
        bull = (
            self.reference_low is not None
            and bar.low < self.reference_low
            and (self.previous_low is None or self.previous_low >= self.reference_low)
        )
        bear = (
            self.reference_high is not None
            and bar.high > self.reference_high
            and (self.previous_high is None or self.previous_high <= self.reference_high)
        )

        if bull or bear:
            bull_depth = (
                (self.reference_low - bar.low) / abs(self.reference_low) * 100 if bull and self.reference_low else 0.0
            )
            bear_depth = (
                (bar.high - self.reference_high) / abs(self.reference_high) * 100
                if bear and self.reference_high
                else 0.0
            )
            depth = max(bull_depth, bear_depth)
            if depth >= SWEEP_DEPTH_STOP_HUNT_PCT and bar.volume_ratio >= SWEEP_VOLUME_RATIO_MIN:
                sweep_type = 1
            elif bar.volume_ratio >= SWEEP_VOLUME_RATIO_MIN:
                sweep_type = 2
            else:
                sweep_type = 3
            reclaimed = (not bull or bar.close > self.reference_low) and (not bear or bar.close < self.reference_high)
            self.event = {
                "bull": bull,
                "bear": bear,
                "type": sweep_type,
                "direction": 1 if bull and not bear else -1 if bear and not bull else 0,
                "takenDirection": -1 if bull and not bear else 1 if bear and not bull else 0,
                "depthPct": round(depth, 6),
                "volumeRatio": bar.volume_ratio,
                "referenceHigh": self.reference_high,
                "referenceLow": self.reference_low,
                "reclaimed": reclaimed,
                "age": 0,
            }
        elif self.event is not None:
            self.event["age"] += 1
            if not self.event["reclaimed"] and self.event["age"] <= SWEEP_RECLAIM_MAX_BARS:
                self.event["reclaimed"] = (not self.event["bull"] or bar.close > self.event["referenceLow"]) and (
                    not self.event["bear"] or bar.close < self.event["referenceHigh"]
                )

        if bar.pivot_high is not None:
            self.reference_high = bar.pivot_high
        if bar.pivot_low is not None:
            self.reference_low = bar.pivot_low
        self.previous_high = bar.high
        self.previous_low = bar.low

        if self.event is None:
            return {
                "bull": False,
                "bear": False,
                "type": 0,
                "direction": 0,
                "reclaimed": False,
                "age": None,
                "fresh": False,
                "quality": 0,
            }

        fresh = self.event["age"] <= self.fresh_max_bars
        quality = 0
        if fresh:
            quality += int(self.event["bull"] or self.event["bear"])
            quality += int(self.event["type"] in (1, 2))
            quality += int(self.event["reclaimed"])
            quality += int(self.event["depthPct"] >= SWEEP_DEPTH_MIN_PCT)
            quality += int(self.event["volumeRatio"] >= SWEEP_VOLUME_RATIO_MIN)
        return {
            "bull": self.event["bull"] if fresh else False,
            "bear": self.event["bear"] if fresh else False,
            "type": self.event["type"] if fresh else 0,
            "direction": self.event["direction"] if fresh else 0,
            "reclaimed": self.event["reclaimed"] if fresh else False,
            "age": self.event["age"],
            "fresh": fresh,
            "quality": min(quality, 5),
        }


class PoolDetector:
    def __init__(self, tolerance_pct: float = 0.1, max_levels: int = 20) -> None:
        self.tolerance_pct = tolerance_pct
        self.max_levels = max_levels
        self.buy: list[list[float | int]] = []
        self.sell: list[list[float | int]] = []

    def _add(self, levels: list[list[float | int]], candidate: float) -> None:
        match: int | None = None
        best: float | None = None
        for index, (level, _strength) in enumerate(levels):
            distance = abs(candidate - float(level)) / max(abs(float(level)), 1e-9) * 100
            if distance <= self.tolerance_pct and (best is None or distance < best):
                match = index
                best = distance
        if match is None:
            levels.insert(0, [candidate, 1])
            del levels[self.max_levels :]
            return
        level, strength = levels[match]
        levels[match] = [
            (float(level) * int(strength) + candidate) / (int(strength) + 1),
            min(5, int(strength) + 1),
        ]

    @staticmethod
    def _nearest(
        levels: list[list[float | int]],
        close: float,
        buy: bool,
    ) -> tuple[float | None, int]:
        candidates = [
            (float(level), int(strength))
            for level, strength in levels
            if (float(level) > close if buy else float(level) < close)
        ]
        if not candidates:
            return None, 0
        return min(candidates, key=lambda item: abs(item[0] - close))

    def process(self, bar: DetectionBar) -> dict:
        self.buy = [item for item in self.buy if bar.high < float(item[0])]
        self.sell = [item for item in self.sell if bar.low > float(item[0])]
        if bar.pivot_high is not None and bar.pivot_high > bar.close:
            self._add(self.buy, bar.pivot_high)
        if bar.pivot_low is not None and bar.pivot_low < bar.close:
            self._add(self.sell, bar.pivot_low)

        buy_level, buy_strength = self._nearest(self.buy, bar.close, True)
        sell_level, sell_strength = self._nearest(self.sell, bar.close, False)
        total_buy = buy_strength + len(self.buy)
        total_sell = sell_strength + len(self.sell)
        total = total_buy + total_sell
        imbalance = round((total_buy - total_sell) / total, 4) if total else 0.0
        magnet = 1 if imbalance >= IMBALANCE_SIG_THRESHOLD else -1 if imbalance <= -IMBALANCE_SIG_THRESHOLD else 0
        proximities = [
            abs(level - bar.close) / abs(bar.close) * 100
            for level in (buy_level, sell_level)
            if level is not None and bar.close
        ]
        proximity = round(min(proximities), 4) if proximities else 0.0
        density = min(5, max(buy_strength, sell_strength))
        quality = sum(
            (
                buy_level is not None or sell_level is not None,
                buy_strength >= 3 or sell_strength >= 3,
                0 < proximity <= PROXIMITY_NEAR_PCT,
                density >= CLUSTER_STRONG_COUNT,
                abs(imbalance) >= IMBALANCE_SIG_THRESHOLD,
            )
        )
        return {
            "buyLevel": buy_level,
            "sellLevel": sell_level,
            "buyStrength": buy_strength,
            "sellStrength": sell_strength,
            "untestedBuy": len(self.buy),
            "untestedSell": len(self.sell),
            "proximityPct": proximity,
            "clusterDensity": density,
            "imbalance": imbalance,
            "magnet": magnet,
            "quality": min(quality, 5),
        }


def aggregate_context(votes: list[int], qualities: list[float | None]) -> dict:
    score = sum(votes)
    bias = 1 if score >= 2 else -1 if score <= -2 else 0
    available = [quality for quality in qualities if quality is not None]
    quality = round(sum(available) / len(available)) if available else 0
    return {
        "directionalScore": score,
        "bias": bias,
        "availableDomains": len(available),
        "qualityScore": quality,
    }


def build_detection_replay() -> dict:
    seed = DetectionBar(95.0, 92.0, 94.0, pivot_high=100.0, pivot_low=90.0)

    immediate = SweepDetector()
    immediate.process(seed)
    immediate_result = immediate.process(DetectionBar(96.0, 89.5, 90.5, volume_ratio=1.5))
    duplicate_result = immediate.process(DetectionBar(96.0, 89.6, 91.0, volume_ratio=1.5))

    delayed = SweepDetector()
    delayed.process(seed)
    delayed_before = delayed.process(DetectionBar(96.0, 89.8, 89.9, volume_ratio=1.0))
    delayed_after = delayed.process(DetectionBar(96.0, 90.0, 90.1, volume_ratio=1.0))
    for _ in range(20):
        stale = delayed.process(DetectionBar(96.0, 91.0, 92.0))

    both = SweepDetector()
    both.process(seed)
    both_result = both.process(DetectionBar(100.4, 89.6, 95.0, volume_ratio=1.3))

    pools = PoolDetector()
    pool_steps = [
        pools.process(DetectionBar(99.0, 94.0, 95.0, pivot_high=100.0, pivot_low=90.0)),
        pools.process(DetectionBar(99.0, 94.0, 95.0, pivot_high=100.05)),
        pools.process(DetectionBar(99.0, 94.0, 95.0, pivot_high=99.98)),
        pools.process(DetectionBar(99.8, 99.0, 99.5)),
    ]
    pool_taken = pools.process(DetectionBar(100.1, 99.0, 99.5))

    return {
        "schemaVersion": 1,
        "gate": "R3-REMAINING-FRAMES",
        "gateStatus": "partial",
        "repositoryReplayStatus": "passed",
        "tradingViewStatus": "pending",
        "sweepCases": {
            "immediateStopHuntReclaim": immediate_result,
            "noDuplicateWhileLevelRemainsPierced": duplicate_result,
            "delayedReclaimBefore": delayed_before,
            "delayedReclaimAfter": delayed_after,
            "staleAfterFreshWindow": stale,
            "twoSidedAmbiguous": both_result,
        },
        "poolCases": {
            "clusterSteps": pool_steps,
            "takenPoolRemoved": pool_taken,
        },
        "aggregateCases": {
            "bullishAgreement": aggregate_context(
                [1, 1, 0, 1, 0, 0],
                [100, 100, None, 80, None, None],
            ),
            "conflictedNeutral": aggregate_context(
                [1, -1, 0, 0, 0, 0],
                [50, 100, None, None, None, None],
            ),
            "bearishAgreement": aggregate_context(
                [-1, -1, -1, 0, 0, 0],
                [100, 100, 100, None, None, None],
            ),
        },
        "limitations": [
            "Pivot confirmations are explicit fixture inputs; TradingView remains authoritative for ta.pivothigh/ta.pivotlow execution.",
            "Repository replay and source contracts do not prove the private Pine library compiles or executes in TradingView.",
        ],
        "openGates": [
            "Compile the complete private context library in TradingView.",
            "Run redacted Pine replay vectors for sweep, pool, session, and aggregate outputs after publication.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    atomic_write_text(
        json.dumps(build_detection_replay(), indent=2, sort_keys=True) + "\n",
        args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
