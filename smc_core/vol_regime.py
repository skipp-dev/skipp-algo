"""Volatility-regime classification with forecast-aware fallback.

The preferred path uses an ``arch``-backed one-step volatility forecast.
If the dependency is unavailable, the data window is too short, or model
fitting fails, the module falls back explicitly to the deterministic ATR-ratio
classifier so downstream snapshot and measurement paths stay available.

Integration:
    - Called by ``smc_integration.service`` to enrich ``snapshot.meta``.
    - Used by ``smc_integration.measurement_evidence`` as a stratification input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

VolRegimeLabel = Literal["LOW_VOL", "NORMAL", "HIGH_VOL", "EXTREME"]
VolRegimeModelSource = Literal["arch_garch", "atr_fallback"]


@dataclass(slots=True, frozen=True)
class VolRegimeResult:
    """Immutable result of the vol-regime classification."""

    label: VolRegimeLabel
    raw_atr_ratio: float  # current ATR / rolling median ATR
    confidence: float     # 0.0–1.0
    bars_used: int
    model_source: VolRegimeModelSource = "atr_fallback"
    fallback_reason: str | None = None
    forecast_volatility: float | None = None
    baseline_volatility: float | None = None
    forecast_ratio: float | None = None


# Thresholds for ATR-ratio → regime label.
_THRESHOLDS: list[tuple[float, VolRegimeLabel]] = [
    (0.5, "LOW_VOL"),
    (1.5, "HIGH_VOL"),
    (2.5, "EXTREME"),
]


class _ForecastUnavailable(RuntimeError):
    def __init__(self, reason: str, detail: str | None = None):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def _classify(atr_ratio: float) -> VolRegimeLabel:
    if atr_ratio <= _THRESHOLDS[0][0]:
        return "LOW_VOL"
    if atr_ratio >= _THRESHOLDS[2][0]:
        return "EXTREME"
    if atr_ratio >= _THRESHOLDS[1][0]:
        return "HIGH_VOL"
    return "NORMAL"


def _coerce_numeric_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        return pd.DataFrame(columns=["high", "low", "close"])

    df = bars.copy()
    for col in ("high", "low", "close"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    return df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)


def _load_arch_model_factory() -> Any | None:
    try:
        from arch import arch_model
    except Exception:
        return None
    return arch_model


def _default_forecast_min_bars(atr_period: int, lookback: int) -> int:
    return max(int(lookback) * 2, int(atr_period) * 4, 80)


def _extract_atr_context(
    df: pd.DataFrame,
    *,
    atr_period: int,
    lookback: int,
) -> tuple[float, float, float, float] | None:
    if df.empty or len(df) < atr_period + 1:
        return None

    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(window=atr_period, min_periods=atr_period).mean().dropna()
    if atr.empty:
        return None

    current_atr = float(atr.iloc[-1])
    window = min(lookback, len(atr))
    median_atr = float(atr.iloc[-window:].median())
    if not math.isfinite(median_atr) or median_atr <= 0:
        return None

    ratio = current_atr / median_atr
    confidence = min(1.0, len(atr) / float(max(lookback, 1)))
    return current_atr, median_atr, ratio, confidence


def _extract_forecast_variance(raw_forecast: Any) -> float:
    variance_frame = getattr(raw_forecast, "variance", None)
    if variance_frame is None or getattr(variance_frame, "empty", True):
        raise _ForecastUnavailable("arch_empty_forecast")

    last_row = variance_frame.iloc[-1]
    variance_series = pd.to_numeric(last_row, errors="coerce").dropna()
    if variance_series.empty:
        raise _ForecastUnavailable("arch_invalid_forecast")

    variance = float(variance_series.iloc[0])
    if not math.isfinite(variance) or variance <= 0:
        raise _ForecastUnavailable("arch_invalid_forecast")
    return variance


def _forecast_context(
    df: pd.DataFrame,
    *,
    lookback: int,
    forecast_min_bars: int,
) -> tuple[float, float, float, float]:
    returns = pd.to_numeric(df["close"], errors="coerce").pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
    if len(returns) < forecast_min_bars:
        raise _ForecastUnavailable("insufficient_forecast_history")

    arch_model_factory = _load_arch_model_factory()
    if arch_model_factory is None:
        raise _ForecastUnavailable("arch_unavailable")

    try:
        model = arch_model_factory(returns * 100.0, mean="Zero", vol="GARCH", p=1, q=1, dist="normal", rescale=False)
        fit_result = model.fit(disp="off", show_warning=False)
        variance = _extract_forecast_variance(fit_result.forecast(horizon=1, reindex=False))
    except _ForecastUnavailable:
        raise
    except Exception as exc:
        raise _ForecastUnavailable("arch_fit_failed", detail=str(exc)) from exc

    window = min(int(lookback), len(returns))
    min_periods = max(5, window // 2)
    baseline_series = returns.abs().rolling(window=window, min_periods=min_periods).mean().dropna()
    if baseline_series.empty:
        raise _ForecastUnavailable("baseline_unavailable")

    baseline_volatility = float(baseline_series.iloc[-window:].median())
    if not math.isfinite(baseline_volatility) or baseline_volatility <= 0:
        raise _ForecastUnavailable("baseline_unavailable")

    forecast_volatility = math.sqrt(variance) / 100.0
    forecast_ratio = forecast_volatility / baseline_volatility
    confidence = min(1.0, len(returns) / float(max(forecast_min_bars, 1)))
    return forecast_volatility, baseline_volatility, forecast_ratio, confidence


def _fallback_result(
    *,
    ratio: float,
    confidence: float,
    bars_used: int,
    reason: str,
) -> VolRegimeResult:
    return VolRegimeResult(
        label=_classify(ratio),
        raw_atr_ratio=round(ratio, 4),
        confidence=round(confidence, 4),
        bars_used=bars_used,
        model_source="atr_fallback",
        fallback_reason=reason,
    )


def compute_vol_regime(
    bars: pd.DataFrame,
    *,
    atr_period: int = 14,
    lookback: int = 50,
    forecast_min_bars: int | None = None,
) -> VolRegimeResult:
    """Classify the current volatility regime from OHLC bars.

    Parameters
    ----------
    bars:
        DataFrame with columns ``high``, ``low``, ``close`` (numeric).
    atr_period:
        Number of bars for the ATR calculation.
    lookback:
        Rolling window for the median ATR baseline.
    forecast_min_bars:
        Minimum number of return observations required before attempting the
        ``arch`` forecast path. Shorter histories fall back to ATR.

    Returns
    -------
    VolRegimeResult
    """
    if bars.empty:
        return VolRegimeResult(
            label="NORMAL",
            raw_atr_ratio=1.0,
            confidence=0.0,
            bars_used=0,
            model_source="atr_fallback",
            fallback_reason="empty_bars",
        )

    df = _coerce_numeric_bars(bars)
    if len(df) < atr_period + 1:
        return VolRegimeResult(
            label="NORMAL",
            raw_atr_ratio=1.0,
            confidence=0.0,
            bars_used=len(df),
            model_source="atr_fallback",
            fallback_reason="insufficient_atr_history",
        )

    atr_context = _extract_atr_context(df, atr_period=atr_period, lookback=lookback)
    if atr_context is None:
        return VolRegimeResult(
            label="NORMAL",
            raw_atr_ratio=1.0,
            confidence=0.0,
            bars_used=len(df),
            model_source="atr_fallback",
            fallback_reason="atr_baseline_unavailable",
        )

    _, _, ratio, atr_confidence = atr_context
    resolved_forecast_min_bars = forecast_min_bars or _default_forecast_min_bars(atr_period, lookback)

    try:
        forecast_volatility, baseline_volatility, forecast_ratio, forecast_confidence = _forecast_context(
            df,
            lookback=lookback,
            forecast_min_bars=resolved_forecast_min_bars,
        )
    except _ForecastUnavailable as exc:
        return _fallback_result(
            ratio=ratio,
            confidence=atr_confidence,
            bars_used=len(df),
            reason=exc.reason,
        )

    return VolRegimeResult(
        label=_classify(forecast_ratio),
        raw_atr_ratio=round(ratio, 4),
        confidence=round(max(atr_confidence, forecast_confidence), 4),
        bars_used=len(df),
        model_source="arch_garch",
        fallback_reason=None,
        forecast_volatility=round(forecast_volatility, 6),
        baseline_volatility=round(baseline_volatility, 6),
        forecast_ratio=round(forecast_ratio, 4),
    )
