from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

from scripts.smc_atomic_write import atomic_write_csv, atomic_write_text
from scripts.smc_enrichment_types import EnrichmentDict


def _pine_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to a finite float for Pine embedding.

    Pine has no ``nan``/``inf`` literal, so a non-finite value would make
    the generated ``export const float NAME = nan`` line a compile error.
    Map any non-finite or uncoercible value to *default*.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return float(default)
    return f if math.isfinite(f) else float(default)
from smc_core.schema_version import SCHEMA_VERSION, classify_version_change

logger = logging.getLogger(__name__)


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

DEPRECATED_COMPATIBILITY_GROUPS: list[str] = [
    # All deprecated v5-v5.3 compatibility groups removed (70 fields total).
    # Sunset completed 2026-04-14.
]

PLACEHOLDER_SYMBOL_SENTINELS = {"AAA", "BBB", "CCC"}


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

    def _normalize_string_column(column: str, *, upper: bool = False) -> None:
        values = out[column]
        normalized = values.astype("string").str.strip()
        if upper:
            normalized = normalized.str.upper()
        out[column] = normalized.where(values.notna(), pd.NA)

    _normalize_string_column("symbol", upper=True)
    _normalize_string_column("exchange", upper=True)
    _normalize_string_column("asset_type")
    _normalize_string_column("universe_bucket")

    for column in out.columns:
        if column in {"asof_date", "symbol", "exchange", "asset_type", "universe_bucket"}:
            continue
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def _primary_key_columns(schema: dict[str, Any]) -> list[str]:
    return [str(column) for column in schema["primary_key"]]


def _primary_key_null_mask(df: pd.DataFrame, primary_key: list[str]) -> pd.Series:
    mask = pd.Series(False, index=df.index, dtype=bool)
    for column in primary_key:
        mask = mask | df[column].isnull()
    return mask


def _duplicate_primary_key_mask(df: pd.DataFrame, primary_key: list[str]) -> pd.Series:
    key_rows = list(zip(*(df[column].tolist() for column in primary_key), strict=False))
    return pd.Series(key_rows, index=df.index, dtype="object").duplicated(keep=False)


def _normalize_group_key(value: object) -> object:
    return None if pd.isna(value) else value


def _iter_group_frames(df: pd.DataFrame, column: str) -> list[tuple[object, pd.DataFrame]]:
    grouped_rows: dict[object, list[dict[str, Any]]] = {}
    ordered_keys: list[object] = []
    for record in df.to_dict("records"):
        key = _normalize_group_key(record.get(column))
        if key not in grouped_rows:
            grouped_rows[key] = []
            ordered_keys.append(key)
        grouped_rows[key].append(record)
    return [
        (key, pd.DataFrame(grouped_rows[key], columns=df.columns))
        for key in ordered_keys
    ]


def _bucket_stat_series(df: pd.DataFrame, column: str, reducer: str, *, quantile: float | None = None) -> pd.Series:
    bucket_keys = [_normalize_group_key(value) for value in df["universe_bucket"].tolist()]
    grouped_values: dict[object, list[float]] = {}
    for key, value in zip(bucket_keys, df[column].tolist(), strict=False):
        if key is None:
            continue
        grouped_values.setdefault(key, []).append(value)

    stats: dict[object, float] = {}
    for key, values in grouped_values.items():
        series = pd.Series(values, dtype=float)
        if reducer == "quantile":
            stats[key] = float(series.quantile(float(quantile)))
        elif reducer == "median":
            stats[key] = float(series.median())
        else:
            raise ValueError(f"Unsupported bucket reducer: {reducer}")

    return pd.Series(
        [stats.get(key, float("nan")) if key is not None else float("nan") for key in bucket_keys],
        index=df.index,
        dtype=float,
    )


def _filtered_records_frame(
    frame: pd.DataFrame,
    *,
    predicate: Any,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    selected_columns = list(columns or frame.columns)
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        if predicate(record):
            rows.append({column: record.get(column) for column in selected_columns})
    return pd.DataFrame(rows, columns=selected_columns)


def validate_schema(df: pd.DataFrame, schema: dict[str, Any]) -> None:
    missing = [column for column in schema["required_columns"] if column not in df.columns]
    if missing:
        fail(f"Missing required columns: {missing}")

    primary_key = _primary_key_columns(schema)
    null_primary_key_mask = _primary_key_null_mask(df, primary_key)
    if bool(null_primary_key_mask.any()):
        fail("Primary key columns cannot contain null values")

    duplicate_primary_key_mask = _duplicate_primary_key_mask(df, primary_key)
    if bool(duplicate_primary_key_mask.any()):
        duplicate_flags = duplicate_primary_key_mask.tolist()
        records = df.to_dict("records")
        duplicates = pd.DataFrame(
            {
                column: [record.get(column) for record, is_duplicate in zip(records, duplicate_flags, strict=False) if is_duplicate]
                for column in primary_key
            }
        )
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
    for _, group in _iter_group_frames(df, "universe_bucket"):
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
    return _bucket_stat_series(df, column, "quantile", quantile=quantile)


def _bucket_median(df: pd.DataFrame, column: str) -> pd.Series:
    return _bucket_stat_series(df, column, "median")


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
    active = _filtered_records_frame(
        state,
        predicate=lambda record: _safe_bool(record.get("is_active")),
    )
    for list_name, group in _iter_group_frames(active, "list_name"):
        if list_name in output:
            output[str(list_name)] = sorted(group["symbol"].astype(str).unique().tolist())
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


def render_csv_export(export_name: str, items: list[str], max_chars: int = 35000) -> str:
    shards = shard_csv_string(items, max_chars=max_chars)
    if not shards:
        return f'export const string {export_name} = ""'
    if len(shards) == 1:
        return f'export const string {export_name} = "{shards[0]}"'
    lines = [f'const string {export_name}_PART_{index} = "{chunk}"' for index, chunk in enumerate(shards, start=1)]
    join_expression = ' + "," + '.join(f"{export_name}_PART_{index}" for index in range(1, len(shards) + 1))
    lines.append(f"export const string {export_name} = {join_expression}")
    return "\n".join(lines)


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
        return render_csv_export(f"{name.upper()}_TICKERS", symbols)

    def split_csv_string(value: str) -> list[str]:
        if not value:
            return []
        return [part for part in value.split(",") if part]

    def _pine_bool(val: Any) -> str:
        return "true" if val else "false"

    content = [
        "//@version=6",
        'library("smc_micro_profiles_generated")',
        "",
        "// ── Usage ──────────────────────────────────────────────────────",
        "// import preuss_steffen/smc_micro_profiles_generated/1 as mp",
        "//",
        "// Fields are grouped into sections (v5.5b Lean, ~102 fields + 5 optional debug):",
        "// Deprecated v5-v5.3 compatibility groups removed (sunset 2026-04-14); only v5.5b Lean fields remain.",
        "//   Core/Meta       — ASOF_DATE, ASOF_TIME, UNIVERSE_SIZE, REFRESH_COUNT (+ UNIVERSE_ID, LOOKBACK_DAYS in debug mode)",
        "//   Microstructure  — *_TICKERS lists (clean_reclaim, stop_hunt_prone, …)",
        "//   Regime          — MARKET_REGIME, VIX_LEVEL, MACRO_BIAS, MACRO_BIAS_RAW, MACRO_BIAS_PE_ADJUSTMENT, MARKET_PE_FORWARD, MARKET_PE_REGIME, SECTOR_BREADTH",
        "//   News            — NEWS_*_TICKERS, NEWS_HEAT_GLOBAL, TICKER_HEAT_MAP",
        "//   Calendar        — EARNINGS_*_TICKERS, HIGH_IMPACT_MACRO_TODAY, MACRO_EVENT_*",
        "//   Layering        — GLOBAL_HEAT, GLOBAL_STRENGTH, TONE, TRADE_STATE",
        "//   Providers       — PROVIDER_COUNT, STALE_PROVIDERS",
        "//   Volume          — VOLUME_LOW_TICKERS, HOLIDAY_SUSPECT_TICKERS",
        "//   Volatility      — VOLATILITY_REGIME, VOLATILITY_REGIME_CONFIDENCE, VOLATILITY_ATR_RATIO, VOLATILITY_MODEL_SOURCE (+ VOLATILITY_FALLBACK_REASON, VOLATILITY_PROXY_SYMBOL, VOLATILITY_PROXY_SOURCE in debug mode)",
        "//   Ensemble Score  — ENSEMBLE_QUALITY_SCORE, ENSEMBLE_QUALITY_TIER, ENSEMBLE_AVAILABLE_COMPONENTS",
        "//   Flow Qualifier (v5.1)  — REL_VOL … ATS_BEARISH_SEQUENCE (14 fields)",
        "//   Compression (v5.1)     — SQUEEZE_ON … ATR_RATIO (5 fields)",
        "//",
        "//   ── v5.5b Lean Surface (preferred) ──",
        "//   Event Risk Light (v5.5b)      — 14 fields (incl. HIGH_RISK_EVENT_TICKERS, NEXT_EVENT_CLASS)",
        "//   Session Context Light (v5.5b) — 5 fields",
        "//   OB Context Light (v5.5b)      — 5 fields",
        "//   FVG Lifecycle Light (v5.5b)   — 7 fields",
        "//   Imbalance Lifecycle Extended  — 1 field (BPR_DIRECTION)",
        "//   Liquidity Pools               — 2 fields (BUY_SIDE_POOL_LEVEL, BUY_SIDE_POOL_STRENGTH)",
        "//   Liquidity Sweeps Extended     — 1 field (LIQUIDITY_TAKEN_DIRECTION)",
        "//   Structure State Light (v5.5b) — 4 fields",
        "//   Signal Quality (v5.5b)        — 5 fields",
        "//",
        "// All fields are export const — safe to read as mp.FIELD_NAME.",
        "// ───────────────────────────────────────────────────────────────",
        "",
        f'export const string ASOF_DATE = "{asof_date}"',
        f'export const string ASOF_TIME = "{(enr.get("meta") or {}).get("asof_time") or ""}"',
        f"export const int UNIVERSE_SIZE = {universe_size}",
        f"export const int REFRESH_COUNT = {int((enr.get('meta') or {}).get('refresh_count') or 0)}",
    ]

    # Universe Coverage — all scanned ticker symbols
    scanned = sorted(set((enr.get("meta") or {}).get("scanned_symbols") or []))
    if scanned:
        content.append(render_csv_export("UNIVERSE_TICKERS", scanned, max_chars=3900))
    else:
        content.append('export const string UNIVERSE_TICKERS = ""')

    debug_mode = bool(enr.get("_debug_mode"))
    if debug_mode:
        content.append('export const string UNIVERSE_ID = "us_equities_v1"')
        content.append("export const int LOOKBACK_DAYS = 20")

    content.append("")
    for list_name in LISTS:
        content.append(render_list(list_name, lists[list_name]))
        content.append("")

    # ── Regime enrichment ───────────────────────────────────────
    regime = enr.get("regime") or {}
    content.append("// ── Market Regime ──")
    content.append(f'export const string MARKET_REGIME = "{regime.get("regime", "NEUTRAL")}"')
    content.append(f'export const float VIX_LEVEL = {_pine_float(regime.get("vix_level") or 0.0)}')
    content.append(f'export const float MACRO_BIAS = {_pine_float(regime.get("macro_bias") or 0.0)}')
    _raw = regime.get("macro_bias_raw")
    content.append(f'export const float MACRO_BIAS_RAW = {_pine_float(_raw if _raw is not None else 0.0)}')
    content.append(f'export const float MACRO_BIAS_PE_ADJUSTMENT = {_pine_float(regime.get("macro_bias_pe_adjustment") or 0.0)}')
    content.append(f'export const float MARKET_PE_FORWARD = {_pine_float(regime.get("market_pe_forward") or 0.0)}')
    content.append(f'export const string MARKET_PE_REGIME = "{regime.get("market_pe_regime") or "UNKNOWN"}"')
    content.append(f'export const float SECTOR_BREADTH = {_pine_float(regime.get("sector_breadth") or 0.0)}')
    content.append("")

    # ── News enrichment ─────────────────────────────────────────
    news = enr.get("news") or {}
    content.append("// ── News Sentiment ──")
    content.append(render_csv_export("NEWS_BULLISH_TICKERS", news.get("bullish_tickers") or []))
    content.append(render_csv_export("NEWS_BEARISH_TICKERS", news.get("bearish_tickers") or []))
    content.append(render_csv_export("NEWS_NEUTRAL_TICKERS", news.get("neutral_tickers") or []))
    content.append(f'export const float NEWS_HEAT_GLOBAL = {_pine_float(news.get("news_heat_global") or 0.0)}')
    content.append(render_csv_export("TICKER_HEAT_MAP", split_csv_string(news.get("ticker_heat_map") or "")))
    # WP-NW4: category, count, breaking, most-mentioned fields
    content.append(f'export const string NEWS_CATEGORY_MAP = "{news.get("news_category_map") or ""}"')
    content.append(f'export const string NEWS_COUNT_MAP = "{news.get("news_count_map") or ""}"')
    content.append(f'export const string BREAKING_NEWS_TICKERS = "{",".join(news.get("breaking_tickers") or [])}"')
    content.append(f'export const int HIGH_IMPACT_NEWS_COUNT = {int(news.get("high_impact_news_count") or 0)}')
    content.append(f'export const string MOST_MENTIONED_TICKER = "{news.get("most_mentioned_ticker") or ""}"')
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
    content.append(f'export const float GLOBAL_HEAT = {_pine_float(lay.get("global_heat") or 0.0)}')
    content.append(f'export const float GLOBAL_STRENGTH = {_pine_float(lay.get("global_strength") or 0.0)}')
    content.append(f'export const string TONE = "{lay.get("tone") or "NEUTRAL"}"')
    content.append(f'export const string TRADE_STATE = "{lay.get("trade_state") or "ALLOWED"}"')
    content.append("")

    # ── Provider status ─────────────────────────────────────────
    prov = enr.get("providers") or {}
    content.append("// ── Provider Status ──")
    content.append(f'export const int PROVIDER_COUNT = {int(prov.get("provider_count") or 0)}')
    content.append(f'export const string STALE_PROVIDERS = "{prov.get("stale_providers") or ""}"')
    content.append("")

    # ── Trust State (ENG-WS2-02) ────────────────────────────────
    # Lifts the canonical product trust state into Pine so consumers can
    # read state + action_impact + degradation reason directly instead
    # of recomputing it from STALE_PROVIDERS / PROVIDER_COUNT.
    from scripts.smc_trust_state_export import (
        render_action_degradation_block_lines,
        render_trust_block_lines,
    )

    content.extend(render_trust_block_lines(enr))
    content.append("")

    # ── Action Degradation (ENG-WS2-04) ────────────────────────
    # Deterministic mapping from the trust state above to a single
    # product-action tier (none/selective/watchlist/no_trade) plus the
    # UI-visible reason string. Pine consumers must not re-derive this.
    content.extend(render_action_degradation_block_lines(enr))
    content.append("")

    # ── Hero Market Mode (ENG-WS3-03) ──────────────────────────
    # Single Hero-level head row: regime + bias + session + trust +
    # freshness. Dashboards must read these fields and not recompute
    # the head themselves (no second competing mode display).
    from scripts.smc_hero_market_mode import render_hero_market_mode_block_lines

    content.extend(render_hero_market_mode_block_lines(enr))
    content.append("")

    # ── Hero Setup Quality (ENG-WS3-04) ────────────────────────
    # Setup quality as a reasoned product object: tier + why_now +
    # main_risk + family_health. Default and Audit views must read the
    # same fields — no second quality classification path.
    from scripts.smc_hero_setup_quality import render_hero_setup_quality_block_lines

    content.extend(render_hero_setup_quality_block_lines(enr))
    content.append("")

    # ── Volume regime ───────────────────────────────────────────
    vol = enr.get("volume_regime") or {}
    content.append("// ── Volume Regime ──")
    content.append(f'export const string VOLUME_LOW_TICKERS = "{",".join(vol.get("low_tickers") or [])}"')
    content.append(f'export const string HOLIDAY_SUSPECT_TICKERS = "{",".join(vol.get("holiday_suspect_tickers") or [])}"')
    content.append("")

    # ── Volatility regime ──────────────────────────────────────
    vreg = enr.get("volatility_regime") or {}
    content.append("// ── Volatility Regime ──")
    content.append(f'export const string VOLATILITY_REGIME = "{vreg.get("label") or "NORMAL"}"')
    content.append(f'export const float VOLATILITY_REGIME_CONFIDENCE = {_pine_float(vreg.get("confidence") or 0.0)}')
    content.append(f'export const float VOLATILITY_ATR_RATIO = {_pine_float(vreg.get("raw_atr_ratio") or 1.0)}')
    content.append(f'export const string VOLATILITY_MODEL_SOURCE = "{vreg.get("model_source") or "atr_fallback"}"')
    if debug_mode:
        content.append(f'export const string VOLATILITY_FALLBACK_REASON = "{vreg.get("fallback_reason") or ""}"')
        content.append(f'export const string VOLATILITY_PROXY_SYMBOL = "{vreg.get("proxy_symbol") or ""}"')
        content.append(f'export const string VOLATILITY_PROXY_SOURCE = "{vreg.get("proxy_source") or ""}"')
    content.append("")

    # ── Ensemble quality ───────────────────────────────────────
    eq = enr.get("ensemble_quality") or {}
    content.append("// ── Ensemble Quality ──")
    content.append(f'export const float ENSEMBLE_QUALITY_SCORE = {_pine_float(eq.get("score") or 0.0)}')
    content.append(f'export const string ENSEMBLE_QUALITY_TIER = "{eq.get("tier") or "low"}"')
    content.append(f'export const string ENSEMBLE_AVAILABLE_COMPONENTS = "{",".join(eq.get("available_components") or [])}"')
    content.append("")

    # ── Flow Qualifier (v5.1) ───────────────────────────────────
    from scripts.smc_flow_qualifier import DEFAULTS as _FQ_DEFAULTS

    fq = enr.get("flow_qualifier") or {}
    content.append("")
    content.append("// ── Flow Qualifier ──")
    content.append(f'export const float REL_VOL = {_pine_float(fq.get("REL_VOL", _FQ_DEFAULTS["REL_VOL"]))}')
    content.append(f'export const float REL_ACTIVITY = {_pine_float(fq.get("REL_ACTIVITY", _FQ_DEFAULTS["REL_ACTIVITY"]))}')
    content.append(f'export const float REL_SIZE = {_pine_float(fq.get("REL_SIZE", _FQ_DEFAULTS["REL_SIZE"]))}')
    content.append(f'export const float DELTA_PROXY_PCT = {_pine_float(fq.get("DELTA_PROXY_PCT", _FQ_DEFAULTS["DELTA_PROXY_PCT"]))}')
    content.append(f'export const bool FLOW_LONG_OK = {_pine_bool(fq.get("FLOW_LONG_OK", _FQ_DEFAULTS["FLOW_LONG_OK"]))}')
    content.append(f'export const bool FLOW_SHORT_OK = {_pine_bool(fq.get("FLOW_SHORT_OK", _FQ_DEFAULTS["FLOW_SHORT_OK"]))}')
    content.append(f'export const float ATS_VALUE = {_pine_float(fq.get("ATS_VALUE", _FQ_DEFAULTS["ATS_VALUE"]))}')
    content.append(f'export const float ATS_CHANGE_PCT = {_pine_float(fq.get("ATS_CHANGE_PCT", _FQ_DEFAULTS["ATS_CHANGE_PCT"]))}')
    content.append(f'export const float ATS_ZSCORE = {_pine_float(fq.get("ATS_ZSCORE", _FQ_DEFAULTS["ATS_ZSCORE"]))}')
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
    content.append(f'export const float ATR_RATIO = {_pine_float(cr.get("ATR_RATIO", _CR_DEFAULTS["ATR_RATIO"]))}')

    # ── v5.5b Lean: Event Risk Light ─────────────────────────────
    from scripts.smc_event_risk_builder import DEFAULTS as _ER_DEFAULTS

    er = enr.get("event_risk") or {}
    erl = enr.get("event_risk_light") or {}
    event_window_state = erl.get("EVENT_WINDOW_STATE", er.get("EVENT_WINDOW_STATE", _ER_DEFAULTS["EVENT_WINDOW_STATE"]))
    event_risk_level = erl.get("EVENT_RISK_LEVEL", er.get("EVENT_RISK_LEVEL", _ER_DEFAULTS["EVENT_RISK_LEVEL"]))
    next_event_name = erl.get("NEXT_EVENT_NAME", er.get("NEXT_EVENT_NAME", _ER_DEFAULTS["NEXT_EVENT_NAME"]))
    next_event_time = erl.get("NEXT_EVENT_TIME", er.get("NEXT_EVENT_TIME", _ER_DEFAULTS["NEXT_EVENT_TIME"]))
    market_event_blocked = erl.get("MARKET_EVENT_BLOCKED", er.get("MARKET_EVENT_BLOCKED", _ER_DEFAULTS["MARKET_EVENT_BLOCKED"]))
    symbol_event_blocked = erl.get("SYMBOL_EVENT_BLOCKED", er.get("SYMBOL_EVENT_BLOCKED", _ER_DEFAULTS["SYMBOL_EVENT_BLOCKED"]))
    event_provider_status = erl.get("EVENT_PROVIDER_STATUS", er.get("EVENT_PROVIDER_STATUS", _ER_DEFAULTS["EVENT_PROVIDER_STATUS"]))
    content.append("")
    content.append("// ── Event Risk Light (v5.5b) ──")
    content.append(f'export const string EVENT_WINDOW_STATE = "{event_window_state}"')
    content.append(f'export const string EVENT_RISK_LEVEL = "{event_risk_level}"')
    content.append(f'export const string NEXT_EVENT_NAME = "{next_event_name}"')
    content.append(f'export const string NEXT_EVENT_TIME = "{next_event_time}"')
    content.append(f'export const string NEXT_EVENT_IMPACT = "{er.get("NEXT_EVENT_IMPACT", _ER_DEFAULTS["NEXT_EVENT_IMPACT"])}"')
    content.append(f'export const int EVENT_RESTRICT_BEFORE_MIN = {int(er.get("EVENT_RESTRICT_BEFORE_MIN", _ER_DEFAULTS["EVENT_RESTRICT_BEFORE_MIN"]))}')
    content.append(f'export const int EVENT_RESTRICT_AFTER_MIN = {int(er.get("EVENT_RESTRICT_AFTER_MIN", _ER_DEFAULTS["EVENT_RESTRICT_AFTER_MIN"]))}')
    content.append(f'export const bool EVENT_COOLDOWN_ACTIVE = {_pine_bool(er.get("EVENT_COOLDOWN_ACTIVE", _ER_DEFAULTS["EVENT_COOLDOWN_ACTIVE"]))}')
    content.append(f'export const bool MARKET_EVENT_BLOCKED = {_pine_bool(market_event_blocked)}')
    content.append(f'export const bool SYMBOL_EVENT_BLOCKED = {_pine_bool(symbol_event_blocked)}')
    content.append(f'export const string EARNINGS_SOON_TICKERS = "{er.get("EARNINGS_SOON_TICKERS", _ER_DEFAULTS["EARNINGS_SOON_TICKERS"])}"')
    content.append(f'export const string EVENT_PROVIDER_STATUS = "{event_provider_status}"')
    content.append(f'export const string HIGH_RISK_EVENT_TICKERS = "{er.get("HIGH_RISK_EVENT_TICKERS", _ER_DEFAULTS["HIGH_RISK_EVENT_TICKERS"])}"')
    content.append(f'export const string NEXT_EVENT_CLASS = "{er.get("NEXT_EVENT_CLASS", _ER_DEFAULTS["NEXT_EVENT_CLASS"])}"')

    # ── v5.5b Lean: Session Context Light ────────────────────────
    from scripts.smc_session_context_block import DEFAULTS as _SC_DEFAULTS
    from scripts.smc_session_context_light import DEFAULTS as _SCL_DEFAULTS

    sc = enr.get("session_context") or {}
    scl = enr.get("session_context_light") or {}
    session_context = scl.get("SESSION_CONTEXT", sc.get("SESSION_CONTEXT", _SC_DEFAULTS["SESSION_CONTEXT"]))
    in_killzone = scl.get("IN_KILLZONE", sc.get("IN_KILLZONE", _SC_DEFAULTS["IN_KILLZONE"]))
    session_direction_bias = scl.get("SESSION_DIRECTION_BIAS", sc.get("SESSION_DIRECTION_BIAS", _SC_DEFAULTS["SESSION_DIRECTION_BIAS"]))
    session_context_score = scl.get("SESSION_CONTEXT_SCORE", sc.get("SESSION_CONTEXT_SCORE", _SC_DEFAULTS["SESSION_CONTEXT_SCORE"]))
    content.append("")
    content.append("// ── Session Context Light (v5.5b) ──")
    content.append(f'export const string SESSION_CONTEXT = "{session_context}"')
    content.append(f'export const bool IN_KILLZONE = {_pine_bool(in_killzone)}')
    content.append(f'export const string SESSION_DIRECTION_BIAS = "{session_direction_bias}"')
    content.append(f'export const int SESSION_CONTEXT_SCORE = {int(session_context_score)}')
    content.append(f'export const string SESSION_VOLATILITY_STATE = "{scl.get("SESSION_VOLATILITY_STATE", _SCL_DEFAULTS["SESSION_VOLATILITY_STATE"])}"')

    # ── v5.5b Lean: Order Block Context Light ────────────────────
    from scripts.smc_ob_context_light import DEFAULTS as _OBL_DEFAULTS

    obl = enr.get("ob_context_light") or {}
    content.append("")
    content.append("// ── Order Block Context Light (v5.5b) ──")
    content.append(f'export const string PRIMARY_OB_SIDE = "{obl.get("PRIMARY_OB_SIDE", _OBL_DEFAULTS["PRIMARY_OB_SIDE"])}"')
    content.append(f'export const float PRIMARY_OB_DISTANCE = {_pine_float(obl.get("PRIMARY_OB_DISTANCE", _OBL_DEFAULTS["PRIMARY_OB_DISTANCE"]))}')
    content.append(f'export const bool OB_FRESH = {_pine_bool(obl.get("OB_FRESH", _OBL_DEFAULTS["OB_FRESH"]))}')
    content.append(f'export const int OB_AGE_BARS = {int(obl.get("OB_AGE_BARS", _OBL_DEFAULTS["OB_AGE_BARS"]))}')
    content.append(f'export const string OB_MITIGATION_STATE = "{obl.get("OB_MITIGATION_STATE", _OBL_DEFAULTS["OB_MITIGATION_STATE"])}"')

    # ── v5.5b Lean: FVG / Imbalance Lifecycle Light ──────────────
    from scripts.smc_fvg_lifecycle_light import DEFAULTS as _FVGL_DEFAULTS

    fvgl = enr.get("fvg_lifecycle_light") or {}
    content.append("")
    content.append("// ── FVG / Imbalance Lifecycle Light (v5.5b) ──")
    content.append(f'export const string PRIMARY_FVG_SIDE = "{fvgl.get("PRIMARY_FVG_SIDE", _FVGL_DEFAULTS["PRIMARY_FVG_SIDE"])}"')
    content.append(f'export const float PRIMARY_FVG_DISTANCE = {_pine_float(fvgl.get("PRIMARY_FVG_DISTANCE", _FVGL_DEFAULTS["PRIMARY_FVG_DISTANCE"]))}')
    content.append(f'export const float FVG_FILL_PCT = {_pine_float(fvgl.get("FVG_FILL_PCT", _FVGL_DEFAULTS["FVG_FILL_PCT"]))}')
    content.append(f'export const int FVG_MATURITY_LEVEL = {int(fvgl.get("FVG_MATURITY_LEVEL", _FVGL_DEFAULTS["FVG_MATURITY_LEVEL"]))}')
    content.append(f'export const bool FVG_FRESH = {_pine_bool(fvgl.get("FVG_FRESH", _FVGL_DEFAULTS["FVG_FRESH"]))}')
    content.append(f'export const bool FVG_INVALIDATED = {_pine_bool(fvgl.get("FVG_INVALIDATED", _FVGL_DEFAULTS["FVG_INVALIDATED"]))}')
    content.append(f'export const int FVG_NET_IMBALANCE = {int(fvgl.get("FVG_NET_IMBALANCE", 0))}')

    # ── Imbalance Lifecycle Extended ─────────────────────────────
    from scripts.smc_imbalance_lifecycle import DEFAULTS as _IL_DEFAULTS

    il = enr.get("imbalance_lifecycle") or {}
    content.append("")
    content.append("// ── Imbalance Lifecycle Extended ──")
    content.append(f'export const string BPR_DIRECTION = "{il.get("BPR_DIRECTION", _IL_DEFAULTS["BPR_DIRECTION"])}"')

    # ── Liquidity Pools ──────────────────────────────────────────
    from scripts.smc_liquidity_pools import DEFAULTS as _LP_DEFAULTS

    lp = enr.get("liquidity_pools") or {}
    content.append("")
    content.append("// ── Liquidity Pools ──")
    content.append(f'export const float BUY_SIDE_POOL_LEVEL = {_pine_float(lp.get("BUY_SIDE_POOL_LEVEL", _LP_DEFAULTS["BUY_SIDE_POOL_LEVEL"]))}')
    content.append(f'export const int BUY_SIDE_POOL_STRENGTH = {int(lp.get("BUY_SIDE_POOL_STRENGTH", _LP_DEFAULTS["BUY_SIDE_POOL_STRENGTH"]))}')

    # ── Liquidity Sweeps Extended ─────────────────────────────────
    from scripts.smc_liquidity_sweeps import DEFAULTS as _LS_DEFAULTS

    ls = enr.get("liquidity_sweeps") or {}
    content.append("")
    content.append("// ── Liquidity Sweeps Extended ──")
    content.append(f'export const string LIQUIDITY_TAKEN_DIRECTION = "{ls.get("LIQUIDITY_TAKEN_DIRECTION", _LS_DEFAULTS["LIQUIDITY_TAKEN_DIRECTION"])}"')

    # ── v5.5b Lean: Structure State Light ────────────────────────
    from scripts.smc_structure_state import DEFAULTS as _SS_DEFAULTS
    from scripts.smc_structure_state_light import DEFAULTS as _SSL_DEFAULTS

    ss = enr.get("structure_state") or {}
    ssl = enr.get("structure_state_light") or {}
    content.append("")
    content.append("// ── Structure State Light (v5.5b) ──")
    content.append(f'export const string STRUCTURE_LAST_EVENT = "{ss.get("STRUCTURE_LAST_EVENT", _SS_DEFAULTS["STRUCTURE_LAST_EVENT"])}"')
    content.append(f'export const int STRUCTURE_EVENT_AGE_BARS = {int(ss.get("STRUCTURE_EVENT_AGE_BARS", _SS_DEFAULTS["STRUCTURE_EVENT_AGE_BARS"]))}')
    content.append(f'export const bool STRUCTURE_FRESH = {str(ss.get("STRUCTURE_FRESH", _SS_DEFAULTS["STRUCTURE_FRESH"])).lower()}')
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

    # ── Short Interest (v6) ─────────────────────────────────────
    si = enr.get("short_interest") or {}
    content.append("")
    content.append("// ── Short Interest ──")
    content.append(f'export const string SHORT_SQUEEZE_RISK_TICKERS = "{",".join(si.get("short_squeeze_risk_tickers") or [])}"')
    content.append(f'export const string HIGH_SHORT_INTEREST_TICKERS = "{",".join(si.get("high_short_interest_tickers") or [])}"')
    content.append(f'export const float MARKET_SHORT_INTEREST_AVG = {_pine_float(si.get("market_short_interest_avg") or 0.0)}')
    content.append(f'export const bool SHORT_INTEREST_EXTREME = {_pine_bool(si.get("short_interest_extreme"))}')

    # ── Treasury / Yield Curve (v6) ─────────────────────────────
    tr = enr.get("treasury") or {}
    content.append("")
    content.append("// ── Treasury / Yield Curve ──")
    content.append(f'export const float TREASURY_10Y_YIELD = {_pine_float(tr.get("treasury_10y_yield") or 0.0)}')
    content.append(f'export const float TREASURY_2Y_YIELD = {_pine_float(tr.get("treasury_2y_yield") or 0.0)}')
    content.append(f'export const float YIELD_CURVE_SPREAD = {_pine_float(tr.get("yield_curve_spread") or 0.0)}')
    content.append(f'export const bool YIELD_CURVE_INVERTED = {_pine_bool(tr.get("yield_curve_inverted"))}')

    # ── Sector Rotation (v6) ────────────────────────────────────
    sr = enr.get("sector_rotation") or {}
    content.append("")
    content.append("// ── Sector Rotation ──")
    content.append(f'export const string SECTOR_LEADING = "{",".join(sr.get("sector_leading") or [])}"')
    content.append(f'export const string SECTOR_LAGGING = "{",".join(sr.get("sector_lagging") or [])}"')
    content.append(f'export const string SECTOR_STRONGEST = "{sr.get("sector_strongest") or ""}"')
    content.append(f'export const string SECTOR_WEAKEST = "{sr.get("sector_weakest") or ""}"')

    # ── Institutional Accumulation (v6) ─────────────────────────
    inst = enr.get("institutional") or {}
    content.append("")
    content.append("// ── Institutional Accumulation ──")
    content.append(f'export const string INSTITUTIONAL_ACCUMULATION_TICKERS = "{",".join(inst.get("institutional_accumulation_tickers") or [])}"')
    content.append(f'export const string INSTITUTIONAL_DISTRIBUTION_TICKERS = "{",".join(inst.get("institutional_distribution_tickers") or [])}"')
    content.append(f'export const bool INSTITUTIONAL_DATA_AVAILABLE = {_pine_bool(inst.get("institutional_data_available"))}')

    # ── Analyst Consensus (v6) ──────────────────────────────────
    anl = enr.get("analyst") or {}
    content.append("")
    content.append("// ── Analyst Consensus ──")
    content.append(f'export const string ANALYST_STRONG_BUY_TICKERS = "{",".join(anl.get("analyst_strong_buy_tickers") or [])}"')
    content.append(f'export const string ANALYST_UNDERPERFORM_TICKERS = "{",".join(anl.get("analyst_underperform_tickers") or [])}"')
    content.append(f'export const string ANALYST_HIGH_UPSIDE_TICKERS = "{",".join(anl.get("analyst_high_upside_tickers") or [])}"')

    # ── Insider Transactions (v6) ───────────────────────────────
    ins = enr.get("insider") or {}
    content.append("")
    content.append("// ── Insider Transactions ──")
    content.append(f'export const string INSIDER_BUYING_TICKERS = "{",".join(ins.get("insider_buying_tickers") or [])}"')
    content.append(f'export const string INSIDER_SELLING_HEAVY_TICKERS = "{",".join(ins.get("insider_selling_heavy_tickers") or [])}"')

    # ── Hero State Contract ───────────────────────────────────────
    # HERO_ACTION is the sole Pine action surface. It is projected from
    # Producer-B's HeroAction recommendation by build_hero_state(); the
    # older HERO_ACTION_VERB* reserved exports are intentionally gone.
    from scripts.smc_hero_state import DEFAULTS as _HERO_DEFAULTS

    hs = enr.get("hero_state") or {}
    content.append("")
    content.append("// ── Hero State ──")
    content.append(f'export const string HERO_MARKET_MODE = "{hs.get("HERO_MARKET_MODE", _HERO_DEFAULTS["HERO_MARKET_MODE"])}"')
    content.append(f'export const string HERO_BIAS = "{hs.get("HERO_BIAS", _HERO_DEFAULTS["HERO_BIAS"])}"')
    content.append(f'export const string HERO_TRUST = "{hs.get("HERO_TRUST", _HERO_DEFAULTS["HERO_TRUST"])}"')
    content.append(f'export const string HERO_SETUP_QUALITY = "{hs.get("HERO_SETUP_QUALITY", _HERO_DEFAULTS["HERO_SETUP_QUALITY"])}"')
    content.append(f'export const string HERO_WHY_NOW = "{hs.get("HERO_WHY_NOW", _HERO_DEFAULTS["HERO_WHY_NOW"])}"')
    content.append(f'export const string HERO_RISK = "{hs.get("HERO_RISK", _HERO_DEFAULTS["HERO_RISK"])}"')
    content.append(f'export const string HERO_ACTION = "{hs.get("HERO_ACTION", _HERO_DEFAULTS["HERO_ACTION"])}"')

    # ── Zone Priority (C9) ──────────────────────────────────────
    from scripts.smc_zone_priority import DEFAULTS as _ZP_DEFAULTS

    zp = enr.get("zone_priority") or {}
    content.append("")
    content.append("// ── Zone Priority ──")
    content.append(f'export const string ZONE_PRIORITY_RANK = "{zp.get("ZONE_PRIORITY_RANK", _ZP_DEFAULTS["ZONE_PRIORITY_RANK"])}"')
    content.append(f'export const int ZONE_PRIORITY_SCORE = {int(zp.get("ZONE_PRIORITY_SCORE", _ZP_DEFAULTS["ZONE_PRIORITY_SCORE"]))}')
    content.append(f'export const string ZONE_PRIORITY_TOP_FAMILY = "{zp.get("ZONE_PRIORITY_TOP_FAMILY", _ZP_DEFAULTS["ZONE_PRIORITY_TOP_FAMILY"])}"')
    content.append(f'export const string ZONE_PRIORITY_CATALYST = "{zp.get("ZONE_PRIORITY_CATALYST", _ZP_DEFAULTS["ZONE_PRIORITY_CATALYST"])}"')
    content.append(f'export const string ZONE_PRIORITY_REASON = "{zp.get("ZONE_PRIORITY_REASON", _ZP_DEFAULTS["ZONE_PRIORITY_REASON"])}"')

    # ── Zone Priority Calibration Weights ────────────────────────
    from scripts.smc_zone_priority import _FAMILY_BASE_PRIORITY as _ZP_FALLBACK

    zpc = enr.get("zone_priority_calibration") or {}
    content.append("")
    content.append("// ── Zone Priority Calibration ──")
    for fam in ("OB", "FVG", "BOS", "SWEEP"):
        w = float(zpc.get(fam, _ZP_FALLBACK.get(fam, 0.50)))
        content.append(f"export const float ZONE_CAL_{fam} = {w:.4f}")

    # ── Phase F: Session-adjusted calibration weights ────────────
    zpc_ctx = enr.get("zone_priority_contextual_calibration") or {}
    ctx_weights = zpc_ctx.get("contextual_weights", {})
    content.append("")
    content.append("// ── Contextual Calibration (Phase F) ──")
    # Q3 F1 wiring: the session taxonomy upstream is now ASIA / LONDON /
    # NY_AM (see scripts/smc_zone_priority_calibration.py). The legacy
    # RTH/ETH keys never matched any bucket, so previously every
    # ZONE_CAL_<FAM>_RTH/ETH constant emitted the global fallback. We
    # now emit one constant per actual session bucket so the
    # NY_AM-specific FVG calibration (~0.50 vs ASIA ~0.69, see
    # docs/FVG_LABEL_AUDIT_Q3.md §2) reaches Pine consumers.
    session_buckets = ctx_weights.get("session", {})
    session_keys = sorted(session_buckets.keys()) if session_buckets else ("ASIA", "LONDON", "NY_AM")
    for session in session_keys:
        session_w = session_buckets.get(session, {})
        for fam in ("OB", "FVG", "BOS", "SWEEP"):
            w = float(session_w.get(fam, zpc.get(fam, _ZP_FALLBACK.get(fam, 0.50))))
            content.append(f"export const float ZONE_CAL_{fam}_{session} = {w:.4f}")

    for vol in ("NORMAL", "HIGH_VOL"):
        vol_w = ctx_weights.get("vol_regime", {}).get(vol, {})
        for fam in ("OB", "FVG", "BOS", "SWEEP"):
            w = float(vol_w.get(fam, zpc.get(fam, _ZP_FALLBACK.get(fam, 0.50))))
            content.append(f"export const float ZONE_CAL_{fam}_{vol} = {w:.4f}")

    # ── Phase H: Pine Consumer Maturity ──────────────────────────
    # Confidence + per-family hit rates + trend, derived from the
    # already-loaded calibration JSON plus optional inputs:
    #   enr["zone_priority_calibration_meta"]["smooth_ece"] (F3)
    #   enr["zone_priority_calibration_meta"]["total_events"] (F1)
    #   enr["zone_priority_calibration_meta"]["family_stats"] (F1)
    #   enr["zone_priority_calibration_history"] (H3 trend)
    # Falls back to neutral DEFAULTS when any source is missing — the
    # Pine consumer always sees a renderable value.
    from scripts.smc_zone_priority_consumer import (
        DEFAULTS as _ZH_DEFAULTS,
    )
    from scripts.smc_zone_priority_consumer import (
        FAMILIES as _ZH_FAMILIES,
    )
    from scripts.smc_zone_priority_consumer import (
        HR_SENTINEL_DEGRADED as _ZH_HR_SENTINEL,
    )
    from scripts.smc_zone_priority_consumer import (
        build_consumer_exports,
    )

    zpc_meta = enr.get("zone_priority_calibration_meta") or {}
    consumer = build_consumer_exports(
        family_stats=zpc_meta.get("family_stats"),
        total_events=zpc_meta.get("total_events"),
        smooth_ece=zpc_meta.get("smooth_ece"),
        history=enr.get("zone_priority_calibration_history"),
    )
    content.append("")
    content.append("// ── Pine Consumer Maturity (Phase H) ──")
    # F-3 (Boundary-Contract Plan 2026-04-23): export the HR sentinel
    # as a first-class Pine library constant so consumers can assert
    # ``mp.ZONE_HR_FVG == mp.HR_SENTINEL_DEGRADED`` instead of
    # hardcoding ``-1.0``. Emitted additively — Pine consumers must
    # opt-in by importing the new symbol (library_field_version
    # ``v5.5b`` → ``v5.5c``). The sentinel is distinct from the ``0.0``
    # neutral-default: ``0.0`` means "no calibration data yet",
    # ``HR_SENTINEL_DEGRADED`` (-1.0) means "suppressed due to
    # sub-saturation corpus" (see ADR 2026-04-22).
    content.append(
        f"export const float HR_SENTINEL_DEGRADED = {_ZH_HR_SENTINEL:.4f}"
    )
    content.append(
        f"export const float ZONE_CAL_CONFIDENCE = "
        f"{_pine_float(consumer.get('ZONE_CAL_CONFIDENCE', _ZH_DEFAULTS['ZONE_CAL_CONFIDENCE'])):.4f}"
    )
    for fam in _ZH_FAMILIES:
        key = f"ZONE_HR_{fam}"
        content.append(
            f"export const float {key} = "
            f"{_pine_float(consumer.get(key, _ZH_DEFAULTS[key])):.4f}"
        )
    content.append(
        f'export const string ZONE_CAL_TREND = '
        f'"{consumer.get("ZONE_CAL_TREND", _ZH_DEFAULTS["ZONE_CAL_TREND"])}"'
    )
    # WS2 trust scaffold (ADR 2026-04-22): degraded corpora suppress
    # per-family HR display in Pine via the -1.0 sentinel; this scalar
    # carries the trust classification for dashboards / alerts.
    content.append(
        f'export const string ZONE_CAL_TRUST = '
        f'"{consumer.get("ZONE_CAL_TRUST", _ZH_DEFAULTS["ZONE_CAL_TRUST"])}"'
    )

    atomic_write_text("\n".join(content).rstrip() + "\n", path)


def render_output_path(root: Path, template: str, asof_date: str) -> Path:
    return root / template.format(asof_date=asof_date)


def write_lists_csv(path: Path, state: pd.DataFrame, asof_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    active = _filtered_records_frame(
        state,
        predicate=lambda record: _safe_bool(record.get("is_active")),
        columns=["symbol", "list_name", "active_since", "last_score", "decision_source", "decision_reason"],
    )
    rows = active.to_dict("records")
    rows.sort(key=lambda record: (str(record.get("list_name", "")), str(record.get("symbol", ""))))
    active = pd.DataFrame(rows, columns=["symbol", "list_name", "active_since", "last_score", "decision_source", "decision_reason"])
    active.insert(0, "asof_date", asof_date)
    atomic_write_csv(active, path, index=False)


def write_diff_report(path: Path, previous_state: pd.DataFrame, new_state: pd.DataFrame, asof_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def active_map(frame: pd.DataFrame) -> dict[str, dict[str, dict[str, str]]]:
        mapping: dict[str, dict[str, dict[str, str]]] = {name: {} for name in LISTS}
        if frame.empty:
            return mapping
        active = _filtered_records_frame(
            frame,
            predicate=lambda record: _safe_bool(record.get("is_active")),
            columns=["symbol", "list_name", "decision_source", "decision_reason"],
        )
        for list_name, group in _iter_group_frames(active, "list_name"):
            mapping[str(list_name)] = {
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
    atomic_write_text("\n".join(lines).rstrip() + "\n", path)


def write_core_import_snippet(path: Path, *, library_owner: str, library_name: str, library_version: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    import_path = f"{library_owner}/{library_name}/{library_version}"
    content = [
        "// Core import snippet — microstructure list bindings only.",
        "// For regime, news, calendar, layering, and event-risk (v5) fields,",
        "// read mp.FIELD_NAME directly from the library. See the full field",
        "// inventory in the library header comment.",
        f"import {import_path} as mp",
        "string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS",
        "string stop_hunt_tickers_effective = mp.STOP_HUNT_PRONE_TICKERS",
        "string midday_dead_tickers_effective = mp.MIDDAY_DEAD_TICKERS",
        "string rth_only_tickers_effective = mp.RTH_ONLY_TICKERS",
        "string weak_premarket_tickers_effective = mp.WEAK_PREMARKET_TICKERS",
        "string weak_afterhours_tickers_effective = mp.WEAK_AFTERHOURS_TICKERS",
        "string fast_decay_tickers_effective = mp.FAST_DECAY_TICKERS",
    ]
    atomic_write_text("\n".join(content) + "\n", path)
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
    atomic_write_text("\n".join(lines).rstrip() + "\n", path)


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
            logger.warning(
                "Failed to read previous manifest schema_version from %s",
                path,
                exc_info=True,
            )

    change_type = classify_version_change(prev_schema, SCHEMA_VERSION).value if prev_schema else "initial"

    def _rel(p: Path) -> str:
        if relative_to is not None:
            try:
                return p.resolve().relative_to(relative_to.resolve()).as_posix()
            except ValueError:
                pass
        return p.as_posix()

    normalized_input_path = _rel(input_path).replace("\\", "/")
    event_risk_source = "smc_event_risk_builder" if (normalized_enrichment or {}).get("event_risk") else "defaults"
    fixture_input_detected = "/tests/fixtures/" in f"/{normalized_input_path.strip('/')}"
    placeholder_symbols = sorted(
        {
            symbol
            for symbols in lists.values()
            for symbol in symbols
            if symbol in PLACEHOLDER_SYMBOL_SENTINELS
        }
    )
    blocking_reasons: list[str] = []
    if fixture_input_detected:
        blocking_reasons.append("fixture_input")
    if event_risk_source == "defaults":
        blocking_reasons.append("default_event_risk")
    if fixture_input_detected and placeholder_symbols:
        blocking_reasons.append("placeholder_symbols")

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
        "input_path": normalized_input_path,
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
        "library_field_version": "v8.0a",
        "deprecated_field_policy": {
            "mode": "compatibility_only",
            "preferred_field_version": "v8.0a",
            "extension_allowed": False,
            "deprecated_groups": DEPRECATED_COMPATIBILITY_GROUPS,
        },
        "v55_lean_blocks": [
            "event_risk_light",
            "session_context_light",
            "ob_context_light",
            "fvg_lifecycle_light",
            "structure_state_light",
            "signal_quality",
        ],
        "event_risk_source": event_risk_source,
        "productivity_gate": {
            "publish_ready": len(blocking_reasons) == 0,
            "blocking_reasons": blocking_reasons,
            "fixture_input_detected": fixture_input_detected,
            "default_event_risk_detected": event_risk_source == "defaults",
            "placeholder_symbols": placeholder_symbols,
        },
        "auto_commit_allowed": change_type in ("unchanged", "patch", "minor", "initial"),
        "asof_time": ((normalized_enrichment or {}).get("meta") or {}).get("asof_time", ""),
        "refresh_count": int(((normalized_enrichment or {}).get("meta") or {}).get("refresh_count", 0)),
    }
    atomic_write_text(json.dumps(payload, indent=2) + "\n", path)


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
    # F-V4-A1b: configure root logging so logger.info / logging.* calls actually
    # surface on stdout when this script is invoked from a GitHub Actions workflow.
    # Without this, the pipeline runs silently and runner-side eviction or
    # mid-pipeline errors are impossible to triage. Also flush eagerly so partial
    # logs survive runner shutdown signals. Self-contained imports to avoid
    # disturbing module-level import order.
    import logging as _v4a1b_logging
    import sys as _v4a1b_sys
    import time as _v4a1b_time
    _v4a1b_logging.basicConfig(
        level=_v4a1b_logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        stream=_v4a1b_sys.stdout,
        force=True,
    )
    _v4a1b_logging.Formatter.converter = _v4a1b_time.gmtime
    try:
        _v4a1b_sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        _v4a1b_sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


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
