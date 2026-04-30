"""Databento reference-data helpers for corporate-actions alias resolution.

This module owns the optional Reference API integration for corporate-actions
events such as ``LCC``, ``BBCC``, ``BBEC``, and ``ICC``. It caches normalized
event rows locally, derives a current symbol-alias map and identifier snapshot,
and degrades safely when the account lacks the reference dataset subscription.

The cache is intentionally file-backed so normalization paths can consult the
latest known alias map without hitting the network on every call.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
import threading
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from databento_client import _make_databento_reference_client, _redact_sensitive_error_text

logger = logging.getLogger(__name__)

CORPORATE_ACTION_CACHE_VERSION = 1
CORPORATE_ACTION_CACHE_TTL_SECONDS = 6 * 3600
CORPORATE_ACTION_FAILURE_TTL_SECONDS = 24 * 3600
CORPORATE_ACTION_BATCH_SIZE = 250
CORPORATE_ACTION_START_DATE = date(2018, 5, 1)
REFERENCE_EVENT_RISK_WINDOW_DAYS = 14
CORPORATE_ACTION_IDENTIFIER_EVENTS = (
    "BBCC",
    "BBEC",
    "DRCHG",
    "ICC",
    "ISCHG",
    "LCC",
    "LSTAT",
    "PRCHG",
    "SCCHG",
    "SDCHG",
)
REFERENCE_CACHE_ROOT = Path(__file__).resolve().parent / "artifacts" / "databento_reference_cache"
REFERENCE_CACHE_FILE = "corporate_actions_reference_state.json"

_STATE_CACHE_PATH: str | None = None
_STATE_CACHE_MTIME: float | None = None
_STATE_CACHE_VALUE: dict[str, Any] | None = None
_STATE_CACHE_LOCK = threading.Lock()


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, 0)


def _cache_root(cache_dir: str | Path | None = None) -> Path:
    if cache_dir is not None:
        root = Path(cache_dir)
    else:
        configured = str(os.getenv("DATABENTO_REFERENCE_CACHE_DIR") or "").strip()
        root = Path(configured) if configured else REFERENCE_CACHE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_path(cache_dir: str | Path | None = None) -> Path:
    return _cache_root(cache_dir) / REFERENCE_CACHE_FILE


def _default_state() -> dict[str, Any]:
    return {
        "version": CORPORATE_ACTION_CACHE_VERSION,
        "provider_status": "uninitialized",
        "fetched_at": None,
        "last_attempted_at": None,
        "last_error": "",
        "coverage_symbols": [],
        "events": [],
        "symbol_aliases": {},
        "identifier_map": {},
    }


def _replace_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)
        raise


def _invalidate_state_cache() -> None:
    global _STATE_CACHE_PATH, _STATE_CACHE_MTIME, _STATE_CACHE_VALUE
    with _STATE_CACHE_LOCK:
        _STATE_CACHE_PATH = None
        _STATE_CACHE_MTIME = None
        _STATE_CACHE_VALUE = None


def _load_state(cache_dir: str | Path | None = None) -> dict[str, Any]:
    global _STATE_CACHE_PATH, _STATE_CACHE_MTIME, _STATE_CACHE_VALUE
    path = _cache_path(cache_dir)
    path_str = str(path)
    mtime = path.stat().st_mtime if path.exists() else None
    with _STATE_CACHE_LOCK:
        if (
            _STATE_CACHE_VALUE is not None
            and path_str == _STATE_CACHE_PATH
            and mtime == _STATE_CACHE_MTIME
        ):
            return _STATE_CACHE_VALUE

    state = _default_state()
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            logger.warning("Failed to read Databento reference cache %s", path, exc_info=True)
    with _STATE_CACHE_LOCK:
        _STATE_CACHE_PATH = path_str
        _STATE_CACHE_MTIME = mtime
        _STATE_CACHE_VALUE = state
        return state


def _save_state(state: dict[str, Any], cache_dir: str | Path | None = None) -> dict[str, Any]:
    path = _cache_path(cache_dir)
    serialized = json.dumps(state, indent=2, sort_keys=True)
    _replace_atomic(path, serialized)
    _invalidate_state_cache()
    return _load_state(cache_dir)


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _coerce_as_of_date(value: date | datetime | None) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    return datetime.now(UTC).date()


def _parse_effective_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _state_age_seconds(state: dict[str, Any], *, failure: bool) -> float | None:
    key = "last_attempted_at" if failure else "fetched_at"
    timestamp = _parse_iso_timestamp(state.get(key))
    if timestamp is None:
        return None
    return max((datetime.now(UTC) - timestamp).total_seconds(), 0.0)


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_symbol_token(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if not text or text in {"NONE", "NAN", "NULL"}:
        return ""
    return re.sub(r"\s+", "", text)


def _normalize_identifier_token(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if not text or text in {"NONE", "NAN", "NULL"}:
        return ""
    return text


def _normalize_event_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10]


def _normalized_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


def _build_row_lookup(row: dict[str, Any]) -> dict[str, Any]:
    return {_normalized_key(key): value for key, value in row.items()}


def _pick_row_value(row_lookup: dict[str, Any], *candidates: str) -> Any:
    for candidate in candidates:
        value = row_lookup.get(_normalized_key(candidate))
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except TypeError:
            pass
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _event_identity(record: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(record.get("event") or ""),
        str(record.get("effective_date") or ""),
        str(record.get("listing_symbol") or ""),
        str(record.get("old_symbol") or ""),
        str(record.get("new_symbol") or ""),
        str(record.get("old_bbg_comp_id") or ""),
        str(record.get("new_bbg_comp_id") or ""),
        str(record.get("old_figi") or ""),
        str(record.get("new_figi") or ""),
        str(record.get("old_isin") or ""),
        str(record.get("new_isin") or ""),
        str(record.get("old_sedol") or ""),
        str(record.get("new_sedol") or ""),
    )


def _extract_event_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []

    records: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        lookup = _build_row_lookup(row)
        event = _normalize_identifier_token(_pick_row_value(lookup, "event", "event_type"))
        if not event:
            continue
        listing_symbol = _normalize_symbol_token(_pick_row_value(lookup, "raw_symbol", "symbol", "listing_symbol"))
        record = {
            "event": event,
            "effective_date": _normalize_event_date(
                _pick_row_value(lookup, "effective_date", "event_date", "primary_date", "name_change_date")
            ),
            "listing_symbol": listing_symbol,
            "old_symbol": _normalize_symbol_token(
                _pick_row_value(
                    lookup,
                    "old_localcode",
                    "old_bbg_comp_ticker",
                    "old_figi_ticker",
                )
            ),
            "new_symbol": _normalize_symbol_token(
                _pick_row_value(
                    lookup,
                    "new_localcode",
                    "new_bbg_comp_ticker",
                    "new_figi_ticker",
                    "raw_symbol",
                    "symbol",
                )
            ),
            "old_bbg_comp_id": _normalize_identifier_token(_pick_row_value(lookup, "old_bbg_comp_id")),
            "new_bbg_comp_id": _normalize_identifier_token(_pick_row_value(lookup, "new_bbg_comp_id")),
            "old_bbg_comp_ticker": _normalize_symbol_token(_pick_row_value(lookup, "old_bbg_comp_ticker")),
            "new_bbg_comp_ticker": _normalize_symbol_token(_pick_row_value(lookup, "new_bbg_comp_ticker")),
            "old_figi": _normalize_identifier_token(_pick_row_value(lookup, "old_figi")),
            "new_figi": _normalize_identifier_token(_pick_row_value(lookup, "new_figi")),
            "old_figi_ticker": _normalize_symbol_token(_pick_row_value(lookup, "old_figi_ticker")),
            "new_figi_ticker": _normalize_symbol_token(_pick_row_value(lookup, "new_figi_ticker")),
            "old_isin": _normalize_identifier_token(_pick_row_value(lookup, "old_isin", "old_i_s_i_n")),
            "new_isin": _normalize_identifier_token(_pick_row_value(lookup, "new_isin", "new_i_s_i_n")),
            "old_sedol": _normalize_identifier_token(_pick_row_value(lookup, "old_sedol")),
            "new_sedol": _normalize_identifier_token(_pick_row_value(lookup, "new_sedol")),
            "old_exchange": _normalize_identifier_token(_pick_row_value(lookup, "old_exchange")),
            "new_exchange": _normalize_identifier_token(_pick_row_value(lookup, "new_exchange")),
            "old_country": _normalize_identifier_token(_pick_row_value(lookup, "old_country")),
            "new_country": _normalize_identifier_token(_pick_row_value(lookup, "new_country")),
            "issuer_old_name": _normalize_identifier_token(_pick_row_value(lookup, "issuer_old_name")),
            "issuer_new_name": _normalize_identifier_token(_pick_row_value(lookup, "issuer_new_name")),
            "security_old_name": _normalize_identifier_token(_pick_row_value(lookup, "security_old_name")),
            "security_new_name": _normalize_identifier_token(_pick_row_value(lookup, "security_new_name")),
        }
        if not any(
            record.get(key)
            for key in (
                "old_symbol",
                "new_symbol",
                "old_bbg_comp_id",
                "new_bbg_comp_id",
                "old_figi",
                "new_figi",
                "old_isin",
                "new_isin",
                "old_sedol",
                "new_sedol",
                "old_exchange",
                "new_exchange",
                "old_country",
                "new_country",
                "issuer_old_name",
                "issuer_new_name",
                "security_old_name",
                "security_new_name",
            )
        ):
            continue
        records.append(record)
    return records


def _merge_event_records(existing: list[dict[str, Any]], new_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {_event_identity(record): dict(record) for record in existing}
    for record in new_records:
        merged[_event_identity(record)] = dict(record)
    return sorted(
        merged.values(),
        key=lambda record: (
            str(record.get("effective_date") or ""),
            str(record.get("event") or ""),
            str(record.get("old_symbol") or ""),
            str(record.get("new_symbol") or ""),
        ),
    )


def _resolve_alias_chain(alias_edges: dict[str, str], symbol: str) -> str:
    current = symbol
    seen: set[str] = set()
    while current in alias_edges and current not in seen:
        seen.add(current)
        current = alias_edges[current]
    return current


def _build_symbol_aliases(records: list[dict[str, Any]]) -> dict[str, str]:
    alias_edges: dict[str, str] = {}
    sorted_records = sorted(records, key=lambda record: str(record.get("effective_date") or ""))
    for record in sorted_records:
        for old_value, new_value in (
            (record.get("old_symbol"), record.get("new_symbol")),
            (record.get("old_bbg_comp_ticker"), record.get("new_bbg_comp_ticker")),
            (record.get("old_figi_ticker"), record.get("new_figi_ticker")),
        ):
            old_symbol = _normalize_symbol_token(old_value)
            new_symbol = _normalize_symbol_token(new_value)
            if old_symbol and new_symbol and old_symbol != new_symbol:
                alias_edges[old_symbol] = new_symbol
    return {
        old_symbol: _resolve_alias_chain(alias_edges, old_symbol)
        for old_symbol in sorted(alias_edges)
    }


def _build_identifier_map(records: list[dict[str, Any]], symbol_aliases: dict[str, str]) -> dict[str, dict[str, Any]]:
    identifier_map: dict[str, dict[str, Any]] = {}
    for record in sorted(records, key=lambda item: str(item.get("effective_date") or "")):
        symbol_candidates = [
            _normalize_symbol_token(record.get("new_symbol")),
            _normalize_symbol_token(record.get("listing_symbol")),
            _normalize_symbol_token(record.get("old_symbol")),
            _normalize_symbol_token(record.get("new_bbg_comp_ticker")),
            _normalize_symbol_token(record.get("new_figi_ticker")),
        ]
        canonical_symbol = ""
        for candidate in symbol_candidates:
            if candidate:
                canonical_symbol = symbol_aliases.get(candidate, candidate)
                break
        if not canonical_symbol:
            continue

        entry = identifier_map.setdefault(
            canonical_symbol,
            {
                "aliases": [],
                "events": [],
                "latest_effective_date": "",
                "identifiers": {},
            },
        )
        for old_symbol in (
            _normalize_symbol_token(record.get("old_symbol")),
            _normalize_symbol_token(record.get("old_bbg_comp_ticker")),
            _normalize_symbol_token(record.get("old_figi_ticker")),
        ):
            if old_symbol and old_symbol != canonical_symbol and old_symbol not in entry["aliases"]:
                entry["aliases"].append(old_symbol)

        event_summary = {
            "event": str(record.get("event") or ""),
            "effective_date": str(record.get("effective_date") or ""),
        }
        if event_summary not in entry["events"]:
            entry["events"].append(event_summary)

        effective_date = str(record.get("effective_date") or "")
        if effective_date >= str(entry.get("latest_effective_date") or ""):
            entry["latest_effective_date"] = effective_date

        for key, old_key, new_key in (
            ("bbg_comp_id", "old_bbg_comp_id", "new_bbg_comp_id"),
            ("figi", "old_figi", "new_figi"),
            ("isin", "old_isin", "new_isin"),
            ("sedol", "old_sedol", "new_sedol"),
            ("exchange", "old_exchange", "new_exchange"),
            ("country", "old_country", "new_country"),
        ):
            previous = _normalize_identifier_token(record.get(old_key))
            current = _normalize_identifier_token(record.get(new_key))
            if previous or current:
                entry["identifiers"][key] = {
                    "previous": previous,
                    "current": current or previous,
                    "effective_date": effective_date,
                    "event": str(record.get("event") or ""),
                }

        for key, old_key, new_key in (
            ("issuer_name", "issuer_old_name", "issuer_new_name"),
            ("security_name", "security_old_name", "security_new_name"),
        ):
            previous = _normalize_identifier_token(record.get(old_key))
            current = _normalize_identifier_token(record.get(new_key))
            if previous or current:
                entry["identifiers"][key] = {
                    "previous": previous,
                    "current": current or previous,
                    "effective_date": effective_date,
                    "event": str(record.get("event") or ""),
                }

    return identifier_map


def get_cached_symbol_aliases(cache_dir: str | Path | None = None) -> dict[str, str]:
    state = _load_state(cache_dir)
    raw_aliases = state.get("symbol_aliases")
    if not isinstance(raw_aliases, dict):
        return {}
    return {
        _normalize_symbol_token(old_symbol): _normalize_symbol_token(new_symbol)
        for old_symbol, new_symbol in raw_aliases.items()
        if _normalize_symbol_token(old_symbol) and _normalize_symbol_token(new_symbol)
    }


def get_cached_identifier_map(cache_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    state = _load_state(cache_dir)
    raw_map = state.get("identifier_map")
    if not isinstance(raw_map, dict):
        return {}
    return raw_map


def get_reference_event_risk_snapshot(
    symbols: Iterable[str],
    *,
    as_of: date | datetime | None = None,
    lookback_days: int | None = None,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    requested_symbols = sorted(
        {
            normalized
            for symbol in symbols
            if (normalized := _normalize_symbol_token(symbol))
        }
    )
    state = _load_state(cache_dir)
    window_days = _env_int(
        "DATABENTO_REFERENCE_EVENT_RISK_WINDOW_DAYS",
        REFERENCE_EVENT_RISK_WINDOW_DAYS,
    ) if lookback_days is None else max(int(lookback_days), 0)
    effective_as_of = _coerce_as_of_date(as_of)
    cutoff = effective_as_of - timedelta(days=window_days)
    alias_map = get_cached_symbol_aliases(cache_dir)
    identifier_map = get_cached_identifier_map(cache_dir)

    by_symbol: dict[str, dict[str, Any]] = {}
    recent_change_tickers: list[str] = []

    for requested_symbol in requested_symbols:
        canonical_symbol = alias_map.get(requested_symbol, requested_symbol)
        entry = identifier_map.get(canonical_symbol)
        if not isinstance(entry, dict):
            continue

        raw_events = entry.get("events")
        if not isinstance(raw_events, list):
            continue

        recent_events: list[dict[str, str]] = []
        for raw_event in raw_events:
            if not isinstance(raw_event, dict):
                continue
            event_date = _parse_effective_date(raw_event.get("effective_date"))
            if event_date is None or event_date < cutoff or event_date > effective_as_of:
                continue
            event_code = str(raw_event.get("event") or "").strip().upper()
            if not event_code:
                continue
            recent_events.append(
                {
                    "event": event_code,
                    "effective_date": event_date.isoformat(),
                }
            )

        if not recent_events:
            continue

        recent_events.sort(key=lambda item: (item["effective_date"], item["event"]))
        aliases = sorted(
            {
                normalized
                for alias in entry.get("aliases") or []
                if (normalized := _normalize_symbol_token(alias))
            }
        )
        event_types = sorted({item["event"] for item in recent_events})
        latest_effective_date = recent_events[-1]["effective_date"]
        by_symbol[requested_symbol] = {
            "canonical_symbol": canonical_symbol,
            "aliases": aliases,
            "event_types": event_types,
            "latest_effective_date": latest_effective_date,
            "recent_events": recent_events,
        }
        if canonical_symbol not in recent_change_tickers:
            recent_change_tickers.append(canonical_symbol)

    return {
        "provider_status": str(state.get("provider_status") or "uninitialized"),
        "as_of": effective_as_of.isoformat(),
        "lookback_days": window_days,
        "reference_change_tickers": sorted(recent_change_tickers),
        "by_symbol": by_symbol,
    }


def resolve_symbol_alias_from_cache(symbol: str, *, cache_dir: str | Path | None = None) -> str:
    normalized = _normalize_symbol_token(symbol)
    if not normalized:
        return ""
    return get_cached_symbol_aliases(cache_dir).get(normalized, normalized)


def maybe_refresh_symbol_reference_cache(
    symbols: Iterable[str],
    *,
    api_key: str | None = None,
    cache_dir: str | Path | None = None,
    force_refresh: bool = False,
    start: date | str | None = None,
    end: date | str | None = None,
    events: Iterable[str] | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    requested_symbols = sorted(
        {
            normalized
            for symbol in symbols
            if (normalized := _normalize_symbol_token(symbol))
        }
    )
    state = _load_state(cache_dir)
    if not requested_symbols:
        return state

    success_ttl = _env_int("DATABENTO_REFERENCE_CACHE_TTL_SECONDS", CORPORATE_ACTION_CACHE_TTL_SECONDS)
    failure_ttl = _env_int("DATABENTO_REFERENCE_FAILURE_TTL_SECONDS", CORPORATE_ACTION_FAILURE_TTL_SECONDS)
    configured_api_key = str(api_key or os.getenv("DATABENTO_API_KEY") or "").strip()
    if not configured_api_key and not force_refresh:
        return state

    coverage_symbols = {
        _normalize_symbol_token(symbol)
        for symbol in state.get("coverage_symbols") or []
        if _normalize_symbol_token(symbol)
    }
    provider_status = str(state.get("provider_status") or "")
    success_age = _state_age_seconds(state, failure=False)
    failure_age = _state_age_seconds(state, failure=True)
    have_full_coverage = set(requested_symbols).issubset(coverage_symbols)

    if not force_refresh:
        if have_full_coverage and success_age is not None and success_age <= success_ttl:
            return state
        if provider_status == "not_subscribed" and failure_age is not None and failure_age <= failure_ttl:
            return state
        if provider_status == "error" and failure_age is not None and failure_age <= failure_ttl:
            return state
        if not configured_api_key:
            return state

    target_symbols = requested_symbols if force_refresh or success_age is None or success_age > success_ttl else [
        symbol for symbol in requested_symbols if symbol not in coverage_symbols
    ]
    if not target_symbols and not force_refresh:
        return state

    current_time = datetime.now(UTC).isoformat(timespec="seconds")
    query_start = start or CORPORATE_ACTION_START_DATE.isoformat()
    query_end = end or datetime.now(UTC).date().isoformat()
    query_events = list(events or CORPORATE_ACTION_IDENTIFIER_EVENTS)

    try:
        reference_client = client if client is not None else _make_databento_reference_client(configured_api_key)
        new_records: list[dict[str, Any]] = []
        for index in range(0, len(target_symbols), CORPORATE_ACTION_BATCH_SIZE):
            batch = target_symbols[index:index + CORPORATE_ACTION_BATCH_SIZE]
            frame = reference_client.corporate_actions.get_range(
                start=query_start,
                end=query_end,
                symbols=batch,
                stype_in="raw_symbol",
                events=query_events,
                flatten=True,
                pit=False,
            )
            if isinstance(frame, pd.DataFrame):
                new_records.extend(_extract_event_records(frame))

        merged_records = _merge_event_records(list(state.get("events") or []), new_records)
        symbol_aliases = _build_symbol_aliases(merged_records)
        identifier_map = _build_identifier_map(merged_records, symbol_aliases)
        coverage_symbols.update(target_symbols)
        updated_state = {
            **state,
            "version": CORPORATE_ACTION_CACHE_VERSION,
            "provider_status": "ok",
            "fetched_at": current_time,
            "last_attempted_at": current_time,
            "last_error": "",
            "coverage_symbols": sorted(coverage_symbols),
            "events": merged_records,
            "symbol_aliases": symbol_aliases,
            "identifier_map": identifier_map,
        }
        return _save_state(updated_state, cache_dir)
    except Exception as exc:
        error_text = _redact_sensitive_error_text(str(exc))
        lowered = error_text.lower()
        provider_status = (
            "not_subscribed"
            if "license_reference_dataset_no_subscription" in lowered
            or "subscription is required" in lowered
            else "error"
        )
        failed_state = {
            **state,
            "version": CORPORATE_ACTION_CACHE_VERSION,
            "provider_status": provider_status,
            "last_attempted_at": current_time,
            "last_error": error_text,
        }
        logger.info("Databento reference cache refresh skipped: %s", error_text)
        return _save_state(failed_state, cache_dir)
