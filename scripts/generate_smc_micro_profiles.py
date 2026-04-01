from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

from smc_core.schema_version import SCHEMA_VERSION, VersionChangeType, classify_version_change
from scripts.smc_enrichment_types import EnrichmentDict


LISTS = [
    "clean_reclaim",
    "stop_hunt_prone",
    "midday_dead",
    "rth_only",
    "weak_premarket",
    "weak_afterhours",
    "fast_decay",
]

LIST_EXPORTS = {name: f"{name.upper()}_TICKERS" for name in LISTS}
STATE_COLUMNS = [
    "symbol",
    "list_name",
    "is_active",
    "active_since",
    "add_streak",
    "remove_streak",
    "last_score",
    "last_run_date",
    "candidate_active",
    "decision_source",
    "decision_reason",
]


@dataclass(frozen=True)
class Thresholds:
    add: float
    remove: float


def fail(message: str) -> None:
    raise RuntimeError(message)


def load_schema(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def coerce_input_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["asof_date"] = pd.to_datetime(out["asof_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    out["exchange"] = out["exchange"].astype(str).str.strip().str.upper()
    out["asset_type"] = out["asset_type"].astype(str).str.strip()
    out["universe_bucket"] = out["universe_bucket"].astype(str).str.strip()
    for column in out.columns:
        if column in {"asof_date", "symbol", "exchange", "asset_type", "universe_bucket"}:
            continue
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def validate_schema(df: pd.DataFrame, schema: dict[str, Any]) -> None:
    missing = [column for column in schema["required_columns"] if column not in df.columns]
    if missing:
        fail(f"Missing required columns: {missing}")

    if df[list(schema["primary_key"])].isnull().any().any():
        fail("Primary key columns cannot contain null values")

    if df.duplicated(subset=schema["primary_key"]).any():
        duplicates = df.loc[df.duplicated(subset=schema["primary_key"], keep=False), schema["primary_key"]]
        fail(f"Duplicate primary keys found:\n{duplicates.to_string(index=False)}")

    if df["asof_date"].nunique() != 1:
        fail("Input snapshot must contain exactly one asof_date")

    if df["asof_date"].isna().any():
        fail("All asof_date values must be valid dates")

    ranges = schema.get("value_ranges", {})
    for column, bounds in ranges.items():
        if column not in df.columns:
            continue
        low, high = bounds
        series = pd.to_numeric(df[column], errors="coerce")
        if series.isna().any():
            fail(f"Column {column} contains non-numeric or null values")
        outside = series[(series < low) | (series > high)]
        if not outside.empty:
            fail(f"Column {column} has values outside [{low}, {high}]")


def pr(series: pd.Series) -> pd.Series:
    lo = float(series.quantile(0.02))
    hi = float(series.quantile(0.98))
    clipped = series.clip(lower=lo, upper=hi)
    return clipped.rank(pct=True, method="average")


def ipr(series: pd.Series) -> pd.Series:
    return 1.0 - pr(series)


def add_bucket_features(df: pd.DataFrame, schema: dict[str, Any]) -> pd.DataFrame:
    eligibility = schema["eligibility"]
    buckets: list[pd.DataFrame] = []
    for _, group in df.groupby("universe_bucket", dropna=False):
        current = group.copy()
        current["eligible_core"] = (
            (current["history_coverage_days_20d"] >= eligibility["min_history_days"])
            & (current["adv_dollar_rth_20d"] >= eligibility["adv_dollar_rth_20d_min"])
            & (current["avg_spread_bps_rth_20d"] <= eligibility["avg_spread_bps_rth_20d_max"])
            & (current["rth_active_minutes_share_20d"] >= eligibility["rth_active_minutes_share_20d_min"])
        )

        current["clean_reclaim_score"] = (
            0.25 * pr(current["clean_intraday_score_20d"])
            + 0.20 * pr(current["consistency_score_20d"])
            + 0.15 * pr(current["close_hygiene_20d"])
            + 0.15 * pr(current["reclaim_respect_rate_20d"])
            + 0.10 * pr(current["reclaim_followthrough_r_20d"])
            + 0.10 * pr(current["adv_dollar_rth_20d"])
            + 0.05 * ipr(current["wickiness_20d"])
        )

        current["stop_hunt_score"] = (
            0.30 * pr(current["stop_hunt_rate_20d"])
            + 0.20 * pr(current["wickiness_20d"])
            + 0.20 * pr(current["ob_sweep_reversal_rate_20d"])
            + 0.10 * pr(current["ob_sweep_depth_p75_20d"])
            + 0.10 * pr(current["fvg_sweep_reversal_rate_20d"])
            + 0.10 * pr(current["fvg_sweep_depth_p75_20d"])
        )

        current["midday_dead_score"] = (
            0.30 * ipr(current["midday_dollar_share_20d"])
            + 0.20 * ipr(current["midday_trades_share_20d"])
            + 0.20 * ipr(current["midday_active_minutes_share_20d"])
            + 0.15 * ipr(current["midday_efficiency_20d"])
            + 0.15 * pr(current["midday_spread_bps_20d"])
        )

        current["pm_quality"] = (
            0.45 * pr(current["pm_dollar_share_20d"])
            + 0.30 * pr(current["pm_trades_share_20d"])
            + 0.15 * pr(current["pm_active_minutes_share_20d"])
            + 0.10 * ipr(current["pm_spread_bps_20d"])
        )

        current["ah_quality"] = (
            0.45 * pr(current["ah_dollar_share_20d"])
            + 0.30 * pr(current["ah_trades_share_20d"])
            + 0.15 * pr(current["ah_active_minutes_share_20d"])
            + 0.10 * ipr(current["ah_spread_bps_20d"])
        )

        current["rth_only_score"] = 0.50 * (1.0 - current["pm_quality"]) + 0.50 * (1.0 - current["ah_quality"])

        current["weak_premarket_score"] = (
            0.40 * ipr(current["pm_dollar_share_20d"])
            + 0.25 * ipr(current["pm_trades_share_20d"])
            + 0.20 * ipr(current["pm_active_minutes_share_20d"])
            + 0.15 * pr(current["pm_spread_bps_20d"])
        )

        current["weak_afterhours_score"] = (
            0.40 * ipr(current["ah_dollar_share_20d"])
            + 0.25 * ipr(current["ah_trades_share_20d"])
            + 0.20 * ipr(current["ah_active_minutes_share_20d"])
            + 0.15 * pr(current["ah_spread_bps_20d"])
        )

        current["fast_decay_score"] = (
            0.35 * ipr(current["setup_decay_half_life_bars_20d"])
            + 0.30 * pr(current["early_vs_late_followthrough_ratio_20d"])
            + 0.20 * pr(current["stale_fail_rate_20d"])
            + 0.15 * pr(current["open_30m_dollar_share_20d"])
        )
        buckets.append(current)
    return pd.concat(buckets, ignore_index=True)


def _bucket_quantile(df: pd.DataFrame, column: str, quantile: float) -> pd.Series:
    return df.groupby("universe_bucket")[column].transform(lambda series: series.quantile(quantile))


def _bucket_median(df: pd.DataFrame, column: str) -> pd.Series:
    return df.groupby("universe_bucket")[column].transform("median")


def apply_candidate_rules(df: pd.DataFrame, schema: dict[str, Any]) -> pd.DataFrame:
    thresholds = {
        name: Thresholds(values["threshold_add"], values["threshold_remove"])
        for name, values in schema["scoring"].items()
    }

    current = df.copy()
    current["cand_clean_reclaim"] = (
        current["eligible_core"]
        & (current["clean_reclaim_score"] >= thresholds["clean_reclaim"].add)
        & (current["stop_hunt_rate_20d"] <= _bucket_quantile(current, "stop_hunt_rate_20d", 0.60))
        & (current["setup_decay_half_life_bars_20d"] >= _bucket_median(current, "setup_decay_half_life_bars_20d"))
    )

    current["cand_stop_hunt_prone"] = (
        current["eligible_core"]
        & (current["stop_hunt_score"] >= thresholds["stop_hunt_prone"].add)
        & (current["clean_reclaim_score"] <= 0.65)
    )

    current["cand_midday_dead"] = (
        current["eligible_core"]
        & (current["midday_dead_score"] >= thresholds["midday_dead"].add)
        & (current["open_30m_dollar_share_20d"] >= _bucket_median(current, "open_30m_dollar_share_20d"))
    )

    current["cand_rth_only"] = (
        current["eligible_core"]
        & (current["rth_only_score"] >= thresholds["rth_only"].add)
        & (current["clean_intraday_score_20d"] >= _bucket_median(current, "clean_intraday_score_20d"))
    )

    current["cand_weak_premarket"] = current["weak_premarket_score"] >= thresholds["weak_premarket"].add
    current["cand_weak_afterhours"] = current["weak_afterhours_score"] >= thresholds["weak_afterhours"].add
    current["cand_fast_decay"] = current["eligible_core"] & (current["fast_decay_score"] >= thresholds["fast_decay"].add)

    both = current["cand_clean_reclaim"] & current["cand_stop_hunt_prone"]
    clean_margin = current["clean_reclaim_score"] - thresholds["clean_reclaim"].add
    stop_margin = current["stop_hunt_score"] - thresholds["stop_hunt_prone"].add
    current.loc[both & (clean_margin >= stop_margin), "cand_stop_hunt_prone"] = False
    current.loc[both & (clean_margin < stop_margin), "cand_clean_reclaim"] = False

    p40_half_life = _bucket_quantile(current, "setup_decay_half_life_bars_20d", 0.40)
    current.loc[
        current["cand_fast_decay"] & current["cand_clean_reclaim"] & (current["setup_decay_half_life_bars_20d"] < p40_half_life),
        "cand_clean_reclaim",
    ] = False
    return current


def load_state(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=STATE_COLUMNS)
    state = pd.read_csv(path)
    for column in STATE_COLUMNS:
        if column not in state.columns:
            if column in {"candidate_active", "is_active", "add_streak", "remove_streak"}:
                state[column] = 0
            else:
                state[column] = "" if column in {"active_since", "decision_source", "decision_reason", "last_run_date"} else 0.0
    return state[STATE_COLUMNS]


def _safe_bool(value: Any) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    if isinstance(value, (int, float)):
        return bool(int(value))
    return bool(value)


def describe_generator_decision(
    *,
    previous_active: bool,
    is_active: bool,
    add_candidate: bool,
    retain_candidate: bool,
    add_streak: int,
    remove_streak: int,
    bootstrap_mode: bool,
    add_runs_required: int,
    remove_runs_required: int,
    held_days: int,
    min_hold_days: int,
) -> str:
    if bootstrap_mode and add_candidate and is_active:
        return "bootstrap activation on first snapshot"
    if add_candidate and not previous_active and is_active:
        return f"candidate met add hysteresis ({add_streak}/{add_runs_required})"
    if add_candidate and not previous_active:
        return f"awaiting add hysteresis ({add_streak}/{add_runs_required})"
    if add_candidate and previous_active and is_active:
        return "retained by active generator candidate"
    if retain_candidate and previous_active and is_active:
        return "retained by remove threshold"
    if previous_active and is_active:
        return (
            f"held by remove hysteresis ({remove_streak}/{remove_runs_required})"
            if held_days >= min_hold_days
            else f"held by minimum hold ({held_days}/{min_hold_days} days)"
        )
    if previous_active and not is_active:
        return f"removed after hysteresis ({remove_streak}/{remove_runs_required}) and hold ({held_days}/{min_hold_days} days)"
    return "below add threshold"


def update_membership_state(
    df: pd.DataFrame,
    state: pd.DataFrame,
    asof_date: str,
    schema: dict[str, Any],
) -> pd.DataFrame:
    score_col_map = {
        "clean_reclaim": "clean_reclaim_score",
        "stop_hunt_prone": "stop_hunt_score",
        "midday_dead": "midday_dead_score",
        "rth_only": "rth_only_score",
        "weak_premarket": "weak_premarket_score",
        "weak_afterhours": "weak_afterhours_score",
        "fast_decay": "fast_decay_score",
    }
    cand_col_map = {
        "clean_reclaim": "cand_clean_reclaim",
        "stop_hunt_prone": "cand_stop_hunt_prone",
        "midday_dead": "cand_midday_dead",
        "rth_only": "cand_rth_only",
        "weak_premarket": "cand_weak_premarket",
        "weak_afterhours": "cand_weak_afterhours",
        "fast_decay": "cand_fast_decay",
    }
    hysteresis = schema["hysteresis"]
    remove_thresholds = {
        name: float(values["threshold_remove"])
        for name, values in schema["scoring"].items()
    }
    bootstrap_mode = state.empty
    previous_rows = {(row["symbol"], row["list_name"]): row for _, row in state.iterrows()}
    rows: list[dict[str, Any]] = []
    asof_ts = pd.Timestamp(asof_date)

    for _, row in df.iterrows():
        for list_name in LISTS:
            key = (row["symbol"], list_name)
            previous = previous_rows.get(key)
            previous_active = _safe_bool(previous["is_active"]) if previous is not None else False
            add_streak = int(previous["add_streak"]) if previous is not None and pd.notna(previous["add_streak"]) else 0
            remove_streak = int(previous["remove_streak"]) if previous is not None and pd.notna(previous["remove_streak"]) else 0
            active_since = str(previous["active_since"]) if previous is not None and pd.notna(previous["active_since"]) else ""
            score = float(row[score_col_map[list_name]])
            add_candidate = bool(row[cand_col_map[list_name]])
            retain_candidate = bool(add_candidate or (previous_active and score >= remove_thresholds[list_name]))

            if previous_active:
                if retain_candidate:
                    remove_streak = 0
                else:
                    remove_streak += 1
            elif add_candidate:
                add_streak += 1
                remove_streak = 0
            else:
                add_streak = 0
                remove_streak = 0

            is_active = previous_active
            held_days = 0
            if active_since:
                held_days = int((asof_ts - pd.Timestamp(active_since)).days)
            if bootstrap_mode and add_candidate:
                is_active = True
                add_streak = hysteresis["add_runs_required"]
                active_since = asof_date
            elif not previous_active and add_streak >= hysteresis["add_runs_required"]:
                is_active = True
                active_since = asof_date
            elif previous_active and remove_streak >= hysteresis["remove_runs_required"]:
                if held_days >= hysteresis["min_hold_days"]:
                    is_active = False

            decision_reason = describe_generator_decision(
                previous_active=previous_active,
                is_active=is_active,
                add_candidate=add_candidate,
                retain_candidate=retain_candidate,
                add_streak=add_streak,
                remove_streak=remove_streak,
                bootstrap_mode=bootstrap_mode,
                add_runs_required=hysteresis["add_runs_required"],
                remove_runs_required=hysteresis["remove_runs_required"],
                held_days=held_days,
                min_hold_days=hysteresis["min_hold_days"],
            )

            rows.append(
                {
                    "symbol": row["symbol"],
                    "list_name": list_name,
                    "is_active": int(is_active),
                    "active_since": active_since,
                    "add_streak": add_streak,
                    "remove_streak": remove_streak,
                    "last_score": round(score, 6),
                    "last_run_date": asof_date,
                    "candidate_active": int(retain_candidate),
                    "decision_source": "generator",
                    "decision_reason": decision_reason,
                }
            )
    return pd.DataFrame(rows, columns=STATE_COLUMNS)


def load_overrides(path: Path | None, asof_date: str) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=["asof_date", "symbol", "list_name", "action", "reason"])
    overrides = pd.read_csv(path)
    if overrides.empty:
        return overrides
    overrides = overrides.copy()
    overrides["asof_date"] = pd.to_datetime(overrides["asof_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    overrides["symbol"] = overrides["symbol"].astype(str).str.strip().str.upper()
    overrides["list_name"] = overrides["list_name"].astype(str).str.strip()
    overrides["action"] = overrides["action"].astype(str).str.strip().str.lower()
    overrides = overrides.loc[overrides["asof_date"] == asof_date]
    invalid_lists = sorted(set(overrides[~overrides["list_name"].isin(LISTS)]["list_name"]))
    if invalid_lists:
        fail(f"Overrides reference unknown lists: {invalid_lists}")
    invalid_actions = sorted(set(overrides[~overrides["action"].isin({"add", "remove"})]["action"]))
    if invalid_actions:
        fail(f"Overrides reference unknown actions: {invalid_actions}")
    return overrides


def apply_overrides(state: pd.DataFrame, overrides: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    if overrides.empty:
        return state
    current = state.copy()
    index = {(row["symbol"], row["list_name"]): idx for idx, row in current.iterrows()}
    for _, override in overrides.iterrows():
        key = (override["symbol"], override["list_name"])
        action = override["action"]
        if key not in index:
            current.loc[len(current)] = {
                "symbol": override["symbol"],
                "list_name": override["list_name"],
                "is_active": 0,
                "active_since": "",
                "add_streak": 0,
                "remove_streak": 0,
                "last_score": 0.0,
                "last_run_date": asof_date,
                "candidate_active": 0,
                "decision_source": "generator",
                "decision_reason": "below add threshold",
            }
            index[key] = len(current) - 1
        row_index = index[key]
        reason = str(override.get("reason", "")).strip() or "manual override"
        if action == "add":
            current.at[row_index, "is_active"] = 1
            current.at[row_index, "active_since"] = asof_date
            current.at[row_index, "add_streak"] = 0
            current.at[row_index, "remove_streak"] = 0
        else:
            current.at[row_index, "is_active"] = 0
            current.at[row_index, "remove_streak"] = 0
            current.at[row_index, "add_streak"] = 0
        current.at[row_index, "last_run_date"] = asof_date
        current.at[row_index, "decision_source"] = f"override:{action}"
        current.at[row_index, "decision_reason"] = reason
    return current


def build_lists_from_state(state: pd.DataFrame) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {name: [] for name in LISTS}
    active = state.loc[state["is_active"] == 1]
    for list_name, group in active.groupby("list_name"):
        output[list_name] = sorted(group["symbol"].astype(str).unique().tolist())
    return output


def shard_csv_string(symbols: list[str], max_chars: int = 35000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for symbol in symbols:
        add_len = len(symbol) + (1 if current else 0)
        if current and current_len + add_len > max_chars:
            chunks.append(",".join(current))
            current = [symbol]
            current_len = len(symbol)
            continue
        current.append(symbol)
        current_len += add_len
    if current:
        chunks.append(",".join(current))
    return chunks


def write_pine_library(
    path: Path,
    lists: dict[str, list[str]],
    asof_date: str,
    universe_size: int,
    enrichment: EnrichmentDict | None = None,
    snapshot: pd.DataFrame | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    from scripts.smc_v55_lean_normalization import normalize_v55_lean_enrichment

    enr = normalize_v55_lean_enrichment(enrichment, snapshot=snapshot) or {}

    def render_list(name: str, symbols: list[str]) -> str:
        const_name = name.upper()
        shards = shard_csv_string(symbols)
        if not shards:
            return f'export const string {const_name}_TICKERS = ""'
        if len(shards) == 1:
            return f'export const string {const_name}_TICKERS = "{shards[0]}"'
        lines = [f'const string {const_name}_PART_{index} = "{chunk}"' for index, chunk in enumerate(shards, start=1)]
        join_expression = " + ".join(f"{const_name}_PART_{index}" for index in range(1, len(shards) + 1))
        lines.append(f"export const string {const_name}_TICKERS = {join_expression}")
        return "\n".join(lines)

    def _pine_bool(val: Any) -> str:
        return "true" if val else "false"

    content = [
        "//@version=6",
        'library("smc_micro_profiles_generated")',
        "",
        "// ── Usage ──────────────────────────────────────────────────────",
        "// import preuss_steffen/smc_micro_profiles_generated/1 as mp",
        "//",
        "// Fields are grouped into sections (v5.5b Lean, ~290 fields total):",
        "//   Core/Meta       — ASOF_DATE, ASOF_TIME, UNIVERSE_ID, LOOKBACK_DAYS, UNIVERSE_SIZE, REFRESH_COUNT",
        "//   Microstructure  — *_TICKERS lists (clean_reclaim, stop_hunt_prone, …)",
        "//   Regime          — MARKET_REGIME, VIX_LEVEL, MACRO_BIAS, SECTOR_BREADTH",
        "//   News            — NEWS_*_TICKERS, NEWS_HEAT_GLOBAL, TICKER_HEAT_MAP",
        "//   Calendar        — EARNINGS_*_TICKERS, HIGH_IMPACT_MACRO_TODAY, MACRO_EVENT_*",
        "//   Layering        — GLOBAL_HEAT, GLOBAL_STRENGTH, TONE, TRADE_STATE",
        "//   Providers       — PROVIDER_COUNT, STALE_PROVIDERS",
        "//   Volume          — VOLUME_LOW_TICKERS, HOLIDAY_SUSPECT_TICKERS",
        "//   Event Risk (v5, deprecated) — EVENT_WINDOW_STATE … EVENT_PROVIDER_STATUS (14 fields)",
        "//   Flow Qualifier (v5.1)  — REL_VOL … ATS_BEARISH_SEQUENCE (14 fields)",
        "//   Compression (v5.1)     — SQUEEZE_ON … ATR_RATIO (5 fields)",
        "//   Zone Intelligence (v5.1, deprecated) — 13 fields",
        "//   Reversal Context (v5.1, deprecated)  — 12 fields",
        "//   Session Context (v5.2, deprecated)   — 16 fields",
        "//   Liquidity Sweeps (v5.2)  — 9 fields",
        "//   Liquidity Pools (v5.2, deprecated)   — 11 fields",
        "//   Order Blocks (v5.2, deprecated)      — 13 fields",
        "//   Zone Projection (v5.2, deprecated)   — 10 fields",
        "//   Profile Context (v5.2, deprecated)   — 18 fields",
        "//   Structure State (v5.3, deprecated)   — 14 fields",
        "//   Imbalance Lifecycle (v5.3, deprecated) — 23 fields",
        "//   Session Structure (v5.3, deprecated)  — 14 fields",
        "//   Range Regime (v5.3)       — 11 fields",
        "//   Range Profile Regime (v5.3) — 22 fields",
        "//",
        "//   ── v5.5b Lean Surface (preferred) ──",
        "//   Event Risk Light (v5.5b)      — 7 fields",
        "//   Session Context Light (v5.5b) — 5 fields",
        "//   OB Context Light (v5.5b)      — 5 fields",
        "//   FVG Lifecycle Light (v5.5b)   — 6 fields",
        "//   Structure State Light (v5.5b) — 4 fields",
        "//   Signal Quality (v5.5b)        — 5 fields",
        "//",
        "// All fields are export const — safe to read as mp.FIELD_NAME.",
        "// ───────────────────────────────────────────────────────────────",
        "",
        f'export const string ASOF_DATE = "{asof_date}"',
        f'export const string ASOF_TIME = "{(enr.get("meta") or {}).get("asof_time") or ""}"',
        'export const string UNIVERSE_ID = "us_equities_v1"',
        "export const int LOOKBACK_DAYS = 20",
        f"export const int UNIVERSE_SIZE = {universe_size}",
        f"export const int REFRESH_COUNT = {int((enr.get('meta') or {}).get('refresh_count') or 0)}",
        "",
    ]
    for list_name in LISTS:
        content.append(render_list(list_name, lists[list_name]))
        content.append("")

    # ── Regime enrichment ───────────────────────────────────────
    regime = enr.get("regime") or {}
    content.append("// ── Market Regime ──")
    content.append(f'export const string MARKET_REGIME = "{regime.get("regime", "NEUTRAL")}"')
    content.append(f'export const float VIX_LEVEL = {float(regime.get("vix_level") or 0.0)}')
    content.append(f'export const float MACRO_BIAS = {float(regime.get("macro_bias") or 0.0)}')
    content.append(f'export const float SECTOR_BREADTH = {float(regime.get("sector_breadth") or 0.0)}')
    content.append("")

    # ── News enrichment ─────────────────────────────────────────
    news = enr.get("news") or {}
    content.append("// ── News Sentiment ──")
    content.append(f'export const string NEWS_BULLISH_TICKERS = "{",".join(news.get("bullish_tickers") or [])}"')
    content.append(f'export const string NEWS_BEARISH_TICKERS = "{",".join(news.get("bearish_tickers") or [])}"')
    content.append(f'export const string NEWS_NEUTRAL_TICKERS = "{",".join(news.get("neutral_tickers") or [])}"')
    content.append(f'export const float NEWS_HEAT_GLOBAL = {float(news.get("news_heat_global") or 0.0)}')
    content.append(f'export const string TICKER_HEAT_MAP = "{news.get("ticker_heat_map") or ""}"')
    content.append("")

    # ── Calendar enrichment ─────────────────────────────────────
    cal = enr.get("calendar") or {}
    content.append("// ── Earnings & Macro Calendar ──")
    content.append(f'export const string EARNINGS_TODAY_TICKERS = "{cal.get("earnings_today_tickers") or ""}"')
    content.append(f'export const string EARNINGS_TOMORROW_TICKERS = "{cal.get("earnings_tomorrow_tickers") or ""}"')
    content.append(f'export const string EARNINGS_BMO_TICKERS = "{cal.get("earnings_bmo_tickers") or ""}"')
    content.append(f'export const string EARNINGS_AMC_TICKERS = "{cal.get("earnings_amc_tickers") or ""}"')
    content.append(f'export const bool HIGH_IMPACT_MACRO_TODAY = {_pine_bool(cal.get("high_impact_macro_today"))}')
    content.append(f'export const string MACRO_EVENT_NAME = "{cal.get("macro_event_name") or ""}"')
    content.append(f'export const string MACRO_EVENT_TIME = "{cal.get("macro_event_time") or ""}"')
    content.append("")

    # ── Layering enrichment ─────────────────────────────────────
    lay = enr.get("layering") or {}
    content.append("// ── Layering / Global Tone ──")
    content.append(f'export const float GLOBAL_HEAT = {float(lay.get("global_heat") or 0.0)}')
    content.append(f'export const float GLOBAL_STRENGTH = {float(lay.get("global_strength") or 0.0)}')
    content.append(f'export const string TONE = "{lay.get("tone") or "NEUTRAL"}"')
    content.append(f'export const string TRADE_STATE = "{lay.get("trade_state") or "ALLOWED"}"')
    content.append("")

    # ── Provider status ─────────────────────────────────────────
    prov = enr.get("providers") or {}
    content.append("// ── Provider Status ──")
    content.append(f'export const int PROVIDER_COUNT = {int(prov.get("provider_count") or 0)}')
    content.append(f'export const string STALE_PROVIDERS = "{prov.get("stale_providers") or ""}"')
    content.append("")

    # ── Volume regime ───────────────────────────────────────────
    vol = enr.get("volume_regime") or {}
    content.append("// ── Volume Regime ──")
    content.append(f'export const string VOLUME_LOW_TICKERS = "{",".join(vol.get("low_tickers") or [])}"')
    content.append(f'export const string HOLIDAY_SUSPECT_TICKERS = "{",".join(vol.get("holiday_suspect_tickers") or [])}"')
    content.append("")

    # ── Event Risk (v5) ─────────────────────────────────────────
    from scripts.smc_event_risk_builder import DEFAULTS as _ER_DEFAULTS

    er = enr.get("event_risk") or {}
    content.append("// ── Event Risk ──")
    content.append(f'export const string EVENT_WINDOW_STATE = "{er.get("EVENT_WINDOW_STATE", _ER_DEFAULTS["EVENT_WINDOW_STATE"])}"')
    content.append(f'export const string EVENT_RISK_LEVEL = "{er.get("EVENT_RISK_LEVEL", _ER_DEFAULTS["EVENT_RISK_LEVEL"])}"')
    content.append(f'export const string NEXT_EVENT_CLASS = "{er.get("NEXT_EVENT_CLASS", _ER_DEFAULTS["NEXT_EVENT_CLASS"])}"')
    content.append(f'export const string NEXT_EVENT_NAME = "{er.get("NEXT_EVENT_NAME", _ER_DEFAULTS["NEXT_EVENT_NAME"])}"')
    content.append(f'export const string NEXT_EVENT_TIME = "{er.get("NEXT_EVENT_TIME", _ER_DEFAULTS["NEXT_EVENT_TIME"])}"')
    content.append(f'export const string NEXT_EVENT_IMPACT = "{er.get("NEXT_EVENT_IMPACT", _ER_DEFAULTS["NEXT_EVENT_IMPACT"])}"')
    content.append(f'export const int EVENT_RESTRICT_BEFORE_MIN = {int(er.get("EVENT_RESTRICT_BEFORE_MIN", _ER_DEFAULTS["EVENT_RESTRICT_BEFORE_MIN"]))}')
    content.append(f'export const int EVENT_RESTRICT_AFTER_MIN = {int(er.get("EVENT_RESTRICT_AFTER_MIN", _ER_DEFAULTS["EVENT_RESTRICT_AFTER_MIN"]))}')
    content.append(f'export const bool EVENT_COOLDOWN_ACTIVE = {_pine_bool(er.get("EVENT_COOLDOWN_ACTIVE", _ER_DEFAULTS["EVENT_COOLDOWN_ACTIVE"]))}')
    content.append(f'export const bool MARKET_EVENT_BLOCKED = {_pine_bool(er.get("MARKET_EVENT_BLOCKED", _ER_DEFAULTS["MARKET_EVENT_BLOCKED"]))}')
    content.append(f'export const bool SYMBOL_EVENT_BLOCKED = {_pine_bool(er.get("SYMBOL_EVENT_BLOCKED", _ER_DEFAULTS["SYMBOL_EVENT_BLOCKED"]))}')
    content.append(f'export const string EARNINGS_SOON_TICKERS = "{er.get("EARNINGS_SOON_TICKERS", _ER_DEFAULTS["EARNINGS_SOON_TICKERS"])}"')
    content.append(f'export const string HIGH_RISK_EVENT_TICKERS = "{er.get("HIGH_RISK_EVENT_TICKERS", _ER_DEFAULTS["HIGH_RISK_EVENT_TICKERS"])}"')
    content.append(f'export const string EVENT_PROVIDER_STATUS = "{er.get("EVENT_PROVIDER_STATUS", _ER_DEFAULTS["EVENT_PROVIDER_STATUS"])}"')

    # ── Flow Qualifier (v5.1) ───────────────────────────────────
    from scripts.smc_flow_qualifier import DEFAULTS as _FQ_DEFAULTS

    fq = enr.get("flow_qualifier") or {}
    content.append("")
    content.append("// ── Flow Qualifier ──")
    content.append(f'export const float REL_VOL = {float(fq.get("REL_VOL", _FQ_DEFAULTS["REL_VOL"]))}')
    content.append(f'export const float REL_ACTIVITY = {float(fq.get("REL_ACTIVITY", _FQ_DEFAULTS["REL_ACTIVITY"]))}')
    content.append(f'export const float REL_SIZE = {float(fq.get("REL_SIZE", _FQ_DEFAULTS["REL_SIZE"]))}')
    content.append(f'export const float DELTA_PROXY_PCT = {float(fq.get("DELTA_PROXY_PCT", _FQ_DEFAULTS["DELTA_PROXY_PCT"]))}')
    content.append(f'export const bool FLOW_LONG_OK = {_pine_bool(fq.get("FLOW_LONG_OK", _FQ_DEFAULTS["FLOW_LONG_OK"]))}')
    content.append(f'export const bool FLOW_SHORT_OK = {_pine_bool(fq.get("FLOW_SHORT_OK", _FQ_DEFAULTS["FLOW_SHORT_OK"]))}')
    content.append(f'export const float ATS_VALUE = {float(fq.get("ATS_VALUE", _FQ_DEFAULTS["ATS_VALUE"]))}')
    content.append(f'export const float ATS_CHANGE_PCT = {float(fq.get("ATS_CHANGE_PCT", _FQ_DEFAULTS["ATS_CHANGE_PCT"]))}')
    content.append(f'export const float ATS_ZSCORE = {float(fq.get("ATS_ZSCORE", _FQ_DEFAULTS["ATS_ZSCORE"]))}')
    content.append(f'export const string ATS_STATE = "{fq.get("ATS_STATE", _FQ_DEFAULTS["ATS_STATE"])}"')
    content.append(f'export const bool ATS_SPIKE_UP = {_pine_bool(fq.get("ATS_SPIKE_UP", _FQ_DEFAULTS["ATS_SPIKE_UP"]))}')
    content.append(f'export const bool ATS_SPIKE_DOWN = {_pine_bool(fq.get("ATS_SPIKE_DOWN", _FQ_DEFAULTS["ATS_SPIKE_DOWN"]))}')
    content.append(f'export const bool ATS_BULLISH_SEQUENCE = {_pine_bool(fq.get("ATS_BULLISH_SEQUENCE", _FQ_DEFAULTS["ATS_BULLISH_SEQUENCE"]))}')
    content.append(f'export const bool ATS_BEARISH_SEQUENCE = {_pine_bool(fq.get("ATS_BEARISH_SEQUENCE", _FQ_DEFAULTS["ATS_BEARISH_SEQUENCE"]))}')

    # ── Compression / ATR Regime (v5.1) ─────────────────────────
    from scripts.smc_compression_regime import DEFAULTS as _CR_DEFAULTS

    cr = enr.get("compression_regime") or {}
    content.append("")
    content.append("// ── Compression / ATR Regime ──")
    content.append(f'export const bool SQUEEZE_ON = {_pine_bool(cr.get("SQUEEZE_ON", _CR_DEFAULTS["SQUEEZE_ON"]))}')
    content.append(f'export const bool SQUEEZE_RELEASED = {_pine_bool(cr.get("SQUEEZE_RELEASED", _CR_DEFAULTS["SQUEEZE_RELEASED"]))}')
    content.append(f'export const string SQUEEZE_MOMENTUM_BIAS = "{cr.get("SQUEEZE_MOMENTUM_BIAS", _CR_DEFAULTS["SQUEEZE_MOMENTUM_BIAS"])}"')
    content.append(f'export const string ATR_REGIME = "{cr.get("ATR_REGIME", _CR_DEFAULTS["ATR_REGIME"])}"')
    content.append(f'export const float ATR_RATIO = {float(cr.get("ATR_RATIO", _CR_DEFAULTS["ATR_RATIO"]))}')

    # ── Zone Intelligence (v5.1) ────────────────────────────────
    from scripts.smc_zone_intelligence import DEFAULTS as _ZI_DEFAULTS

    zi = enr.get("zone_intelligence") or {}
    content.append("")
    content.append("// ── Zone Intelligence ──")
    content.append(f'export const int ACTIVE_SUPPORT_COUNT = {int(zi.get("ACTIVE_SUPPORT_COUNT", _ZI_DEFAULTS["ACTIVE_SUPPORT_COUNT"]))}')
    content.append(f'export const int ACTIVE_RESISTANCE_COUNT = {int(zi.get("ACTIVE_RESISTANCE_COUNT", _ZI_DEFAULTS["ACTIVE_RESISTANCE_COUNT"]))}')
    content.append(f'export const int ACTIVE_ZONE_COUNT = {int(zi.get("ACTIVE_ZONE_COUNT", _ZI_DEFAULTS["ACTIVE_ZONE_COUNT"]))}')
    content.append(f'export const float PRIMARY_SUPPORT_LEVEL = {float(zi.get("PRIMARY_SUPPORT_LEVEL", _ZI_DEFAULTS["PRIMARY_SUPPORT_LEVEL"]))}')
    content.append(f'export const float PRIMARY_RESISTANCE_LEVEL = {float(zi.get("PRIMARY_RESISTANCE_LEVEL", _ZI_DEFAULTS["PRIMARY_RESISTANCE_LEVEL"]))}')
    content.append(f'export const int PRIMARY_SUPPORT_STRENGTH = {int(zi.get("PRIMARY_SUPPORT_STRENGTH", _ZI_DEFAULTS["PRIMARY_SUPPORT_STRENGTH"]))}')
    content.append(f'export const int PRIMARY_RESISTANCE_STRENGTH = {int(zi.get("PRIMARY_RESISTANCE_STRENGTH", _ZI_DEFAULTS["PRIMARY_RESISTANCE_STRENGTH"]))}')
    content.append(f'export const int SUPPORT_SWEEP_COUNT = {int(zi.get("SUPPORT_SWEEP_COUNT", _ZI_DEFAULTS["SUPPORT_SWEEP_COUNT"]))}')
    content.append(f'export const int RESISTANCE_SWEEP_COUNT = {int(zi.get("RESISTANCE_SWEEP_COUNT", _ZI_DEFAULTS["RESISTANCE_SWEEP_COUNT"]))}')
    content.append(f'export const float SUPPORT_MITIGATION_PCT = {float(zi.get("SUPPORT_MITIGATION_PCT", _ZI_DEFAULTS["SUPPORT_MITIGATION_PCT"]))}')
    content.append(f'export const float RESISTANCE_MITIGATION_PCT = {float(zi.get("RESISTANCE_MITIGATION_PCT", _ZI_DEFAULTS["RESISTANCE_MITIGATION_PCT"]))}')
    content.append(f'export const string ZONE_CONTEXT_BIAS = "{zi.get("ZONE_CONTEXT_BIAS", _ZI_DEFAULTS["ZONE_CONTEXT_BIAS"])}"')
    content.append(f'export const float ZONE_LIQUIDITY_IMBALANCE = {float(zi.get("ZONE_LIQUIDITY_IMBALANCE", _ZI_DEFAULTS["ZONE_LIQUIDITY_IMBALANCE"]))}')

    # ── Reversal Context (v5.1) ─────────────────────────────────
    from scripts.smc_reversal_context import DEFAULTS as _RC_DEFAULTS

    rc = enr.get("reversal_context") or {}
    content.append("")
    content.append("// ── Reversal Context ──")
    content.append(f'export const bool REVERSAL_CONTEXT_ACTIVE = {_pine_bool(rc.get("REVERSAL_CONTEXT_ACTIVE", _RC_DEFAULTS["REVERSAL_CONTEXT_ACTIVE"]))}')
    content.append(f'export const int SETUP_SCORE = {int(rc.get("SETUP_SCORE", _RC_DEFAULTS["SETUP_SCORE"]))}')
    content.append(f'export const int CONFIRM_SCORE = {int(rc.get("CONFIRM_SCORE", _RC_DEFAULTS["CONFIRM_SCORE"]))}')
    content.append(f'export const int FOLLOW_THROUGH_SCORE = {int(rc.get("FOLLOW_THROUGH_SCORE", _RC_DEFAULTS["FOLLOW_THROUGH_SCORE"]))}')
    content.append(f'export const bool HTF_STRUCTURE_OK = {_pine_bool(rc.get("HTF_STRUCTURE_OK", _RC_DEFAULTS["HTF_STRUCTURE_OK"]))}')
    content.append(f'export const bool HTF_BULLISH_PATTERN = {_pine_bool(rc.get("HTF_BULLISH_PATTERN", _RC_DEFAULTS["HTF_BULLISH_PATTERN"]))}')
    content.append(f'export const bool HTF_BEARISH_PATTERN = {_pine_bool(rc.get("HTF_BEARISH_PATTERN", _RC_DEFAULTS["HTF_BEARISH_PATTERN"]))}')
    content.append(f'export const bool HTF_BULLISH_DIVERGENCE = {_pine_bool(rc.get("HTF_BULLISH_DIVERGENCE", _RC_DEFAULTS["HTF_BULLISH_DIVERGENCE"]))}')
    content.append(f'export const bool HTF_BEARISH_DIVERGENCE = {_pine_bool(rc.get("HTF_BEARISH_DIVERGENCE", _RC_DEFAULTS["HTF_BEARISH_DIVERGENCE"]))}')
    content.append(f'export const bool FVG_CONFIRM_OK = {_pine_bool(rc.get("FVG_CONFIRM_OK", _RC_DEFAULTS["FVG_CONFIRM_OK"]))}')
    content.append(f'export const bool VWAP_HOLD_OK = {_pine_bool(rc.get("VWAP_HOLD_OK", _RC_DEFAULTS["VWAP_HOLD_OK"]))}')
    content.append(f'export const bool RETRACE_OK = {_pine_bool(rc.get("RETRACE_OK", _RC_DEFAULTS["RETRACE_OK"]))}')

    # ── Session Context (v5.2) ──────────────────────────────────
    from scripts.smc_session_context_block import DEFAULTS as _SC_DEFAULTS

    sc = enr.get("session_context") or {}
    content.append("")
    content.append("// ── Session Context ──")
    content.append(f'export const string SESSION_CONTEXT = "{sc.get("SESSION_CONTEXT", _SC_DEFAULTS["SESSION_CONTEXT"])}"')
    content.append(f'export const bool IN_KILLZONE = {_pine_bool(sc.get("IN_KILLZONE", _SC_DEFAULTS["IN_KILLZONE"]))}')
    content.append(f'export const bool SESSION_MSS_BULL = {_pine_bool(sc.get("SESSION_MSS_BULL", _SC_DEFAULTS["SESSION_MSS_BULL"]))}')
    content.append(f'export const bool SESSION_MSS_BEAR = {_pine_bool(sc.get("SESSION_MSS_BEAR", _SC_DEFAULTS["SESSION_MSS_BEAR"]))}')
    content.append(f'export const string SESSION_STRUCTURE_STATE = "{sc.get("SESSION_STRUCTURE_STATE", _SC_DEFAULTS["SESSION_STRUCTURE_STATE"])}"')
    content.append(f'export const bool SESSION_FVG_BULL_ACTIVE = {_pine_bool(sc.get("SESSION_FVG_BULL_ACTIVE", _SC_DEFAULTS["SESSION_FVG_BULL_ACTIVE"]))}')
    content.append(f'export const bool SESSION_FVG_BEAR_ACTIVE = {_pine_bool(sc.get("SESSION_FVG_BEAR_ACTIVE", _SC_DEFAULTS["SESSION_FVG_BEAR_ACTIVE"]))}')
    content.append(f'export const bool SESSION_BPR_ACTIVE = {_pine_bool(sc.get("SESSION_BPR_ACTIVE", _SC_DEFAULTS["SESSION_BPR_ACTIVE"]))}')
    content.append(f'export const float SESSION_RANGE_TOP = {float(sc.get("SESSION_RANGE_TOP", _SC_DEFAULTS["SESSION_RANGE_TOP"]))}')
    content.append(f'export const float SESSION_RANGE_BOTTOM = {float(sc.get("SESSION_RANGE_BOTTOM", _SC_DEFAULTS["SESSION_RANGE_BOTTOM"]))}')
    content.append(f'export const float SESSION_MEAN = {float(sc.get("SESSION_MEAN", _SC_DEFAULTS["SESSION_MEAN"]))}')
    content.append(f'export const float SESSION_VWAP = {float(sc.get("SESSION_VWAP", _SC_DEFAULTS["SESSION_VWAP"]))}')
    content.append(f'export const float SESSION_TARGET_BULL = {float(sc.get("SESSION_TARGET_BULL", _SC_DEFAULTS["SESSION_TARGET_BULL"]))}')
    content.append(f'export const float SESSION_TARGET_BEAR = {float(sc.get("SESSION_TARGET_BEAR", _SC_DEFAULTS["SESSION_TARGET_BEAR"]))}')
    content.append(f'export const string SESSION_DIRECTION_BIAS = "{sc.get("SESSION_DIRECTION_BIAS", _SC_DEFAULTS["SESSION_DIRECTION_BIAS"])}"')
    content.append(f'export const int SESSION_CONTEXT_SCORE = {int(sc.get("SESSION_CONTEXT_SCORE", _SC_DEFAULTS["SESSION_CONTEXT_SCORE"]))}')

    # ── Liquidity Sweeps (v5.2) ─────────────────────────────────
    from scripts.smc_liquidity_sweeps import DEFAULTS as _LS_DEFAULTS

    ls = enr.get("liquidity_sweeps") or {}
    content.append("")
    content.append("// ── Liquidity Sweeps ──")
    content.append(f'export const bool RECENT_BULL_SWEEP = {_pine_bool(ls.get("RECENT_BULL_SWEEP", _LS_DEFAULTS["RECENT_BULL_SWEEP"]))}')
    content.append(f'export const bool RECENT_BEAR_SWEEP = {_pine_bool(ls.get("RECENT_BEAR_SWEEP", _LS_DEFAULTS["RECENT_BEAR_SWEEP"]))}')
    content.append(f'export const string SWEEP_TYPE = "{ls.get("SWEEP_TYPE", _LS_DEFAULTS["SWEEP_TYPE"])}"')
    content.append(f'export const string SWEEP_DIRECTION = "{ls.get("SWEEP_DIRECTION", _LS_DEFAULTS["SWEEP_DIRECTION"])}"')
    content.append(f'export const float SWEEP_ZONE_TOP = {float(ls.get("SWEEP_ZONE_TOP", _LS_DEFAULTS["SWEEP_ZONE_TOP"]))}')
    content.append(f'export const float SWEEP_ZONE_BOTTOM = {float(ls.get("SWEEP_ZONE_BOTTOM", _LS_DEFAULTS["SWEEP_ZONE_BOTTOM"]))}')
    content.append(f'export const bool SWEEP_RECLAIM_ACTIVE = {_pine_bool(ls.get("SWEEP_RECLAIM_ACTIVE", _LS_DEFAULTS["SWEEP_RECLAIM_ACTIVE"]))}')
    content.append(f'export const string LIQUIDITY_TAKEN_DIRECTION = "{ls.get("LIQUIDITY_TAKEN_DIRECTION", _LS_DEFAULTS["LIQUIDITY_TAKEN_DIRECTION"])}"')
    content.append(f'export const int SWEEP_QUALITY_SCORE = {int(ls.get("SWEEP_QUALITY_SCORE", _LS_DEFAULTS["SWEEP_QUALITY_SCORE"]))}')

    # ── Liquidity Pools (v5.2) ──────────────────────────────────
    from scripts.smc_liquidity_pools import DEFAULTS as _LP_DEFAULTS

    lp = enr.get("liquidity_pools") or {}
    content.append("")
    content.append("// ── Liquidity Pools ──")
    content.append(f'export const float BUY_SIDE_POOL_LEVEL = {float(lp.get("BUY_SIDE_POOL_LEVEL", _LP_DEFAULTS["BUY_SIDE_POOL_LEVEL"]))}')
    content.append(f'export const float SELL_SIDE_POOL_LEVEL = {float(lp.get("SELL_SIDE_POOL_LEVEL", _LP_DEFAULTS["SELL_SIDE_POOL_LEVEL"]))}')
    content.append(f'export const int BUY_SIDE_POOL_STRENGTH = {int(lp.get("BUY_SIDE_POOL_STRENGTH", _LP_DEFAULTS["BUY_SIDE_POOL_STRENGTH"]))}')
    content.append(f'export const int SELL_SIDE_POOL_STRENGTH = {int(lp.get("SELL_SIDE_POOL_STRENGTH", _LP_DEFAULTS["SELL_SIDE_POOL_STRENGTH"]))}')
    content.append(f'export const float POOL_PROXIMITY_PCT = {float(lp.get("POOL_PROXIMITY_PCT", _LP_DEFAULTS["POOL_PROXIMITY_PCT"]))}')
    content.append(f'export const int POOL_CLUSTER_DENSITY = {int(lp.get("POOL_CLUSTER_DENSITY", _LP_DEFAULTS["POOL_CLUSTER_DENSITY"]))}')
    content.append(f'export const int UNTESTED_BUY_POOLS = {int(lp.get("UNTESTED_BUY_POOLS", _LP_DEFAULTS["UNTESTED_BUY_POOLS"]))}')
    content.append(f'export const int UNTESTED_SELL_POOLS = {int(lp.get("UNTESTED_SELL_POOLS", _LP_DEFAULTS["UNTESTED_SELL_POOLS"]))}')
    content.append(f'export const float POOL_IMBALANCE = {float(lp.get("POOL_IMBALANCE", _LP_DEFAULTS["POOL_IMBALANCE"]))}')
    content.append(f'export const string POOL_MAGNET_DIRECTION = "{lp.get("POOL_MAGNET_DIRECTION", _LP_DEFAULTS["POOL_MAGNET_DIRECTION"])}"')
    content.append(f'export const int POOL_QUALITY_SCORE = {int(lp.get("POOL_QUALITY_SCORE", _LP_DEFAULTS["POOL_QUALITY_SCORE"]))}')

    # ── Order Blocks (v5.2) ─────────────────────────────────────
    from scripts.smc_order_blocks import DEFAULTS as _OB_DEFAULTS

    ob = enr.get("order_blocks") or {}
    content.append("")
    content.append("// ── Order Blocks ──")
    content.append(f'export const float NEAREST_BULL_OB_LEVEL = {float(ob.get("NEAREST_BULL_OB_LEVEL", _OB_DEFAULTS["NEAREST_BULL_OB_LEVEL"]))}')
    content.append(f'export const float NEAREST_BEAR_OB_LEVEL = {float(ob.get("NEAREST_BEAR_OB_LEVEL", _OB_DEFAULTS["NEAREST_BEAR_OB_LEVEL"]))}')
    content.append(f'export const int BULL_OB_FRESHNESS = {int(ob.get("BULL_OB_FRESHNESS", _OB_DEFAULTS["BULL_OB_FRESHNESS"]))}')
    content.append(f'export const int BEAR_OB_FRESHNESS = {int(ob.get("BEAR_OB_FRESHNESS", _OB_DEFAULTS["BEAR_OB_FRESHNESS"]))}')
    content.append(f'export const bool BULL_OB_MITIGATED = {_pine_bool(ob.get("BULL_OB_MITIGATED", _OB_DEFAULTS["BULL_OB_MITIGATED"]))}')
    content.append(f'export const bool BEAR_OB_MITIGATED = {_pine_bool(ob.get("BEAR_OB_MITIGATED", _OB_DEFAULTS["BEAR_OB_MITIGATED"]))}')
    content.append(f'export const bool BULL_OB_FVG_CONFLUENCE = {_pine_bool(ob.get("BULL_OB_FVG_CONFLUENCE", _OB_DEFAULTS["BULL_OB_FVG_CONFLUENCE"]))}')
    content.append(f'export const bool BEAR_OB_FVG_CONFLUENCE = {_pine_bool(ob.get("BEAR_OB_FVG_CONFLUENCE", _OB_DEFAULTS["BEAR_OB_FVG_CONFLUENCE"]))}')
    content.append(f'export const int OB_DENSITY = {int(ob.get("OB_DENSITY", _OB_DEFAULTS["OB_DENSITY"]))}')
    content.append(f'export const string OB_BIAS = "{ob.get("OB_BIAS", _OB_DEFAULTS["OB_BIAS"])}"')
    content.append(f'export const float OB_NEAREST_DISTANCE_PCT = {float(ob.get("OB_NEAREST_DISTANCE_PCT", _OB_DEFAULTS["OB_NEAREST_DISTANCE_PCT"]))}')
    content.append(f'export const int OB_STRENGTH_SCORE = {int(ob.get("OB_STRENGTH_SCORE", _OB_DEFAULTS["OB_STRENGTH_SCORE"]))}')
    content.append(f'export const int OB_CONTEXT_SCORE = {int(ob.get("OB_CONTEXT_SCORE", _OB_DEFAULTS["OB_CONTEXT_SCORE"]))}')

    # ── Zone Projection (v5.2) ──────────────────────────────────
    from scripts.smc_zone_projection import DEFAULTS as _ZP_DEFAULTS

    zp = enr.get("zone_projection") or {}
    content.append("")
    content.append("// ── Zone Projection ──")
    content.append(f'export const float ZONE_PROJ_TARGET_BULL = {float(zp.get("ZONE_PROJ_TARGET_BULL", _ZP_DEFAULTS["ZONE_PROJ_TARGET_BULL"]))}')
    content.append(f'export const float ZONE_PROJ_TARGET_BEAR = {float(zp.get("ZONE_PROJ_TARGET_BEAR", _ZP_DEFAULTS["ZONE_PROJ_TARGET_BEAR"]))}')
    content.append(f'export const bool ZONE_PROJ_RETEST_EXPECTED = {_pine_bool(zp.get("ZONE_PROJ_RETEST_EXPECTED", _ZP_DEFAULTS["ZONE_PROJ_RETEST_EXPECTED"]))}')
    content.append(f'export const string ZONE_PROJ_TRAP_RISK = "{zp.get("ZONE_PROJ_TRAP_RISK", _ZP_DEFAULTS["ZONE_PROJ_TRAP_RISK"])}"')
    content.append(f'export const string ZONE_PROJ_SPREAD_QUALITY = "{zp.get("ZONE_PROJ_SPREAD_QUALITY", _ZP_DEFAULTS["ZONE_PROJ_SPREAD_QUALITY"])}"')
    content.append(f'export const bool ZONE_PROJ_HTF_ALIGNED = {_pine_bool(zp.get("ZONE_PROJ_HTF_ALIGNED", _ZP_DEFAULTS["ZONE_PROJ_HTF_ALIGNED"]))}')
    content.append(f'export const string ZONE_PROJ_BIAS = "{zp.get("ZONE_PROJ_BIAS", _ZP_DEFAULTS["ZONE_PROJ_BIAS"])}"')
    content.append(f'export const int ZONE_PROJ_CONFIDENCE = {int(zp.get("ZONE_PROJ_CONFIDENCE", _ZP_DEFAULTS["ZONE_PROJ_CONFIDENCE"]))}')
    content.append(f'export const int ZONE_PROJ_DECAY_BARS = {int(zp.get("ZONE_PROJ_DECAY_BARS", _ZP_DEFAULTS["ZONE_PROJ_DECAY_BARS"]))}')
    content.append(f'export const int ZONE_PROJ_SCORE = {int(zp.get("ZONE_PROJ_SCORE", _ZP_DEFAULTS["ZONE_PROJ_SCORE"]))}')

    # ── Profile Context (v5.2) ──────────────────────────────────
    from scripts.smc_profile_context import DEFAULTS as _PC_DEFAULTS

    pc = enr.get("profile_context") or {}
    content.append("")
    content.append("// ── Profile Context ──")
    content.append(f'export const string PROFILE_VOLUME_NODE = "{pc.get("PROFILE_VOLUME_NODE", _PC_DEFAULTS["PROFILE_VOLUME_NODE"])}"')
    content.append(f'export const string PROFILE_VWAP_POSITION = "{pc.get("PROFILE_VWAP_POSITION", _PC_DEFAULTS["PROFILE_VWAP_POSITION"])}"')
    content.append(f'export const float PROFILE_VWAP_DISTANCE_PCT = {float(pc.get("PROFILE_VWAP_DISTANCE_PCT", _PC_DEFAULTS["PROFILE_VWAP_DISTANCE_PCT"]))}')
    content.append(f'export const string PROFILE_SPREAD_REGIME = "{pc.get("PROFILE_SPREAD_REGIME", _PC_DEFAULTS["PROFILE_SPREAD_REGIME"])}"')
    content.append(f'export const float PROFILE_AVG_SPREAD_BPS = {float(pc.get("PROFILE_AVG_SPREAD_BPS", _PC_DEFAULTS["PROFILE_AVG_SPREAD_BPS"]))}')
    content.append(f'export const string PROFILE_SESSION_BIAS = "{pc.get("PROFILE_SESSION_BIAS", _PC_DEFAULTS["PROFILE_SESSION_BIAS"])}"')
    content.append(f'export const float PROFILE_RTH_DOMINANCE_PCT = {float(pc.get("PROFILE_RTH_DOMINANCE_PCT", _PC_DEFAULTS["PROFILE_RTH_DOMINANCE_PCT"]))}')
    content.append(f'export const string PROFILE_PM_QUALITY = "{pc.get("PROFILE_PM_QUALITY", _PC_DEFAULTS["PROFILE_PM_QUALITY"])}"')
    content.append(f'export const string PROFILE_AH_QUALITY = "{pc.get("PROFILE_AH_QUALITY", _PC_DEFAULTS["PROFILE_AH_QUALITY"])}"')
    content.append(f'export const float PROFILE_MIDDAY_EFFICIENCY = {float(pc.get("PROFILE_MIDDAY_EFFICIENCY", _PC_DEFAULTS["PROFILE_MIDDAY_EFFICIENCY"]))}')
    content.append(f'export const float PROFILE_DECAY_HALFLIFE = {float(pc.get("PROFILE_DECAY_HALFLIFE", _PC_DEFAULTS["PROFILE_DECAY_HALFLIFE"]))}')
    content.append(f'export const float PROFILE_CONSISTENCY = {float(pc.get("PROFILE_CONSISTENCY", _PC_DEFAULTS["PROFILE_CONSISTENCY"]))}')
    content.append(f'export const float PROFILE_WICKINESS = {float(pc.get("PROFILE_WICKINESS", _PC_DEFAULTS["PROFILE_WICKINESS"]))}')
    content.append(f'export const float PROFILE_CLEAN_SCORE = {float(pc.get("PROFILE_CLEAN_SCORE", _PC_DEFAULTS["PROFILE_CLEAN_SCORE"]))}')
    content.append(f'export const float PROFILE_RECLAIM_RATE = {float(pc.get("PROFILE_RECLAIM_RATE", _PC_DEFAULTS["PROFILE_RECLAIM_RATE"]))}')
    content.append(f'export const float PROFILE_STOP_HUNT_RATE = {float(pc.get("PROFILE_STOP_HUNT_RATE", _PC_DEFAULTS["PROFILE_STOP_HUNT_RATE"]))}')
    content.append(f'export const string PROFILE_TICKER_GRADE = "{pc.get("PROFILE_TICKER_GRADE", _PC_DEFAULTS["PROFILE_TICKER_GRADE"])}"')
    content.append(f'export const int PROFILE_CONTEXT_SCORE = {int(pc.get("PROFILE_CONTEXT_SCORE", _PC_DEFAULTS["PROFILE_CONTEXT_SCORE"]))}')

    # ── Structure State (v5.3) ──────────────────────────────────
    from scripts.smc_structure_state import DEFAULTS as _SS_DEFAULTS

    ss = enr.get("structure_state") or {}
    content.append("")
    content.append("// ── Structure State ──")
    content.append(f'export const string STRUCTURE_STATE = "{ss.get("STRUCTURE_STATE", _SS_DEFAULTS["STRUCTURE_STATE"])}"')
    content.append(f'export const bool STRUCTURE_BULL_ACTIVE = {str(ss.get("STRUCTURE_BULL_ACTIVE", _SS_DEFAULTS["STRUCTURE_BULL_ACTIVE"])).lower()}')
    content.append(f'export const bool STRUCTURE_BEAR_ACTIVE = {str(ss.get("STRUCTURE_BEAR_ACTIVE", _SS_DEFAULTS["STRUCTURE_BEAR_ACTIVE"])).lower()}')
    content.append(f'export const bool CHOCH_BULL = {str(ss.get("CHOCH_BULL", _SS_DEFAULTS["CHOCH_BULL"])).lower()}')
    content.append(f'export const bool CHOCH_BEAR = {str(ss.get("CHOCH_BEAR", _SS_DEFAULTS["CHOCH_BEAR"])).lower()}')
    content.append(f'export const bool BOS_BULL = {str(ss.get("BOS_BULL", _SS_DEFAULTS["BOS_BULL"])).lower()}')
    content.append(f'export const bool BOS_BEAR = {str(ss.get("BOS_BEAR", _SS_DEFAULTS["BOS_BEAR"])).lower()}')
    content.append(f'export const string STRUCTURE_LAST_EVENT = "{ss.get("STRUCTURE_LAST_EVENT", _SS_DEFAULTS["STRUCTURE_LAST_EVENT"])}"')
    content.append(f'export const int STRUCTURE_EVENT_AGE_BARS = {int(ss.get("STRUCTURE_EVENT_AGE_BARS", _SS_DEFAULTS["STRUCTURE_EVENT_AGE_BARS"]))}')
    content.append(f'export const bool STRUCTURE_FRESH = {str(ss.get("STRUCTURE_FRESH", _SS_DEFAULTS["STRUCTURE_FRESH"])).lower()}')
    content.append(f'export const float ACTIVE_SUPPORT = {float(ss.get("ACTIVE_SUPPORT", _SS_DEFAULTS["ACTIVE_SUPPORT"]))}')
    content.append(f'export const float ACTIVE_RESISTANCE = {float(ss.get("ACTIVE_RESISTANCE", _SS_DEFAULTS["ACTIVE_RESISTANCE"]))}')
    content.append(f'export const bool SUPPORT_ACTIVE = {str(ss.get("SUPPORT_ACTIVE", _SS_DEFAULTS["SUPPORT_ACTIVE"])).lower()}')
    content.append(f'export const bool RESISTANCE_ACTIVE = {str(ss.get("RESISTANCE_ACTIVE", _SS_DEFAULTS["RESISTANCE_ACTIVE"])).lower()}')

    # ── Imbalance Lifecycle (v5.3) ──────────────────────────────
    from scripts.smc_imbalance_lifecycle import DEFAULTS as _IL_DEFAULTS

    il = enr.get("imbalance_lifecycle") or {}
    content.append("")
    content.append("// ── Imbalance Lifecycle ──")
    content.append(f'export const bool BULL_FVG_ACTIVE = {str(il.get("BULL_FVG_ACTIVE", _IL_DEFAULTS["BULL_FVG_ACTIVE"])).lower()}')
    content.append(f'export const bool BEAR_FVG_ACTIVE = {str(il.get("BEAR_FVG_ACTIVE", _IL_DEFAULTS["BEAR_FVG_ACTIVE"])).lower()}')
    content.append(f'export const float BULL_FVG_TOP = {float(il.get("BULL_FVG_TOP", _IL_DEFAULTS["BULL_FVG_TOP"]))}')
    content.append(f'export const float BULL_FVG_BOTTOM = {float(il.get("BULL_FVG_BOTTOM", _IL_DEFAULTS["BULL_FVG_BOTTOM"]))}')
    content.append(f'export const float BEAR_FVG_TOP = {float(il.get("BEAR_FVG_TOP", _IL_DEFAULTS["BEAR_FVG_TOP"]))}')
    content.append(f'export const float BEAR_FVG_BOTTOM = {float(il.get("BEAR_FVG_BOTTOM", _IL_DEFAULTS["BEAR_FVG_BOTTOM"]))}')
    content.append(f'export const bool BULL_FVG_PARTIAL_MITIGATION = {str(il.get("BULL_FVG_PARTIAL_MITIGATION", _IL_DEFAULTS["BULL_FVG_PARTIAL_MITIGATION"])).lower()}')
    content.append(f'export const bool BEAR_FVG_PARTIAL_MITIGATION = {str(il.get("BEAR_FVG_PARTIAL_MITIGATION", _IL_DEFAULTS["BEAR_FVG_PARTIAL_MITIGATION"])).lower()}')
    content.append(f'export const bool BULL_FVG_FULL_MITIGATION = {str(il.get("BULL_FVG_FULL_MITIGATION", _IL_DEFAULTS["BULL_FVG_FULL_MITIGATION"])).lower()}')
    content.append(f'export const bool BEAR_FVG_FULL_MITIGATION = {str(il.get("BEAR_FVG_FULL_MITIGATION", _IL_DEFAULTS["BEAR_FVG_FULL_MITIGATION"])).lower()}')
    content.append(f'export const int BULL_FVG_COUNT = {int(il.get("BULL_FVG_COUNT", _IL_DEFAULTS["BULL_FVG_COUNT"]))}')
    content.append(f'export const int BEAR_FVG_COUNT = {int(il.get("BEAR_FVG_COUNT", _IL_DEFAULTS["BEAR_FVG_COUNT"]))}')
    content.append(f'export const float BULL_FVG_MITIGATION_PCT = {float(il.get("BULL_FVG_MITIGATION_PCT", _IL_DEFAULTS["BULL_FVG_MITIGATION_PCT"]))}')
    content.append(f'export const float BEAR_FVG_MITIGATION_PCT = {float(il.get("BEAR_FVG_MITIGATION_PCT", _IL_DEFAULTS["BEAR_FVG_MITIGATION_PCT"]))}')
    content.append(f'export const bool BPR_ACTIVE = {str(il.get("BPR_ACTIVE", _IL_DEFAULTS["BPR_ACTIVE"])).lower()}')
    content.append(f'export const string BPR_DIRECTION = "{il.get("BPR_DIRECTION", _IL_DEFAULTS["BPR_DIRECTION"])}"')
    content.append(f'export const float BPR_TOP = {float(il.get("BPR_TOP", _IL_DEFAULTS["BPR_TOP"]))}')
    content.append(f'export const float BPR_BOTTOM = {float(il.get("BPR_BOTTOM", _IL_DEFAULTS["BPR_BOTTOM"]))}')
    content.append(f'export const bool LIQ_VOID_BULL_ACTIVE = {str(il.get("LIQ_VOID_BULL_ACTIVE", _IL_DEFAULTS["LIQ_VOID_BULL_ACTIVE"])).lower()}')
    content.append(f'export const bool LIQ_VOID_BEAR_ACTIVE = {str(il.get("LIQ_VOID_BEAR_ACTIVE", _IL_DEFAULTS["LIQ_VOID_BEAR_ACTIVE"])).lower()}')
    content.append(f'export const float LIQ_VOID_TOP = {float(il.get("LIQ_VOID_TOP", _IL_DEFAULTS["LIQ_VOID_TOP"]))}')
    content.append(f'export const float LIQ_VOID_BOTTOM = {float(il.get("LIQ_VOID_BOTTOM", _IL_DEFAULTS["LIQ_VOID_BOTTOM"]))}')
    content.append(f'export const string IMBALANCE_STATE = "{il.get("IMBALANCE_STATE", _IL_DEFAULTS["IMBALANCE_STATE"])}"')

    # ── Session Structure (v5.3) ────────────────────────────────
    from scripts.smc_session_structure import DEFAULTS as _SES_DEFAULTS

    ses = enr.get("session_structure") or {}
    content.append("")
    content.append("// ── Session Structure ──")
    content.append(f'export const float SESS_HIGH = {float(ses.get("SESS_HIGH", _SES_DEFAULTS["SESS_HIGH"]))}')
    content.append(f'export const float SESS_LOW = {float(ses.get("SESS_LOW", _SES_DEFAULTS["SESS_LOW"]))}')
    content.append(f'export const float SESS_OPEN_RANGE_HIGH = {float(ses.get("SESS_OPEN_RANGE_HIGH", _SES_DEFAULTS["SESS_OPEN_RANGE_HIGH"]))}')
    content.append(f'export const float SESS_OPEN_RANGE_LOW = {float(ses.get("SESS_OPEN_RANGE_LOW", _SES_DEFAULTS["SESS_OPEN_RANGE_LOW"]))}')
    content.append(f'export const string SESS_OPEN_RANGE_BREAK = "{ses.get("SESS_OPEN_RANGE_BREAK", _SES_DEFAULTS["SESS_OPEN_RANGE_BREAK"])}"')
    content.append(f'export const string SESS_IMPULSE_DIR = "{ses.get("SESS_IMPULSE_DIR", _SES_DEFAULTS["SESS_IMPULSE_DIR"])}"')
    content.append(f'export const int SESS_IMPULSE_STRENGTH = {int(ses.get("SESS_IMPULSE_STRENGTH", _SES_DEFAULTS["SESS_IMPULSE_STRENGTH"]))}')
    content.append(f'export const int SESS_INTRA_BOS_COUNT = {int(ses.get("SESS_INTRA_BOS_COUNT", _SES_DEFAULTS["SESS_INTRA_BOS_COUNT"]))}')
    content.append(f'export const bool SESS_INTRA_CHOCH = {str(ses.get("SESS_INTRA_CHOCH", _SES_DEFAULTS["SESS_INTRA_CHOCH"])).lower()}')
    content.append(f'export const float SESS_PDH = {float(ses.get("SESS_PDH", _SES_DEFAULTS["SESS_PDH"]))}')
    content.append(f'export const float SESS_PDL = {float(ses.get("SESS_PDL", _SES_DEFAULTS["SESS_PDL"]))}')
    content.append(f'export const bool SESS_PDH_SWEPT = {str(ses.get("SESS_PDH_SWEPT", _SES_DEFAULTS["SESS_PDH_SWEPT"])).lower()}')
    content.append(f'export const bool SESS_PDL_SWEPT = {str(ses.get("SESS_PDL_SWEPT", _SES_DEFAULTS["SESS_PDL_SWEPT"])).lower()}')
    content.append(f'export const int SESS_STRUCT_SCORE = {int(ses.get("SESS_STRUCT_SCORE", _SES_DEFAULTS["SESS_STRUCT_SCORE"]))}')

    # ── Range Regime (v5.3) ─────────────────────────────────────
    from scripts.smc_range_regime import DEFAULTS as _RR_DEFAULTS

    rr = enr.get("range_regime") or {}
    content.append("")
    content.append("// ── Range Regime ──")
    content.append(f'export const string RANGE_REGIME = "{rr.get("RANGE_REGIME", _RR_DEFAULTS["RANGE_REGIME"])}"')
    content.append(f'export const float RANGE_WIDTH_PCT = {float(rr.get("RANGE_WIDTH_PCT", _RR_DEFAULTS["RANGE_WIDTH_PCT"]))}')
    content.append(f'export const string RANGE_POSITION = "{rr.get("RANGE_POSITION", _RR_DEFAULTS["RANGE_POSITION"])}"')
    content.append(f'export const float RANGE_HIGH = {float(rr.get("RANGE_HIGH", _RR_DEFAULTS["RANGE_HIGH"]))}')
    content.append(f'export const float RANGE_LOW = {float(rr.get("RANGE_LOW", _RR_DEFAULTS["RANGE_LOW"]))}')
    content.append(f'export const int RANGE_DURATION_BARS = {int(rr.get("RANGE_DURATION_BARS", _RR_DEFAULTS["RANGE_DURATION_BARS"]))}')
    content.append(f'export const float RANGE_VPOC_LEVEL = {float(rr.get("RANGE_VPOC_LEVEL", _RR_DEFAULTS["RANGE_VPOC_LEVEL"]))}')
    content.append(f'export const float RANGE_VAH_LEVEL = {float(rr.get("RANGE_VAH_LEVEL", _RR_DEFAULTS["RANGE_VAH_LEVEL"]))}')
    content.append(f'export const float RANGE_VAL_LEVEL = {float(rr.get("RANGE_VAL_LEVEL", _RR_DEFAULTS["RANGE_VAL_LEVEL"]))}')
    content.append(f'export const string RANGE_BALANCE_STATE = "{rr.get("RANGE_BALANCE_STATE", _RR_DEFAULTS["RANGE_BALANCE_STATE"])}"')
    content.append(f'export const int RANGE_REGIME_SCORE = {int(rr.get("RANGE_REGIME_SCORE", _RR_DEFAULTS["RANGE_REGIME_SCORE"]))}')

    # ── Range Profile Regime (v5.3) ─────────────────────────────
    from scripts.smc_range_profile_regime import DEFAULTS as _RPR_DEFAULTS

    rpr = enr.get("range_profile_regime") or {}
    content.append("")
    content.append("// ── Range Profile Regime ──")
    content.append(f'export const bool RANGE_ACTIVE = {_pine_bool(rpr.get("RANGE_ACTIVE", _RPR_DEFAULTS["RANGE_ACTIVE"]))}')
    content.append(f'export const float RANGE_TOP = {float(rpr.get("RANGE_TOP", _RPR_DEFAULTS["RANGE_TOP"]))}')
    content.append(f'export const float RANGE_BOTTOM = {float(rpr.get("RANGE_BOTTOM", _RPR_DEFAULTS["RANGE_BOTTOM"]))}')
    content.append(f'export const float RANGE_MID = {float(rpr.get("RANGE_MID", _RPR_DEFAULTS["RANGE_MID"]))}')
    content.append(f'export const float RANGE_WIDTH_ATR = {float(rpr.get("RANGE_WIDTH_ATR", _RPR_DEFAULTS["RANGE_WIDTH_ATR"]))}')
    content.append(f'export const string RANGE_BREAK_DIRECTION = "{rpr.get("RANGE_BREAK_DIRECTION", _RPR_DEFAULTS["RANGE_BREAK_DIRECTION"])}"')
    content.append(f'export const float PROFILE_POC = {float(rpr.get("PROFILE_POC", _RPR_DEFAULTS["PROFILE_POC"]))}')
    content.append(f'export const float PROFILE_VALUE_AREA_TOP = {float(rpr.get("PROFILE_VALUE_AREA_TOP", _RPR_DEFAULTS["PROFILE_VALUE_AREA_TOP"]))}')
    content.append(f'export const float PROFILE_VALUE_AREA_BOTTOM = {float(rpr.get("PROFILE_VALUE_AREA_BOTTOM", _RPR_DEFAULTS["PROFILE_VALUE_AREA_BOTTOM"]))}')
    content.append(f'export const bool PROFILE_VALUE_AREA_ACTIVE = {_pine_bool(rpr.get("PROFILE_VALUE_AREA_ACTIVE", _RPR_DEFAULTS["PROFILE_VALUE_AREA_ACTIVE"]))}')
    content.append(f'export const float PROFILE_BULLISH_SENTIMENT = {float(rpr.get("PROFILE_BULLISH_SENTIMENT", _RPR_DEFAULTS["PROFILE_BULLISH_SENTIMENT"]))}')
    content.append(f'export const float PROFILE_BEARISH_SENTIMENT = {float(rpr.get("PROFILE_BEARISH_SENTIMENT", _RPR_DEFAULTS["PROFILE_BEARISH_SENTIMENT"]))}')
    content.append(f'export const string PROFILE_SENTIMENT_BIAS = "{rpr.get("PROFILE_SENTIMENT_BIAS", _RPR_DEFAULTS["PROFILE_SENTIMENT_BIAS"])}"')
    content.append(f'export const float LIQUIDITY_ABOVE_PCT = {float(rpr.get("LIQUIDITY_ABOVE_PCT", _RPR_DEFAULTS["LIQUIDITY_ABOVE_PCT"]))}')
    content.append(f'export const float LIQUIDITY_BELOW_PCT = {float(rpr.get("LIQUIDITY_BELOW_PCT", _RPR_DEFAULTS["LIQUIDITY_BELOW_PCT"]))}')
    content.append(f'export const float LIQUIDITY_IMBALANCE = {float(rpr.get("LIQUIDITY_IMBALANCE", _RPR_DEFAULTS["LIQUIDITY_IMBALANCE"]))}')
    content.append(f'export const float PRED_RANGE_MID = {float(rpr.get("PRED_RANGE_MID", _RPR_DEFAULTS["PRED_RANGE_MID"]))}')
    content.append(f'export const float PRED_RANGE_UPPER_1 = {float(rpr.get("PRED_RANGE_UPPER_1", _RPR_DEFAULTS["PRED_RANGE_UPPER_1"]))}')
    content.append(f'export const float PRED_RANGE_UPPER_2 = {float(rpr.get("PRED_RANGE_UPPER_2", _RPR_DEFAULTS["PRED_RANGE_UPPER_2"]))}')
    content.append(f'export const float PRED_RANGE_LOWER_1 = {float(rpr.get("PRED_RANGE_LOWER_1", _RPR_DEFAULTS["PRED_RANGE_LOWER_1"]))}')
    content.append(f'export const float PRED_RANGE_LOWER_2 = {float(rpr.get("PRED_RANGE_LOWER_2", _RPR_DEFAULTS["PRED_RANGE_LOWER_2"]))}')
    content.append(f'export const bool IN_PREDICTIVE_RANGE_EXTREME = {_pine_bool(rpr.get("IN_PREDICTIVE_RANGE_EXTREME", _RPR_DEFAULTS["IN_PREDICTIVE_RANGE_EXTREME"]))}')

    # ── v5.5b Lean: Event Risk Light ─────────────────────────────
    from scripts.smc_event_risk_light import DEFAULTS as _ERL_DEFAULTS

    erl = enr.get("event_risk_light") or {}
    content.append("")
    content.append("// ── Event Risk Light (v5.5b) ──")
    content.append(f'export const string EVENT_RISK_LIGHT_WINDOW_STATE = "{erl.get("EVENT_WINDOW_STATE", _ERL_DEFAULTS["EVENT_WINDOW_STATE"])}"')
    content.append(f'export const string EVENT_RISK_LIGHT_LEVEL = "{erl.get("EVENT_RISK_LEVEL", _ERL_DEFAULTS["EVENT_RISK_LEVEL"])}"')
    content.append(f'export const string EVENT_RISK_LIGHT_NEXT_NAME = "{erl.get("NEXT_EVENT_NAME", _ERL_DEFAULTS["NEXT_EVENT_NAME"])}"')
    content.append(f'export const string EVENT_RISK_LIGHT_NEXT_TIME = "{erl.get("NEXT_EVENT_TIME", _ERL_DEFAULTS["NEXT_EVENT_TIME"])}"')
    content.append(f'export const bool EVENT_RISK_LIGHT_MARKET_BLOCKED = {_pine_bool(erl.get("MARKET_EVENT_BLOCKED", _ERL_DEFAULTS["MARKET_EVENT_BLOCKED"]))}')
    content.append(f'export const bool EVENT_RISK_LIGHT_SYMBOL_BLOCKED = {_pine_bool(erl.get("SYMBOL_EVENT_BLOCKED", _ERL_DEFAULTS["SYMBOL_EVENT_BLOCKED"]))}')
    content.append(f'export const string EVENT_RISK_LIGHT_PROVIDER_STATUS = "{erl.get("EVENT_PROVIDER_STATUS", _ERL_DEFAULTS["EVENT_PROVIDER_STATUS"])}"')

    # ── v5.5b Lean: Session Context Light ────────────────────────
    from scripts.smc_session_context_light import DEFAULTS as _SCL_DEFAULTS

    scl = enr.get("session_context_light") or {}
    content.append("")
    content.append("// ── Session Context Light (v5.5b) ──")
    content.append(f'export const string SESSION_CONTEXT_LIGHT = "{scl.get("SESSION_CONTEXT", _SCL_DEFAULTS["SESSION_CONTEXT"])}"')
    content.append(f'export const bool SESSION_LIGHT_IN_KILLZONE = {_pine_bool(scl.get("IN_KILLZONE", _SCL_DEFAULTS["IN_KILLZONE"]))}')
    content.append(f'export const string SESSION_LIGHT_DIRECTION_BIAS = "{scl.get("SESSION_DIRECTION_BIAS", _SCL_DEFAULTS["SESSION_DIRECTION_BIAS"])}"')
    content.append(f'export const int SESSION_LIGHT_CONTEXT_SCORE = {int(scl.get("SESSION_CONTEXT_SCORE", _SCL_DEFAULTS["SESSION_CONTEXT_SCORE"]))}')
    content.append(f'export const string SESSION_LIGHT_VOLATILITY_STATE = "{scl.get("SESSION_VOLATILITY_STATE", _SCL_DEFAULTS["SESSION_VOLATILITY_STATE"])}"')

    # ── v5.5b Lean: Order Block Context Light ────────────────────
    from scripts.smc_ob_context_light import DEFAULTS as _OBL_DEFAULTS

    obl = enr.get("ob_context_light") or {}
    content.append("")
    content.append("// ── Order Block Context Light (v5.5b) ──")
    content.append(f'export const string PRIMARY_OB_SIDE = "{obl.get("PRIMARY_OB_SIDE", _OBL_DEFAULTS["PRIMARY_OB_SIDE"])}"')
    content.append(f'export const float PRIMARY_OB_DISTANCE = {float(obl.get("PRIMARY_OB_DISTANCE", _OBL_DEFAULTS["PRIMARY_OB_DISTANCE"]))}')
    content.append(f'export const bool OB_FRESH = {_pine_bool(obl.get("OB_FRESH", _OBL_DEFAULTS["OB_FRESH"]))}')
    content.append(f'export const int OB_AGE_BARS = {int(obl.get("OB_AGE_BARS", _OBL_DEFAULTS["OB_AGE_BARS"]))}')
    content.append(f'export const string OB_MITIGATION_STATE = "{obl.get("OB_MITIGATION_STATE", _OBL_DEFAULTS["OB_MITIGATION_STATE"])}"')

    # ── v5.5b Lean: FVG / Imbalance Lifecycle Light ──────────────
    from scripts.smc_fvg_lifecycle_light import DEFAULTS as _FVGL_DEFAULTS

    fvgl = enr.get("fvg_lifecycle_light") or {}
    content.append("")
    content.append("// ── FVG / Imbalance Lifecycle Light (v5.5b) ──")
    content.append(f'export const string PRIMARY_FVG_SIDE = "{fvgl.get("PRIMARY_FVG_SIDE", _FVGL_DEFAULTS["PRIMARY_FVG_SIDE"])}"')
    content.append(f'export const float PRIMARY_FVG_DISTANCE = {float(fvgl.get("PRIMARY_FVG_DISTANCE", _FVGL_DEFAULTS["PRIMARY_FVG_DISTANCE"]))}')
    content.append(f'export const float FVG_FILL_PCT = {float(fvgl.get("FVG_FILL_PCT", _FVGL_DEFAULTS["FVG_FILL_PCT"]))}')
    content.append(f'export const int FVG_MATURITY_LEVEL = {int(fvgl.get("FVG_MATURITY_LEVEL", _FVGL_DEFAULTS["FVG_MATURITY_LEVEL"]))}')
    content.append(f'export const bool FVG_FRESH = {_pine_bool(fvgl.get("FVG_FRESH", _FVGL_DEFAULTS["FVG_FRESH"]))}')
    content.append(f'export const bool FVG_INVALIDATED = {_pine_bool(fvgl.get("FVG_INVALIDATED", _FVGL_DEFAULTS["FVG_INVALIDATED"]))}')

    # ── v5.5b Lean: Structure State Light ────────────────────────
    from scripts.smc_structure_state_light import DEFAULTS as _SSL_DEFAULTS

    ssl = enr.get("structure_state_light") or {}
    content.append("")
    content.append("// ── Structure State Light (v5.5b) ──")
    content.append(f'export const string STRUCTURE_LIGHT_LAST_EVENT = "{ssl.get("STRUCTURE_LAST_EVENT", _SSL_DEFAULTS["STRUCTURE_LAST_EVENT"])}"')
    content.append(f'export const int STRUCTURE_LIGHT_EVENT_AGE_BARS = {int(ssl.get("STRUCTURE_EVENT_AGE_BARS", _SSL_DEFAULTS["STRUCTURE_EVENT_AGE_BARS"]))}')
    content.append(f'export const bool STRUCTURE_LIGHT_FRESH = {_pine_bool(ssl.get("STRUCTURE_FRESH", _SSL_DEFAULTS["STRUCTURE_FRESH"]))}')
    content.append(f'export const int STRUCTURE_TREND_STRENGTH = {int(ssl.get("STRUCTURE_TREND_STRENGTH", _SSL_DEFAULTS["STRUCTURE_TREND_STRENGTH"]))}')

    # ── v5.5b Lean: Signal Quality ───────────────────────────────
    from scripts.smc_signal_quality import DEFAULTS as _SQ_DEFAULTS

    sq = enr.get("signal_quality") or {}
    content.append("")
    content.append("// ── Signal Quality (v5.5b) ──")
    content.append(f'export const int SIGNAL_QUALITY_SCORE = {int(sq.get("SIGNAL_QUALITY_SCORE", _SQ_DEFAULTS["SIGNAL_QUALITY_SCORE"]))}')
    content.append(f'export const string SIGNAL_QUALITY_TIER = "{sq.get("SIGNAL_QUALITY_TIER", _SQ_DEFAULTS["SIGNAL_QUALITY_TIER"])}"')
    content.append(f'export const string SIGNAL_WARNINGS = "{sq.get("SIGNAL_WARNINGS", _SQ_DEFAULTS["SIGNAL_WARNINGS"])}"')
    content.append(f'export const string SIGNAL_BIAS_ALIGNMENT = "{sq.get("SIGNAL_BIAS_ALIGNMENT", _SQ_DEFAULTS["SIGNAL_BIAS_ALIGNMENT"])}"')
    content.append(f'export const string SIGNAL_FRESHNESS = "{sq.get("SIGNAL_FRESHNESS", _SQ_DEFAULTS["SIGNAL_FRESHNESS"])}"')

    path.write_text("\n".join(content).rstrip() + "\n", encoding="utf-8")


def render_output_path(root: Path, template: str, asof_date: str) -> Path:
    return root / template.format(asof_date=asof_date)


def write_lists_csv(path: Path, state: pd.DataFrame, asof_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    active = state.loc[
        state["is_active"] == 1,
        ["symbol", "list_name", "active_since", "last_score", "decision_source", "decision_reason"],
    ].copy()
    active.insert(0, "asof_date", asof_date)
    active = active.sort_values(["list_name", "symbol"]).reset_index(drop=True)
    active.to_csv(path, index=False)


def write_diff_report(path: Path, previous_state: pd.DataFrame, new_state: pd.DataFrame, asof_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def active_map(frame: pd.DataFrame) -> dict[str, dict[str, dict[str, str]]]:
        mapping: dict[str, dict[str, dict[str, str]]] = {name: {} for name in LISTS}
        if frame.empty:
            return mapping
        active = frame.loc[
            frame["is_active"] == 1,
            ["symbol", "list_name", "decision_source", "decision_reason"],
        ].copy()
        for list_name, group in active.groupby("list_name"):
            mapping[list_name] = {
                str(record["symbol"]): {
                    "decision_source": str(record.get("decision_source", "generator")),
                    "decision_reason": str(record.get("decision_reason", "")),
                }
                for record in group.to_dict("records")
            }
        return mapping

    before = active_map(previous_state)
    after = active_map(new_state)
    lines = [
        f"# Microstructure List Diff {asof_date}",
        "",
    ]
    for list_name in LISTS:
        added = sorted(set(after[list_name]) - set(before[list_name]))
        removed = sorted(set(before[list_name]) - set(after[list_name]))
        lines.append(f"## {list_name}")
        lines.append("")
        lines.append(f"- Added: {len(added)}")
        lines.append(f"- Removed: {len(removed)}")
        if added:
            lines.append("")
            lines.append("### Added details")
            lines.append("")
            lines.append("| Symbol | Source | Reason |")
            lines.append("| --- | --- | --- |")
            for symbol in added:
                details = after[list_name][symbol]
                lines.append(f"| {symbol} | {details['decision_source']} | {details['decision_reason']} |")
        if removed:
            lines.append("")
            lines.append("### Removed details")
            lines.append("")
            lines.append("| Symbol | Source | Reason |")
            lines.append("| --- | --- | --- |")
            for symbol in removed:
                details = before[list_name][symbol]
                lines.append(f"| {symbol} | {details['decision_source']} | {details['decision_reason']} |")
        if not added and not removed:
            lines.append("- No changes")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_core_import_snippet(path: Path, *, library_owner: str, library_name: str, library_version: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    import_path = f"{library_owner}/{library_name}/{library_version}"
    content = [
        f"// Core import snippet — microstructure list bindings only.",
        f"// For regime, news, calendar, layering, and event-risk (v5) fields,",
        f"// read mp.FIELD_NAME directly from the library. See the full field",
        f"// inventory in the library header comment.",
        f"import {import_path} as mp",
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS",
        "string stop_hunt_tickers_effective = mp.STOP_HUNT_PRONE_TICKERS",
        "string midday_dead_tickers_effective = mp.MIDDAY_DEAD_TICKERS",
        "string rth_only_tickers_effective = mp.RTH_ONLY_TICKERS",
        "string weak_premarket_tickers_effective = mp.WEAK_PREMARKET_TICKERS",
        "string weak_afterhours_tickers_effective = mp.WEAK_AFTERHOURS_TICKERS",
        "string fast_decay_tickers_effective = mp.FAST_DECAY_TICKERS",
    ]
    path.write_text("\n".join(content) + "\n", encoding="utf-8")
    return import_path


def assess_csv_against_schema(schema: dict[str, Any], csv_path: Path) -> dict[str, Any]:
    header = pd.read_csv(csv_path, nrows=0)
    required = [str(column) for column in schema["required_columns"]]
    present = [column for column in required if column in header.columns]
    missing = [column for column in required if column not in header.columns]
    extra = sorted(column for column in header.columns if column not in required)
    return {
        "path": str(csv_path),
        "present_required": present,
        "missing_required": missing,
        "extra_columns": extra,
        "required_coverage": round(len(present) / len(required), 4) if required else 1.0,
    }


def write_readiness_report(path: Path, assessment: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    present = assessment["present_required"]
    missing = assessment["missing_required"]
    extra = assessment["extra_columns"]
    lines = [
        f"# Microstructure Input Readiness: {Path(str(assessment['path'])).name}",
        "",
        f"- Source CSV: {assessment['path']}",
        f"- Required coverage: {len(present)}/{len(present) + len(missing)} ({assessment['required_coverage']:.2%})",
        "",
        "## Present required columns",
        "",
    ]
    lines.extend([f"- {column}" for column in present] or ["- None"])
    lines.extend([
        "",
        "## Missing required columns",
        "",
    ])
    lines.extend([f"- {column}" for column in missing] or ["- None"])
    lines.extend([
        "",
        "## Extra source columns",
        "",
    ])
    lines.extend([f"- {column}" for column in extra] or ["- None"])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_manifest(
    path: Path,
    *,
    asof_date: str,
    input_path: Path,
    schema_path: Path,
    features_path: Path,
    lists_path: Path,
    state_path: Path,
    diff_report_path: Path,
    pine_path: Path,
    core_import_snippet_path: Path,
    universe_size: int,
    lists: dict[str, list[str]],
    library_owner: str,
    library_version: int,
    recommended_import_path: str,
    enrichment: EnrichmentDict | None = None,
    relative_to: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    from scripts.smc_v55_lean_normalization import normalize_v55_lean_enrichment

    normalized_enrichment = normalize_v55_lean_enrichment(enrichment)

    # Read previous manifest to record governance metadata
    prev_schema = ""
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            prev_schema = prev.get("schema_version", "")
        except Exception:
            pass

    if prev_schema:
        change_type = classify_version_change(prev_schema, SCHEMA_VERSION).value
    else:
        change_type = "initial"

    def _rel(p: Path) -> str:
        if relative_to is not None:
            try:
                return str(p.resolve().relative_to(relative_to.resolve()))
            except ValueError:
                pass
        return str(p)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "schema_version_previous": prev_schema,
        "version_change_type": change_type,
        "asof_date": asof_date,
        "library_name": "smc_micro_profiles_generated",
        "library_owner": library_owner,
        "library_version": library_version,
        "recommended_import_path": recommended_import_path,
        "library_publish_required": True,
        "deployment_note": "Publish the generated Pine library in TradingView before importing it into SMC_Core_Engine.",
        "input_path": _rel(input_path),
        "schema_path": _rel(schema_path),
        "features_csv": _rel(features_path),
        "lists_csv": _rel(lists_path),
        "state_csv": _rel(state_path),
        "diff_report_md": _rel(diff_report_path),
        "pine_library": _rel(pine_path),
        "core_import_snippet": _rel(core_import_snippet_path),
        "universe_size": universe_size,
        "exported_lists": LIST_EXPORTS,
        "list_counts": {name: len(symbols) for name, symbols in lists.items()},
        "enrichment_blocks": sorted((normalized_enrichment or {}).keys()),
        "library_field_version": "v5.5b",
        "v55_lean_blocks": [
            "event_risk_light",
            "session_context_light",
            "ob_context_light",
            "fvg_lifecycle_light",
            "structure_state_light",
            "signal_quality",
        ],
        "event_risk_source": "smc_event_risk_builder" if (normalized_enrichment or {}).get("event_risk") else "defaults",
        "auto_commit_allowed": change_type in ("unchanged", "patch", "minor", "initial"),
        "asof_time": ((normalized_enrichment or {}).get("meta") or {}).get("asof_time", ""),
        "refresh_count": int(((normalized_enrichment or {}).get("meta") or {}).get("refresh_count", 0)),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_generation(
    *,
    schema_path: Path,
    input_path: Path,
    overrides_path: Path | None = None,
    output_root: Path | None = None,
    library_owner: str = "preuss_steffen",
    library_version: int = 1,
    enrichment: EnrichmentDict | None = None,
) -> dict[str, Path]:
    """Orchestrate generate → validate → publish in sequence.

    This is the backward-compatible entry point.  For finer control,
    use :mod:`scripts.smc_micro_generator`,
    :mod:`scripts.smc_micro_validator`, and
    :mod:`scripts.smc_micro_publisher` directly.
    """
    from scripts.smc_micro_generator import generate
    from scripts.smc_micro_publisher import publish_generation_result
    from scripts.smc_micro_validator import validate_generation_input

    root = output_root or Path(".")
    schema = load_schema(schema_path)
    raw_df = pd.read_csv(input_path)
    df = coerce_input_frame(raw_df)

    # 1. Validate
    validate_generation_input(df, schema)

    # 2. Generate (pure computation)
    state_path_resolved = root / schema["generator_outputs"]["state_csv"]
    result = generate(
        schema=schema,
        input_df=df,
        schema_path=schema_path,
        input_path=input_path,
        state_path=state_path_resolved if state_path_resolved.exists() else None,
        overrides_path=overrides_path,
    )

    # 3. Publish (file I/O)
    return publish_generation_result(
        result,
        output_root=root,
        library_owner=library_owner,
        library_version=library_version,
        enrichment=enrichment,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate microstructure profile membership lists and Pine library exports.")
    from scripts.smc_schema_resolver import resolve_microstructure_schema_path
    parser.add_argument("--schema", type=Path, default=resolve_microstructure_schema_path(), help="Path to the schema file.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/input/microstructure_base_snapshot_2026-03-23.csv"),
        help="Path to the base snapshot CSV.",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=Path("data/input/microstructure_overrides.csv"),
        help="Optional path to per-run membership overrides.",
    )
    parser.add_argument("--output-root", type=Path, default=Path("."), help="Workspace root for generator outputs.")
    parser.add_argument("--library-owner", default="preuss_steffen", help="TradingView owner for the generated library import path.")
    parser.add_argument("--library-version", type=int, default=1, help="TradingView library version for the generated import path.")
    parser.add_argument("--assess-input", type=Path, help="Optional CSV path to assess against the microstructure schema.")
    parser.add_argument(
        "--assess-output",
        type=Path,
        help="Optional output path for the readiness markdown report. Defaults to reports/<input_stem>_microstructure_readiness.md.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.assess_input is not None:
        from scripts.smc_micro_publisher import publish_readiness_report
        from scripts.smc_micro_validator import assess_input_coverage

        schema = load_schema(args.schema)
        assessment = assess_input_coverage(schema, args.assess_input)
        output_path = args.assess_output or Path("reports") / f"{args.assess_input.stem}_microstructure_readiness.md"
        publish_readiness_report(assessment, output_path=output_path)
        return
    run_generation(
        schema_path=args.schema,
        input_path=args.input,
        overrides_path=args.overrides,
        output_root=args.output_root,
        library_owner=args.library_owner,
        library_version=args.library_version,
    )


if __name__ == "__main__":
    main()