from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

from smc_core.schema_version import SCHEMA_VERSION
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
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    enr = enrichment or {}

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
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "asof_date": asof_date,
        "library_name": "smc_micro_profiles_generated",
        "library_owner": library_owner,
        "library_version": library_version,
        "recommended_import_path": recommended_import_path,
        "library_publish_required": True,
        "deployment_note": "Publish the generated Pine library in TradingView before importing it into SMC_Core_Engine.",
        "input_path": str(input_path),
        "schema_path": str(schema_path),
        "features_csv": str(features_path),
        "lists_csv": str(lists_path),
        "state_csv": str(state_path),
        "diff_report_md": str(diff_report_path),
        "pine_library": str(pine_path),
        "core_import_snippet": str(core_import_snippet_path),
        "universe_size": universe_size,
        "exported_lists": LIST_EXPORTS,
        "list_counts": {name: len(symbols) for name, symbols in lists.items()},
        "enrichment_blocks": sorted((enrichment or {}).keys()),
        "library_field_version": "v4",
        "asof_time": ((enrichment or {}).get("meta") or {}).get("asof_time", ""),
        "refresh_count": int(((enrichment or {}).get("meta") or {}).get("refresh_count", 0)),
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