from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time as time_module
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env before argparse defaults are resolved (they call os.getenv).
from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

from scripts.generate_smc_micro_profiles import load_schema
from scripts.smc_atomic_write import atomic_write_csv, atomic_write_text
from scripts.smc_enrichment_types import EnrichmentDict
from scripts.smc_library_layering import compute_library_layering
from scripts.smc_live_news_bus import DEFAULT_SYMBOL_LIMIT, export_live_news_snapshot, resolve_live_news_symbols
from scripts.smc_microstructure_base_runtime import (
    ETF_KEYWORDS,
    MappingStatus,
    generate_base_from_bundle,
    generate_pine_library_from_base,
    infer_asset_type,
    infer_universe_bucket,
    run_databento_base_scan_pipeline,
)
from scripts.smc_news_scorer import compute_news_sentiment

# Re-exported for legacy callers / pin tests:
__all__ = ["ETF_KEYWORDS"]

logger = logging.getLogger(__name__)

_VOLATILITY_PROXY_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ", "IWM", "DIA")


def _emit_cli_progress(message: str) -> None:
    print(message, flush=True)


DERIVED_FIELD_NOTES = {
    "asset_type": "Derived heuristically from company_name ETF/fund keywords; defaults to stock when no ETF marker is present.",
    "universe_bucket": "Derived from asset_type plus market_cap bands: ETF -> us_etf, else large/mid/small-cap buckets.",
    "history_coverage_days_20d": "Derived as trailing daily_bars row count up to the selected asof_date, capped at 20 sessions.",
    "adv_dollar_rth_20d": "Derived as mean(close * volume) over trailing daily_bars rows up to the selected asof_date, capped at 20 sessions.",
}


def load_workbook_frames(path: Path) -> dict[str, pd.DataFrame]:
    workbook = pd.ExcelFile(path)
    frames: dict[str, pd.DataFrame] = {}
    for sheet_name in workbook.sheet_names:
        frames[sheet_name] = workbook.parse(sheet_name)
    return frames


def choose_asof_date(summary: pd.DataFrame, asof_date: str | None = None) -> str:
    trade_dates = pd.to_datetime(summary["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if asof_date is not None:
        if asof_date not in set(trade_dates.dropna()):
            raise ValueError(f"Requested asof_date {asof_date} is not present in the workbook")
        return asof_date
    latest = trade_dates.dropna().max()
    if not latest:
        raise ValueError("Workbook summary sheet does not contain a valid trade_date")
    return str(latest)


def build_trailing_daily_metrics(daily_bars: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    frame = daily_bars.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame = frame.loc[frame["trade_date"] <= pd.Timestamp(asof_date)].copy()
    frame = frame.sort_values(["symbol", "trade_date"])
    frame["dollar_volume"] = pd.to_numeric(frame["close"], errors="coerce") * pd.to_numeric(frame["volume"], errors="coerce")
    trailing = frame.groupby("symbol", group_keys=False).tail(20)
    metrics = (
        trailing.groupby("symbol", dropna=False)
        .agg(
            history_coverage_days_20d=("trade_date", "nunique"),
            adv_dollar_rth_20d=("dollar_volume", "mean"),
        )
        .reset_index()
    )
    metrics["history_coverage_days_20d"] = metrics["history_coverage_days_20d"].fillna(0).astype(int)
    return metrics


def build_mapping_statuses(required_columns: list[str]) -> list[MappingStatus]:
    direct = {
        "asof_date": MappingStatus("asof_date", "direct", "summary", ["trade_date"], "Latest trade_date snapshot selected from workbook summary."),
        "symbol": MappingStatus("symbol", "direct", "summary", ["symbol"], "Copied from workbook summary."),
        "exchange": MappingStatus("exchange", "direct", "summary", ["exchange"], "Copied from workbook summary."),
    }
    derived = {
        name: MappingStatus(name, "derived", "summary,daily_bars", [], DERIVED_FIELD_NOTES[name])
        for name in DERIVED_FIELD_NOTES
    }
    statuses: list[MappingStatus] = []
    for field in required_columns:
        if field in direct:
            statuses.append(direct[field])
        elif field in derived:
            statuses.append(derived[field])
        else:
            statuses.append(
                MappingStatus(
                    field,
                    "missing",
                    "",
                    [],
                    "Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.",
                )
            )
    return statuses


def build_base_snapshot_from_workbook(
    workbook_path: Path,
    *,
    schema_path: Path,
    asof_date: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    schema = load_schema(schema_path)
    frames = load_workbook_frames(workbook_path)
    if "summary" not in frames or "daily_bars" not in frames:
        raise ValueError("Workbook must contain summary and daily_bars sheets")

    summary = frames["summary"].copy()
    summary["trade_date"] = pd.to_datetime(summary["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    selected_asof_date = choose_asof_date(summary, asof_date=asof_date)
    latest = summary.loc[summary["trade_date"] == selected_asof_date].copy()
    latest = latest.sort_values(["symbol", "rank"]).drop_duplicates(subset=["symbol"], keep="first")

    daily_metrics = build_trailing_daily_metrics(frames["daily_bars"], selected_asof_date)
    snapshot = latest.merge(daily_metrics, on="symbol", how="left")

    snapshot["asof_date"] = selected_asof_date
    snapshot["asset_type"] = snapshot["company_name"].map(infer_asset_type)
    snapshot["universe_bucket"] = [
        infer_universe_bucket(asset_type, market_cap)
        for asset_type, market_cap in zip(snapshot["asset_type"], snapshot.get("market_cap", pd.Series(dtype=float)), strict=False)
    ]

    required_columns = [str(column) for column in schema["required_columns"]]
    output = pd.DataFrame(index=snapshot.index)
    output["asof_date"] = snapshot["asof_date"]
    output["symbol"] = snapshot["symbol"].astype(str).str.upper()
    output["exchange"] = snapshot["exchange"].astype(str).str.upper()
    output["asset_type"] = snapshot["asset_type"]
    output["universe_bucket"] = snapshot["universe_bucket"]
    output["history_coverage_days_20d"] = snapshot["history_coverage_days_20d"].fillna(0).astype(int)
    output["adv_dollar_rth_20d"] = pd.to_numeric(snapshot["adv_dollar_rth_20d"], errors="coerce")

    for column in required_columns:
        if column not in output.columns:
            output[column] = pd.NA
    output = output[required_columns].sort_values(["symbol"]).reset_index(drop=True)

    statuses = build_mapping_statuses(required_columns)
    missing_fields = [status.field for status in statuses if status.status == "missing"]
    derived_fields = [status.field for status in statuses if status.status == "derived"]
    payload = {
        "workbook_path": str(workbook_path),
        "asof_date": selected_asof_date,
        "row_count": len(output),
        "direct_fields": [status.field for status in statuses if status.status == "direct"],
        "derived_fields": derived_fields,
        "missing_fields": missing_fields,
        "mapping_status": [
            {
                "field": status.field,
                "status": status.status,
                "source_sheet": status.source_sheet,
                "source_columns": status.source_columns,
                "note": status.note,
            }
            for status in statuses
        ],
    }
    return output, payload


def write_mapping_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def md_row(*cells: str) -> str:
        return "|" + "|".join(cells) + "|"

    lines = [
        f"# Databento Workbook To Microstructure Base Mapping: {Path(payload['workbook_path']).name}",
        "",
        f"- Workbook: {payload['workbook_path']}",
        f"- Selected asof_date: {payload['asof_date']}",
        f"- Output rows: {payload['row_count']}",
        f"- Direct fields: {len(payload['direct_fields'])}",
        f"- Derived fields: {len(payload['derived_fields'])}",
        f"- Missing fields: {len(payload['missing_fields'])}",
        "",
        md_row("Contract field", "Status", "Source sheet", "Source columns", "Note"),
        md_row("---", "---", "---", "---", "---"),
    ]
    for status in payload["mapping_status"]:
        source_columns = ", ".join(status["source_columns"]) if status["source_columns"] else ""
        lines.append(md_row(status["field"], status["status"], status["source_sheet"], source_columns, status["note"]))
    atomic_write_text("\n".join(lines).rstrip() + "\n", path)


def build_default_output_paths(workbook_path: Path, asof_date: str) -> tuple[Path, Path, Path]:
    stem = workbook_path.stem
    base_csv = Path("data/input") / f"{stem}_microstructure_base_{asof_date}.csv"
    report_md = Path("reports") / f"{stem}_microstructure_mapping_{asof_date}.md"
    report_json = Path("reports") / f"{stem}_microstructure_mapping_{asof_date}.json"
    return base_csv, report_md, report_json


# ── FMP enrichment helpers ──────────────────────────────────────────

def _make_fmp_client(api_key: str) -> Any:
    """Create a standalone FMP client for the v4 enrichment pipeline.

    Uses ``scripts.smc_fmp_client.SMCFMPClient`` — no ``open_prep``
    dependency at runtime.
    """
    from scripts.smc_fmp_client import SMCFMPClient
    return SMCFMPClient(api_key=api_key, retry_attempts=2, timeout_seconds=12)


def _derive_volume_regime(
    base_snapshot: pd.DataFrame | None,
    adv_threshold: float = 5_000_000,
) -> dict[str, Any]:
    """Derive volume-regime tickers from base snapshot data.

    * **low_tickers**: symbols whose ``adv_dollar_rth_20d`` is below
      *adv_threshold* (schema eligibility floor).
    * **holiday_suspect_tickers**: symbols whose ``adv_dollar_rth_20d``
      is below 20 % of the universe median — a heuristic that flags
      unusually thin trading days (holidays, half-days).
    """
    if base_snapshot is None or base_snapshot.empty:
        return {"low_tickers": [], "holiday_suspect_tickers": []}
    if "adv_dollar_rth_20d" not in base_snapshot.columns:
        return {"low_tickers": [], "holiday_suspect_tickers": []}
    adv = pd.to_numeric(base_snapshot["adv_dollar_rth_20d"], errors="coerce")
    syms = base_snapshot["symbol"].astype(str).str.upper()
    low = sorted(syms[adv < adv_threshold].dropna().tolist())
    median_adv = adv.median()
    holiday = sorted(syms[adv < 0.2 * median_adv].dropna().tolist()) if pd.notna(median_adv) and median_adv > 0 else []
    return {"low_tickers": low, "holiday_suspect_tickers": holiday}


def _read_previous_refresh_count(manifest_path: Path | None) -> int:
    """Read refresh_count from a previously-written manifest, or 0."""
    if manifest_path is None or not manifest_path.exists():
        return 0
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return int(data.get("refresh_count", 0))
    except Exception:
        return 0


def _coerce_non_negative_float(value: Any) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _safe_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return float(numeric)


def _select_volatility_proxy_symbol(
    *,
    daily_bars: pd.DataFrame | None,
    base_snapshot: pd.DataFrame | None,
) -> tuple[str, str]:
    if not isinstance(daily_bars, pd.DataFrame) or daily_bars.empty or "symbol" not in daily_bars.columns:
        return "", "none"

    available_symbols = {
        str(symbol).strip().upper()
        for symbol in daily_bars["symbol"].dropna().astype(str).tolist()
        if str(symbol).strip()
    }
    for symbol in _VOLATILITY_PROXY_SYMBOLS:
        if symbol in available_symbols:
            return symbol, "preferred_benchmark"

    if base_snapshot is not None and not base_snapshot.empty and {"symbol", "adv_dollar_rth_20d"}.issubset(base_snapshot.columns):
        ranked = base_snapshot.copy()
        ranked["symbol"] = ranked["symbol"].astype(str).str.strip().str.upper()
        ranked = ranked.loc[ranked["symbol"].isin(available_symbols)].copy()
        ranked["adv_dollar_rth_20d"] = pd.to_numeric(ranked["adv_dollar_rth_20d"], errors="coerce")
        ranked = ranked.sort_values("adv_dollar_rth_20d", ascending=False)
        if not ranked.empty:
            return str(ranked.iloc[0]["symbol"]), "highest_adv_symbol"

    return sorted(available_symbols)[0], "first_available_symbol"


def _select_daily_bars_for_volatility(
    *,
    daily_bars: pd.DataFrame | None,
    symbol: str,
) -> pd.DataFrame:
    if not isinstance(daily_bars, pd.DataFrame) or daily_bars.empty or not symbol:
        return pd.DataFrame(columns=["high", "low", "close"])
    if not {"high", "low", "close"}.issubset(daily_bars.columns):
        return pd.DataFrame(columns=["high", "low", "close"])

    frame = daily_bars.copy()
    if "symbol" in frame.columns:
        frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
        frame = frame.loc[frame["symbol"].eq(symbol.strip().upper())].copy()
    sort_column = next((name for name in ("trade_date", "date", "timestamp") if name in frame.columns), None)
    if sort_column is not None:
        frame = frame.sort_values(sort_column)
    return frame


def _build_volatility_regime_block(
    *,
    daily_bars: pd.DataFrame | None,
    base_snapshot: pd.DataFrame | None,
) -> dict[str, Any] | None:
    if not isinstance(daily_bars, pd.DataFrame) or daily_bars.empty:
        return None

    from smc_core.vol_regime import compute_vol_regime

    proxy_symbol, proxy_source = _select_volatility_proxy_symbol(
        daily_bars=daily_bars,
        base_snapshot=base_snapshot,
    )
    if not proxy_symbol:
        return None

    proxy_bars = _select_daily_bars_for_volatility(
        daily_bars=daily_bars,
        symbol=proxy_symbol,
    )
    if proxy_bars.empty:
        return None

    result = compute_vol_regime(proxy_bars)
    return {
        "label": result.label,
        "confidence": float(result.confidence),
        "raw_atr_ratio": float(result.raw_atr_ratio),
        "model_source": result.model_source,
        "fallback_reason": str(result.fallback_reason or ""),
        "proxy_symbol": proxy_symbol,
        "proxy_source": proxy_source,
    }


def _macro_bias_direction(macro_bias: float) -> str:
    if macro_bias > 0.05:
        return "BULLISH"
    if macro_bias < -0.05:
        return "BEARISH"
    return "NEUTRAL"


def _build_ensemble_quality_block(
    *,
    regime_result: dict[str, Any],
    layering: dict[str, Any] | None,
    volatility_regime: dict[str, Any] | None,
) -> dict[str, Any]:
    from smc_core.ensemble_quality import build_ensemble_quality

    macro_bias = _safe_float(regime_result.get("macro_bias")) or 0.0
    heuristic_quality = _safe_float((layering or {}).get("global_strength"))
    result = build_ensemble_quality(
        heuristic_quality=heuristic_quality if heuristic_quality is not None else 0.5,
        bias_direction=_macro_bias_direction(macro_bias),
        bias_confidence=min(abs(macro_bias), 1.0),
        vol_regime_label=str((volatility_regime or {}).get("label") or ""),
        vol_regime_confidence=_safe_float((volatility_regime or {}).get("confidence")),
    )
    return {
        "score": float(result.score),
        "tier": str(result.tier),
        "available_components": list(result.available_components),
    }


def _load_newsapi_feed_state(path: Path | None) -> dict[str, Any]:
    state = {"last_seen_epoch": 0.0, "last_seen_news_uri": ""}
    if path is None or not path.exists():
        return state
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read NewsAPI.ai feed state: %s", path, exc_info=True)
        return state
    if not isinstance(payload, dict):
        return state
    state["last_seen_epoch"] = _coerce_non_negative_float(payload.get("last_seen_epoch"))
    state["last_seen_news_uri"] = str(payload.get("last_seen_news_uri") or "").strip()
    return state


def _save_newsapi_feed_state(
    path: Path | None,
    *,
    last_seen_epoch: float,
    last_seen_news_uri: str,
) -> None:
    if path is None:
        return
    payload = {
        "last_seen_epoch": _coerce_non_negative_float(last_seen_epoch),
        "last_seen_news_uri": str(last_seen_news_uri or "").strip(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(payload, indent=2) + "\n", path)


def _load_live_news_snapshot(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return None
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read live news snapshot: %s", snapshot_path, exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def _parse_ticker_heat_map(raw_value: Any) -> dict[str, float]:
    score_map: dict[str, float] = {}
    for part in str(raw_value or "").split(","):
        item = part.strip()
        if not item:
            continue
        ticker, separator, raw_score = item.partition(":")
        if not separator:
            continue
        symbol = str(ticker).strip().upper()
        if not symbol:
            continue
        try:
            score_map[symbol] = float(raw_score)
        except (TypeError, ValueError):
            continue
    return score_map


def _build_news_payload_from_score_map(score_map: dict[str, float]) -> dict[str, Any]:
    bullish = sorted(symbol for symbol, score in score_map.items() if score > 0.1)
    bearish = sorted(symbol for symbol, score in score_map.items() if score < -0.1)
    neutral = sorted(
        symbol for symbol, score in score_map.items() if -0.1 <= score <= 0.1
    )
    news_heat_global = round(sum(score_map.values()) / len(score_map), 4) if score_map else 0.0
    ticker_heat_map = ",".join(
        f"{symbol}:{score_map[symbol]:.2f}" for symbol in sorted(score_map)
    )
    return {
        "bullish_tickers": bullish,
        "bearish_tickers": bearish,
        "neutral_tickers": neutral,
        "news_heat_global": news_heat_global,
        "ticker_heat_map": ticker_heat_map,
    }


def _news_payload_has_mentions(payload: dict[str, Any]) -> bool:
    if str(payload.get("ticker_heat_map") or "").strip():
        return True
    return any(bool(payload.get(key)) for key in ("bullish_tickers", "bearish_tickers", "neutral_tickers"))


def _summarize_news_payload(payload: dict[str, Any]) -> dict[str, Any]:
    bullish = [str(symbol).strip().upper() for symbol in list(payload.get("bullish_tickers") or []) if str(symbol).strip()]
    bearish = [str(symbol).strip().upper() for symbol in list(payload.get("bearish_tickers") or []) if str(symbol).strip()]
    neutral = [str(symbol).strip().upper() for symbol in list(payload.get("neutral_tickers") or []) if str(symbol).strip()]
    score_map = _parse_ticker_heat_map(payload.get("ticker_heat_map"))
    symbols = set(score_map)
    symbols.update(bullish)
    symbols.update(bearish)
    symbols.update(neutral)
    return {
        "news_heat_global": float(payload.get("news_heat_global") or 0.0),
        "symbol_count": len(symbols),
        "bullish_ticker_count": len(bullish),
        "bearish_ticker_count": len(bearish),
        "neutral_ticker_count": len(neutral),
    }


def _score_live_news_snapshot(
    *,
    symbols: list[str],
    live_news_snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    raw_stories = live_news_snapshot.get("stories")
    if not isinstance(raw_stories, list):
        return None

    articles: list[dict[str, Any]] = []
    for story in raw_stories:
        if not isinstance(story, dict):
            continue
        tickers = [
            str(raw_symbol).strip().upper()
            for raw_symbol in list(story.get("tickers") or [])
            if str(raw_symbol).strip()
        ]
        articles.append(
            {
                "headline": str(story.get("headline") or "").strip(),
                "tickers": tickers,
            }
        )

    scored = compute_news_sentiment(symbols, articles, include_diagnostics=True)
    diagnostics = dict(scored.pop("diagnostics", {}))
    raw_summary = live_news_snapshot.get("summary")
    summary = raw_summary if isinstance(raw_summary, dict) else {}
    raw_provider_payloads = live_news_snapshot.get("providers")
    provider_payloads = raw_provider_payloads if isinstance(raw_provider_payloads, dict) else {}
    diagnostics.update(
        {
            "snapshot_story_count": len(raw_stories),
            "snapshot_active_story_count": int(summary.get("active_story_count") or 0),
            "snapshot_actionable_story_count": int(summary.get("actionable_story_count") or 0),
            "snapshot_actionable_symbol_count": len(list(summary.get("actionable_symbols") or [])),
            "snapshot_symbol_count": int(summary.get("symbol_count") or 0),
            "providers_with_new_items": sorted(
                provider_name
                for provider_name, payload in provider_payloads.items()
                if isinstance(payload, dict) and int(payload.get("new_item_count") or 0) > 0
            ),
        }
    )
    return scored, diagnostics


def _merge_news_payloads(
    *,
    base_payload: dict[str, Any],
    live_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_scores = _parse_ticker_heat_map(base_payload.get("ticker_heat_map"))
    live_scores = _parse_ticker_heat_map(live_payload.get("ticker_heat_map"))
    merged_scores = dict(base_scores)

    live_added_symbols: list[str] = []
    live_directional_override_symbols: list[str] = []
    live_neutral_preserved_base_symbols: list[str] = []

    for symbol, live_score in live_scores.items():
        if symbol not in merged_scores:
            merged_scores[symbol] = live_score
            live_added_symbols.append(symbol)
            continue

        base_score = merged_scores[symbol]
        live_is_directional = abs(live_score) > 0.1
        base_is_directional = abs(base_score) > 0.1
        if live_is_directional or not base_is_directional:
            if live_score != base_score and live_is_directional:
                live_directional_override_symbols.append(symbol)
            merged_scores[symbol] = live_score
            continue

        live_neutral_preserved_base_symbols.append(symbol)

    merged_payload = _build_news_payload_from_score_map(merged_scores)
    diagnostics = {
        "base_symbol_count": len(base_scores),
        "live_symbol_count": len(live_scores),
        "merged_symbol_count": len(merged_scores),
        "live_added_count": len(live_added_symbols),
        "live_directional_override_count": len(live_directional_override_symbols),
        "live_neutral_preserved_base_count": len(live_neutral_preserved_base_symbols),
        "live_added_sample": sorted(live_added_symbols)[:10],
        "live_directional_override_sample": sorted(live_directional_override_symbols)[:10],
        "live_neutral_preserved_base_sample": sorted(live_neutral_preserved_base_symbols)[:10],
        "base_news_heat_global": float(base_payload.get("news_heat_global") or 0.0),
        "live_news_heat_global": float(live_payload.get("news_heat_global") or 0.0),
        "merged_news_heat_global": float(merged_payload.get("news_heat_global") or 0.0),
    }
    return merged_payload, diagnostics


def _provider_status_from_result(result: Any) -> tuple[str, str]:
    provider_status = str(result.meta.get("provider_status") or ("ok" if result.ok else "no_data")).strip()
    if not provider_status:
        provider_status = "ok" if result.ok else "no_data"
    status_detail = str(result.meta.get("status_detail") or "").strip()
    if not status_detail and not result.ok:
        status_detail = "All configured providers in the chain failed."
    return provider_status, status_detail


def _normalize_provider_attempts(raw_attempts: Any) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    if not isinstance(raw_attempts, list):
        return attempts
    for item in raw_attempts:
        if not isinstance(item, dict):
            continue
        row = {
            "provider": str(item.get("provider") or "").strip(),
            "delivered_provider": str(item.get("delivered_provider") or item.get("provider") or "").strip(),
            "outcome": str(item.get("outcome") or "").strip(),
            "provider_status": str(item.get("provider_status") or "").strip(),
            "status_detail": str(item.get("status_detail") or "").strip(),
        }
        if str(item.get("failure_class") or "").strip():
            row["failure_class"] = str(item.get("failure_class") or "").strip()
        if str(item.get("error_type") or "").strip():
            row["error_type"] = str(item.get("error_type") or "").strip()
        for key in (
            "last_seen_epoch",
            "last_seen_news_uri",
            "raw_record_count",
            "matched_record_count",
            "cursor_before_epoch",
            "cursor_before_uri",
        ):
            if key in item:
                row[key] = item[key]
        attempts.append(row)
    return attempts


def _build_domain_diagnostic(
    domain: str,
    result: Any,
    *,
    cursor_before: dict[str, Any] | None = None,
    cursor_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_status, status_detail = _provider_status_from_result(result)
    diagnostic: dict[str, Any] = {
        "domain": domain,
        "ok": bool(result.ok),
        "selected_provider": str(result.provider or "none").strip() or "none",
        "provider_status": provider_status,
        "status_detail": status_detail,
        "stale_providers": [str(provider) for provider in result.stale if str(provider).strip()],
        "attempts": _normalize_provider_attempts(result.meta.get("attempts")),
    }
    if cursor_before is not None or cursor_after is not None:
        diagnostic["cursor"] = {
            "before": dict(cursor_before or {}),
            "after": dict(cursor_after or {}),
        }
    raw_diagnostics = result.meta.get("diagnostics")
    if isinstance(raw_diagnostics, dict):
        diagnostic["diagnostics"] = dict(raw_diagnostics)
    return diagnostic


def _build_library_provider_diagnostics_report(
    *,
    enrichment: EnrichmentDict | None,
    symbols_count: int,
) -> dict[str, Any]:
    providers = (enrichment or {}).get("providers") or {}
    raw_domain_diagnostics = providers.get("domain_diagnostics") if isinstance(providers, dict) else {}

    domain_results: list[dict[str, Any]] = []
    if isinstance(raw_domain_diagnostics, dict):
        for domain_name in sorted(raw_domain_diagnostics):
            payload = raw_domain_diagnostics.get(domain_name)
            if not isinstance(payload, dict):
                continue
            row = dict(payload)
            row["domain"] = str(domain_name)
            domain_results.append(row)

    stale_providers = [
        provider
        for provider in str(providers.get("stale_providers") or "").split(",")
        if provider
    ]
    overall_status = "warn" if stale_providers else "ok"
    if any(str(row.get("provider_status") or "").strip() not in {"", "ok"} for row in domain_results):
        overall_status = "warn"

    failure_reasons: list[dict[str, str]] = []
    for row in domain_results:
        status = str(row.get("provider_status") or "").strip()
        if status in {"", "ok"}:
            continue
        domain = str(row.get("domain") or "unknown").strip() or "unknown"
        selected_provider = str(row.get("selected_provider") or "none").strip() or "none"
        failure_reasons.append(
            {
                "domain": domain,
                "provider": selected_provider,
                "code": f"LIBRARY_{domain.upper()}_{status.upper()}",
                "detail": str(row.get("status_detail") or "").strip(),
            }
        )

    return {
        "report_kind": "library_provider_diagnostics",
        "overall_status": overall_status,
        "generated_at": time_module.time(),
        "symbols_count": int(symbols_count),
        "provider_count": int(providers.get("provider_count") or 0),
        "stale_providers": stale_providers,
        "provider_domain_results": domain_results,
        "failure_reasons": failure_reasons,
    }


def _write_library_provider_diagnostics_report(
    path: Path,
    *,
    enrichment: EnrichmentDict | None,
    symbols_count: int,
) -> dict[str, Any]:
    payload = _build_library_provider_diagnostics_report(
        enrichment=enrichment,
        symbols_count=symbols_count,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(payload, indent=2) + "\n", path)
    return payload


def build_enrichment(
    *,
    fmp_api_key: str,
    symbols: list[str],
    benzinga_api_key: str = "",
    newsapi_ai_key: str = "",
    enrich_regime: bool = False,
    enrich_news: bool = False,
    enrich_calendar: bool = False,
    enrich_layering: bool = False,
    enrich_event_risk: bool = False,
    enrich_flow_qualifier: bool = False,
    enrich_compression_regime: bool = False,
    enrich_zone_intelligence: bool = False,
    enrich_reversal_context: bool = False,
    enrich_session_context: bool = False,
    enrich_liquidity_sweeps: bool = False,
    enrich_liquidity_pools: bool = False,
    enrich_order_blocks: bool = False,
    enrich_zone_projection: bool = False,
    enrich_zone_priority: bool = False,
    enrich_profile_context: bool = False,
    enrich_structure_state: bool = False,
    enrich_imbalance_lifecycle: bool = False,
    enrich_session_structure: bool = False,
    enrich_range_regime: bool = False,
    enrich_range_profile_regime: bool = False,
    enrich_short_interest: bool = False,
    enrich_treasury: bool = False,
    enrich_sector_rotation: bool = False,
    enrich_institutional: bool = False,
    enrich_analyst: bool = False,
    enrich_insider: bool = False,
    base_snapshot: pd.DataFrame | None = None,
    daily_bars: pd.DataFrame | None = None,
    manifest_path: Path | None = None,
    newsapi_feed_state_path: Path | None = None,
    live_news_snapshot_path: Path | None = None,
) -> EnrichmentDict | None:
    """Build the enrichment dict using the v5 provider policy matrix.

    Each domain runs through its explicit provider chain (primary →
    fallback) as defined in ``smc_provider_policy``.  Every failure path
    records the stale provider and falls through to the next candidate
    or to safe defaults.  Provenance is recorded per-domain.

    When ``enrich_event_risk`` is *True* the v5 event-risk layer is
    derived from the calendar + news results already obtained in
    earlier stages.  ``EVENT_PROVIDER_STATUS`` reflects real runtime
    provider conditions.

    Parameters
    ----------
    base_snapshot:
        Optional base snapshot DataFrame.  When provided, volume-regime
        tickers (``VOLUME_LOW_TICKERS``, ``HOLIDAY_SUSPECT_TICKERS``)
        are derived from ``adv_dollar_rth_20d``.
    daily_bars:
        Optional daily OHLCV frame for activating volatility-regime and
        ensemble-quality derivations in the active production path.
    manifest_path:
        Path to the previously-written manifest JSON.  When provided,
        ``refresh_count`` is read from it and incremented by 1.
    """
    if not any([enrich_regime, enrich_news, enrich_calendar, enrich_layering, enrich_event_risk,
                enrich_flow_qualifier, enrich_compression_regime, enrich_zone_intelligence, enrich_reversal_context,
                enrich_session_context, enrich_liquidity_sweeps, enrich_liquidity_pools,
                enrich_order_blocks, enrich_zone_projection, enrich_zone_priority, enrich_profile_context,
                enrich_structure_state, enrich_imbalance_lifecycle, enrich_session_structure, enrich_range_regime,
                enrich_range_profile_regime, enrich_short_interest, enrich_treasury, enrich_sector_rotation,
                enrich_institutional, enrich_analyst, enrich_insider]):
        return None

    from scripts.smc_provider_policy import resolve_domain
    from scripts.smc_v55_lean_normalization import normalize_v55_lean_enrichment

    fmp = _make_fmp_client(fmp_api_key) if fmp_api_key else None
    enrichment: dict[str, Any] = {}
    all_stale: list[str] = []
    provenance: dict[str, str] = {}
    domain_diagnostics: dict[str, Any] = {}
    newsapi_feed_state = _load_newsapi_feed_state(newsapi_feed_state_path)

    # ── Base scan (Databento) — always the canonical source ─────
    provenance["base_scan_provider"] = "databento"

    # ── Regime ──────────────────────────────────────────────────
    regime_result: dict[str, Any] = {"regime": "NEUTRAL"}
    if enrich_regime:
        pr = resolve_domain("regime", fmp=fmp, symbols=symbols)
        all_stale.extend(pr.stale)
        if pr.ok:
            regime_result = pr.data
        provenance["regime_provider"] = pr.provider
        domain_diagnostics["regime"] = _build_domain_diagnostic("regime", pr)
        enrichment["regime"] = regime_result
        enrichment["regime"]["_hierarchy"] = "primary"

    # ── News ────────────────────────────────────────────────────
    news_result: dict[str, Any] = {}
    if enrich_news:
        news_cursor_before = dict(newsapi_feed_state)
        pr = resolve_domain(
            "news",
            fmp=fmp,
            benzinga_api_key=benzinga_api_key,
            newsapi_ai_key=newsapi_ai_key,
            symbols=symbols,
            newsapi_ai_feed_after_epoch=newsapi_feed_state["last_seen_epoch"],
            newsapi_ai_feed_after_uri=newsapi_feed_state["last_seen_news_uri"],
        )
        all_stale.extend(pr.stale)
        provider_news_result = dict(pr.data) if pr.ok else {}
        news_result = dict(provider_news_result)

        live_snapshot_diagnostics: dict[str, Any] | None = None
        merge_diagnostics: dict[str, Any] | None = None
        live_news_snapshot = _load_live_news_snapshot(live_news_snapshot_path)
        if live_news_snapshot is not None:
            live_snapshot_scored = _score_live_news_snapshot(
                symbols=symbols,
                live_news_snapshot=live_news_snapshot,
            )
            if live_snapshot_scored is not None:
                live_snapshot_payload, live_snapshot_diagnostics = live_snapshot_scored
                if _news_payload_has_mentions(live_snapshot_payload):
                    news_result, merge_diagnostics = _merge_news_payloads(
                        base_payload=provider_news_result,
                        live_payload=live_snapshot_payload,
                    )

        if pr.ok:
            news_result = news_result or provider_news_result
        if pr.provider == "newsapi_ai" and newsapi_feed_state_path is not None:
            next_epoch = _coerce_non_negative_float(pr.meta.get("last_seen_epoch"))
            next_uri = str(pr.meta.get("last_seen_news_uri") or "").strip()
            persisted_epoch = newsapi_feed_state["last_seen_epoch"]
            persisted_uri = newsapi_feed_state["last_seen_news_uri"]
            if next_epoch > persisted_epoch:
                persisted_epoch = next_epoch
                persisted_uri = next_uri
            elif next_uri:
                persisted_uri = next_uri
            if persisted_epoch != newsapi_feed_state["last_seen_epoch"] or persisted_uri != newsapi_feed_state["last_seen_news_uri"]:
                _save_newsapi_feed_state(
                    newsapi_feed_state_path,
                    last_seen_epoch=persisted_epoch,
                    last_seen_news_uri=persisted_uri,
                )
                newsapi_feed_state = {
                    "last_seen_epoch": persisted_epoch,
                    "last_seen_news_uri": persisted_uri,
                }
        resolved_news_provider = pr.provider
        news_domain_diagnostic = _build_domain_diagnostic(
            "news",
            pr,
            cursor_before=news_cursor_before,
            cursor_after=newsapi_feed_state,
        )
        news_domain_diagnostic["render_source"] = "provider_chain_only"
        news_domain_diagnostic["rendered_symbol_count"] = len(
            _parse_ticker_heat_map(news_result.get("ticker_heat_map"))
        )

        base_diagnostics = dict(news_domain_diagnostic.get("diagnostics") or {})
        rendered_payload_diagnostics = _summarize_news_payload(news_result)
        diagnostics = dict(base_diagnostics)
        diagnostics["base_provider_chain"] = {
            "provider": pr.provider,
            "provider_status": news_domain_diagnostic.get("provider_status"),
            "status_detail": news_domain_diagnostic.get("status_detail"),
            "raw_diagnostics": dict(base_diagnostics),
            "rendered_payload": _summarize_news_payload(provider_news_result),
        }
        diagnostics["rendered_payload"] = rendered_payload_diagnostics

        if live_snapshot_diagnostics is not None:
            news_domain_diagnostic["render_source"] = "provider_chain_plus_live_snapshot"
            diagnostics["live_snapshot"] = live_snapshot_diagnostics
        if merge_diagnostics is not None:
            diagnostics["merge"] = merge_diagnostics

        news_domain_diagnostic["diagnostics"] = diagnostics

        if (
            live_snapshot_diagnostics is not None
            and pr.provider == "none"
            and _news_payload_has_mentions(news_result)
        ):
            resolved_news_provider = "live_snapshot"
            news_domain_diagnostic["selected_provider"] = "live_snapshot"
            news_domain_diagnostic["provider_status"] = "ok"
            news_domain_diagnostic["ok"] = True
            news_domain_diagnostic["status_detail"] = "Provider chain returned no data; using live news snapshot overlay."

        provenance["news_provider"] = resolved_news_provider
        domain_diagnostics["news"] = news_domain_diagnostic
        enrichment["news"] = {
            "bullish_tickers": news_result.get("bullish_tickers", []),
            "bearish_tickers": news_result.get("bearish_tickers", []),
            "neutral_tickers": news_result.get("neutral_tickers", []),
            "news_heat_global": news_result.get("news_heat_global", 0.0),
            "ticker_heat_map": news_result.get("ticker_heat_map", ""),
        }

    # ── Calendar ────────────────────────────────────────────────
    calendar_result: dict[str, Any] = {}
    if enrich_calendar:
        pr = resolve_domain(
            "calendar", fmp=fmp, benzinga_api_key=benzinga_api_key, symbols=symbols,
        )
        all_stale.extend(pr.stale)
        if pr.ok:
            calendar_result = pr.data
        else:
            all_stale.append("calendar")
        provenance["calendar_provider"] = pr.provider
        domain_diagnostics["calendar"] = _build_domain_diagnostic("calendar", pr)
        enrichment["calendar"] = {
            "earnings_today_tickers": calendar_result.get("earnings_today_tickers", ""),
            "earnings_tomorrow_tickers": calendar_result.get("earnings_tomorrow_tickers", ""),
            "earnings_bmo_tickers": calendar_result.get("earnings_bmo_tickers", ""),
            "earnings_amc_tickers": calendar_result.get("earnings_amc_tickers", ""),
            "high_impact_macro_today": calendar_result.get("high_impact_macro_today", False),
            "macro_event_name": calendar_result.get("macro_event_name", ""),
            "macro_event_time": calendar_result.get("macro_event_time", ""),
        }

    # ── Layering ────────────────────────────────────────────────
    if enrich_layering:
        tech_strength, tech_bias = (0.5, "NEUTRAL")
        pr = resolve_domain("technical", fmp=fmp, symbols=symbols)
        all_stale.extend(pr.stale)
        if pr.ok:
            tech_strength = pr.data.get("strength", 0.5)
            tech_bias = pr.data.get("bias", "NEUTRAL")
        provenance["technical_provider"] = pr.provider
        domain_diagnostics["technical"] = _build_domain_diagnostic("technical", pr)

        # Determine news tone for layering
        bullish_count = len(news_result.get("bullish_tickers", []))
        bearish_count = len(news_result.get("bearish_tickers", []))
        if bullish_count > bearish_count:
            news_tone = "BULLISH"
        elif bearish_count > bullish_count:
            news_tone = "BEARISH"
        else:
            news_tone = "NEUTRAL"

        try:
            layering = compute_library_layering(
                regime=regime_result.get("regime", "NEUTRAL"),
                news=news_tone,
                technical_strength=tech_strength,
                technical_bias=tech_bias,
            )
        except Exception:
            logger.warning("Layering computation failed — using defaults", exc_info=True)
            layering = {
                "global_heat": 0.0,
                "global_strength": 0.5,
                "tone": "NEUTRAL",
                "trade_state": "ALLOWED",
            }
            all_stale.append("layering")
        enrichment["layering"] = layering

    volatility_regime = _build_volatility_regime_block(
        daily_bars=daily_bars,
        base_snapshot=base_snapshot,
    )
    if volatility_regime is not None:
        enrichment["volatility_regime"] = volatility_regime
        enrichment["ensemble_quality"] = _build_ensemble_quality_block(
            regime_result=regime_result,
            layering=cast(dict[str, Any] | None, enrichment.get("layering")),
            volatility_regime=volatility_regime,
        )

    # ── Event risk (v5) ─────────────────────────────────────────
    if enrich_event_risk:
        from databento_reference import (
            get_reference_event_risk_snapshot,
            maybe_refresh_symbol_reference_cache,
        )
        from scripts.smc_event_risk_builder import build_event_risk

        reference_risk: dict[str, Any] = {}
        try:
            maybe_refresh_symbol_reference_cache(symbols)
            reference_risk = get_reference_event_risk_snapshot(symbols)
        except Exception:
            logger.debug("Databento reference event-risk refresh skipped", exc_info=True)

        event_risk = build_event_risk(
            calendar=enrichment.get("calendar", {}),
            news=enrichment.get("news", {}),
            reference=reference_risk,
        )
        # Override builder's internal status with runtime-aware logic:
        # only flag degradation when the domain was *requested* but failed.
        cal_stale = enrich_calendar and provenance.get("calendar_provider") == "none"
        news_stale = enrich_news and provenance.get("news_provider") == "none"
        if cal_stale and news_stale:
            event_risk["EVENT_PROVIDER_STATUS"] = "no_data"
        elif cal_stale:
            event_risk["EVENT_PROVIDER_STATUS"] = "calendar_missing"
        elif news_stale:
            event_risk["EVENT_PROVIDER_STATUS"] = "news_missing"
        else:
            event_risk["EVENT_PROVIDER_STATUS"] = "ok"
        enrichment["event_risk"] = event_risk
        provenance["event_risk_provider"] = "smc_event_risk_builder"

    # ── Providers ───────────────────────────────────────────────
    active_providers = {v for v in provenance.values() if v != "none"}
    enrichment["providers"] = {
        "provider_count": len(active_providers),
        "stale_providers": ",".join(sorted(set(all_stale))),
        "domain_diagnostics": domain_diagnostics,
        **provenance,
    }

    # ── Volume regime ───────────────────────────────────────────
    enrichment["volume_regime"] = _derive_volume_regime(base_snapshot)

    # ── Flow Qualifier (v5.1) ───────────────────────────────────
    if enrich_flow_qualifier:
        from scripts.smc_flow_qualifier import build_flow_qualifier

        enrichment["flow_qualifier"] = build_flow_qualifier(
            snapshot=base_snapshot, symbol="",
        )

    # ── Compression / ATR Regime (v5.1) ─────────────────────────
    if enrich_compression_regime:
        from scripts.smc_compression_regime import build_compression_regime

        enrichment["compression_regime"] = build_compression_regime(
            snapshot=base_snapshot, symbol="",
        )
        enrichment["compression_regime"]["_hierarchy"] = "enrichment_only"

    # ── Zone Intelligence (v5.1) ────────────────────────────────
    if enrich_zone_intelligence:
        from scripts.smc_zone_intelligence import build_zone_intelligence

        enrichment["zone_intelligence"] = build_zone_intelligence(
            snapshot=base_snapshot, symbol="",
        )

    # ── Reversal Context (v5.1) ─────────────────────────────────
    if enrich_reversal_context:
        from scripts.smc_reversal_context import build_reversal_context

        enrichment["reversal_context"] = build_reversal_context(
            snapshot=base_snapshot, symbol="",
        )

    # ── Session Context (v5.2) ──────────────────────────────────
    if enrich_session_context:
        from scripts.smc_session_context_block import build_session_context_block

        enrichment["session_context"] = build_session_context_block(
            snapshot=base_snapshot, symbol="",
        )

    # ── Liquidity Sweeps (v5.2) ─────────────────────────────────
    if enrich_liquidity_sweeps:
        from scripts.smc_liquidity_sweeps import build_liquidity_sweeps

        enrichment["liquidity_sweeps"] = build_liquidity_sweeps(
            snapshot=base_snapshot, symbol="",
        )

    # ── Liquidity Pools (v5.2) ──────────────────────────────────
    if enrich_liquidity_pools:
        from scripts.smc_liquidity_pools import build_liquidity_pools

        enrichment["liquidity_pools"] = build_liquidity_pools(
            snapshot=base_snapshot, symbol="",
        )

    # ── Order Blocks (v5.2) ─────────────────────────────────────
    if enrich_order_blocks:
        from scripts.smc_order_blocks import build_order_blocks

        enrichment["order_blocks"] = build_order_blocks(
            snapshot=base_snapshot, symbol="",
        )

    # ── Zone Projection (v5.2) ──────────────────────────────────
    if enrich_zone_projection:
        from scripts.smc_zone_projection import build_zone_projection

        enrichment["zone_projection"] = build_zone_projection(
            snapshot=base_snapshot, symbol="",
        )

    # ── Zone Priority (C9) ──────────────────────────────────────
    if enrich_zone_priority:
        from scripts.smc_zone_priority import build_zone_priority

        # Load calibrated family weights (best-effort)
        _calibrated_fw: dict[str, float] | None = None
        _calibrated_meta: dict[str, Any] | None = None
        for _cal_candidate in (
            Path("artifacts/reports/zone_priority_calibration.json"),
            Path("artifacts/ci/measurement_benchmark/zone_priority_calibration.json"),
        ):
            if _cal_candidate.exists():
                try:
                    _cal_data = json.loads(_cal_candidate.read_text(encoding="utf-8"))
                    _calibrated_fw = _cal_data.get("family_weights")
                    if _calibrated_fw:
                        logger.info("Zone priority: loaded calibrated weights from %s", _cal_candidate)
                    # Phase H consumer inputs — best-effort, neutral on miss.
                    _calibrated_meta = {
                        "family_stats": _cal_data.get("family_stats"),
                        "total_events": _cal_data.get("total_events"),
                    }
                    # Pull smECE from the per-bucket sibling if present (F3 follow-on).
                    _per_bucket_path = _cal_candidate.with_name(
                        "zone_priority_per_bucket_calibration.json"
                    )
                    if _per_bucket_path.exists():
                        try:
                            _pb = json.loads(_per_bucket_path.read_text(encoding="utf-8"))
                            # Use the largest "ok" bucket as the corpus proxy
                            # (matches what compute_testable_calibration would
                            # report on the global corpus).
                            ok_buckets = [
                                v for v in _pb.values()
                                if isinstance(v, dict) and v.get("status") == "ok"
                                and v.get("smooth_ece") is not None
                            ]
                            if ok_buckets:
                                largest = max(ok_buckets, key=lambda v: v.get("n_events", 0))
                                _calibrated_meta["smooth_ece"] = largest["smooth_ece"]
                        except Exception:
                            pass
                except Exception:
                    pass
                break

        # Gather context from already-computed enrichment blocks
        _regime = (enrichment.get("regime") or {}).get("regime", "NEUTRAL")
        _eq = enrichment.get("ensemble_quality") or {}
        _news = enrichment.get("news") or {}
        _er = enrichment.get("event_risk") or enrichment.get("event_risk_light") or {}
        _sc = enrichment.get("session_context_light") or enrichment.get("session_context") or {}
        _vr = enrichment.get("volatility_regime") or {}
        _zp = enrichment.get("zone_projection") or {}

        enrichment["zone_priority"] = build_zone_priority(
            regime=str(_regime),
            ensemble_score=float(_eq.get("score") or 0.0),
            news_heat=float(_news.get("news_heat_global") or 0.0),
            event_risk_level=str(_er.get("EVENT_RISK_LEVEL", "NONE")),
            session_context=str(_sc.get("SESSION_CONTEXT", "")),
            vol_regime=str(_vr.get("label", "NORMAL")),
            zone_proj_score=int(_zp.get("ZONE_PROJ_SCORE", 0)),
            htf_aligned=bool(_zp.get("ZONE_PROJ_HTF_ALIGNED", False)),
            calibrated_family_weights=_calibrated_fw,
        )
        # Attach calibrated weights for Pine export
        if _calibrated_fw:
            enrichment["zone_priority_calibration"] = _calibrated_fw
        # Attach Phase H consumer inputs (confidence + per-family HR).
        # Trend (H3) requires a history feed which is not yet sourced
        # — generator falls back to "STABLE" via DEFAULTS until then.
        if _calibrated_meta:
            enrichment["zone_priority_calibration_meta"] = _calibrated_meta
        # H3 trend feed — load the rolling history JSONL written by
        # smc_zone_priority_calibration.py::append_history_entry. Limited
        # to the most recent 10 entries to bound enrichment size; the
        # consumer's compute_calibration_trend only inspects the first
        # and last anyway.
        try:
            from scripts.smc_zone_priority_calibration import load_history_entries
            for _cal_candidate in (
                Path("artifacts/reports/zone_priority_calibration.json"),
                Path("artifacts/ci/measurement_benchmark/zone_priority_calibration.json"),
            ):
                if _cal_candidate.exists():
                    _history = load_history_entries(_cal_candidate, limit=10)
                    if _history:
                        enrichment["zone_priority_calibration_history"] = _history
                    break
        except Exception:
            # Non-fatal: trend simply falls back to STABLE via DEFAULTS.
            pass

    # ── Profile Context (v5.2) ──────────────────────────────────
    if enrich_profile_context:
        from scripts.smc_profile_context import build_profile_context

        enrichment["profile_context"] = build_profile_context(
            snapshot=base_snapshot, symbol="",
        )

    # ── Structure State (v5.3) ──────────────────────────────────
    if enrich_structure_state:
        from scripts.smc_structure_state import build_structure_state

        enrichment["structure_state"] = build_structure_state(
            snapshot=base_snapshot, symbol="",
        )

    # ── Imbalance Lifecycle (v5.3) ──────────────────────────────
    if enrich_imbalance_lifecycle:
        from scripts.smc_imbalance_lifecycle import build_imbalance_lifecycle

        enrichment["imbalance_lifecycle"] = build_imbalance_lifecycle(
            snapshot=base_snapshot, symbol="",
        )

    # ── Session Structure (v5.3) ────────────────────────────────
    if enrich_session_structure:
        from scripts.smc_session_structure import build_session_structure

        enrichment["session_structure"] = build_session_structure(
            snapshot=base_snapshot, symbol="",
        )

    # ── Range Regime (v5.3) ─────────────────────────────────────
    if enrich_range_regime:
        from scripts.smc_range_regime import build_range_regime

        enrichment["range_regime"] = build_range_regime(
            snapshot=base_snapshot, symbol="",
        )
        enrichment["range_regime"]["_hierarchy"] = "enrichment_only"

    # ── Range Profile Regime (v5.3) ─────────────────────────────
    if enrich_range_profile_regime:
        from scripts.smc_range_profile_regime import build_range_profile_regime

        enrichment["range_profile_regime"] = build_range_profile_regime(
            snapshot=base_snapshot, symbol="",
        )
        enrichment["range_profile_regime"]["_hierarchy"] = "enrichment_only"

    # ── Regime Hierarchy Conflict Detection (F-06) ──────────────
    # Primary regimes: vol_regime (smc_core), regime_classifier (scripts)
    # Enrichment-only: compression_regime, range_regime, range_profile_regime
    regime_conflicts: list[dict[str, str]] = []
    primary_regime = regime_result.get("regime", "NEUTRAL")
    vol_regime_label = str((enrichment.get("volatility_regime") or {}).get("label", "")).upper()
    compression_atr = str((enrichment.get("compression_regime") or {}).get("ATR_REGIME", "")).upper()

    # Check: if primary says RISK_OFF but vol_regime says LOW_VOL, that's a conflict.
    if primary_regime == "RISK_OFF" and vol_regime_label == "LOW_VOL":
        regime_conflicts.append({
            "code": "REGIME_CONFLICT",
            "primary": f"market_regime={primary_regime}",
            "enrichment": f"vol_regime={vol_regime_label}",
            "resolution": "primary wins",
        })
    # Check: if vol_regime says EXTREME but compression says COMPRESSION.
    if vol_regime_label == "EXTREME" and compression_atr == "COMPRESSION":
        regime_conflicts.append({
            "code": "REGIME_CONFLICT",
            "primary": f"vol_regime={vol_regime_label}",
            "enrichment": f"compression_atr={compression_atr}",
            "resolution": "primary wins",
        })
    if regime_conflicts:
        logger.warning("Regime hierarchy conflicts detected: %s", regime_conflicts)
        enrichment.setdefault("_diagnostics", {})["regime_conflicts"] = regime_conflicts

    # ── Short Interest (v6) ─────────────────────────────────────
    if enrich_short_interest and fmp is not None:
        try:
            from scripts.smc_short_interest_enrichment import compute_short_interest_enrichment
            enrichment["short_interest"] = compute_short_interest_enrichment(symbols[:50], fmp)
        except Exception as exc:
            logger.warning("Short interest enrichment failed", exc_info=True)
            enrichment.setdefault("_diagnostics", {})["short_interest_error"] = str(exc)

    # ── Treasury / Yield Curve (v6) ─────────────────────────────
    if enrich_treasury and fmp is not None:
        try:
            yields = fmp.get_treasury_yields()
            enrichment["treasury"] = {
                "treasury_10y_yield": yields["10y"],
                "treasury_2y_yield": yields["2y"],
                "yield_curve_spread": yields["spread"],
                "yield_curve_inverted": yields["inverted"],
            }
        except Exception as exc:
            logger.warning("Treasury enrichment failed", exc_info=True)
            enrichment.setdefault("_diagnostics", {})["treasury_error"] = str(exc)

    # ── Sector Rotation Detail (v6) ─────────────────────────────
    if enrich_sector_rotation and fmp is not None:
        try:
            from scripts.smc_sector_rotation_enrichment import compute_sector_rotation
            sector_data = fmp.get_sector_performance()
            enrichment["sector_rotation"] = compute_sector_rotation(sector_data or [])
        except Exception as exc:
            logger.warning("Sector rotation enrichment failed", exc_info=True)
            enrichment.setdefault("_diagnostics", {})["sector_rotation_error"] = str(exc)

    # ── Institutional Accumulation (v6) ─────────────────────────
    if enrich_institutional and fmp is not None:
        try:
            from scripts.smc_institutional_enrichment import compute_institutional_enrichment
            enrichment["institutional"] = compute_institutional_enrichment(symbols[:30], fmp)
        except Exception as exc:
            logger.warning("Institutional enrichment failed", exc_info=True)
            enrichment.setdefault("_diagnostics", {})["institutional_error"] = str(exc)

    # ── Analyst Consensus (v6) ──────────────────────────────────
    if enrich_analyst and fmp is not None:
        try:
            from scripts.smc_analyst_enrichment import compute_analyst_enrichment
            enrichment["analyst"] = compute_analyst_enrichment(symbols[:50], fmp)
        except Exception as exc:
            logger.warning("Analyst enrichment failed", exc_info=True)
            enrichment.setdefault("_diagnostics", {})["analyst_error"] = str(exc)

    # ── Insider Transactions (v6) ───────────────────────────────
    if enrich_insider and fmp is not None:
        try:
            from scripts.smc_insider_enrichment import compute_insider_enrichment
            enrichment["insider"] = compute_insider_enrichment(symbols[:30], fmp)
        except Exception as exc:
            logger.warning("Insider enrichment failed", exc_info=True)
            enrichment.setdefault("_diagnostics", {})["insider_error"] = str(exc)

    # ── Hero State Contract ──────────────────────────────────────
    from scripts.smc_hero_state import build_hero_state

    enrichment["hero_state"] = build_hero_state(enrichment)

    # ── Meta ────────────────────────────────────────────────────
    prev_count = _read_previous_refresh_count(manifest_path)
    enrichment["meta"] = {
        "asof_time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "refresh_count": prev_count + 1,
        "scanned_symbols": sorted(set(symbols)),
    }

    return normalize_v55_lean_enrichment(cast(EnrichmentDict, enrichment), snapshot=base_snapshot)


def _export_live_news_sidecar(
    *,
    base_result: dict[str, Any],
    base_csv: Path,
    artifacts_root: Path,
    fmp_api_key: str,
    benzinga_api_key: str,
    newsapi_ai_key: str,
) -> dict[str, Any]:
    output_path = artifacts_root / "smc_live_news_snapshot.json"
    state_path = artifacts_root / "smc_live_news_state.json"
    output_paths = base_result.get("output_paths") if isinstance(base_result, dict) else None
    raw_manifest_path = output_paths.get("base_manifest") if isinstance(output_paths, dict) else None
    base_manifest_path = Path(raw_manifest_path) if raw_manifest_path else None

    try:
        symbols, scope_metadata = resolve_live_news_symbols(
            base_csv_path=base_csv,
            base_manifest_path=base_manifest_path,
            symbol_limit=DEFAULT_SYMBOL_LIMIT,
        )
        snapshot = export_live_news_snapshot(
            symbols=symbols,
            output_path=output_path,
            state_path=state_path,
            fmp_api_key=fmp_api_key,
            benzinga_api_key=benzinga_api_key,
            newsapi_ai_key=newsapi_ai_key,
            scope_metadata=scope_metadata,
        )
    except Exception as exc:
        logger.warning("Failed to export live news snapshot sidecar", exc_info=True)
        return {
            "status": "error",
            "snapshot_path": str(output_path),
            "state_path": str(state_path),
            "error": f"{type(exc).__name__}: {exc}",
        }

    provider_errors = {
        provider: str(payload.get("error") or "")
        for provider, payload in (snapshot.get("providers") or {}).items()
        if str(payload.get("error") or "").strip()
    }
    summary = snapshot.get("summary") or {}
    return {
        "status": "ok",
        "snapshot_path": str(output_path),
        "state_path": str(state_path),
        "symbol_count": len(symbols),
        "active_story_count": int(summary.get("active_story_count") or 0),
        "new_story_count": int(summary.get("new_story_count") or 0),
        "actionable_symbols": list(summary.get("actionable_symbols") or []),
        "provider_errors": provider_errors,
        "symbol_scope": snapshot.get("symbol_scope") or scope_metadata,
    }


def finalize_pipeline(
    *,
    base_result: dict[str, Any],
    schema_path: Path,
    output_root: Path,
    artifacts_root: Path | None = None,
    fmp_api_key: str = "",
    benzinga_api_key: str = "",
    newsapi_ai_key: str = "",
    library_owner: str = "preuss_steffen",
    library_version: int = 1,
    enrich_regime: bool = False,
    enrich_news: bool = False,
    enrich_calendar: bool = False,
    enrich_layering: bool = False,
    enrich_event_risk: bool = False,
    enrich_flow_qualifier: bool = False,
    enrich_compression_regime: bool = False,
    enrich_zone_intelligence: bool = False,
    enrich_reversal_context: bool = False,
    enrich_session_context: bool = False,
    enrich_liquidity_sweeps: bool = False,
    enrich_liquidity_pools: bool = False,
    enrich_order_blocks: bool = False,
    enrich_zone_projection: bool = False,
    enrich_zone_priority: bool = False,
    enrich_profile_context: bool = False,
    enrich_structure_state: bool = False,
    enrich_imbalance_lifecycle: bool = False,
    enrich_session_structure: bool = False,
    enrich_range_regime: bool = False,
    enrich_range_profile_regime: bool = False,
    enrich_short_interest: bool = False,
    enrich_treasury: bool = False,
    enrich_sector_rotation: bool = False,
    enrich_institutional: bool = False,
    enrich_analyst: bool = False,
    enrich_insider: bool = False,
    debug_mode: bool = False,
    live_news_snapshot_path: Path | None = None,
    emit_live_news_snapshot: bool = False,
    progress_callback: Any = None,
) -> dict[str, Any]:
    """Shared post-base orchestration: enrichment + Pine library generation.

    Called by both the ``--run-scan`` and ``--bundle`` CLI paths as well
    as UI-triggered flows.  Returns a structured, machine-readable result
    dict that downstream gates / CI can consume directly.
    """
    output_root = Path(output_root)
    artifacts_root = Path(artifacts_root) if artifacts_root is not None else output_root
    artifacts_root.mkdir(parents=True, exist_ok=True)

    def _progress(message: str) -> None:
        logger.info(message)
        if progress_callback is not None:
            progress_callback(message)

    base_csv = Path(base_result["output_paths"]["base_csv"])
    snapshot_df = base_result["base_snapshot"]
    symbols = sorted(
        snapshot_df["symbol"].dropna().unique().tolist()
    )

    # Resolve manifest path for refresh_count persistence
    manifest_path = output_root / "pine" / "generated" / "smc_micro_profiles_generated.json"

    requested_live_news_snapshot_path = (
        Path(live_news_snapshot_path) if live_news_snapshot_path is not None else None
    )
    live_news_result = None
    prepared_live_news_snapshot_path = requested_live_news_snapshot_path
    prepare_live_news_before_enrichment = bool(
        emit_live_news_snapshot
        and enrich_news
        and requested_live_news_snapshot_path is None
    )
    if prepare_live_news_before_enrichment:
        live_news_started_at = time_module.perf_counter()
        _progress("Finalize 1/3: Exporting live-news sidecars for enrichment input...")
        live_news_result = _export_live_news_sidecar(
            base_result=base_result,
            base_csv=base_csv,
            artifacts_root=artifacts_root,
            fmp_api_key=fmp_api_key,
            benzinga_api_key=benzinga_api_key,
            newsapi_ai_key=newsapi_ai_key,
        )
        live_news_status = live_news_result.get("status") if isinstance(live_news_result, dict) else "unknown"
        if live_news_status == "ok":
            prepared_live_news_snapshot_path = Path(live_news_result["snapshot_path"])
        _progress(
            f"Finalize 1/3 complete in {time_module.perf_counter() - live_news_started_at:.1f}s "
            f"(status={live_news_status})"
        )

    enrichment_step_label = "2/3" if prepare_live_news_before_enrichment else "1/3"
    pine_step_label = "3/3" if prepare_live_news_before_enrichment else "2/3"

    # ── Enrichment ──────────────────────────────────────────────
    enrichment_started_at = time_module.perf_counter()
    _progress(f"Finalize {enrichment_step_label}: Building enrichment for {len(symbols)} symbols...")
    enrichment = build_enrichment(
        fmp_api_key=fmp_api_key,
        benzinga_api_key=benzinga_api_key,
        newsapi_ai_key=newsapi_ai_key,
        symbols=symbols,
        enrich_regime=enrich_regime,
        enrich_news=enrich_news,
        enrich_calendar=enrich_calendar,
        enrich_layering=enrich_layering,
        enrich_event_risk=enrich_event_risk,
        enrich_flow_qualifier=enrich_flow_qualifier,
        enrich_compression_regime=enrich_compression_regime,
        enrich_zone_intelligence=enrich_zone_intelligence,
        enrich_reversal_context=enrich_reversal_context,
        enrich_session_context=enrich_session_context,
        enrich_liquidity_sweeps=enrich_liquidity_sweeps,
        enrich_liquidity_pools=enrich_liquidity_pools,
        enrich_order_blocks=enrich_order_blocks,
        enrich_zone_projection=enrich_zone_projection,
        enrich_zone_priority=enrich_zone_priority,
        enrich_profile_context=enrich_profile_context,
        enrich_structure_state=enrich_structure_state,
        enrich_imbalance_lifecycle=enrich_imbalance_lifecycle,
        enrich_session_structure=enrich_session_structure,
        enrich_range_regime=enrich_range_regime,
        enrich_range_profile_regime=enrich_range_profile_regime,
        enrich_short_interest=enrich_short_interest,
        enrich_treasury=enrich_treasury,
        enrich_sector_rotation=enrich_sector_rotation,
        enrich_institutional=enrich_institutional,
        enrich_analyst=enrich_analyst,
        enrich_insider=enrich_insider,
        base_snapshot=snapshot_df,
        daily_bars=cast(
            pd.DataFrame | None,
            (base_result.get("export_result") or {}).get("daily_bars")
            if isinstance(base_result, dict)
            else None,
        ),
        manifest_path=manifest_path,
        newsapi_feed_state_path=artifacts_root / "newsapi_ai_feed_state.json",
        live_news_snapshot_path=prepared_live_news_snapshot_path,
    )
    enrichment_keys = list(enrichment.keys()) if enrichment else []
    if debug_mode:
        if enrichment is None:
            enrichment = {}
        enrichment["_debug_mode"] = True
    _progress(
        f"Finalize {enrichment_step_label} complete in {time_module.perf_counter() - enrichment_started_at:.1f}s "
        f"(enrichment_keys={len(enrichment_keys)})"
    )

    provider_diagnostics_report_path = output_root / "artifacts" / "ci" / "smc_library_provider_diagnostics_report.json"
    provider_diagnostics_report = None
    if enrichment is not None:
        provider_diagnostics_report = _write_library_provider_diagnostics_report(
            provider_diagnostics_report_path,
            enrichment=enrichment,
            symbols_count=len(symbols),
        )

    # ── Pine library generation ─────────────────────────────────
    pine_started_at = time_module.perf_counter()
    _progress(f"Finalize {pine_step_label}: Generating Pine library artifacts...")
    pine_paths = generate_pine_library_from_base(
        base_csv_path=base_csv,
        schema_path=schema_path,
        output_root=output_root,
        library_owner=library_owner,
        library_version=library_version,
        enrichment=enrichment,
    )
    _progress(
        f"Finalize {pine_step_label} complete in {time_module.perf_counter() - pine_started_at:.1f}s "
        f"(artifacts={len(pine_paths)})"
    )

    if emit_live_news_snapshot and live_news_result is None:
        live_news_started_at = time_module.perf_counter()
        _progress("Finalize 3/3: Exporting live-news sidecars...")
        live_news_result = _export_live_news_sidecar(
            base_result=base_result,
            base_csv=base_csv,
            artifacts_root=artifacts_root,
            fmp_api_key=fmp_api_key,
            benzinga_api_key=benzinga_api_key,
            newsapi_ai_key=newsapi_ai_key,
        )
        live_news_status = live_news_result.get("status") if isinstance(live_news_result, dict) else "unknown"
        _progress(
            f"Finalize 3/3 complete in {time_module.perf_counter() - live_news_started_at:.1f}s "
            f"(status={live_news_status})"
        )

    result = {
        "status": "ok",
        "base_csv": str(base_csv),
        "symbols_count": len(symbols),
        "enrichment_keys": list(enrichment.keys()) if enrichment else [],
        "stale_providers": (
            enrichment.get("providers", {}).get("stale_providers", "")
            if enrichment
            else ""
        ),
        "output_root": str(output_root),
        "artifacts_root": str(artifacts_root),
        "pine_paths": {k: str(v) for k, v in pine_paths.items()},
        "base_result_keys": list(base_result.keys()),
    }
    if provider_diagnostics_report is not None:
        result["provider_diagnostics_report"] = str(provider_diagnostics_report_path)
        result["provider_diagnostics_status"] = str(provider_diagnostics_report.get("overall_status") or "unknown")
    if live_news_result is not None:
        result["live_news_snapshot"] = live_news_result
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an SMC microstructure base snapshot from a Databento workbook, an export bundle, or a fresh Databento full-universe scan."
    )
    parser.add_argument("workbook", nargs="?", type=Path, help="Legacy path to databento_volatility_production_*.xlsx")
    parser.add_argument("--bundle", type=Path, help="Manifest path, export directory, or bundle basename for Databento production exports")
    parser.add_argument("--run-scan", action="store_true", help="Run the full Databento production export first, then build the base snapshot from the generated bundle")
    parser.add_argument("--databento-api-key", default=os.getenv("DATABENTO_API_KEY", ""), help="Databento API key for --run-scan")
    parser.add_argument("--fmp-api-key", default=os.getenv("FMP_API_KEY", ""), help="FMP API key for enrichment and --run-scan")
    parser.add_argument("--dataset", default=os.getenv("DATABENTO_DATASET", "DBEQ.BASIC"), help="Databento dataset for --run-scan")
    parser.add_argument("--lookback-days", type=int, default=30, help="Trading-day lookback for --run-scan")
    parser.add_argument("--export-dir", type=Path, default=Path("artifacts/smc_microstructure_exports"), help="Output directory for bundle/base artifacts")
    parser.add_argument("--output-root", type=Path, default=Path("."), help="Root directory for canonical generated library artifacts")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.getenv("SMC_DATABENTO_CACHE_DIR", "artifacts/databento_volatility_cache")),
        help="File cache directory for --run-scan Databento data reuse; point this at a persistent path on self-hosted runners",
    )
    parser.add_argument("--force-refresh", action="store_true", help="Bypass file cache during --run-scan")
    parser.add_argument("--incremental-base-only", action="store_true", help="Reuse the persisted base-only seed and only refresh changed trade days during --run-scan")
    parser.add_argument("--write-xlsx", action="store_true", help="Also emit an .xlsx base workbook for bundle/scan generation")
    parser.add_argument("--library-owner", default="preuss_steffen", help="TradingView owner for the generated library import path metadata")
    parser.add_argument("--library-version", type=int, default=1, help="TradingView library version for generated import metadata")
    from scripts.smc_schema_resolver import resolve_microstructure_schema_path
    parser.add_argument("--schema", type=Path, default=resolve_microstructure_schema_path(), help="Path to the microstructure schema")
    parser.add_argument("--asof-date", help="Optional YYYY-MM-DD trade date to extract; defaults to the latest workbook trade_date")
    parser.add_argument("--output-csv", type=Path, help="Output path for the generated partial base snapshot CSV")
    parser.add_argument("--report-md", type=Path, help="Output path for the markdown mapping report")
    parser.add_argument("--report-json", type=Path, help="Output path for the JSON mapping report")
    # Enrichment flags
    parser.add_argument("--enrich-regime", action="store_true", help="Add market-regime enrichment (VIX, sector performance via FMP)")
    parser.add_argument("--enrich-news", action="store_true", help="Add news-sentiment enrichment (FMP stock news)")
    parser.add_argument("--enrich-calendar", action="store_true", help="Add earnings/macro calendar enrichment (FMP)")
    parser.add_argument("--enrich-layering", action="store_true", help="Add pre-computed layering signals (smc_core)")
    parser.add_argument("--enrich-event-risk", action="store_true", help="Add v5 event-risk layer (derived from calendar + news)")
    parser.add_argument("--enrich-flow-qualifier", action="store_true", help="Add v5.1 flow qualifier (snapshot-derived)")
    parser.add_argument("--enrich-compression-regime", action="store_true", help="Add v5.1 compression / ATR regime (snapshot-derived)")
    parser.add_argument("--enrich-zone-intelligence", action="store_true", help="Add v5.1 zone intelligence (snapshot-derived)")
    parser.add_argument("--enrich-reversal-context", action="store_true", help="Add v5.1 reversal context (snapshot-derived)")
    parser.add_argument("--enrich-session-context", action="store_true", help="Add v5.2 session context (snapshot-derived)")
    parser.add_argument("--enrich-liquidity-sweeps", action="store_true", help="Add v5.2 liquidity sweeps (snapshot-derived)")
    parser.add_argument("--enrich-liquidity-pools", action="store_true", help="Add v5.2 liquidity pools (snapshot-derived)")
    parser.add_argument("--enrich-order-blocks", action="store_true", help="Add v5.2 order blocks (snapshot-derived)")
    parser.add_argument("--enrich-zone-projection", action="store_true", help="Add v5.2 zone projection (snapshot-derived)")
    parser.add_argument("--enrich-zone-priority", action="store_true", help="Add v5.2 zone priority ranking (composite scoring)")
    parser.add_argument("--enrich-profile-context", action="store_true", help="Add v5.2 profile context (snapshot-derived)")
    parser.add_argument("--enrich-structure-state", action="store_true", help="Add v5.3 structure state (snapshot-derived)")
    parser.add_argument("--enrich-imbalance-lifecycle", action="store_true", help="Add v5.3 imbalance lifecycle (snapshot-derived)")
    parser.add_argument("--enrich-session-structure", action="store_true", help="Add v5.3 session structure (snapshot-derived)")
    parser.add_argument("--enrich-range-regime", action="store_true", help="Add v5.3 range regime (snapshot-derived)")
    parser.add_argument("--enrich-range-profile-regime", action="store_true", help="Add v5.3 range/profile regime (snapshot-derived)")
    parser.add_argument("--enrich-short-interest", action="store_true", help="Add v6 short interest enrichment (FMP)")
    parser.add_argument("--enrich-treasury", action="store_true", help="Add v6 treasury / yield curve enrichment (FMP)")
    parser.add_argument("--enrich-sector-rotation", action="store_true", help="Add v6 sector rotation detail enrichment (FMP)")
    parser.add_argument("--enrich-institutional", action="store_true", help="Add v6 institutional accumulation enrichment (FMP)")
    parser.add_argument("--enrich-analyst", action="store_true", help="Add v6 analyst consensus enrichment (FMP)")
    parser.add_argument("--enrich-insider", action="store_true", help="Add v6 insider transactions enrichment (FMP)")
    parser.add_argument("--enrich-all", action="store_true", help="Enable all enrichment blocks")
    parser.add_argument("--debug", action="store_true", help="Include diagnostic fields (LOOKBACK_DAYS, UNIVERSE_ID, VOLATILITY_MODEL_SOURCE, etc.)")
    parser.add_argument("--benzinga-api-key", default=os.getenv("BENZINGA_API_KEY", ""), help="Benzinga API key for news/calendar fallback")
    parser.add_argument("--newsapi-ai-key", default=os.getenv("NEWSAPI_AI_KEY", ""), help="NewsAPI.ai API key for optional news fallback")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cli_progress_callback = _emit_cli_progress
    enrichment_flags = _resolve_enrichment_flags(args)
    fmp_api_key = str(args.fmp_api_key).strip()
    benzinga_api_key = str(getattr(args, 'benzinga_api_key', '') or '').strip()
    newsapi_ai_key = str(getattr(args, 'newsapi_ai_key', '') or '').strip()

    finalize_kwargs = dict(
        schema_path=args.schema,
        output_root=args.output_root,
        artifacts_root=args.export_dir,
        fmp_api_key=fmp_api_key,
        benzinga_api_key=benzinga_api_key,
        newsapi_ai_key=newsapi_ai_key,
        library_owner=str(args.library_owner).strip(),
        library_version=int(args.library_version),
        emit_live_news_snapshot=True,
        debug_mode=bool(args.debug),
        progress_callback=cli_progress_callback,
        **enrichment_flags,
    )

    if args.run_scan:
        if not args.databento_api_key:
            raise ValueError("Databento API key is required when using --run-scan")
        base_result = run_databento_base_scan_pipeline(
            databento_api_key=str(args.databento_api_key).strip(),
            fmp_api_key=fmp_api_key,
            dataset=str(args.dataset).strip(),
            export_dir=args.export_dir,
            schema_path=args.schema,
            lookback_days=int(args.lookback_days),
            force_refresh=bool(args.force_refresh),
            incremental_base_only=bool(args.incremental_base_only),
            cache_dir=args.cache_dir,
            use_file_cache=True,
            display_timezone="Europe/Berlin",
            bullish_score_profile="balanced",
            write_xlsx=bool(args.write_xlsx),
            library_owner=str(args.library_owner).strip(),
            library_version=int(args.library_version),
            progress_callback=cli_progress_callback,
        )
        result = finalize_pipeline(base_result=base_result, **finalize_kwargs)
        logger.info("Pipeline complete: %s", json.dumps(result, indent=2))
        return

    if args.bundle is not None:
        bundle_result = generate_base_from_bundle(
            args.bundle,
            schema_path=args.schema,
            output_dir=args.export_dir,
            asof_date=args.asof_date,
            write_xlsx=bool(args.write_xlsx),
            library_owner=str(args.library_owner).strip(),
            library_version=int(args.library_version),
        )
        result = finalize_pipeline(base_result=bundle_result, **finalize_kwargs)
        logger.info("Pipeline complete: %s", json.dumps(result, indent=2))
        return

    if args.workbook is None:
        raise ValueError("Provide either a legacy workbook path, --bundle, or --run-scan")

    output, payload = build_base_snapshot_from_workbook(args.workbook, schema_path=args.schema, asof_date=args.asof_date)
    default_csv, default_md, default_json = build_default_output_paths(args.workbook, payload["asof_date"])
    output_csv = args.output_csv or default_csv
    report_md = args.report_md or default_md
    report_json = args.report_json or default_json
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_csv(output, output_csv, index=False)
    write_mapping_report(report_md, payload)
    atomic_write_text(json.dumps(payload, indent=2) + "\n", report_json)


def _resolve_enrichment_flags(args: argparse.Namespace) -> dict[str, bool]:
    """Return the resolved enrichment flags keyed for build_enrichment/finalize_pipeline."""
    flag_names = (
        "enrich_regime",
        "enrich_news",
        "enrich_calendar",
        "enrich_layering",
        "enrich_event_risk",
        "enrich_flow_qualifier",
        "enrich_compression_regime",
        "enrich_zone_intelligence",
        "enrich_reversal_context",
        "enrich_session_context",
        "enrich_liquidity_sweeps",
        "enrich_liquidity_pools",
        "enrich_order_blocks",
        "enrich_zone_projection",
        "enrich_zone_priority",
        "enrich_profile_context",
        "enrich_structure_state",
        "enrich_imbalance_lifecycle",
        "enrich_session_structure",
        "enrich_range_regime",
        "enrich_range_profile_regime",
        "enrich_short_interest",
        "enrich_treasury",
        "enrich_sector_rotation",
        "enrich_institutional",
        "enrich_analyst",
        "enrich_insider",
    )
    if args.enrich_all:
        return {flag_name: True for flag_name in flag_names}
    return {flag_name: bool(getattr(args, flag_name)) for flag_name in flag_names}


if __name__ == "__main__":
    main()
