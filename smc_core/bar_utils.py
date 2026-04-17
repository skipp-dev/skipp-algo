"""Low-level bar normalization helpers.

Extracted from scripts/smc_price_action_engine.py so that smc_core and
smc_integration can use them without importing from the scripts layer.
"""
from __future__ import annotations

import pandas as pd

REQUIRED_BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def coerce_timestamps_to_epoch_seconds(timestamps: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(timestamps):
        return pd.to_numeric(timestamps, errors="coerce")

    parsed_timestamps = pd.to_datetime(timestamps, utc=True, errors="coerce")
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    return (parsed_timestamps - epoch) // pd.Timedelta(seconds=1)


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    missing = sorted(set(REQUIRED_BAR_COLUMNS).difference(out.columns))
    if missing:
        raise ValueError(f"Missing required bar columns: {missing}")

    out["timestamp"] = coerce_timestamps_to_epoch_seconds(out["timestamp"])

    out = out.sort_values("timestamp").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["timestamp", "open", "high", "low", "close"]).reset_index(drop=True)
    return out
