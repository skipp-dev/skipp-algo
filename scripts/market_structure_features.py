from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd


def _clip_score(value: float) -> float:
    return float(max(0.0, min(100.0, value)))


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _as_key_dict(group_keys: Sequence[str], key: Any) -> dict[str, Any]:
    if len(group_keys) == 1:
        return {group_keys[0]: key}
    return dict(zip(group_keys, key, strict=False))


def _detect_swings(high: np.ndarray, low: np.ndarray, *, left: int = 2, right: int = 2) -> tuple[list[int], list[int]]:
    swing_highs: list[int] = []
    swing_lows: list[int] = []
    total = len(high)
    if total < (left + right + 1):
        return swing_highs, swing_lows
    for idx in range(left, total - right):
        high_window = high[idx - left : idx + right + 1]
        low_window = low[idx - left : idx + right + 1]
        if np.isfinite(high[idx]) and high[idx] >= np.nanmax(high_window):
            swing_highs.append(idx)
        if np.isfinite(low[idx]) and low[idx] <= np.nanmin(low_window):
            swing_lows.append(idx)
    return swing_highs, swing_lows


def _latest_value(values: np.ndarray, indices: list[int]) -> float:
    if not indices:
        return float("nan")
    return float(values[indices[-1]])


def _empty_metrics(prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_trend_state": 0,
        f"{prefix}_last_event": "none",
        f"{prefix}_break_quality_score": np.nan,
        f"{prefix}_pressure_score": np.nan,
        f"{prefix}_compression_score": np.nan,
        f"{prefix}_distance_to_swing_high_pct": np.nan,
        f"{prefix}_distance_to_swing_low_pct": np.nan,
        f"{prefix}_reclaim_flag": False,
        f"{prefix}_failed_break_flag": False,
        f"{prefix}_alignment_score": np.nan,
        f"{prefix}_bias_score": np.nan,
    }


def _compute_group_structure_metrics(group: pd.DataFrame, *, prefix: str) -> dict[str, Any]:
    ordered = group.sort_values("timestamp").reset_index(drop=True)
    open_values = pd.to_numeric(ordered.get("open"), errors="coerce").to_numpy(dtype=float)
    high_values = pd.to_numeric(ordered.get("high"), errors="coerce").to_numpy(dtype=float)
    low_values = pd.to_numeric(ordered.get("low"), errors="coerce").to_numpy(dtype=float)
    close_values = pd.to_numeric(ordered.get("close"), errors="coerce").to_numpy(dtype=float)
    volume_values = pd.to_numeric(ordered.get("volume"), errors="coerce").fillna(0.0).to_numpy(dtype=float)

    valid_mask = np.isfinite(open_values) & np.isfinite(high_values) & np.isfinite(low_values) & np.isfinite(close_values)
    if not valid_mask.any():
        return _empty_metrics(prefix)

    open_values = open_values[valid_mask]
    high_values = high_values[valid_mask]
    low_values = low_values[valid_mask]
    close_values = close_values[valid_mask]
    volume_values = volume_values[valid_mask]
    if len(close_values) == 0:
        return _empty_metrics(prefix)

    close_series = pd.Series(close_values)
    ema_fast = close_series.ewm(span=min(5, max(len(close_values), 2)), adjust=False).mean()
    ema_slow = close_series.ewm(span=min(13, max(len(close_values), 3)), adjust=False).mean()
    ema_long = close_series.ewm(span=min(21, max(len(close_values), 5)), adjust=False).mean()

    initial_open = float(open_values[0])
    last_open = float(open_values[-1])
    last_high = float(high_values[-1])
    last_low = float(low_values[-1])
    last_close = float(close_values[-1])
    last_range = max(last_high - last_low, 0.0)
    last_body = abs(last_close - last_open)
    upper_wick = max(last_high - max(last_open, last_close), 0.0)
    lower_wick = max(min(last_open, last_close) - last_low, 0.0)

    swing_high_indices, swing_low_indices = _detect_swings(high_values, low_values)
    last_swing_high = _latest_value(high_values, swing_high_indices)
    last_swing_low = _latest_value(low_values, swing_low_indices)

    move_sign = _sign(last_close - float(close_values[0]))
    ema_sign = _sign(float(ema_fast.iloc[-1] - ema_slow.iloc[-1]))
    long_sign = _sign(float(last_close - ema_long.iloc[-1]))
    trend_state = ema_sign if ema_sign != 0 else move_sign

    broke_up = np.isfinite(last_swing_high) and last_close > last_swing_high
    broke_down = np.isfinite(last_swing_low) and last_close < last_swing_low
    if broke_up:
        last_event = "bos_up" if trend_state >= 0 else "choch_up"
        trend_state = 1
    elif broke_down:
        last_event = "bos_down" if trend_state <= 0 else "choch_down"
        trend_state = -1
    else:
        last_event = "range"

    body_pct = 100.0 if last_range <= 0 else _clip_score((last_body / last_range) * 100.0)
    close_position_pct = 100.0 if last_range <= 0 else _clip_score(((last_close - last_low) / last_range) * 100.0)
    bearish_close_position_pct = 100.0 - close_position_pct
    average_volume = float(np.nanmean(volume_values[-min(len(volume_values), 20) :])) if len(volume_values) else 0.0
    volume_ratio_score = _clip_score(((float(volume_values[-1]) / average_volume) - 0.5) * 50.0) if average_volume > 0 else 50.0
    wick_penalty = _clip_score((max(upper_wick, lower_wick) / last_range) * 100.0) if last_range > 0 else 0.0
    directional_close_score = close_position_pct if trend_state >= 0 else bearish_close_position_pct
    break_quality_score = _clip_score((body_pct + directional_close_score + volume_ratio_score + (100.0 - wick_penalty)) / 4.0)

    price_delta = np.diff(close_values, prepend=close_values[0])
    signed_flow = np.sign(price_delta) * np.where(np.isfinite(volume_values), volume_values, 1.0)
    flow_denominator = float(np.sum(np.abs(signed_flow)))
    pressure_balance = float(np.sum(signed_flow) / flow_denominator) if flow_denominator > 0 else 0.0
    pressure_score = _clip_score(50.0 + pressure_balance * 50.0)

    true_range = np.maximum(high_values - low_values, 0.0)
    recent_span = min(len(true_range), 5)
    recent_tr = float(np.nanmean(true_range[-recent_span:])) if recent_span else np.nan
    baseline_tr = float(np.nanmean(true_range)) if len(true_range) else np.nan
    compression_ratio = (recent_tr / baseline_tr) if baseline_tr and np.isfinite(baseline_tr) and baseline_tr > 0 else np.nan
    compression_score = _clip_score((1.0 - min(max(compression_ratio, 0.0), 1.5) / 1.5) * 100.0) if np.isfinite(compression_ratio) else np.nan

    distance_to_swing_high_pct = ((last_swing_high - last_close) / last_close) * 100.0 if np.isfinite(last_swing_high) and last_close > 0 else np.nan
    distance_to_swing_low_pct = ((last_close - last_swing_low) / last_close) * 100.0 if np.isfinite(last_swing_low) and last_close > 0 else np.nan

    total_volume = float(np.sum(volume_values))
    vwap = float(np.sum(close_values * volume_values) / total_volume) if total_volume > 0 else float(np.nanmean(close_values))
    reclaim_flag = bool(np.nanmin(low_values) < initial_open and last_close > max(initial_open, vwap))
    failed_break_flag = bool(np.isfinite(last_swing_high) and float(np.nanmax(high_values)) > last_swing_high and last_close <= max(initial_open, vwap))

    alignment_components = [trend_state, long_sign, move_sign]
    non_zero_alignment = [component for component in alignment_components if component != 0]
    if not non_zero_alignment:
        alignment_score = 50.0
    else:
        agreement_count = sum(1 for component in non_zero_alignment if component == trend_state)
        alignment_score = _clip_score((agreement_count / len(non_zero_alignment)) * 100.0)

    trend_score = 100.0 if trend_state > 0 else 0.0 if trend_state < 0 else 50.0
    reclaim_bonus = 100.0 if reclaim_flag else 0.0
    failed_break_penalty = 25.0 if failed_break_flag else 0.0
    bias_score = _clip_score(
        (trend_score * 0.25)
        + (break_quality_score * 0.25)
        + (pressure_score * 0.20)
        + (alignment_score * 0.20)
        + (reclaim_bonus * 0.10)
        - failed_break_penalty
    )

    return {
        f"{prefix}_trend_state": int(trend_state),
        f"{prefix}_last_event": last_event,
        f"{prefix}_break_quality_score": round(float(break_quality_score), 4),
        f"{prefix}_pressure_score": round(float(pressure_score), 4),
        f"{prefix}_compression_score": round(float(compression_score), 4) if np.isfinite(compression_score) else np.nan,
        f"{prefix}_distance_to_swing_high_pct": round(float(distance_to_swing_high_pct), 4) if np.isfinite(distance_to_swing_high_pct) else np.nan,
        f"{prefix}_distance_to_swing_low_pct": round(float(distance_to_swing_low_pct), 4) if np.isfinite(distance_to_swing_low_pct) else np.nan,
        f"{prefix}_reclaim_flag": reclaim_flag,
        f"{prefix}_failed_break_flag": failed_break_flag,
        f"{prefix}_alignment_score": round(float(alignment_score), 4),
        f"{prefix}_bias_score": round(float(bias_score), 4),
    }


def build_market_structure_feature_frame(
    detail: pd.DataFrame,
    *,
    group_keys: Sequence[str],
    prefix: str,
) -> pd.DataFrame:
    columns = list(group_keys) + [
        f"{prefix}_trend_state",
        f"{prefix}_last_event",
        f"{prefix}_break_quality_score",
        f"{prefix}_pressure_score",
        f"{prefix}_compression_score",
        f"{prefix}_distance_to_swing_high_pct",
        f"{prefix}_distance_to_swing_low_pct",
        f"{prefix}_reclaim_flag",
        f"{prefix}_failed_break_flag",
        f"{prefix}_alignment_score",
        f"{prefix}_bias_score",
    ]
    if detail.empty:
        return pd.DataFrame(columns=columns)

    normalized = detail.copy()
    for column in group_keys:
        if column == "trade_date":
            normalized[column] = pd.to_datetime(normalized[column], errors="coerce").dt.date
        elif column == "symbol":
            normalized[column] = normalized[column].astype(str).str.upper()
    normalized["timestamp"] = pd.to_datetime(normalized.get("timestamp"), errors="coerce", utc=True)
    normalized = normalized.dropna(subset=[*group_keys, "timestamp"]).copy()
    if normalized.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for key, group in normalized.groupby(list(group_keys), sort=False, dropna=False):
        row = _as_key_dict(group_keys, key)
        row.update(_compute_group_structure_metrics(group, prefix=prefix))
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)