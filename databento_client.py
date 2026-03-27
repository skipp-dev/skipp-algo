"""Databento SDK client wrapper and retry infrastructure.

This module owns the Databento SDK import, client construction,
TLS certificate normalization, schema-available-end queries,
request-end clamping, and the get_range retry loop.

**No feature / pipeline logic lives here.**  Higher-level consumers
(``databento_provider``, pipeline scripts) import these building blocks
and compose them into domain workflows.

Backward compatibility:  all names exported from this module are still
importable from ``databento_volatility_screener`` via re-export shims.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import re
import time as time_module
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import certifi
import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

DATABENTO_GET_RANGE_MAX_ATTEMPTS = 3

_API_KEY_REDACTION_PATTERNS = (
    re.compile(r"(api[_-]?key=)([^&\s]+)", flags=re.IGNORECASE),
    re.compile(r"(token=)([^&\s]+)", flags=re.IGNORECASE),
    re.compile(r"(Authorization:\s*Bearer\s+)([^\s]+)", flags=re.IGNORECASE),
)


# ── TLS / certificate helpers ──────────────────────────────────────────────

def _normalize_tls_certificate_env() -> str:
    """Ensure TLS CA-bundle env vars point to valid paths (falls back to certifi)."""
    cafile = str(certifi.where())
    for env_name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        current = str(os.getenv(env_name) or "").strip()
        if not current or current == cafile:
            continue
        if Path(current).exists():
            continue
        logger.warning(
            "Replacing invalid TLS CA bundle path from %s=%s with certifi bundle %s.",
            env_name,
            current,
            cafile,
        )
        os.environ[env_name] = cafile
    return cafile


# ── SDK import & client construction ────────────────────────────────────────

def _import_databento() -> Any:
    """Import the ``databento`` package, cleaning up stray event loops it creates."""
    existing_loop_ids = {
        id(obj)
        for obj in gc.get_objects()
        if isinstance(obj, asyncio.AbstractEventLoop)
    }
    import databento as db

    for obj in gc.get_objects():
        if not isinstance(obj, asyncio.AbstractEventLoop):
            continue
        if id(obj) in existing_loop_ids:
            continue
        if obj.is_closed() or obj.is_running():
            continue
        obj.close()

    return db


def _make_databento_client(api_key: str | None = None) -> Any:
    """Return a ``databento.Historical`` client, normalizing TLS first."""
    _normalize_tls_certificate_env()
    db = _import_databento()
    return db.Historical(api_key or os.getenv("DATABENTO_API_KEY"))


# ── Schema / request-end helpers ────────────────────────────────────────────

def _get_schema_available_end(client: Any, dataset: str, schema: str) -> pd.Timestamp | None:
    """Query the latest available timestamp for *dataset/schema*."""
    try:
        dataset_range = client.metadata.get_dataset_range(dataset=dataset)
    except Exception:
        logger.debug("metadata.get_dataset_range failed for %s/%s; clamping disabled", dataset, schema, exc_info=True)
        return None
    if not isinstance(dataset_range, dict):
        return None
    schema_ranges = dataset_range.get("schema")
    if isinstance(schema_ranges, dict):
        schema_info = schema_ranges.get(schema)
        if isinstance(schema_info, dict):
            end_value = schema_info.get("end")
            if end_value:
                return pd.Timestamp(end_value, tz=UTC)
    end_value = dataset_range.get("end")
    if not end_value:
        return None
    return pd.Timestamp(end_value, tz=UTC)


def _clamp_request_end(requested_end: pd.Timestamp, available_end: pd.Timestamp | None) -> pd.Timestamp:
    """Return *min(requested_end, available_end)*, or *requested_end* if unknown."""
    if available_end is None:
        return requested_end
    return min(requested_end, available_end)


def _exclusive_ohlcv_1s_end(logical_end: datetime | pd.Timestamp) -> pd.Timestamp:
    """Shift *logical_end* by +1 s to form an exclusive end for ohlcv-1s requests."""
    end_timestamp = pd.Timestamp(logical_end)
    if end_timestamp.tzinfo is None:
        end_timestamp = end_timestamp.tz_localize(UTC)
    return end_timestamp + pd.Timedelta(seconds=1)


def _daily_request_end_exclusive(last_trading_day: date, available_end: pd.Timestamp | None) -> date:
    """Compute the exclusive calendar-day end for a daily-bars request."""
    requested_end = pd.Timestamp(last_trading_day + timedelta(days=1), tz=UTC)
    clamped_end = _clamp_request_end(requested_end, available_end)
    clamped_dt = pd.Timestamp(clamped_end).to_pydatetime()
    end_date = date(clamped_dt.year, clamped_dt.month, clamped_dt.day)
    if clamped_dt.hour or clamped_dt.minute or clamped_dt.second or clamped_dt.microsecond:
        end_date += timedelta(days=1)
    return end_date


# ── Redaction helpers ───────────────────────────────────────────────────────

def _redact_sensitive_error_text(text: str) -> str:
    """Scrub API keys / tokens from error messages."""
    redacted = str(text)
    for pattern in _API_KEY_REDACTION_PATTERNS:
        redacted = pattern.sub(r"\1***", redacted)
    return redacted


def _warn_with_redacted_exception(message: str, exc: BaseException, *, include_traceback: bool = False) -> None:
    """Log a warning with sensitive data redacted from the exception text."""
    logger.warning("%s: %s", message, _redact_sensitive_error_text(str(exc)), exc_info=include_traceback)


# ── Retry logic ─────────────────────────────────────────────────────────────

def _is_retryable_databento_get_range_error(exc: BaseException) -> bool:
    """Return True if *exc* looks like a transient Databento API error."""
    message = _redact_sensitive_error_text(str(exc)).lower()
    if not message:
        return False
    retryable_fragments = (
        "read timed out",
        "timed out",
        "too many requests",
        "429",
        "503",
        "504",
        "service unavailable",
        "gateway timeout",
        "connection aborted",
        "connection broken",
        "connection reset",
        "remote end closed connection without response",
        "remotedisconnected",
        "temporarily unavailable",
    )
    return any(fragment in message for fragment in retryable_fragments)


def _databento_get_range_with_retry(client: Any, *, context: str, **kwargs: Any) -> Any:
    """Call ``client.timeseries.get_range`` with automatic retry on transient errors."""
    last_exc: BaseException | None = None
    for attempt in range(1, DATABENTO_GET_RANGE_MAX_ATTEMPTS + 1):
        try:
            _normalize_tls_certificate_env()
            return client.timeseries.get_range(**kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt >= DATABENTO_GET_RANGE_MAX_ATTEMPTS or not _is_retryable_databento_get_range_error(exc):
                raise
            wait_seconds = float(2 ** (attempt - 1))
            logger.warning(
                "%s: transient Databento get_range failure (%s). Retrying in %.0fs (%d/%d).",
                context,
                _redact_sensitive_error_text(str(exc)),
                wait_seconds,
                attempt,
                DATABENTO_GET_RANGE_MAX_ATTEMPTS,
            )
            time_module.sleep(wait_seconds)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{context}: Databento get_range retry loop exited unexpectedly")


# ── Dataset enumeration ────────────────────────────────────────────────────

def list_accessible_datasets(databento_api_key: str | None = None) -> list[str]:
    """Return sorted list of datasets the API key can access."""
    client = _make_databento_client(databento_api_key)
    datasets = client.metadata.list_datasets()
    return sorted({str(dataset) for dataset in datasets if dataset})
