"""Technical analysis utilities ported from IB_monitoring.py.

Provides:
  #1  calculate_support_resistance_targets  — S/R levels, Fibonacci, ATR targets
  #2  apply_diminishing_returns             — sqrt() compression for score components
  #3  compute_risk_penalty                  — gradual risk penalty [0.05, 0.20]
  #4  compute_adaptive_gates                — VIX + instrument-class dynamic thresholds
  #5  classify_instrument                   — penny / small_cap / mid_cap / large_cap
  #6  detect_consolidation                  — BB squeeze + low ADX + ATR contraction
  #7  detect_breakout                       — range breakout / capitulation patterns
  #8  validate_data_quality                 — plausibility checks on candidate data
  #10 GateTracker                           — structured gate-rejection logger
  #12 detect_symbol_regime                  — per-symbol TRENDING / RANGING
  #13 compute_entry_probability             — sigmoid-based entry probability [0,1]
  #14 EWMA                                 — Energy-Weighted Moving Average score
  #15 resolve_regime_weights                — regime-adaptive weight adjustments

All functions operate on simple dicts / scalars — no pandas required.
Daily OHLCV bars are passed as ``list[dict]`` with keys
``open, high, low, close, volume``.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("open_prep.ta")


# ═══════════════════════════════════════════════════════════════════════════
# Helper: unit_scale
# ═══════════════════════════════════════════════════════════════════════════

def _unit_scale(value: float | None, lower: float, upper: float, default: float = 0.5) -> float:
    """Scale *value* into [0, 1] with clamping."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    if upper == lower:
        return max(0.0, min(1.0, default))
    scaled = (value - lower) / (upper - lower)
    return max(0.0, min(1.0, scaled))


def _safe_float(v: Any, default: float = 0.0) -> float:
    """Safely convert to float; NaN → default."""
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════════════════
# #2  Diminishing Returns
# ═══════════════════════════════════════════════════════════════════════════

def apply_diminishing_returns(raw_value: float, *, use_sqrt: bool = True) -> float:
    """Apply sqrt() compression to prevent extreme score components.

    Maps [0, 1] → [0, 1] with diminishing marginal gain.  Low values are
    amplified, high values are compressed.

    Examples::

        0.25 → 0.50   (doubled)
        0.49 → 0.70
        0.64 → 0.80
        0.81 → 0.90   (compressed)
    """
    if not use_sqrt:
        return raw_value
    clamped = max(0.0, min(1.0, raw_value))
    return math.sqrt(clamped)


# ═══════════════════════════════════════════════════════════════════════════
# #3  Risk Penalty
# ═══════════════════════════════════════════════════════════════════════════

def compute_risk_penalty(
    price: float,
    atr: float | None,
    volume_ratio: float,
    spread_pct: float = 0.0,
) -> float:
    """Compute a gradual risk penalty in [0.05, 0.20].

    Combines:
      • ATR penalty  — high ATR relative to price (0–12 %)
      • Volume penalty — low liquidity (0–6 %)
      • Spread penalty — wide bid-ask (0–2 %)

    A minimum floor of 5 % acknowledges baseline risk for every stock.
    The 20 % cap prevents over-penalisation of volatile but tradeable names.
    """
    total = 0.0

    # ATR penalty: high ATR% → high risk
    if atr and price > 0:
        atr_pct = (atr / price) * 100.0
        atr_unit = _unit_scale(atr_pct, 0.5, 3.0)
        total += atr_unit * 0.12

    # Volume penalty: rvol < 0.8 → thin liquidity
    if volume_ratio < 0.8:
        vol_unit = _unit_scale(0.8 - volume_ratio, 0.0, 0.5)
        total += vol_unit * 0.06

    # Spread penalty
    if spread_pct > 0:
        total += min(spread_pct * 10.0, 0.02)

    return max(0.05, min(total, 0.20))


# ═══════════════════════════════════════════════════════════════════════════
# #5  Instrument Classification
# ═══════════════════════════════════════════════════════════════════════════

def classify_instrument(price: float, atr_pct: float) -> str:
    """Classify a stock into penny / small_cap / mid_cap / large_cap.

    Uses price and ATR-% (ATR / price * 100) as dual criteria.
    """
    if price < 5.0 or atr_pct > 8.0:
        return "penny"
    if price < 20.0 or (atr_pct > 3.0 and price < 50.0):
        return "small_cap"
    if price < 100.0 or (atr_pct > 1.5 and price < 200.0):
        return "mid_cap"
    return "large_cap"


# ═══════════════════════════════════════════════════════════════════════════
# #4  Adaptive Gating
# ═══════════════════════════════════════════════════════════════════════════

def compute_adaptive_gates(
    *,
    base_score_min: float = 0.35,
    base_trend_z_min: float = 0.3,
    base_atr_ratio_min: float = 1.5,
    vix_level: float = 20.0,
    instrument_class: str = "mid_cap",
) -> dict[str, float]:
    """Compute adaptive gate thresholds from VIX and instrument class.

    • High VIX (>30)  → relax gates by 15 % (more opportunities)
    • Low VIX  (<15)  → tighten gates by 15 % (demand stronger signals)
    • Instrument class → ATR-ratio threshold varies
    """
    # VIX multiplier
    if vix_level > 30:
        vix_mult = 0.85
    elif vix_level < 15:
        vix_mult = 1.15
    else:
        vix_mult = 1.0

    adapted_score = max(0.20, min(0.50, base_score_min * vix_mult))
    adapted_trend = max(0.15, min(0.50, base_trend_z_min * vix_mult))

    atr_table = {
        "penny": 0.5,
        "small_cap": 1.0,
        "mid_cap": 1.5,
        "large_cap": 2.5,
    }
    adapted_atr = max(0.5, min(3.0, atr_table.get(instrument_class, base_atr_ratio_min)))

    return {
        "score_min": round(adapted_score, 3),
        "trend_z_min": round(adapted_trend, 3),
        "atr_ratio_min": round(adapted_atr, 3),
    }


# ═══════════════════════════════════════════════════════════════════════════
# #12  Per-Symbol Regime Detection
# ═══════════════════════════════════════════════════════════════════════════

def detect_symbol_regime(
    adx: float,
    bb_width_pct: float,
) -> str:
    """Classify per-symbol regime as TRENDING or RANGING.

    Uses ADX and Bollinger Band width (% of middle band).

    • TRENDING:  ADX > 25 **and** BB width > 4 %
    • RANGING :  ADX < 20 **and** BB width < 2 %
    • Otherwise defaults to NEUTRAL (uncertain — no weight adjustments).
    """
    if adx > 25.0 and bb_width_pct > 4.0:
        return "TRENDING"
    if adx < 20.0 and bb_width_pct < 2.0:
        return "RANGING"
    return "NEUTRAL"  # uncertain → no weight adjustments


# ═══════════════════════════════════════════════════════════════════════════
# #6  Consolidation Detection
# ═══════════════════════════════════════════════════════════════════════════

def detect_consolidation(
    bb_width_pct: float,
    adx: float,
    atr_ratio: float | None = None,
    *,
    bb_squeeze_threshold: float = 10.0,
) -> dict[str, Any]:
    """Detect consolidation (tight range before potential breakout).

    Uses three signals:
      1. Bollinger-Band squeeze  — ``bb_width_pct < threshold``
      2. Weak ADX               — ``adx < 20``
      3. ATR contraction         — ``atr_ratio < 1.5``

    Returns::

        {
            "is_consolidating": bool,
            "score": float (0..1),
            "bb_squeeze": bool,
            "adx_weak": bool,
            "atr_contracted": bool,
        }
    """
    # Defensive clamp: prevent ZeroDivisionError if caller passes threshold=0.
    bb_squeeze_threshold = max(bb_squeeze_threshold, 0.001)
    bb_squeeze = bb_width_pct < bb_squeeze_threshold
    adx_weak = adx < 20.0
    is_consolidating = bb_squeeze and adx_weak

    # Composite score
    score = 0.0
    if is_consolidating:
        bb_score = max(0.0, min(1.0, 1.0 - (bb_width_pct / bb_squeeze_threshold)))
        adx_score = max(0.0, min(1.0, 1.0 - (adx / 20.0)))
        atr_score = 0.5  # neutral default
        if atr_ratio is not None:
            if atr_ratio < 1.5:
                atr_score = 1.0
            elif atr_ratio < 2.0:
                atr_score = 0.7
            else:
                atr_score = 0.3
        score = round(0.4 * bb_score + 0.35 * adx_score + 0.25 * atr_score, 4)

    atr_contracted = (atr_ratio is not None and atr_ratio < 1.5)
    return {
        "is_consolidating": is_consolidating,
        "score": score,
        "bb_squeeze": bb_squeeze,
        "adx_weak": adx_weak,
        "atr_contracted": atr_contracted,
    }


# ═══════════════════════════════════════════════════════════════════════════
# #7  Breakout Detection  (daily OHLCV bars)
# ═══════════════════════════════════════════════════════════════════════════

def _ema(values: list[float], span: int) -> float:
    """Compute the final EMA value from a list of floats.

    Returns ``float('nan')`` when *values* is empty so callers can
    distinguish 'no data' from a genuine zero price.
    """
    if not values:
        return float("nan")
    k = 2.0 / (span + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def detect_breakout(
    bars: list[dict[str, Any]],
    *,
    short_n: int = 30,
    long_n: int = 60,
) -> dict[str, Any]:
    """Detect breakout patterns on daily OHLCV bars.

    Patterns detected:
      • **B_UP**   — bullish capitulation (massive volume spike + reversal at lows)
      • **B_DOWN** — bearish distribution (volume spike during decline)
      • **LONG**   — price breaks above prior-range high
      • **SHORT**  — price breaks below prior-range low

    Parameters
    ----------
    bars : list[dict]
        Daily OHLCV bars ordered oldest → newest.  Required keys:
        ``open, high, low, close, volume``.
    short_n : int
        Lookback for short-range high/low (default 30 bars).
    long_n : int
        Lookback for long-range high/low (default 60 bars).

    Returns
    -------
    dict
        ``{"direction": str | None, "pattern": str, "details": dict}``
    """
    min_bars = max(short_n, long_n) + 5
    if not bars or len(bars) < min_bars:
        return {"direction": None, "pattern": "insufficient_data", "details": {}}

    closes = [_safe_float(b.get("close")) for b in bars]
    volumes = [_safe_float(b.get("volume")) for b in bars]
    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else last_close
    last_volume = volumes[-1]

    avg_volume = sum(volumes[-50:]) / max(len(volumes[-50:]), 1) if len(volumes) >= 50 else (sum(volumes) / max(len(volumes), 1))
    volume_ratio = last_volume / avg_volume if avg_volume > 0 else 1.0

    ema_20 = _ema(closes, 20)
    _ema_50 = _ema(closes, 50) if len(closes) >= 50 else ema_20

    recent_5 = closes[-5:]
    is_declining = all(recent_5[i] <= recent_5[i - 1] for i in range(1, len(recent_5)))
    is_rising = all(recent_5[i] >= recent_5[i - 1] for i in range(1, len(recent_5)))
    price_change_pct = ((last_close / prev_close) - 1) * 100 if prev_close > 0 else 0.0

    prior_high_s = max(closes[-(short_n + 1):-1])
    prior_low_s = min(closes[-(short_n + 1):-1])
    prior_high_l = max(closes[-(long_n + 1):-1])
    prior_low_l = min(closes[-(long_n + 1):-1])

    # --- Pattern 1: Bullish Capitulation ---
    if volume_ratio >= 5.0:
        recent_low = min(closes[-10:])
        at_recent_low = last_close <= recent_low * 1.02
        has_reversal = price_change_pct > 0.5 and not is_rising
        breaking_above_ema = last_close > ema_20 and prev_close < ema_20
        if (has_reversal or breaking_above_ema) and at_recent_low:
            return {
                "direction": "B_UP",
                "pattern": "bullish_capitulation",
                "details": {
                    "volume_ratio": round(volume_ratio, 2),
                    "price_change_pct": round(price_change_pct, 2),
                },
            }

    # --- Pattern 2: Bearish Distribution ---
    if volume_ratio >= 1.5 and is_declining and price_change_pct < -0.3:
        below_ema20 = last_close < ema_20
        if below_ema20:
            return {
                "direction": "B_DOWN",
                "pattern": "bearish_distribution",
                "details": {
                    "volume_ratio": round(volume_ratio, 2),
                    "price_change_pct": round(price_change_pct, 2),
                },
            }

    # --- Pattern 3: Range Breakout ---
    tol = 0.0015
    if prior_high_s > 0 and last_close > prior_high_s * (1 + tol):
        return {
            "direction": "LONG",
            "pattern": "range_breakout_short",
            "details": {
                "prior_high": round(prior_high_s, 2),
                "pct_above": round((last_close / prior_high_s - 1) * 100, 2),
            },
        }
    if prior_high_l > 0 and last_close > prior_high_l * (1 + tol):
        return {
            "direction": "LONG",
            "pattern": "range_breakout_long",
            "details": {
                "prior_high": round(prior_high_l, 2),
                "pct_above": round((last_close / prior_high_l - 1) * 100, 2),
            },
        }
    if prior_low_s > 0 and last_close < prior_low_s * (1 - tol):
        return {
            "direction": "SHORT",
            "pattern": "range_breakdown_short",
            "details": {
                "prior_low": round(prior_low_s, 2),
                "pct_below": round((1 - last_close / prior_low_s) * 100, 2),
            },
        }
    if prior_low_l > 0 and last_close < prior_low_l * (1 - tol):
        return {
            "direction": "SHORT",
            "pattern": "range_breakdown_long",
            "details": {
                "prior_low": round(prior_low_l, 2),
                "pct_below": round((1 - last_close / prior_low_l) * 100, 2),
            },
        }

    return {"direction": None, "pattern": "no_breakout", "details": {}}


# ═══════════════════════════════════════════════════════════════════════════
# #8  Data Quality Validation
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DataQualityResult:
    """Result of data-quality validation for a candidate."""
    passed: bool
    issues: list[str] = field(default_factory=list)


def validate_data_quality(candidate: dict[str, Any]) -> DataQualityResult:
    """Run plausibility checks on a candidate dict.

    Checks ported from ``is_actionable()`` data-quality gates:

    1. **zero_volume**  — volume == 0 ⇒ no trading activity
    2. **rsi_extreme**  — RSI ≤ 0.1 or ≥ 99.9 ⇒ bad data / illiquid
    3. **oversold_1.0_low_volume** — perfect oversold + thin volume = suspicious
    4. **avg_volume_zero** — missing average-volume baseline
    5. **atr_missing** — ATR ≤ 0 ⇒ insufficient history
    6. **price_zero** — no valid price
    """
    issues: list[str] = []

    price = _safe_float(candidate.get("price"))
    volume = _safe_float(candidate.get("volume"))
    avg_volume = _safe_float(candidate.get("avg_volume") or candidate.get("avgVolume"))
    rsi = _safe_float(candidate.get("rsi"), default=50.0)
    momentum_z = _safe_float(candidate.get("momentum_z_score") or candidate.get("momentum_z"))
    rel_vol = _safe_float(candidate.get("volume_ratio") or candidate.get("rel_vol"))

    if price <= 0.0:
        issues.append("price_zero")
    if volume <= 0.0:
        issues.append("zero_volume")
    if rsi <= 0.1 or rsi >= 99.9:
        issues.append("rsi_extreme")
    if avg_volume <= 0.0:
        issues.append("avg_volume_zero")
    # Only flag atr_missing when the raw field exists but is invalid;
    # a completely absent key is not a quality issue here.
    atr_raw = candidate.get("atr")
    if atr_raw is not None and _safe_float(atr_raw) <= 0.0:
        issues.append("atr_missing")

    # Suspicious: perfect oversold + very low volume
    if momentum_z is not None and momentum_z <= -4.5 and rel_vol < 0.3:
        issues.append("extreme_momentum_low_volume")

    return DataQualityResult(passed=len(issues) == 0, issues=issues)


# ═══════════════════════════════════════════════════════════════════════════
# #10  Gate Tracking (structured logging)
# ═══════════════════════════════════════════════════════════════════════════

class GateTracker:
    """Collects gate-rejection events per pipeline run with analytics.

    Enhanced with deficit tracking, bottleneck detection, and per-gate
    statistics for data-driven threshold tuning (#2 Gate Rejection Analytics).

    Usage::

        tracker = GateTracker()
        tracker.reject("AAPL", "price_below_5", {"price": 3.2, "threshold": 5.0})
        tracker.reject("XYZ", "zero_volume", {"volume": 0})
        summary = tracker.summary()
        bottlenecks = tracker.bottleneck_report(total_candidates=100)
    """

    def __init__(self) -> None:
        self._rejections: list[dict[str, Any]] = []
        # Per-gate aggregate stats for deficit tracking
        self._gate_deficits: dict[str, list[float]] = {}
        self._gate_symbols: dict[str, set[str]] = {}

    # ── public API ──────────────────────────────────────────────────────

    def reject(
        self,
        symbol: str,
        gate: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a gate rejection with optional deficit information.

        If ``details`` contains both ``"value"`` and ``"threshold"`` keys,
        the deficit (how far the value was from passing) is tracked for
        analytics.
        """
        entry: dict[str, Any] = {"symbol": symbol, "gate": gate}
        if details:
            entry["details"] = details
            # Track deficit if value/threshold provided
            val = details.get("value") or details.get("score") or details.get("price")
            thr = details.get("threshold")
            if val is not None and thr is not None:
                try:
                    deficit = abs(float(thr) - float(val))
                    entry["deficit"] = round(deficit, 4)
                    self._gate_deficits.setdefault(gate, []).append(deficit)
                except (TypeError, ValueError):
                    pass
        self._rejections.append(entry)
        self._gate_symbols.setdefault(gate, set()).add(symbol)
        logger.debug("Gate rejected: %s — %s %s", symbol, gate, details or "")

    def summary(self) -> dict[str, Any]:
        """Return an aggregated summary of all rejections.

        Returns::

            {
                "total_rejections": int,
                "by_gate": {"gate_name": count, …},
                "by_gate_detail": {"gate_name": {count, unique_symbols, avg_deficit}, …},
                "by_symbol": {"SYM": [{"gate": …, "details": …}, …], …},
                "rejections": [full list],
            }
        """
        by_gate: dict[str, int] = {}
        by_symbol: dict[str, list[dict]] = {}
        for r in self._rejections:
            g = r["gate"]
            s = r["symbol"]
            by_gate[g] = by_gate.get(g, 0) + 1
            by_symbol.setdefault(s, []).append(
                {"gate": g, "details": r.get("details")},
            )

        by_gate_detail: dict[str, dict[str, Any]] = {}
        for gate, count in by_gate.items():
            deficits = self._gate_deficits.get(gate, [])
            by_gate_detail[gate] = {
                "count": count,
                "unique_symbols": len(self._gate_symbols.get(gate, set())),
                "avg_deficit": round(sum(deficits) / len(deficits), 4) if deficits else None,
                "min_deficit": round(min(deficits), 4) if deficits else None,
                "max_deficit": round(max(deficits), 4) if deficits else None,
            }

        return {
            "total_rejections": len(self._rejections),
            "by_gate": by_gate,
            "by_gate_detail": by_gate_detail,
            "by_symbol": by_symbol,
            "rejections": list(self._rejections),
        }

    def bottleneck_report(
        self,
        total_candidates: int,
        threshold_pct: float = 0.25,
    ) -> list[dict[str, Any]]:
        """Identify gates that reject an outsized fraction of candidates.

        A gate is flagged as a bottleneck if it rejects more than
        ``threshold_pct`` (default 25 %) of all candidates.

        Returns a list of bottleneck dicts with recommendation text.
        """
        if total_candidates <= 0:
            return []
        by_gate: dict[str, int] = {}
        for r in self._rejections:
            g = r["gate"]
            by_gate[g] = by_gate.get(g, 0) + 1

        bottlenecks: list[dict[str, Any]] = []
        for gate, count in sorted(by_gate.items(), key=lambda x: -x[1]):
            rate = count / total_candidates
            if rate >= threshold_pct:
                deficits = self._gate_deficits.get(gate, [])
                avg_def = (sum(deficits) / len(deficits)) if deficits else None
                rec = f"Gate '{gate}' rejected {rate:.0%} of candidates."
                if avg_def is not None:
                    rec += f" Avg deficit: {avg_def:.4f}. Consider relaxing threshold."
                bottlenecks.append({
                    "gate": gate,
                    "rejection_rate": round(rate, 4),
                    "rejection_count": count,
                    "unique_symbols": len(self._gate_symbols.get(gate, set())),
                    "avg_deficit": round(avg_def, 4) if avg_def is not None else None,
                    "recommendation": rec,
                })
        return bottlenecks

    def clear(self) -> None:
        self._rejections.clear()
        self._gate_deficits.clear()
        self._gate_symbols.clear()

    @property
    def rejection_count(self) -> int:
        return len(self._rejections)


# ═══════════════════════════════════════════════════════════════════════════
# #1  Support / Resistance / Targets  (daily OHLCV bars)
# ═══════════════════════════════════════════════════════════════════════════

def calculate_support_resistance_targets(
    bars: list[dict[str, Any]],
    current_price: float,
    direction: str = "long",
) -> dict[str, Any]:
    """Calculate support, resistance, and target price levels.

    Adapted for the open_prep daily-OHLCV context (no pandas required).

    Methods combined:
      1. Standard Pivot Points (last 20 bars)
      2. Swing highs / lows (last 50 bars, 2-bar confirmation)
      3. EMA levels (20, 50, optionally 200)
      4. Fibonacci retracement (recent high-to-low range)
      5. ATR-based targets & stop

    Parameters
    ----------
    bars : list[dict]
        Daily OHLCV bars ordered oldest → newest.
    current_price : float
        Current (or last-close) price.
    direction : str
        ``"long"`` or ``"short"``.

    Returns
    -------
    dict  with keys:
        support_1/2/3, resistance_1/2/3, target_1/2/3,
        stop_loss, risk_reward_ratio, atr, and *_pct variants.
    """
    empty: dict[str, Any] = {
        "support_1": None, "support_2": None, "support_3": None,
        "resistance_1": None, "resistance_2": None, "resistance_3": None,
        "target_1": None, "target_2": None, "target_3": None,
        "stop_loss": None, "risk_reward_ratio": None, "atr": None,
    }
    if not bars or len(bars) < 50 or current_price <= 0:
        return empty

    result: dict[str, Any] = dict(empty)

    # --- Bar prep (required by all subsequent sections) ---
    try:
        recent = bars[-50:]
        pivot_bars = bars[-20:]

        highs_raw = [_safe_float(b.get("high")) for b in recent]
        lows_raw = [_safe_float(b.get("low")) for b in recent]
        closes = [_safe_float(b.get("close")) for b in recent]
        # Filter out zero values that would corrupt S/R calculations
        highs = [h if h > 0 else current_price for h in highs_raw]
        lows = [lo if lo > 0 else current_price for lo in lows_raw]
    except Exception as exc:
        logger.warning("S/R bar prep failed — returning empty result", exc_info=True)
        return empty

    # --- ATR (14-bar, Wilder's Smoothing, true range) ---
    atr = 0.0
    try:
        tr_values = [highs[0] - lows[0]]  # first bar: H-L only (no prior close)
        for i in range(1, len(recent)):
            prev_c = closes[i - 1] if closes[i - 1] > 0 else current_price
            tr_values.append(max(
                highs[i] - lows[i],
                abs(highs[i] - prev_c),
                abs(lows[i] - prev_c),
            ))
        atr = sum(tr_values[:14]) / min(14.0, len(tr_values))
        for tr in tr_values[14:]:
            atr = (atr * 13.0 + tr) / 14.0
        result["atr"] = round(atr, 2)
    except Exception as exc:
        logger.warning("S/R ATR computation failed", exc_info=True)

    # --- Pivot Points (off last 20 bars) ---
    r1 = r2 = r3 = s1 = s2 = s3 = None
    try:
        p_highs = [_safe_float(b.get("high")) for b in pivot_bars]
        p_lows = [_safe_float(b.get("low")) for b in pivot_bars]
        # Replace zeros with current_price to avoid nonsensical pivots
        p_highs = [h if h > 0 else current_price for h in p_highs]
        p_lows = [lo if lo > 0 else current_price for lo in p_lows]
        pivot_high = max(p_highs)
        pivot_low = min(p_lows)
        pivot_close = _safe_float(pivot_bars[-1].get("close")) or current_price
        pivot = (pivot_high + pivot_low + pivot_close) / 3.0

        r1 = 2 * pivot - pivot_low
        r2 = pivot + (pivot_high - pivot_low)
        r3 = pivot_high + 2 * (pivot - pivot_low)
        s1 = 2 * pivot - pivot_high
        s2 = pivot - (pivot_high - pivot_low)
        s3 = pivot_low - 2 * (pivot_high - pivot)
    except Exception as exc:
        logger.warning("S/R pivot computation failed", exc_info=True)

    # --- Swing highs / lows ---
    swing_highs: list[float] = []
    swing_lows: list[float] = []
    try:
        for i in range(2, len(recent) - 2):
            h = highs[i]
            if h > highs[i - 1] and h > highs[i - 2] and h > highs[i + 1] and h > highs[i + 2]:
                swing_highs.append(h)
            lo = lows[i]
            if lo < lows[i - 1] and lo < lows[i - 2] and lo < lows[i + 1] and lo < lows[i + 2]:
                swing_lows.append(lo)
    except Exception as exc:
        logger.warning("S/R swing detection failed", exc_info=True)

    # --- EMAs ---
    ema_20: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None
    try:
        all_closes = [_safe_float(b.get("close"), current_price) for b in bars]
        ema_20 = _ema(all_closes, 20)
        ema_50 = _ema(all_closes, 50) if len(all_closes) >= 50 else None
        ema_200 = _ema(all_closes, 200) if len(all_closes) >= 200 else None

        # Convert NaN to None for downstream guards
        if ema_20 is not None and math.isnan(ema_20):
            ema_20 = None
        if ema_50 is not None and math.isnan(ema_50):
            ema_50 = None
        if ema_200 is not None and math.isnan(ema_200):
            ema_200 = None
    except Exception as exc:
        logger.warning("S/R EMA computation failed", exc_info=True)

    # --- Fibonacci ---
    fib_382 = fib_500 = fib_618 = None
    try:
        recent_high = max(highs)
        recent_low = min(lows)
        fib_range = recent_high - recent_low
        fib_382 = recent_high - fib_range * 0.382
        fib_500 = recent_high - fib_range * 0.500
        fib_618 = recent_high - fib_range * 0.618
    except Exception as exc:
        logger.warning("S/R Fibonacci computation failed", exc_info=True)

    # --- Combine & sort ---
    try:
        res_candidates = [v for v in [r1, r2, r3] if v is not None] + swing_highs + [
            v for v in (ema_20, ema_50, ema_200) if v is not None
        ]
        res_candidates = sorted(v for v in res_candidates if v > current_price * 1.001)

        sup_candidates = [v for v in [s1, s2, s3] if v is not None] + swing_lows + [
            v for v in (ema_20, ema_50, ema_200, fib_382, fib_500, fib_618) if v is not None
        ]
        sup_candidates = sorted(
            (v for v in sup_candidates if v < current_price * 0.999),
            reverse=True,
        )

        def _pick(lst: list[float], idx: int) -> float | None:
            return lst[idx] if idx < len(lst) else None

        resistance_1 = _pick(res_candidates, 0)
        resistance_2 = _pick(res_candidates, 1)
        resistance_3 = _pick(res_candidates, 2)
        support_1 = _pick(sup_candidates, 0)
        support_2 = _pick(sup_candidates, 1)
        support_3 = _pick(sup_candidates, 2)

        # --- Targets & Stop ---
        if direction == "long":
            stop_loss = min(
                support_1 if support_1 else current_price - 2 * atr,
                current_price - 2 * atr,
            )
            target_1 = resistance_1 if resistance_1 else current_price + 1.5 * atr
            target_2 = resistance_2 if resistance_2 else current_price + 3.0 * atr
            target_3 = resistance_3 if resistance_3 else current_price + 4.5 * atr
        else:
            stop_loss = max(
                resistance_1 if resistance_1 else current_price + 2 * atr,
                current_price + 2 * atr,
            )
            target_1 = support_1 if support_1 else current_price - 1.5 * atr
            target_2 = support_2 if support_2 else current_price - 3.0 * atr
            target_3 = support_3 if support_3 else current_price - 4.5 * atr

        risk = abs(current_price - stop_loss)
        reward = abs(target_1 - current_price) if target_1 else 0.0
        rr_ratio = round(reward / risk, 2) if risk > 0 else None

        def _r(v: float | None) -> float | None:
            return round(v, 2) if v is not None else None

        def _pct(v: float | None) -> float | None:
            if v is None or current_price <= 0:
                return None
            return round((v - current_price) / current_price * 100, 2)

        result.update({
            "support_1": _r(support_1),
            "support_2": _r(support_2),
            "support_3": _r(support_3),
            "resistance_1": _r(resistance_1),
            "resistance_2": _r(resistance_2),
            "resistance_3": _r(resistance_3),
            "target_1": _r(target_1),
            "target_2": _r(target_2),
            "target_3": _r(target_3),
            "stop_loss": _r(stop_loss),
            "risk_reward_ratio": rr_ratio,
            "atr": round(atr, 2),
            "target_1_pct": _pct(target_1),
            "target_2_pct": _pct(target_2),
            "target_3_pct": _pct(target_3),
            "stop_loss_pct": _pct(stop_loss),
            "support_1_pct": _pct(support_1),
            "resistance_1_pct": _pct(resistance_1),
        })
    except Exception as exc:
        logger.warning("S/R combine/targets computation failed — returning partial result", exc_info=True)

    return result


# ---------------------------------------------------------------------------
# #13  Entry Probability (sigmoid-based)
# ---------------------------------------------------------------------------

def compute_entry_probability(
    score: float,
    momentum_z: float = 0.0,
    volume_ratio: float = 1.0,
    atr_pct: float = 0.0,
    spread_pct: float = 0.0,
    *,
    k: float = 3.0,
    threshold: float = 0.0,
) -> float:
    """Return a [0, 1] probability estimate for a profitable entry.

    Combines multiple signals into a single composite via a logistic sigmoid:

        composite = 0.50 * score_norm + 0.25 * momentum_signal
                  + 0.15 * volume_signal + 0.10 * risk_signal
        prob      = 1 / (1 + exp(-k * (composite - threshold)))

    Parameters
    ----------
    score : float
        Raw composite score from the scoring pipeline.
    momentum_z : float
        Z-score of recent momentum (positive = trend-aligned).
    volume_ratio : float
        Relative volume (rvol); >1.0 indicates above-average volume.
    atr_pct : float
        ATR as percentage of price (volatility proxy).
    spread_pct : float
        Bid–ask spread as percentage of price (liquidity proxy).
    k : float
        Steepness of the sigmoid curve (higher = sharper transition).
    threshold : float
        Midpoint of the sigmoid (composite value yielding 50% probability).

    Returns
    -------
    float
        Probability in [0.0, 1.0].
    """
    # Normalise score to roughly [0, 1] via a soft clamp
    score_norm = max(min(score / 5.0, 1.0), -1.0)

    # Momentum signal: tanh compression keeps it in [-1, 1]
    momentum_signal = math.tanh(momentum_z / 3.0)

    # Volume signal: log-scale compression, above-average is positive
    volume_signal = max(min(math.log(max(volume_ratio, 0.1)) / math.log(5.0), 1.0), -1.0)

    # Risk signal: penalise high spread, reward moderate volatility
    atr_term = min(atr_pct / 5.0, 1.0) if atr_pct > 0 else 0.0
    spread_term = min(spread_pct / 1.0, 1.0) if spread_pct > 0 else 0.0
    risk_signal = atr_term * 0.5 - spread_term * 0.5  # moderate vol good, wide spread bad

    # Weighted composite
    composite = (
        0.50 * score_norm
        + 0.25 * momentum_signal
        + 0.15 * volume_signal
        + 0.10 * risk_signal
    )

    # Logistic sigmoid
    try:
        prob = 1.0 / (1.0 + math.exp(-k * (composite - threshold)))
    except OverflowError:
        prob = 0.0 if (composite - threshold) < 0 else 1.0

    return round(prob, 4)


# ═══════════════════════════════════════════════════════════════════════════
# #14  EWMA (Energy-Weighted Moving Average)
# ═══════════════════════════════════════════════════════════════════════════

def _calculate_energy_weights(
    bars: list[dict[str, Any]],
    length: int = 50,
) -> list[float] | None:
    """Compute volume × volatility energy weights for the last *length* bars.

    Each bar's *true range* serves as a volatility proxy.  Weights are
    normalised to sum to 1.0.

    Parameters
    ----------
    bars : list[dict]
        OHLCV bars with keys ``open, high, low, close, volume``.
    length : int
        Number of trailing bars to use.

    Returns
    -------
    list[float] | None
        Normalised weights, or ``None`` if insufficient data.
    """
    if not bars or len(bars) < length:
        return None

    recent = bars[-length:]
    weights: list[float] = []

    prev_close: float | None = None
    for bar in recent:
        h = _safe_float(bar.get("high", 0.0))
        lo = _safe_float(bar.get("low", 0.0))
        c = _safe_float(bar.get("close", 0.0))
        v = max(_safe_float(bar.get("volume", 0.0)), 0.0)

        # True range
        if prev_close is not None:
            tr = max(h - lo, abs(h - prev_close), abs(lo - prev_close))
        else:
            tr = h - lo
        prev_close = c

        energy = v * max(tr, 1e-10)
        weights.append(energy)

    total = sum(weights)
    if total <= 0:
        # Fallback: equal weights
        return [1.0 / length] * length
    return [w / total for w in weights]


def calculate_ewma(
    bars: list[dict[str, Any]],
    length: int = 50,
) -> dict[str, Any] | None:
    """Calculate Energy-Weighted Moving Average and price channels.

    EWMA weighs each bar by (Volume × TrueRange), giving more importance to
    bars with high institutional activity.

    Parameters
    ----------
    bars : list[dict]
        OHLCV bars (keys: ``open, high, low, close, volume``).
    length : int
        Number of trailing bars (default 50 — suitable for daily bars in
        open_prep's batch context).

    Returns
    -------
    dict | None
        ``{ewma, highest, lowest, bars_used}`` or ``None``.
    """
    if not bars or len(bars) < length:
        return None

    weights = _calculate_energy_weights(bars, length)
    if weights is None:
        return None

    recent = bars[-length:]
    closes = [_safe_float(b.get("close", 0.0)) for b in recent]
    highs = [_safe_float(b.get("high", 0.0)) for b in recent]
    lows = [_safe_float(b.get("low", 0.0)) for b in recent]

    ewma_val = sum(p * w for p, w in zip(closes, weights))
    highest = max(highs) if highs else ewma_val
    lowest = min(lows) if lows else ewma_val

    return {
        "ewma": round(ewma_val, 6),
        "highest": round(highest, 6),
        "lowest": round(lowest, 6),
        "bars_used": length,
    }


def calculate_ewma_metrics(
    current_price: float,
    ewma_data: dict[str, Any] | None,
    *,
    bounce_threshold_pct: float = 2.0,
    breakdown_threshold_pct: float = -5.0,
    overextended_threshold_pct: float = 5.0,
) -> dict[str, Any] | None:
    """Derive metrics from an EWMA calculation.

    Returns
    -------
    dict | None
        ``{distance_pct, channel_pct, bounce_zone, breakdown, overextended}``
    """
    if ewma_data is None:
        return None

    ewma = ewma_data["ewma"]
    highest = ewma_data["highest"]
    lowest = ewma_data["lowest"]

    distance_pct = ((current_price - ewma) / ewma * 100.0) if ewma > 0 else 0.0

    channel_range = highest - lowest
    if channel_range > 0:
        channel_pct = max(0.0, min(100.0, (current_price - lowest) / channel_range * 100.0))
    else:
        channel_pct = 50.0

    bounce_zone = -bounce_threshold_pct <= distance_pct <= bounce_threshold_pct
    breakdown = distance_pct < breakdown_threshold_pct
    overextended = distance_pct > overextended_threshold_pct

    return {
        "distance_pct": round(distance_pct, 2),
        "channel_pct": round(channel_pct, 1),
        "bounce_zone": bounce_zone,
        "breakdown": breakdown,
        "overextended": overextended,
    }


def calculate_ewma_score(
    ewma_metrics: dict[str, Any] | None,
    *,
    bounce_threshold_pct: float = 2.0,
    breakdown_threshold_pct: float = -5.0,
) -> float:
    """Score a candidate based on its EWMA position.

    Scoring logic:
      - Bounce zone (|distance| ≤ 2%): 0.9–1.0 (ideal entry)
      - Between bounce and breakdown: 0.5–0.9 (moderate)
      - Breakdown (< −5%): 0.0 (avoid)
      - Overextended (> +5%): 0.3 (caution, chase risk)

    Returns 0.5 (neutral) when metrics are unavailable.
    """
    if ewma_metrics is None:
        return 0.5

    dist = ewma_metrics["distance_pct"]

    if ewma_metrics["breakdown"]:
        return 0.0

    if ewma_metrics["bounce_zone"]:
        return 1.0 if dist < 0 else 0.9

    if breakdown_threshold_pct < dist < -bounce_threshold_pct:
        # Linear interpolation between 0.5 and 0.9
        span = -bounce_threshold_pct - breakdown_threshold_pct
        score = 0.5 + 0.4 * (dist - breakdown_threshold_pct) / span if span > 0 else 0.5
        return max(0.0, min(1.0, round(score, 4)))

    if ewma_metrics["overextended"]:
        return 0.3

    # Moderate distance above EWMA
    return 0.6


# ═══════════════════════════════════════════════════════════════════════════
# #15  Regime-Adaptive Score Weights
# ═══════════════════════════════════════════════════════════════════════════

def resolve_regime_weights(
    base_weights: dict[str, float],
    regime: str,
    *,
    component_cap: float = 0.45,
) -> dict[str, float]:
    """Adjust scoring weights based on the current market regime.

    Regimes:
      - ``TRENDING`` → boost momentum & ext-hours, dampen gap
      - ``RANGING``  → boost gap & rvol, dampen momentum
      - ``NEUTRAL``  → return base weights unchanged

    After adjustment an iterative cap prevents any single weight from
    exceeding *component_cap* × sum-of-positive-weights.

    Parameters
    ----------
    base_weights : dict[str, float]
        The DEFAULT_WEIGHTS dict from scorer.py.
    regime : str
        One of ``"TRENDING"``, ``"RANGING"``, ``"NEUTRAL"``.
    component_cap : float
        Maximum fraction any single weight may occupy (default 0.45).

    Returns
    -------
    dict[str, float]
        A *copy* of the weights with regime-specific adjustments applied.
    """
    w = dict(base_weights)  # shallow copy — never mutate the original
    regime_upper = (regime or "NEUTRAL").upper()

    if regime_upper == "TRENDING":
        w["gap"] = w.get("gap", 0.8) * 0.7            # gap less reliable
        w["gap_sector_relative"] = w.get("gap_sector_relative", 0.6) * 0.8
        w["momentum_z"] = w.get("momentum_z", 0.5) * 1.4  # momentum is king
        w["ext_hours"] = w.get("ext_hours", 1.0) * 1.2
        w["rvol"] = w.get("rvol", 1.2) * 0.9
    elif regime_upper == "RANGING":
        w["gap"] = w.get("gap", 0.8) * 1.3            # gap mean-reversion
        w["gap_sector_relative"] = w.get("gap_sector_relative", 0.6) * 1.2
        w["momentum_z"] = w.get("momentum_z", 0.5) * 0.6  # momentum is noise
        w["ext_hours"] = w.get("ext_hours", 1.0) * 0.8
        w["rvol"] = w.get("rvol", 1.2) * 1.2              # volume spikes matter
    # else NEUTRAL — no adjustments

    # Iterative cap on positive weights
    positive_keys = [k for k, v in w.items() if v > 0]
    for _ in range(5):
        total_pos = sum(w[k] for k in positive_keys if w[k] > 0)
        if total_pos <= 0:
            break
        cap_val = component_cap * total_pos
        changed = False
        for k in positive_keys:
            if w[k] > cap_val:
                w[k] = cap_val
                changed = True
        if not changed:
            break

    return w

