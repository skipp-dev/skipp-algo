from __future__ import annotations

import csv
import logging
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smc_core.vol_regime import classify_volume_regime_from_rvol

from .base import SourceCapabilities, SourceDescriptor

WATCHLIST_CSV = Path(__file__).resolve().parents[2] / "reports" / "databento_watchlist_top5_pre1530.csv"
_LOG = logging.getLogger(__name__)
_RVOL_FIELD_CANDIDATES = (
    "day_volume_rvol_20d",
    "open_5m_rvol_20d",
    "open_1m_rvol_20d",
    "rvol_20d",
    "rvol_5d",
    "rvol",
    "rel_vol",
    "relative_volume",
    "volume_ratio",
)
_DAILY_VOLUME_FIELD_CANDIDATES = (
    "current_volume",
    "day_volume",
    "daily_volume",
    "volume",
)
_DAILY_AVG_VOLUME_FIELD_CANDIDATES = (
    "avg_daily_volume",
    "avg_day_volume_20d",
    "average_daily_volume",
    "adv20",
    "adv_20d",
)
_VOLUME_REGIME_CONTRACT_VERSION = "1"
_VOLUME_REGIME_BASELINE_PRIORITY_ORDER = (
    "rvol",
    "explicit_average_volume",
    "peer_median_same_trade_date",
    "premarket_liquidity",
)
_PEER_MEDIAN_ROLLOUT = "always_on"
_PEER_SCOPE = "same_trade_date_excluding_symbol"


def describe_source() -> SourceDescriptor:
    return SourceDescriptor(
        name="databento_watchlist_csv",
        path_hint="reports/databento_watchlist_top5_pre1530.csv",
        capabilities=SourceCapabilities(
            has_structure=True,
            has_meta=True,
            structure_mode="partial",
            meta_mode="partial",
        ),
        notes=[
            "Real repo watchlist source with symbol and trade-date context.",
            "Volume regime is derived from same-day premarket liquidity columns when available and surfaced as UNKNOWN otherwise.",
            "Does not publish explicit BOS/OB/FVG/sweep events; structure mapping remains explicit empty lists.",
        ],
    )


def _load_rows() -> list[dict[str, str]]:
    if not WATCHLIST_CSV.exists():
        raise FileNotFoundError(f"watchlist source not found: {WATCHLIST_CSV}")

    with WATCHLIST_CSV.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]

    if not rows:
        raise ValueError(f"watchlist source is empty: {WATCHLIST_CSV}")
    return rows


def _select_symbol_row(rows: list[dict[str, str]], symbol: str) -> dict[str, str]:
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("symbol must not be empty")

    matching = [row for row in rows if str(row.get("symbol", "")).strip().upper() == wanted]
    if not matching:
        raise ValueError(f"symbol {wanted} not present in watchlist source")

    latest_trade_date = max(str(row.get("trade_date", "")).strip() for row in matching)
    latest_rows = [row for row in matching if str(row.get("trade_date", "")).strip() == latest_trade_date]

    def _rank_value(row: dict[str, str]) -> int:
        raw = str(row.get("watchlist_rank", "")).strip()
        try:
            return int(raw)
        except ValueError:
            return 10**9

    return sorted(latest_rows, key=_rank_value)[0]


def _asof_ts_from_trade_date(trade_date: str) -> float:
    parsed = datetime.fromisoformat(trade_date).date()
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC).timestamp()


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _same_trade_date_peer_rows(rows: list[dict[str, str]], trade_date: str, symbol: str) -> list[dict[str, str]]:
    wanted = str(symbol).strip().upper()
    return [
        row
        for row in rows
        if str(row.get("trade_date", "")).strip() == trade_date
        and str(row.get("symbol", "")).strip().upper() != wanted
    ]


def _positive_peer_values(rows: list[dict[str, str]], field_name: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw_value = _coerce_optional_float(row.get(field_name))
        if raw_value is None or raw_value <= 0:
            continue
        values.append(raw_value)
    return values


def _extract_rvol_value(row: dict[str, str]) -> tuple[float | None, str | None]:
    for field_name in _RVOL_FIELD_CANDIDATES:
        raw_value = _coerce_optional_float(row.get(field_name))
        if raw_value is None:
            continue
        return raw_value, field_name
    return None, None


def _extract_daily_bar_rvol(
    row: dict[str, str],
    peer_rows: list[dict[str, str]],
) -> dict[str, Any] | None:
    for volume_field in _DAILY_VOLUME_FIELD_CANDIDATES:
        current_volume = _coerce_optional_float(row.get(volume_field))
        if current_volume is None or current_volume <= 0:
            continue

        for avg_field in _DAILY_AVG_VOLUME_FIELD_CANDIDATES:
            avg_volume = _coerce_optional_float(row.get(avg_field))
            if avg_volume is None or avg_volume <= 0:
                continue
            return {
                "rvol": current_volume / avg_volume,
                "daily_volume_field": volume_field,
                "daily_volume_baseline": avg_field,
                "model_source": "daily_bar_rvol_explicit_average",
                "selected_baseline": "explicit_average_volume",
            }

        peer_values = _positive_peer_values(peer_rows, volume_field)
        if not peer_values:
            continue
        peer_median = statistics.median(peer_values)
        if peer_median <= 0:
            continue
        return {
            "rvol": current_volume / peer_median,
            "daily_volume_field": volume_field,
            "daily_volume_baseline": f"peer_median:{volume_field}",
            "model_source": "daily_bar_rvol_peer_median",
            "selected_baseline": "peer_median_same_trade_date",
            "peer_count": len(peer_values),
            "peer_scope": _PEER_SCOPE,
        }

    return None


def _volume_contract_fields(*, model_source: str, selected_baseline: str) -> dict[str, Any]:
    return {
        "contract_version": _VOLUME_REGIME_CONTRACT_VERSION,
        "baseline_priority_order": list(_VOLUME_REGIME_BASELINE_PRIORITY_ORDER),
        "selected_baseline": selected_baseline,
        "model_source": model_source,
        "peer_median_rollout": _PEER_MEDIAN_ROLLOUT,
    }


def _derive_volume_meta(row: dict[str, str], peer_rows: list[dict[str, str]]) -> dict[str, Any]:
    rvol_value, rvol_field = _extract_rvol_value(row)
    if rvol_value is not None:
        regime, thin_fraction = classify_volume_regime_from_rvol(rvol_value)
        if regime != "UNKNOWN":
            return {
                **_volume_contract_fields(model_source="explicit_rvol", selected_baseline="rvol"),
                "regime": regime,
                "thin_fraction": thin_fraction,
                "source": "rvol",
                "rvol": round(rvol_value, 4),
                "rvol_field": rvol_field,
            }

    daily_bar_rvol = _extract_daily_bar_rvol(row, peer_rows)
    if daily_bar_rvol is not None:
        regime, thin_fraction = classify_volume_regime_from_rvol(daily_bar_rvol["rvol"])
        if regime != "UNKNOWN":
            return {
                **_volume_contract_fields(
                    model_source=str(daily_bar_rvol.get("model_source") or "daily_bar_rvol_explicit_average"),
                    selected_baseline=str(daily_bar_rvol.get("selected_baseline") or "explicit_average_volume"),
                ),
                "regime": regime,
                "thin_fraction": thin_fraction,
                "source": "daily_bar_rvol",
                "rvol": round(float(daily_bar_rvol["rvol"]), 4),
                "daily_volume_field": daily_bar_rvol.get("daily_volume_field"),
                "daily_volume_baseline": daily_bar_rvol.get("daily_volume_baseline"),
                "peer_count": daily_bar_rvol.get("peer_count"),
                "peer_scope": daily_bar_rvol.get("peer_scope"),
            }

    liquidity_ratios: list[float] = []
    for field_name in ("premarket_volume", "premarket_trade_count"):
        peer_values = _positive_peer_values(peer_rows, field_name)
        row_value = _coerce_optional_float(row.get(field_name))
        if row_value is None or row_value < 0 or not peer_values:
            continue
        peer_median = statistics.median(peer_values)
        if peer_median <= 0:
            continue
        liquidity_ratios.append(max(0.0, row_value) / peer_median)

    if not liquidity_ratios:
        _LOG.warning(
            "databento volume regime UNKNOWN for %s on %s: no usable RVOL or premarket liquidity evidence",
            str(row.get("symbol") or "").strip().upper() or "?",
            str(row.get("trade_date") or "").strip() or "?",
        )
        return {
            **_volume_contract_fields(model_source="missing_baseline", selected_baseline="none"),
            "regime": "UNKNOWN",
            "thin_fraction": None,
            "source": "none",
        }

    liquidity_ratio = min(liquidity_ratios)
    clamped_ratio = min(max(liquidity_ratio, 0.0), 1.0)
    thin_fraction = round(1.0 - clamped_ratio, 4)

    regime = "NORMAL"
    if liquidity_ratio <= 0.2:
        regime = "HOLIDAY_SUSPECT"
    elif liquidity_ratio <= 0.6:
        regime = "LOW_VOLUME"

    return {
        **_volume_contract_fields(
            model_source="premarket_liquidity_peer_median",
            selected_baseline="premarket_liquidity",
        ),
        "regime": regime,
        "thin_fraction": thin_fraction,
        "source": "premarket_liquidity",
        "peer_scope": _PEER_SCOPE,
    }


def load_raw_structure_input(symbol: str, timeframe: str) -> dict[str, Any]:
    del timeframe
    rows = _load_rows()
    _select_symbol_row(rows, symbol)
    return {
        "bos": [],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }


def load_raw_meta_input(symbol: str, timeframe: str, **_kwargs: Any) -> dict[str, Any]:
    rows = _load_rows()
    row = _select_symbol_row(rows, symbol)
    normalized_symbol = str(row.get("symbol", symbol)).strip().upper()

    trade_date = str(row.get("trade_date", "")).strip()
    if not trade_date:
        raise ValueError("watchlist row is missing trade_date")

    asof_ts = _asof_ts_from_trade_date(trade_date)
    volume_meta = _derive_volume_meta(row, _same_trade_date_peer_rows(rows, trade_date, normalized_symbol))

    payload: dict[str, Any] = {
        "symbol": normalized_symbol,
        "timeframe": str(timeframe).strip(),
        "asof_ts": asof_ts,
        "volume": {
            "value": volume_meta,
            "asof_ts": asof_ts,
            "stale": False,
        },
        "provenance": [
            "repo:reports/databento_watchlist_top5_pre1530.csv",
            f"repo:reports/databento_watchlist_top5_pre1530.csv#symbol={normalized_symbol}",
            f"repo:reports/databento_watchlist_top5_pre1530.csv#trade_date={trade_date}",
            "smc_integration:partial_structure_only",
        ],
    }

    contract_version = str(volume_meta.get("contract_version") or "").strip()
    model_source = str(volume_meta.get("model_source") or "").strip()
    selected_baseline = str(volume_meta.get("selected_baseline") or "").strip()
    peer_median_rollout = str(volume_meta.get("peer_median_rollout") or "").strip()
    peer_scope = str(volume_meta.get("peer_scope") or "").strip()
    peer_count = volume_meta.get("peer_count")

    if contract_version:
        payload["provenance"].append(f"smc_integration:volume_regime_contract_version={contract_version}")
    if model_source:
        payload["provenance"].append(f"smc_integration:volume_regime_model_source={model_source}")
    if selected_baseline:
        payload["provenance"].append(f"smc_integration:volume_regime_selected_baseline={selected_baseline}")
    if peer_median_rollout:
        payload["provenance"].append(f"smc_integration:volume_regime_peer_median_rollout={peer_median_rollout}")
    if peer_scope:
        payload["provenance"].append(f"smc_integration:volume_regime_peer_scope={peer_scope}")
    if isinstance(peer_count, int):
        payload["provenance"].append(f"smc_integration:volume_regime_peer_count={peer_count}")

    if volume_meta.get("regime") == "UNKNOWN":
        payload["provenance"].append("smc_integration:volume_regime_unknown_no_premarket_liquidity")
    elif volume_meta.get("source") == "rvol":
        payload["provenance"].append("smc_integration:volume_regime_derived_from_rvol")
        rvol_field = str(volume_meta.get("rvol_field") or "").strip()
        if rvol_field:
            payload["provenance"].append(
                f"smc_integration:volume_regime_rvol_field={rvol_field}"
            )
    elif volume_meta.get("source") == "daily_bar_rvol":
        payload["provenance"].append("smc_integration:volume_regime_derived_from_daily_bar_rvol")
        daily_volume_field = str(volume_meta.get("daily_volume_field") or "").strip()
        daily_volume_baseline = str(volume_meta.get("daily_volume_baseline") or "").strip()
        if daily_volume_field:
            payload["provenance"].append(
                f"smc_integration:volume_regime_daily_volume_field={daily_volume_field}"
            )
        if daily_volume_baseline:
            payload["provenance"].append(
                f"smc_integration:volume_regime_daily_volume_baseline={daily_volume_baseline}"
            )
    else:
        payload["provenance"].append("smc_integration:volume_regime_derived_from_premarket_liquidity")

    return payload
