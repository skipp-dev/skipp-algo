from __future__ import annotations

from typing import Any

import pandas as pd

from scripts.smc_price_action_engine import (
    detect_high_volume_bars,
    detect_ob_fvg_stack,
    detect_pivots,
    detect_structure_breaking_fvg,
    is_down,
    is_up,
    normalize_bars,
)


def build_pivots_top_bottom(df: pd.DataFrame, pivot_lookup: int = 1) -> pd.DataFrame:
    bars = normalize_bars(df)
    pivots = detect_pivots(bars, pivot_lookup=pivot_lookup)

    top = pd.Series(index=bars.index, dtype="float64")
    bottom = pd.Series(index=bars.index, dtype="float64")

    for row in pivots.to_dict("records"):
        idx = int(row["confirmed_at_index"])
        if idx >= len(bars):
            continue
        if str(row["kind"]).upper() == "HIGH":
            top.iloc[idx] = float(row["price"])
        else:
            bottom.iloc[idx] = float(row["price"])

    top = top.ffill()
    bottom = bottom.ffill()
    return pd.DataFrame({"top": top, "bottom": bottom})


def detect_ppdd(df: pd.DataFrame, pivots_top_bottom: pd.DataFrame) -> list[dict]:
    bars = normalize_bars(df)
    if len(pivots_top_bottom) != len(bars):
        raise ValueError("pivots_top_bottom must match bar length")

    out: list[dict[str, Any]] = []
    for i in range(2, len(bars)):
        b = bars.iloc[i - 1]
        c = bars.iloc[i]

        is_ob_down_0 = is_up(b) and is_down(c) and float(c["close"]) < float(b["low"])
        is_ob_up_0 = is_down(b) and is_up(c) and float(c["close"]) > float(b["high"])

        top = pivots_top_bottom.iloc[i]["top"]
        top_prev = pivots_top_bottom.iloc[i - 1]["top"]
        bottom = pivots_top_bottom.iloc[i]["bottom"]
        bottom_prev = pivots_top_bottom.iloc[i - 1]["bottom"]

        premium_premium = False
        discount_discount = False

        if pd.notna(top) and pd.notna(top_prev):
            premium_premium = is_ob_down_0 and (
                (max(float(c["high"]), float(b["high"])) > float(top) and float(c["close"]) < float(top))
                or (max(float(c["high"]), float(b["high"])) > float(top_prev) and float(c["close"]) < float(top_prev))
            )

        if pd.notna(bottom) and pd.notna(bottom_prev):
            discount_discount = is_ob_up_0 and (
                (min(float(c["low"]), float(b["low"])) < float(bottom) and float(c["close"]) > float(bottom))
                or (min(float(c["low"]), float(b["low"])) < float(bottom_prev) and float(c["close"]) > float(bottom_prev))
            )

        if premium_premium:
            out.append({"time": int(c["timestamp"]), "dir": "BEAR", "kind": "PPDD"})
        if discount_discount:
            out.append({"time": int(c["timestamp"]), "dir": "BULL", "kind": "PPDD"})

        premium_premium_weak = (
            is_up(b)
            and is_down(c)
            and float(c["close"]) < float(b["open"])
            and premium_premium is False
        )
        discount_discount_weak = (
            is_down(b)
            and is_up(c)
            and float(c["close"]) > float(b["open"])
            and discount_discount is False
        )

        if premium_premium_weak:
            out.append({"time": int(c["timestamp"]), "dir": "BEAR", "kind": "PPDD_WEAK"})
        if discount_discount_weak:
            out.append({"time": int(c["timestamp"]), "dir": "BULL", "kind": "PPDD_WEAK"})

    return out


def detect_broken_fractal(df: pd.DataFrame, n: int = 2, mode: str = "provisional") -> list[dict]:
    bars = normalize_bars(df)
    out: list[dict[str, Any]] = []

    fractal_counter = 0
    high_at_down_fractal: float | None = None
    low_at_up_fractal: float | None = None

    for i in range(len(bars)):
        if i < 2:
            continue

        down_fractal = False
        up_fractal = False

        if mode == "confirmed":
            if i >= n and i + n < len(bars):
                center = bars.iloc[i]
                left = bars.iloc[i - n:i]
                right = bars.iloc[i + 1:i + n + 1]
                down_fractal = bool((left["high"] < center["high"]).all() and (right["high"] < center["high"]).all())
                up_fractal = bool((left["low"] > center["low"]).all() and (right["low"] > center["low"]).all())
        else:
            center = bars.iloc[i]
            left = bars.iloc[i - 2:i]
            down_fractal = bool((left["high"] < center["high"]).all())
            up_fractal = bool((left["low"] > center["low"]).all())

        if down_fractal:
            if fractal_counter > 0:
                fractal_counter = 0
            high_at_down_fractal = float(bars.iloc[i]["high"])
            fractal_counter -= 1

        if up_fractal:
            if fractal_counter < 0:
                fractal_counter = 0
            low_at_up_fractal = float(bars.iloc[i]["low"])
            fractal_counter += 1

        row = bars.iloc[i]
        if low_at_up_fractal is not None and high_at_down_fractal is not None:
            sell_signal = (
                fractal_counter < 0
                and float(row["open"]) > low_at_up_fractal
                and float(row["close"]) < low_at_up_fractal
            )
            buy_signal = (
                fractal_counter >= 1
                and float(row["close"]) > high_at_down_fractal
            )

            if sell_signal:
                out.append(
                    {
                        "time": int(row["timestamp"]),
                        "dir": "BEAR",
                        "kind": "BROKEN_FRACTAL",
                        "mode": mode,
                        "top": high_at_down_fractal,
                        "bottom": low_at_up_fractal,
                    }
                )

            if buy_signal:
                out.append(
                    {
                        "time": int(row["timestamp"]),
                        "dir": "BULL",
                        "kind": "BROKEN_FRACTAL",
                        "mode": mode,
                        "top": high_at_down_fractal,
                        "bottom": low_at_up_fractal,
                    }
                )

    return out


def build_structure_qualifiers(df: pd.DataFrame, pivot_lookup: int = 1) -> dict:
    bars = normalize_bars(df)
    pivots_top_bottom = build_pivots_top_bottom(bars, pivot_lookup=pivot_lookup)

    return {
        "structure_breaking_fvg": detect_structure_breaking_fvg(bars, pivot_lookup=pivot_lookup),
        "high_volume_bars": detect_high_volume_bars(bars, ema_period=12, multiplier=1.5),
        "ob_fvg_stack": detect_ob_fvg_stack(bars),
        "ppdd": detect_ppdd(bars, pivots_top_bottom),
        "broken_fractal_provisional": detect_broken_fractal(bars, n=2, mode="provisional"),
        "broken_fractal_confirmed": detect_broken_fractal(bars, n=2, mode="confirmed"),
    }
