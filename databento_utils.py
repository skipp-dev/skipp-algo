"""Extracted utility functions for Databento pipeline infrastructure.

This module contains cache, symbol-normalization, timezone, frame-processing,
and warning helpers that were previously embedded in the monolithic
``databento_volatility_screener`` module.  They carry **zero** Databento-API
dependency so they can be imported by any consumer without pulling in the
``databento`` package.

Existing consumers may still import these names from
``databento_volatility_screener`` (compatibility is preserved there).  New or
refactored code should import directly from this module.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)

# ── Timezone constants ──────────────────────────────────────────────────────

US_EASTERN_TZ = ZoneInfo("America/New_York")
DEFAULT_DISPLAY_TZ = "Europe/Berlin"
SUPPORTED_DISPLAY_TZ = {
    "America/New_York": ZoneInfo("America/New_York"),
    "Europe/Berlin": ZoneInfo("Europe/Berlin"),
}


def resolve_display_timezone(display_timezone: str) -> tzinfo:
    tz = SUPPORTED_DISPLAY_TZ.get(display_timezone)
    if tz is None:
        raise ValueError(f"Unsupported display timezone: {display_timezone}")
    return tz


# ── Cache constants & helpers ───────────────────────────────────────────────

CACHE_VERSION = "v1"
CACHE_VERSION_BY_CATEGORY = {
    # v3 categories: universe-scope token removed from `parts` (#2334) so the
    # filename is invariant under daily volatility-screener rotation. Bumping
    # the version invalidates v2 cache files that still carry the old token.
    "daily_bars": "v3",
    "symbol_support": "v2",
    "full_universe_open_second_detail": "v3",
    "full_universe_close_trade_detail": "v2",
    "full_universe_close_outcome_minute_detail": "v2",
    "intraday_summary": "v3",
    "symbol_detail_second": "v2",
    "symbol_detail_minute": "v2",
}
CACHE_ROOT = Path(__file__).resolve().parent / "artifacts" / "databento_volatility_cache"

DATA_CACHE_TTL_SECONDS = 4 * 3600  # 4 hours
RECENT_INTRADAY_CACHE_TTL_SECONDS = DATA_CACHE_TTL_SECONDS


def get_cache_root(cache_dir: str | Path | None = None) -> Path:
    root = Path(cache_dir) if cache_dir is not None else CACHE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_cache_path(
    cache_dir: str | Path | None,
    category: str,
    *,
    dataset: str,
    parts: list[str],
    suffix: str = ".parquet",
) -> Path:
    safe_dataset = dataset.replace(".", "_").replace("/", "_")
    normalized = [str(part).replace(":", "-").replace("/", "_").replace(" ", "_") for part in parts]
    cache_version = CACHE_VERSION_BY_CATEGORY.get(category, CACHE_VERSION)
    digest = hashlib.sha1(
        "|".join([cache_version, category, dataset, *normalized]).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:12]
    directory = get_cache_root(cache_dir) / category / safe_dataset
    directory.mkdir(parents=True, exist_ok=True)
    filename = "__".join([*normalized, digest]) + suffix
    return directory / filename


def _read_cached_frame(path: Path, *, max_age_seconds: int | None = None) -> pd.DataFrame | None:
    if not path.exists():
        return None
    if max_age_seconds is not None:
        # ``max_age_seconds == 0`` is the "force-expire" sentinel used to
        # bypass the cache regardless of mtime precision. The Windows
        # NTFS clock has ~10 ms granularity and can record an
        # ``st_mtime`` slightly *in the future* of ``datetime.now(UTC)``
        # right after ``_write_cached_frame`` returns; that would
        # produce a negative ``age`` and incorrectly keep the cache
        # alive against the caller's stated TTL of zero. Short-circuit
        # before the arithmetic. Mirrors the same fix in
        # ``databento_volatility_screener._read_cached_frame`` (#2277).
        if max_age_seconds <= 0:
            logger.info("Cache forcibly expired (TTL=0): %s", path.name)
            return None
        # Clamp non-positive ages to zero so an mtime slightly in the
        # future never *extends* the effective TTL.
        age = max(
            (datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)).total_seconds(),
            0.0,
        )
        if age >= max_age_seconds:
            logger.info("Cache expired (%.1f h old, TTL %.1f h): %s", age / 3600, max_age_seconds / 3600, path.name)
            return None
    try:
        return pd.read_parquet(path)
    except Exception:
        logger.warning("Corrupt cache file removed: %s", path, exc_info=True)
        with contextlib.suppress(OSError):
            path.unlink()
        return None


def _trade_day_cache_max_age_seconds(trade_day: date, latest_trade_day: date | None) -> int | None:
    if latest_trade_day is None:
        return DATA_CACHE_TTL_SECONDS
    if trade_day >= latest_trade_day:
        return 0
    if trade_day >= latest_trade_day - timedelta(days=1):
        return RECENT_INTRADAY_CACHE_TTL_SECONDS
    return None


def _make_atomic_temp_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    return Path(temp_name)


def _replace_atomic(path: Path, write_temp: Callable[[Path], None]) -> None:
    temp_path = _make_atomic_temp_path(path)
    try:
        write_temp(temp_path)
        os.replace(temp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)
        raise


def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    def write_temp(temp_path: Path) -> None:
        frame.to_parquet(temp_path, index=False)

    _replace_atomic(path, write_temp)


def _write_cached_frame(path: Path, frame: pd.DataFrame) -> None:
    _write_parquet_atomic(path, frame)


def _cached_frame_coverage(
    cache_path: Path,
    requested_symbols: Any,
    *,
    max_age_seconds: int | None = None,
    symbol_col: str = "symbol",
) -> tuple[pd.DataFrame | None, set[str]]:
    """Return ``(cached_frame, missing_symbols)`` for a per-key cache file.

    Used by callers whose cache key no longer encodes the requested symbol
    set (#2334) to detect when a cached file is a strict *subset* of the
    current request — in which case the caller must delta-fetch and merge
    the missing symbols rather than silently returning incomplete data.

    Outcomes:
      - ``(None, set(requested))``        cache missing/expired/corrupt → full fetch
      - ``(frame, set())``                cache covers every requested symbol → use as-is
      - ``(frame, missing_subset)``       cache is a subset → delta-fetch ``missing_subset``

    Coverage is determined by the distinct values in ``symbol_col``. A cached
    frame missing that column is treated as corrupt and forces a full fetch.
    """
    cached = _read_cached_frame(cache_path, max_age_seconds=max_age_seconds)
    requested_set = {str(s) for s in requested_symbols}
    if cached is None:
        return None, requested_set
    if symbol_col not in cached.columns:
        logger.warning(
            "Cache file missing %r column, forcing refetch: %s", symbol_col, cache_path.name
        )
        return None, requested_set
    cached_syms = {str(s) for s in cached[symbol_col].dropna().unique()}
    return cached, requested_set - cached_syms


# ── Symbol normalization ────────────────────────────────────────────────────

MAX_SYMBOLS_PER_REQUEST = 2000

DATABENTO_SYMBOL_ALIASES = {
    "BRK-A": "BRK.A",
    "BRK-B": "BRK.B",
    "BRK/A": "BRK.A",
    "BRK/B": "BRK.B",
    "BF-B": "BF.B",
    "MKC-V": "MKC.V",
    "MOG-A": "MOG.A",
}
DATABENTO_UNSUPPORTED_SYMBOLS: set[str] = {
    "CTA-PA",
}
_DATABENTO_INVALID_CHAR_RE = re.compile(r"[^A-Z0-9.]")
_DATABENTO_UNIT_OR_WARRANT_SUFFIXES = (
    ".U",
    ".W",
    ".WS",
    ".R",
    ".RT",
)


def normalize_symbol_for_databento(symbol: str) -> str:
    normalized = str(symbol).strip().upper()
    if not normalized:
        return ""
    try:
        from databento_reference import resolve_symbol_alias_from_cache

        normalized = resolve_symbol_alias_from_cache(normalized)
    except Exception:
        logger.debug("Databento reference alias resolution failed.", exc_info=True)
    normalized = DATABENTO_SYMBOL_ALIASES.get(normalized, normalized)
    if _DATABENTO_INVALID_CHAR_RE.search(normalized):
        return ""
    if normalized.endswith(_DATABENTO_UNIT_OR_WARRANT_SUFFIXES):
        return ""
    if normalized in DATABENTO_UNSUPPORTED_SYMBOLS:
        return ""
    return normalized


def _normalize_symbols(symbols: set[str] | list[str] | tuple[str, ...]) -> list[str]:
    try:
        from databento_reference import maybe_refresh_symbol_reference_cache

        maybe_refresh_symbol_reference_cache(symbols)
    except Exception:
        logger.debug("Databento reference alias refresh skipped.", exc_info=True)
    normalized = {
        normalized_symbol
        for symbol in symbols
        if (normalized_symbol := normalize_symbol_for_databento(str(symbol)))
    }
    return sorted(normalized)


def _iter_symbol_batches(
    symbols: set[str] | list[str] | tuple[str, ...],
    *,
    batch_size: int = MAX_SYMBOLS_PER_REQUEST,
) -> list[list[str]]:
    normalized = _normalize_symbols(symbols)
    return [normalized[index:index + batch_size] for index in range(0, len(normalized), batch_size)]


def _extract_unresolved_symbols_from_warning_messages(messages: list[str]) -> set[str]:
    unresolved: set[str] = set()
    patterns = (
        r"did not resolve:\s*(.+?)(?:$|\\.)",
        r"unresolved symbols?:\s*(.+?)(?:$|\\.)",
        r"symbols? (?:were )?not (?:resolved|found|available):\s*(.+?)(?:$|\\.)",
    )
    for message in messages:
        raw_text = str(message)
        for pattern in patterns:
            for match in re.finditer(pattern, raw_text, flags=re.IGNORECASE):
                payload = match.group(1).replace("...", "")
                for raw_symbol in re.split(r"[,\s]+", payload):
                    cleaned = raw_symbol.strip().upper().strip(" .;:\t\n\r\"'[](){}")
                    norm = normalize_symbol_for_databento(cleaned)
                    if norm:
                        unresolved.add(norm)
    return unresolved


# ── Request / timestamp helpers ─────────────────────────────────────────────

def _clamp_request_end(requested_end: pd.Timestamp, available_end: pd.Timestamp | None) -> pd.Timestamp:
    if available_end is None:
        return requested_end
    return min(requested_end, available_end)


def _exclusive_ohlcv_1s_end(logical_end: datetime | pd.Timestamp) -> pd.Timestamp:
    end_timestamp = pd.Timestamp(logical_end)
    if end_timestamp.tzinfo is None:
        end_timestamp = end_timestamp.tz_localize(UTC)
    return end_timestamp + pd.Timedelta(seconds=1)


# ── Frame processing helpers ───────────────────────────────────────────────

def _coerce_timestamp_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    frame = df.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.reset_index()
        idx_name = frame.columns[0]
        frame = frame.rename(columns={idx_name: "ts"})
    elif "ts_event" in frame.columns:
        frame = frame.rename(columns={"ts_event": "ts"})
    elif "ts_recv" in frame.columns:
        frame = frame.rename(columns={"ts_recv": "ts"})
    elif "index" in frame.columns:
        frame = frame.rename(columns={"index": "ts"})
    else:
        raise ValueError("No timestamp column found in Databento frame")
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


def _store_to_frame(store: Any, *, count: int | None = None, context: str) -> pd.DataFrame:
    payload = store.to_df(count=count) if count is not None else store.to_df()
    if isinstance(payload, pd.DataFrame):
        return _coerce_timestamp_frame(payload)
    chunks = list(payload)
    if not chunks:
        return pd.DataFrame()
    concatenated = pd.concat(chunks, ignore_index=False)
    return _coerce_timestamp_frame(concatenated)


def _validate_frame_columns(frame: pd.DataFrame, *, required: set[str], context: str) -> pd.DataFrame:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{context} missing required columns: {', '.join(missing)}")
    return frame


# ── Warning / redaction helpers ─────────────────────────────────────────────

_API_KEY_REDACTION_PATTERNS = (
    re.compile(r"(api[_-]?key=)([^&\s]+)", flags=re.IGNORECASE),
    re.compile(r"(token=)([^&\s]+)", flags=re.IGNORECASE),
    re.compile(r"(Authorization:\s*Bearer\s+)([^\s]+)", flags=re.IGNORECASE),
    # PR #2113 (Copilot follow-up to PR #2112 M1): Discord and Slack
    # webhook URLs embed the secret directly in the URL **path** (not a
    # query parameter), so the canonical ``api_key=`` / ``token=`` /
    # ``Bearer ...`` patterns above cannot mask them. ``repr(httpx_exc)``
    # routinely includes the request URL, which is how those tokens
    # would otherwise leak into the redaction sites in terminal_export,
    # terminal_tradingview_news and terminal_notifications.
    re.compile(
        r"(https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/)([\w-]+)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(https?://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/)([A-Za-z0-9]+)",
        flags=re.IGNORECASE,
    ),
)


def _redact_sensitive_error_text(text: str) -> str:
    redacted = str(text)
    for pattern in _API_KEY_REDACTION_PATTERNS:
        redacted = pattern.sub(r"\1***", redacted)
    return redacted


def _warn_with_redacted_exception(message: str, exc: BaseException, *, include_traceback: bool = False) -> None:
    logger.warning("%s: %s", message, _redact_sensitive_error_text(str(exc)), exc_info=include_traceback)


# ── Dataset selection ───────────────────────────────────────────────────────

PREFERRED_DATABENTO_DATASETS = (
    "XNAS.ITCH",
    "XNYS.PILLAR",
    "DBEQ.BASIC",
    "XNAS.BASIC",
)


# ── Public aliases ───────────────────────────────────────────────────────
#
# The helpers below were originally extracted with underscore prefixes to
# preserve backward-compatibility with the screener monolith.  These
# unprefixed aliases are the **stable public API** that external consumers
# (e.g. smc_microstructure_base_runtime) should use.

clamp_request_end = _clamp_request_end
extract_unresolved_symbols_from_warning_messages = _extract_unresolved_symbols_from_warning_messages
iter_symbol_batches = _iter_symbol_batches
read_cached_frame = _read_cached_frame
store_to_frame = _store_to_frame
trade_day_cache_max_age_seconds = _trade_day_cache_max_age_seconds
validate_frame_columns = _validate_frame_columns
warn_with_redacted_exception = _warn_with_redacted_exception
write_cached_frame = _write_cached_frame


def choose_default_dataset(
    available_datasets: list[str],
    requested_dataset: str | None = None,
) -> str:
    normalized = [str(dataset).strip() for dataset in available_datasets if str(dataset).strip()]
    available_lookup = {dataset.upper(): dataset for dataset in normalized}
    requested_normalized = str(requested_dataset).strip() if requested_dataset else None
    if requested_normalized:
        matched_requested = available_lookup.get(requested_normalized.upper())
        if matched_requested:
            return matched_requested
        logger.warning("Requested dataset %r not in available datasets %r, falling back.", requested_dataset, normalized)
    for dataset in PREFERRED_DATABENTO_DATASETS:
        matched_preferred = available_lookup.get(dataset.upper())
        if matched_preferred:
            return matched_preferred
    if normalized:
        return normalized[0]
    return requested_normalized or PREFERRED_DATABENTO_DATASETS[0]


def list_datasets_normalized(client: Any) -> set[str]:
    """Return the client's dataset list as a normalized ``set[str]``.

    ``client.metadata.list_datasets()`` may return non-string items (vendor
    SDK changes have historically alternated between ``list[str]`` and a
    list of typed records). Membership tests like ``"OPRA.PILLAR" in
    datasets`` therefore have a silent-false-FAIL hazard if the items are
    not strings.

    This helper centralizes the normalization (R11 from
    ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md``) so every probe
    and dataset-selection call-site can use the same contract::

        from databento_utils import list_datasets_normalized
        datasets = list_datasets_normalized(client)
        if "OPRA.PILLAR" not in datasets:
            ...
    """
    raw = client.metadata.list_datasets()
    return {s for s in (str(item).strip() for item in raw) if s}

