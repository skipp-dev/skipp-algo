from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from typing import Any


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _unique_preserve_order(values: list[str]) -> list[str]:
    return list(OrderedDict.fromkeys(values))


def _domain_payload(raw_meta: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    value = raw_meta.get(key)
    if not isinstance(value, Mapping):
        return None
    return dict(value)


def merge_raw_meta_domains(
    *,
    volume_meta: Mapping[str, Any],
    technical_meta: Mapping[str, Any] | None,
    news_meta: Mapping[str, Any] | None,
    domain_sources: Mapping[str, str],
) -> dict[str, Any]:
    volume_raw = _as_mapping(volume_meta)
    technical_raw = _as_mapping(technical_meta) if technical_meta is not None else {}
    news_raw = _as_mapping(news_meta) if news_meta is not None else {}

    symbol = _coerce_str(volume_raw.get("symbol")) or _coerce_str(technical_raw.get("symbol")) or _coerce_str(news_raw.get("symbol"))
    timeframe = _coerce_str(volume_raw.get("timeframe")) or _coerce_str(technical_raw.get("timeframe")) or _coerce_str(news_raw.get("timeframe"))
    if not symbol:
        raise ValueError("merged raw_meta requires symbol")
    if not timeframe:
        raise ValueError("merged raw_meta requires timeframe")

    asof_candidates = [
        _coerce_float(volume_raw.get("asof_ts")),
        _coerce_float(technical_raw.get("asof_ts")),
        _coerce_float(news_raw.get("asof_ts")),
    ]
    asof_values = [value for value in asof_candidates if value is not None]
    if not asof_values:
        raise ValueError("merged raw_meta requires at least one numeric asof_ts")
    merged_asof_ts = max(asof_values)

    volume = _domain_payload(volume_raw, "volume")
    if volume is None:
        raise ValueError("merged raw_meta requires volume payload")

    merged: dict[str, Any] = {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "asof_ts": merged_asof_ts,
        "volume": volume,
    }

    technical = _domain_payload(technical_raw, "technical")
    if technical is not None:
        merged["technical"] = technical

    news = _domain_payload(news_raw, "news")
    if news is not None:
        merged["news"] = news

    # --- Domain visibility: track which meta domains are present vs missing ---
    meta_domains_present: list[str] = ["volume"]
    meta_domains_missing: list[str] = []
    if technical is not None:
        meta_domains_present.append("technical")
    else:
        meta_domains_missing.append("technical")
    if news is not None:
        meta_domains_present.append("news")
    else:
        meta_domains_missing.append("news")
    merged["meta_domains_present"] = meta_domains_present
    merged["meta_domains_missing"] = meta_domains_missing

    provenance: list[str] = []
    for raw in (volume_raw, technical_raw, news_raw):
        items = raw.get("provenance", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item.strip():
                    provenance.append(item)

    summary_parts = [
        f"structure={domain_sources.get('structure', 'n/a')}",
        f"volume={domain_sources.get('volume', 'n/a')}",
        f"technical={domain_sources.get('technical', 'n/a')}",
        f"news={domain_sources.get('news', 'n/a')}",
    ]
    provenance.append("smc_integration:composite_meta[" + ",".join(summary_parts) + "]")
    merged["provenance"] = _unique_preserve_order(provenance)

    return merged