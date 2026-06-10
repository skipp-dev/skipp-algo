from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import math
import os
import re
import ssl
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

try:
    import certifi
except Exception:  # pragma: no cover
    certifi = None

_prev_trading_day: Any = None

with contextlib.suppress(Exception):  # pragma: no cover
    from newsstack_fmp._market_cal import prev_trading_day as _prev_trading_day


logger = logging.getLogger(__name__)
_US_EASTERN = ZoneInfo("America/New_York")
_FMP_FEATURE_UNAVAILABLE_LOGGED: set[str] = set()

DEFAULT_HIGH_IMPACT_EVENTS: tuple[str, ...] = (
    "cpi",
    "core cpi",
    "ppi",
    "pce",
    "core pce",
    "nonfarm payroll",
    "initial jobless claims",
    "jobless claims",
    "gdp growth",
    "gross domestic product",
    "philadelphia fed business outlook survey",
)

_MID_IMPACT_EVENT_TOKENS: tuple[str, ...] = (
    "consumer sentiment",
    "michigan consumer sentiment",
    "ism services",
    "ism non-manufacturing",
    "retail sales",
    "durable goods",
    "factory orders",
    "existing home sales",
    "new home sales",
)

_CONSENSUS_FIELDS: tuple[str, ...] = (
    "consensus",
    "estimate",
    "forecast",
    "expected",
    "median",
)


def _today_et_date() -> date:
    return datetime.now(UTC).astimezone(_US_EASTERN).date()


def _prev_us_equity_trading_day(day: date) -> date:
    if _prev_trading_day is not None:
        return cast(date, _prev_trading_day(day))
    probe = day
    while True:
        probe = probe.fromordinal(probe.toordinal() - 1)
        if probe.weekday() < 5:
            return probe


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_csv_value(value: str) -> Any:
    stripped = value.strip()
    if stripped == "":
        return ""
    try:
        if any(char in stripped for char in (".", "e", "E")):
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped


def _parse_retry_after_seconds(raw_value: str | None) -> float | None:
    if not raw_value:
        return None
    try:
        v = float(raw_value)
    except (TypeError, ValueError):
        v = None
    if v is not None:
        # Reject NaN/Inf — ``time.sleep(NaN)`` raises ValueError and
        # ``time.sleep(inf)`` would wedge the retry loop.
        if math.isnan(v) or math.isinf(v):
            return None
        return max(v, 0.0)
    try:
        parsed = parsedate_to_datetime(str(raw_value))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max((parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds(), 0.0)


# F1 (2026-06-10): CA-bundle normalisation must run at most once — in the main
# thread before any ThreadPoolExecutor worker calls _build_tls_context.
# Concurrent os.environ writes (putenv) from worker threads are a C-level race.
_TLS_NORMALIZE_LOCK: threading.Lock = threading.Lock()
_TLS_NORMALIZED: bool = False


def _normalize_tls_certificate_env() -> str | None:
    global _TLS_NORMALIZED
    if certifi is None:
        return None
    cafile = str(certifi.where())
    if _TLS_NORMALIZED:
        return cafile
    with _TLS_NORMALIZE_LOCK:
        if _TLS_NORMALIZED:  # double-checked locking
            return cafile
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
        _TLS_NORMALIZED = True
    return cafile


def _build_tls_context() -> ssl.SSLContext:
    cafile = _normalize_tls_certificate_env()
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def _normalize_event_name(event_name: str) -> str:
    return " ".join(str(event_name or "").strip().lower().replace("_", " ").split())


def _normalize_event_date_key(raw_date: Any, fallback_index: int) -> str:
    if raw_date in (None, ""):
        return f"__missing_date__{fallback_index}"
    text = str(raw_date).strip()
    if not text:
        return f"__missing_date__{fallback_index}"
    date_part = text.split("T", 1)[0].split(" ", 1)[0]
    if len(date_part) == 10 and date_part[4:5] == "-" and date_part[7:8] == "-":
        return date_part
    parts = date_part.split("/")
    if len(parts) == 3:
        try:
            month = int(parts[0])
            day = int(parts[1])
            year = int(parts[2])
            if year < 100:
                year += 2000
            return date(year, month, day).isoformat()
        except ValueError:
            return date_part
    return date_part


def _event_impact_rank(event: dict[str, Any]) -> int:
    impact = str(event.get("impact") or event.get("importance") or event.get("priority") or "").strip().lower()
    if impact == "high":
        return 2
    if impact in {"medium", "mid", "moderate"}:
        return 1
    return 0


def _canonical_event_name(event_name: str) -> str:
    normalized = _normalize_event_name(event_name)
    if "gdpnow" in normalized:
        return "gdpnow"
    if "gross domestic product" in normalized or "gdp growth rate" in normalized or normalized.startswith("gdp ") or normalized == "gdp":
        return "gdp_qoq"
    if "s&p global" in normalized and "pmi" in normalized:
        return "pmi_sp_global"
    if "core pce" in normalized:
        if "yoy" in normalized:
            return "core_pce_yoy"
        if "mom" in normalized:
            return "core_pce_mom"
        return "core_pce"
    if "pce" in normalized:
        if "yoy" in normalized:
            return "pce_yoy"
        if "mom" in normalized:
            return "pce_mom"
        return "pce"
    if "core cpi" in normalized:
        if "yoy" in normalized:
            return "core_cpi_yoy"
        if "mom" in normalized:
            return "core_cpi_mom"
        return "core_cpi"
    if "cpi" in normalized:
        if "yoy" in normalized:
            return "cpi_yoy"
        if "mom" in normalized:
            return "cpi_mom"
        return "cpi"
    if "core ppi" in normalized:
        if "yoy" in normalized:
            return "core_ppi_yoy"
        if "mom" in normalized:
            return "core_ppi_mom"
        return "core_ppi"
    if "ppi" in normalized:
        if "yoy" in normalized:
            return "ppi_yoy"
        if "mom" in normalized:
            return "ppi_mom"
        return "ppi"
    if "nonfarm payroll" in normalized:
        return "nonfarm_payrolls"
    if "jobless claims" in normalized:
        return "jobless_claims"
    if "ism services" in normalized or "ism non-manufacturing" in normalized:
        return "ism_services"
    if "ism manufacturing" in normalized:
        return "ism_manufacturing"
    if "consumer sentiment" in normalized:
        return "consumer_sentiment"
    if "philadelphia fed" in normalized:
        return "philadelphia_fed"
    return normalized.replace(" ", "_")


def canonicalize_event_name(event_name: str) -> str:
    return _canonical_event_name(event_name)


def get_consensus(event: dict[str, Any]) -> tuple[Any | None, str | None]:
    for field_name in _CONSENSUS_FIELDS:
        if event.get(field_name) not in (None, ""):
            return event.get(field_name), field_name
    return None, None


def _is_high_impact_event_name(
    event_name: str,
    high_impact_events: tuple[str, ...] = DEFAULT_HIGH_IMPACT_EVENTS,
) -> bool:
    normalized = _normalize_event_name(event_name)
    if "gdpnow" in normalized:
        return False
    return any(token in normalized for token in high_impact_events)


def filter_us_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for event in events:
        country = str(event.get("country") or "").upper()
        currency = str(event.get("currency") or "").upper()
        if country == "US" or currency == "USD":
            cloned = dict(event)
            if currency == "USD" and not country:
                cloned["country"] = "US"
            filtered.append(cloned)
    return filtered


def filter_us_high_impact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for event in filter_us_events(events):
        impact_rank = _event_impact_rank(event)
        event_name = str(event.get("event") or event.get("name") or "")
        if impact_rank == 2 or (impact_rank == 0 and _is_high_impact_event_name(event_name)):
            filtered.append(dict(event))
    return filtered


def filter_us_mid_impact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for event in filter_us_events(events):
        if _event_impact_rank(event) != 1:
            continue
        normalized = _normalize_event_name(str(event.get("event") or event.get("name") or ""))
        if any(token in normalized for token in _MID_IMPACT_EVENT_TOKENS):
            filtered.append(dict(event))
    return filtered


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: dict[tuple[str, str], dict[str, Any]] = {}
    dropped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str]] = []

    for index, event in enumerate(events):
        cloned = dict(event)
        if str(cloned.get("currency") or "").upper() == "USD" and not str(cloned.get("country") or "").strip():
            cloned["country"] = "US"
        cloned["canonical_event"] = _canonical_event_name(str(cloned.get("event") or cloned.get("name") or ""))
        key_date = _normalize_event_date_key(cloned.get("date"), index)
        key = (key_date, str(cloned["canonical_event"]))
        if key not in kept:
            kept[key] = cloned
            dropped[key] = []
            order.append(key)
            continue

        existing = kept[key]
        existing_score = (_event_impact_rank(existing), existing.get("actual") is not None)
        new_score = (_event_impact_rank(cloned), cloned.get("actual") is not None)
        if new_score > existing_score:
            dropped[key].append(existing)
            kept[key] = cloned
        else:
            dropped[key].append(cloned)

    result: list[dict[str, Any]] = []
    for key in order:
        event = kept[key]
        chosen_event = event.get("event") or event.get("name")
        event["dedup"] = {
            "was_deduped": bool(dropped[key]),
            "duplicates_count": 1 + len(dropped[key]),
            "dropped_count": len(dropped[key]),
            "chosen_event": chosen_event,
        }
        result.append(event)
    return result


def _macro_orientation(canonical_event: str) -> float:
    if canonical_event.startswith(("cpi", "core_cpi", "ppi", "core_ppi", "pce", "core_pce", "jobless_claims")):
        return -1.0
    return 1.0


def _macro_weight(
    event: dict[str, Any],
    *,
    allow_mid_impact: bool,
    include_headline_pce_confirm: bool,
) -> float:
    impact_rank = _event_impact_rank(event)
    canonical_event = str(event.get("canonical_event") or _canonical_event_name(str(event.get("event") or event.get("name") or "")))
    if canonical_event in {"pce_mom", "pce_yoy"}:
        return 0.25 if include_headline_pce_confirm else 0.0
    if canonical_event == "gdp_qoq":
        return 0.5
    if canonical_event in {
        "pce_yoy",
        "core_pce_yoy",
        "cpi_yoy",
        "core_cpi_yoy",
        "ppi_yoy",
        "core_ppi_yoy",
        "pmi_sp_global",
    }:
        return 0.25
    if canonical_event in {"consumer_sentiment", "ism_services", "ism_manufacturing", "philadelphia_fed"}:
        return 0.25 if allow_mid_impact or impact_rank == 2 else 0.0
    if impact_rank == 2:
        return 1.0
    if impact_rank == 1:
        return 0.25 if allow_mid_impact else 0.0
    if canonical_event in {"consumer_sentiment", "ism_services", "ism_manufacturing", "philadelphia_fed"}:
        return 0.25 if allow_mid_impact else 0.0
    return 1.0 if _is_high_impact_event_name(str(event.get("event") or event.get("name") or "")) else 0.0


def macro_bias_with_components(
    events: list[dict[str, Any]],
    *,
    include_mid_if_no_high: bool = True,
    include_headline_pce_confirm: bool = True,
) -> dict[str, Any]:
    events_for_bias = dedupe_events(filter_us_events(events))
    has_high_impact = any(
        _event_impact_rank(event) == 2 or _is_high_impact_event_name(str(event.get("event") or event.get("name") or ""))
        for event in events_for_bias
    )
    score_components: list[dict[str, Any]] = []
    annotated_events: list[dict[str, Any]] = []
    total = 0.0

    for event in events_for_bias:
        canonical_event = str(event.get("canonical_event") or _canonical_event_name(str(event.get("event") or event.get("name") or "")))
        actual = _to_float(event.get("actual"))
        consensus_value, consensus_field = get_consensus(event)
        consensus = _to_float(consensus_value)
        quality_flags: list[str] = []
        if actual is None:
            quality_flags.append("missing_actual")
        if consensus is None:
            quality_flags.append("missing_consensus")
        if not event.get("unit"):
            quality_flags.append("missing_unit")
        annotated_event = dict(event)
        annotated_event["canonical_event"] = canonical_event
        annotated_event["data_quality_flags"] = quality_flags
        annotated_event["dedup"] = event.get("dedup") or {
            "was_deduped": False,
            "duplicates_count": 1,
            "dropped_count": 0,
            "chosen_event": event.get("event") or event.get("name"),
        }
        weight = _macro_weight(
            annotated_event,
            allow_mid_impact=include_mid_if_no_high and not has_high_impact,
            include_headline_pce_confirm=include_headline_pce_confirm,
        )

        surprise = 0.0
        contribution = 0.0
        if weight > 0.0 and actual is not None and consensus is not None:
            surprise = (actual - consensus) / max(abs(consensus), 1.0)
            if actual > consensus:
                contribution = _macro_orientation(canonical_event) * weight
            elif actual < consensus:
                contribution = -_macro_orientation(canonical_event) * weight
            total += contribution

        score_components.append(
            {
                "canonical_event": canonical_event,
                "consensus_value": consensus,
                "consensus_field": consensus_field,
                "surprise": surprise,
                "weight": weight,
                "contribution": contribution,
                "data_quality_flags": quality_flags,
                "dedup": annotated_event["dedup"],
            }
        )
        annotated_events.append(annotated_event)

    return {
        "macro_bias": max(min(total / 2.0, 1.0), -1.0),
        "events_for_bias": annotated_events,
        "score_components": score_components,
    }


def macro_bias_score(
    events: list[dict[str, Any]],
    *,
    include_mid_if_no_high: bool = True,
    include_headline_pce_confirm: bool = True,
) -> float:
    return float(
        macro_bias_with_components(
            events,
            include_mid_if_no_high=include_mid_if_no_high,
            include_headline_pce_confirm=include_headline_pce_confirm,
        ).get("macro_bias", 0.0)
    )


class UpstreamPayloadError(RuntimeError):
    """Raised when the response payload itself signals an upstream issue.

    Subclass of RuntimeError so existing ``except RuntimeError`` callers
    remain compatible. Distinguished from generic RuntimeError so the
    circuit breaker only trips on true upstream-outage signals (HTML
    error pages, FMP ``status=error`` payloads), not on parse errors or
    schema drift in our own code.
    """


class _CircuitBreaker:
    """Thread-safe single-failure circuit breaker.

    State (`_state`, `_opened_at`) is mutated by parallel API workers
    (`_atr14_by_symbol` / `_fetch_premarket_high_low_bulk` use
    ``ThreadPoolExecutor`` with up to 8 workers), so all reads/writes
    are guarded by ``_lock`` to avoid torn reads and the spurious
    half-open re-open race documented in PRODUCTION_BUG_REPORT.
    """

    def __init__(self, cooldown_seconds: float = 60.0) -> None:
        self.cooldown_seconds = max(cooldown_seconds, 1.0)
        self._state = "CLOSED"
        self._opened_at = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def allow_request(self) -> bool:
        with self._lock:
            if self._state == "OPEN":
                if time.time() - self._opened_at >= self.cooldown_seconds:
                    self._state = "HALF_OPEN"
                    return True
                return False
            return True

    def on_success(self) -> None:
        with self._lock:
            self._state = "CLOSED"
            self._opened_at = 0.0

    def on_failure(self) -> None:
        with self._lock:
            self._state = "OPEN"
            self._opened_at = time.time()


# Permanent vs transient HTTP failure classification.
#
# ``_execute_get`` raises ``RuntimeError("FMP API HTTP {code} on {path}: ...")``
# for ALL upstream HTTP errors — both permanent (auth/missing/retired) and
# transient (rate-limit/timeout/5xx). The once-per-process dedupe in
# ``_log_feature_unavailable_once`` is the right semantic for permanent
# failures ("this feature is unavailable on this tier; stop spamming the
# log") but the *wrong* semantic for transient outages, where we want every
# WARNING so on-call can see sustained 429s / 5xx storms.
#
# Status-code groups (RFC 7231 + provider-specific):
#   408 Request Timeout      → transient
#   429 Too Many Requests    → transient
#   500/502/503/504          → transient
#   400/401/403/404/410/451  → permanent (auth, missing, retired, legal-block)
#   any other 4xx            → permanent (treat client-side errors as deterministic)
_HTTP_CODE_RE = re.compile(r"HTTP (\d{3})")
_TRANSIENT_HTTP_CODES = frozenset({"408", "429", "500", "502", "503", "504"})
_CIRCUIT_OPEN_RE = re.compile(r"FMP API circuit open for ")
_NETWORK_ERROR_RE = re.compile(r"FMP API network error on ")
_RETRIES_EXHAUSTED_RE = re.compile(r"FMP API request exhausted retries on ")


def _is_permanent_feature_failure(exc: BaseException | None) -> bool:
    """Return True if ``exc`` represents a deterministic, recurring failure.

    Permanent  = same input → same failure on every retry (404 retired
                 endpoint, 401 missing API key, 403 tier mismatch,
                 ``UpstreamPayloadError`` HTML/error-payload).
    Transient  = self-healing (408/429/5xx, network error, retries-exhausted,
                 circuit-open) — we MUST keep WARN-ing every occurrence so
                 sustained outages stay visible.

    ``exc=None`` is treated as permanent so legacy callers without an
    exception object behave like the pre-refactor INFO-once path.
    """
    if exc is None:
        return True
    if isinstance(exc, UpstreamPayloadError):
        return True
    text = str(exc)
    if _CIRCUIT_OPEN_RE.search(text) or _NETWORK_ERROR_RE.search(text) or _RETRIES_EXHAUSTED_RE.search(text):
        return False
    match = _HTTP_CODE_RE.search(text)
    if match is None:
        # Non-HTTP RuntimeError: treat as permanent (parse error / schema
        # drift) so we don't spam, but include the exception class name in
        # the once-only log for forensic context.
        return True
    code = match.group(1)
    # Transient codes self-heal on retry; everything else (other 4xx, 5xx like
    # 501/505 server-side rejections) is treated as permanent — those don't
    # self-heal.
    return code not in _TRANSIENT_HTTP_CODES


def _log_feature_unavailable_once(
    feature_key: str,
    message: str,
    *,
    exc: BaseException | None = None,
) -> None:
    """Log a feature-unavailable event with permanent/transient discipline.

    Permanent failures (401/403/404/410, ``UpstreamPayloadError``,
    deterministic parse errors): INFO once per ``feature_key`` per process.
    Transient failures (408/429/5xx, network errors, circuit-open,
    retries-exhausted): WARNING every occurrence with the exception type
    and message so on-call sees sustained outages.
    """
    if not _is_permanent_feature_failure(exc):
        # Transient — always warn so persistent outages stay visible.
        if exc is not None:
            logger.warning(
                "%s [transient %s: %s]",
                message,
                type(exc).__name__,
                exc,
            )
        else:
            logger.warning("%s [transient]", message)
        return
    if feature_key in _FMP_FEATURE_UNAVAILABLE_LOGGED:
        return
    _FMP_FEATURE_UNAVAILABLE_LOGGED.add(feature_key)
    if exc is not None:
        logger.info("%s [permanent %s: %s]", message, type(exc).__name__, exc)
    else:
        logger.info(message)


def _normalise_analyst_estimates_period(period: object) -> str:
    """Coerce ``period`` to a value FMP /stable/analyst-estimates accepts.

    The endpoint returns HTTP 400 for anything other than ``annual`` or
    ``quarterly``. Historical callers (and FMP's sibling endpoints) pass
    ``quarter``; map any value starting with 'q' (case-insensitive) to
    ``quarterly`` and everything else (including blank) to ``annual``.
    """
    text = str(period).strip().lower() if period is not None else ""
    if text.startswith("q"):
        return "quarterly"
    return "annual"


def _aggregate_sector_snapshot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate /stable/sector-performance-snapshot rows to the legacy
    ``[{sector, changesPercentage}, ...]`` shape consumers expect.

    The snapshot endpoint returns one row per (sector, exchange) with field
    ``averageChange``. Aggregate (mean) per sector across exchanges.
    """
    sector_totals: dict[str, list[float]] = {}
    for row in rows:
        sector = str(row.get("sector") or "").strip()
        if not sector:
            continue
        raw = row.get("averageChange")
        if raw is None:
            raw = row.get("changesPercentage")
        try:
            change = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(change):
            continue
        sector_totals.setdefault(sector, []).append(change)
    return [
        {"sector": sector, "changesPercentage": round(sum(changes) / len(changes), 4)}
        for sector, changes in sector_totals.items()
    ]


@dataclass
class FMPClient:
    api_key: str
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.5
    timeout_seconds: float = 30.0
    base_url: str = "https://financialmodelingprep.com/api/v3"
    stable_base_url: str = "https://financialmodelingprep.com"
    _circuit_breaker: _CircuitBreaker = field(default_factory=_CircuitBreaker, init=False, repr=False)
    _last_quote_fetch_diagnostics: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    # G6 (2026-05-12): per-endpoint usage counters for provider-utilization audits.
    # Tracks {endpoint_path: {"calls": int, "errors": int, "empty_responses": int}}.
    # Read via get_endpoint_usage_stats(); intentionally process-local (no daemon
    # threads, no persistence) so it stays cheap and side-effect-free.
    _endpoint_usage_stats: dict[str, dict[str, int]] = field(default_factory=dict, init=False, repr=False)
    # R5 (2026-05-12): guards _endpoint_usage_stats against the
    # ThreadPoolExecutor in get_batch_quotes(). See
    # docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def from_env(cls) -> FMPClient:
        return cls(api_key=str(os.environ.get("FMP_API_KEY") or ""))

    def _build_url(self, path: str, params: dict[str, Any]) -> str:
        query = {key: value for key, value in params.items() if value is not None}
        if self.api_key:
            query.setdefault("apikey", self.api_key)
        base_url = self.stable_base_url if str(path).startswith("/stable/") else self.base_url
        if not query:
            return f"{base_url}{path}"
        return f"{base_url}{path}?{urlencode(query, doseq=True)}"

    def _parse_payload(self, path: str, payload: str) -> Any:
        text = payload.strip()
        if text.lower().startswith("<!doctype html") or text.lower().startswith("<html"):
            raise UpstreamPayloadError(f"FMP API returned HTML on {path}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            first_line = text.splitlines()[0] if text else ""
            if "," in first_line and (first_line.startswith('"') or first_line.lower().startswith("symbol,")):
                reader = csv.DictReader(io.StringIO(text))
                return [{key: _coerce_csv_value(value) for key, value in row.items()} for row in reader]
            raise RuntimeError(f"FMP API returned invalid JSON on {path}: {text[:120]}") from exc
        if isinstance(data, dict) and str(data.get("status") or "").lower() == "error":
            raise UpstreamPayloadError(f"FMP API error on {path}: {data.get('message') or 'unknown error'}")
        return data

    def _request_once(self, path: str, params: dict[str, Any]) -> Any:
        request = Request(self._build_url(path, params), headers={"User-Agent": "skipp-algo/1.0"})
        with urlopen(request, timeout=self.timeout_seconds, context=_build_tls_context()) as response:
            payload = response.read().decode("utf-8")
        return self._parse_payload(path, payload)

    def _record_endpoint_event(self, path: str, *, calls: int = 0, errors: int = 0, empty_responses: int = 0) -> None:
        """Increment per-endpoint counters (G6 instrumentation).

        Aggregates by exact ``path`` (e.g. "/stable/quote", "/stable/profile").
        Guarded by ``self._lock`` because ``get_batch_quotes()`` submits work
        through a ``ThreadPoolExecutor`` and the nested
        ``bucket["count"] += n`` is read-modify-write at the Python level
        (LOAD_ATTR + INPLACE_ADD + STORE_ATTR is not single-bytecode-atomic
        even under the GIL). Without the lock, increments are silently
        lost under contention. See R5 in
        ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md``.
        """

        with self._lock:
            bucket = self._endpoint_usage_stats.setdefault(
                path, {"calls": 0, "errors": 0, "empty_responses": 0}
            )
            if calls:
                bucket["calls"] += calls
            if errors:
                bucket["errors"] += errors
            if empty_responses:
                bucket["empty_responses"] += empty_responses

    def get_endpoint_usage_stats(self) -> dict[str, dict[str, int]]:
        """Return a deep copy of per-endpoint usage counters (G6).

        Producer-side audit hook: callers can log this at end-of-run to capture
        which FMP paths were actually exercised in a given pipeline invocation.
        Empty when no calls have been made on this client instance.

        Snapshot is taken under ``self._lock`` to avoid
        ``RuntimeError: dictionary changed size during iteration`` when a
        concurrent ``_record_endpoint_event`` call inserts a new path bucket.
        """

        with self._lock:
            return {path: dict(stats) for path, stats in self._endpoint_usage_stats.items()}

    def _execute_get(self, path: str, params: dict[str, Any], *, use_circuit_breaker: bool) -> Any:
        self._record_endpoint_event(path, calls=1)
        if use_circuit_breaker and not self._circuit_breaker.allow_request():
            self._record_endpoint_event(path, errors=1)
            raise RuntimeError(f"FMP API circuit open for {path}")
        max_attempts = max(self.retry_attempts, 1)
        for attempt in range(max_attempts):
            try:
                data = self._request_once(path, params)
                if use_circuit_breaker:
                    self._circuit_breaker.on_success()
                return data
            except urllib.error.HTTPError as exc:
                # 408 (Request Timeout) is a provider-side stall — treat it the
                # same as 429/5xx: retry with backoff before tripping the breaker.
                transient = exc.code in {408, 429, 500, 502, 503, 504}
                if transient and attempt + 1 < max_attempts:
                    headers = getattr(exc, "headers", None) or {}
                    retry_after = _parse_retry_after_seconds(headers.get("Retry-After"))
                    delay = retry_after if retry_after is not None else self.retry_backoff_seconds * (attempt + 1)
                    time.sleep(max(delay, 0.0))
                    continue
                # Other 4xx are client/data errors (e.g. /stable/foo retired,
                # symbol unknown, no data for date). They must NOT trip the
                # breaker — otherwise one stale endpoint nukes every other
                # unrelated FMP call for the cooldown window.
                provider_outage = exc.code in {408, 429, 500, 502, 503, 504}
                if use_circuit_breaker and provider_outage:
                    self._circuit_breaker.on_failure()
                body = ""
                if getattr(exc, "fp", None) is not None:
                    try:
                        body = exc.fp.read().decode("utf-8")
                    except Exception:
                        body = ""
                self._record_endpoint_event(path, errors=1)
                raise RuntimeError(f"FMP API HTTP {exc.code} on {path}: {body or exc.msg or 'HTTP error'}") from exc
            except urllib.error.URLError as exc:
                if attempt + 1 < max_attempts:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
                    continue
                if use_circuit_breaker:
                    self._circuit_breaker.on_failure()
                self._record_endpoint_event(path, errors=1)
                raise RuntimeError(f"FMP API network error on {path}: {exc}") from exc
            except UpstreamPayloadError:
                if use_circuit_breaker:
                    self._circuit_breaker.on_failure()
                self._record_endpoint_event(path, errors=1)
                raise
            except RuntimeError:
                # Parse errors / schema drift are NOT upstream outages; let
                # them surface without tripping the breaker.
                raise
        if use_circuit_breaker:
            self._circuit_breaker.on_failure()
        raise RuntimeError(f"FMP API request exhausted retries on {path}")

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        return self._execute_get(path, params, use_circuit_breaker=True)

    def _resolve_quote_fetch_workers(self, symbol_count: int) -> int:
        configured_raw = str(
            os.environ.get("OPEN_PREP_FMP_QUOTE_WORKERS")
            or os.environ.get("FMP_QUOTE_WORKERS")
            or "4"
        ).strip()
        try:
            configured = int(configured_raw)
        except ValueError:
            configured = 4
        return max(1, min(configured, 8, max(symbol_count, 1)))

    def get_last_quote_fetch_diagnostics(self) -> dict[str, Any]:
        diagnostics = dict(self._last_quote_fetch_diagnostics)
        for key in (
            "requested_symbols",
            "deduped_symbols",
            "fetched_unique_symbols",
            "failed_quote_symbols",
        ):
            diagnostics[key] = list(diagnostics.get(key) or [])
        return diagnostics

    def get_profile_bulk(self) -> list[dict[str, Any]]:
        try:
            data = self._get("/stable/profile-bulk", {})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/profile-bulk",
                "FMP feature unavailable (stable/profile-bulk); continuing without profile bulk data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_profiles(self, symbols: list[str]) -> list[dict[str, Any]]:
        # FMP /stable/profile only accepts a SINGLE symbol; passing a comma-
        # joined list silently returns []. Iterate per symbol and warn-skip on
        # individual failures so a single bad ticker does not nuke the batch.
        requested_symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
        if not requested_symbols:
            return []
        rows: list[dict[str, Any]] = []
        for sym in requested_symbols:
            try:
                data = self._get("/stable/profile", {"symbol": sym})
            except RuntimeError as exc:
                logger.warning("profile fetch failed for %s: %s", sym, exc)
                continue
            if isinstance(data, list):
                rows.extend(data)
        return rows

    def get_ratios_ttm(self, symbol: str) -> list[dict[str, Any]]:
        requested_symbol = str(symbol).strip().upper()
        if not requested_symbol:
            return []
        try:
            data = self._get("/stable/ratios-ttm", {"symbol": requested_symbol})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/ratios-ttm",
                "FMP feature unavailable (stable/ratios-ttm); continuing without TTM ratios.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_company_screener(self, **kwargs: Any) -> list[dict[str, Any]]:
        try:
            data = self._get("/stable/company-screener", kwargs)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/company-screener",
                "FMP feature unavailable (stable/company-screener); continuing without screener results.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def screener(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        _ = args
        return self.get_company_screener(**kwargs)

    def get_batch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        requested_symbols: list[str] = []
        deduped_symbols: list[str] = []
        seen_symbols: set[str] = set()
        for raw_symbol in symbols:
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol:
                continue
            requested_symbols.append(symbol)
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            deduped_symbols.append(symbol)

        started_at = time.perf_counter()
        rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
        failed_symbol_errors: dict[str, str] = {}
        worker_count = self._resolve_quote_fetch_workers(len(deduped_symbols)) if deduped_symbols else 1

        def fetch_symbol_quote(symbol: str) -> tuple[str, list[dict[str, Any]], str | None]:
            data = self._execute_get("/stable/quote", {"symbol": symbol}, use_circuit_breaker=False)
            if not isinstance(data, list) or not data:
                return symbol, [], "empty quote response"
            matching_rows = [
                row
                for row in data
                if str(row.get("symbol") or "").strip().upper() == symbol
            ]
            if not matching_rows:
                return symbol, [], "quote response missing requested symbol"
            return symbol, matching_rows, None

        if worker_count == 1:
            for symbol in deduped_symbols:
                try:
                    fetched_symbol, symbol_rows, error = fetch_symbol_quote(symbol)
                except Exception as exc:  # pragma: no cover - defensive catch
                    fetched_symbol, symbol_rows, error = symbol, [], str(exc)
                if error:
                    failed_symbol_errors[fetched_symbol] = error
                    continue
                rows_by_symbol[fetched_symbol] = symbol_rows
        else:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="fmp-quote") as executor:
                future_map = {
                    executor.submit(fetch_symbol_quote, symbol): symbol
                    for symbol in deduped_symbols
                }
                for future in as_completed(future_map):
                    requested_symbol = future_map[future]
                    try:
                        fetched_symbol, symbol_rows, error = future.result()
                    except Exception as exc:  # pragma: no cover - defensive catch
                        fetched_symbol, symbol_rows, error = requested_symbol, [], str(exc)
                    if error:
                        failed_symbol_errors[fetched_symbol] = error
                        continue
                    rows_by_symbol[fetched_symbol] = symbol_rows

        rows: list[dict[str, Any]] = []
        fetched_unique_symbols: list[str] = []
        for symbol in deduped_symbols:
            symbol_rows = rows_by_symbol.get(symbol, [])
            if not symbol_rows:
                continue
            fetched_unique_symbols.append(symbol)
            rows.extend(symbol_rows)

        failed_quote_symbols = [symbol for symbol in deduped_symbols if symbol in failed_symbol_errors]
        error_summary = "; ".join(
            f"{symbol}: {failed_symbol_errors[symbol]}"
            for symbol in failed_quote_symbols
        ) or None
        duration_ms = round((time.perf_counter() - started_at) * 1000.0)
        self._last_quote_fetch_diagnostics = {
            "quote_fetch_mode": "fmp_stable_quote_per_symbol",
            "requested_symbols": requested_symbols,
            "requested_symbol_count": len(requested_symbols),
            "deduped_symbols": deduped_symbols,
            "deduped_symbol_count": len(deduped_symbols),
            "fetched_quote_rows": len(rows),
            "fetched_unique_symbols": fetched_unique_symbols,
            "fetched_unique_symbol_count": len(fetched_unique_symbols),
            "failed_quote_symbols": failed_quote_symbols,
            "failed_quote_symbol_count": len(failed_quote_symbols),
            "quote_fetch_error_summary": error_summary,
            "partial_quote_fetch": bool(failed_quote_symbols) and bool(fetched_unique_symbols),
            "quote_fetch_all_failed": bool(deduped_symbols) and not fetched_unique_symbols,
            "quote_fetch_duration_ms": duration_ms,
            "quote_fetch_workers": worker_count,
            "endpoint_used": "/stable/quote",
        }
        return rows

    def get_fmp_articles(self, limit: int = 250) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "page": 0,
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/fmp-articles", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/fmp-articles",
                "FMP feature unavailable (stable/fmp-articles); continuing without FMP article data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_stock_latest_news(self, *, symbol: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": max(int(limit), 1)}
        if symbol:
            params["symbol"] = str(symbol).strip().upper()
        try:
            data = self._get("/stable/news/stock-latest", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/news/stock-latest",
                "FMP feature unavailable (stable/news/stock-latest); continuing without latest stock news.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_batch_crypto_quotes(self) -> list[dict[str, Any]]:
        try:
            data = self._get("/stable/batch-crypto-quotes", {})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/batch-crypto-quotes",
                "FMP feature unavailable (stable/batch-crypto-quotes); continuing without crypto batch quotes.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_cryptocurrency_historical_price(self, symbol: str) -> list[dict[str, Any]]:
        # FMP retired /stable/cryptocurrency-historical-price; the EOD history
        # for crypto symbols is now served by /stable/historical-price-eod/full.
        params = {"symbol": str(symbol).strip().upper()}
        try:
            data = self._get("/stable/historical-price-eod/full", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/historical-price-eod/full",
                "FMP feature unavailable (stable/historical-price-eod/full); continuing without EOD price history.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_cryptocurrency_list(self) -> list[dict[str, Any]]:
        try:
            data = self._get("/stable/cryptocurrency-list", {})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/cryptocurrency-list",
                "FMP feature unavailable (stable/cryptocurrency-list); continuing without crypto reference list.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    # Removed: ``get_fear_and_greed_index`` (P-6, 2026-04-30).
    # FMP retired ``/stable/fear-and-greed-index`` and the legacy
    # ``/api/v3/fear-and-greed-index`` returns 403 "Legacy Endpoint".
    # Crypto F&G now flows through ``api.alternative.me/fng/`` in
    # ``terminal_bitcoin.fetch_fear_greed`` and equity F&G through
    # ``open_prep/sentiment_fng.py::fetch_cnn_equity_fear_greed``.
    # See docs/reviews/2026-04-24-system-review.md (P-6).

    def get_technical_indicator(
        self,
        symbol: str,
        timeframe: str,
        indicator_type: str,
        *,
        indicator_period: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbol": str(symbol).strip().upper(),
            "timeframe": str(timeframe).strip(),
        }
        if indicator_period is not None:
            params["periodLength"] = int(indicator_period)
        try:
            data = self._get(f"/stable/technical-indicators/{indicator_type}", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                f"stable/technical-indicators/{indicator_type}",
                f"FMP feature unavailable (stable/technical-indicators/{indicator_type}); continuing without this indicator.",
                exc=exc,
            )
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}

    def get_batch_aftermarket_trade(self, symbols: list[str]) -> list[dict[str, Any]]:
        # FMP /stable/batch-aftermarket-trade has no documented batch limit but
        # the gateway returns 414 / 401 (truncated apikey) once the URL exceeds
        # ~6 KB. Empirically ~500 typical tickers fit; chunk at 250 for safety.
        # On per-chunk failure, skip that chunk so a single bad batch does not
        # poison the whole pre-market context.
        cleaned = [str(s).strip().upper() for s in symbols if str(s).strip()]
        if not cleaned:
            return []
        rows: list[dict[str, Any]] = []
        chunk_size = 250
        chunk_count = 0
        failures = 0
        last_exc: RuntimeError | None = None
        for start in range(0, len(cleaned), chunk_size):
            chunk = cleaned[start : start + chunk_size]
            chunk_count += 1
            try:
                data = self._get(
                    "/stable/batch-aftermarket-trade",
                    {"symbols": ",".join(chunk)},
                )
            except RuntimeError as exc:
                logger.warning(
                    "batch-aftermarket-trade chunk %d-%d failed: %s",
                    start,
                    start + len(chunk),
                    exc,
                )
                failures += 1
                last_exc = exc
                continue
            if isinstance(data, list):
                rows.extend(data)
        # Per-chunk swallow protects against URL-length / single-batch glitches,
        # but if EVERY chunk failed it is almost certainly a real configuration
        # / auth error (bad apikey, retired endpoint, full provider outage). Re-
        # raise so the caller does not silently treat a misconfiguration as
        # "no data".
        if chunk_count > 0 and failures == chunk_count and last_exc is not None:
            raise last_exc
        return rows

    def get_biggest_gainers(self) -> list[dict[str, Any]]:
        data = self._get("/stable/biggest-gainers", {})
        return list(data) if isinstance(data, list) else []

    def get_biggest_losers(self) -> list[dict[str, Any]]:
        data = self._get("/stable/biggest-losers", {})
        return list(data) if isinstance(data, list) else []

    def get_eod_bulk(self, as_of: date | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"datatype": "json"}
        if as_of is not None:
            params["date"] = as_of.isoformat()
        try:
            data = self._get("/stable/eod-bulk", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/eod-bulk",
                "FMP feature unavailable (stable/eod-bulk); continuing without bulk EOD data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_earnings_calendar(self, from_date: date, to_date: date) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        }
        try:
            data = self._get("/stable/earnings-calendar", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/earnings-calendar",
                "FMP feature unavailable (stable/earnings-calendar); continuing without earnings calendar data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_macro_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        params = {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        try:
            data = self._get("/stable/economic-calendar", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/economic-calendar",
                "FMP feature unavailable (stable/economic-calendar); continuing without macro calendar data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_premarket_movers(self) -> list[dict[str, Any]]:
        try:
            data = self._get("/stable/most-actives", {})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/most-actives",
                "FMP feature unavailable (stable/most-actives); continuing without pre-market movers.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_batch_aftermarket_quote(self, symbols: list[str]) -> list[dict[str, Any]]:
        # See get_batch_aftermarket_trade: gateway returns 414/401 once the URL
        # exceeds ~6 KB. Chunk at 250 and skip-with-warn on per-chunk failure.
        cleaned = [str(s).strip().upper() for s in symbols if str(s).strip()]
        if not cleaned:
            return []
        rows: list[dict[str, Any]] = []
        chunk_size = 250
        for start in range(0, len(cleaned), chunk_size):
            chunk = cleaned[start : start + chunk_size]
            try:
                data = self._get(
                    "/stable/batch-aftermarket-quote",
                    {"symbols": ",".join(chunk)},
                )
            except RuntimeError as exc:
                logger.warning(
                    "batch-aftermarket-quote chunk %d-%d failed: %s",
                    start,
                    start + len(chunk),
                    exc,
                )
                continue
            if isinstance(data, list):
                rows.extend(data)
        return rows

    def get_splits_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        params = {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        try:
            data = self._get("/stable/splits-calendar", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/splits-calendar",
                "FMP feature unavailable (stable/splits-calendar); continuing without splits calendar data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_dividends_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        params = {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        try:
            data = self._get("/stable/dividends-calendar", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/dividends-calendar",
                "FMP feature unavailable (stable/dividends-calendar); continuing without dividends calendar data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_ipos_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        params = {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        try:
            data = self._get("/stable/ipos-calendar", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/ipos-calendar",
                "FMP feature unavailable (stable/ipos-calendar); continuing without ipos calendar data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # F-V4-FMP-PHASE2 (2026-05-01): batch commodity / forex quotes,
    # CoT report + analysis, latest stock news, and the three core
    # financial statements. See docs/FMP_ENDPOINT_GAP_ANALYSE.md.
    # ------------------------------------------------------------------

    def get_batch_commodity_quotes(
        self, symbols: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """FMP `/stable/batch-commodity-quotes` (DXY proxies, gold, oil, ...)."""
        params: dict[str, Any] = {}
        if symbols:
            cleaned = [s.strip().upper() for s in symbols if str(s or "").strip()]
            if cleaned:
                params["symbols"] = ",".join(cleaned)
        try:
            data = self._get("/stable/batch-commodity-quotes", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/batch-commodity-quotes",
                "FMP feature unavailable (stable/batch-commodity-quotes); continuing without commodity quote data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_commodities_list(self) -> list[dict[str, Any]]:
        """FMP `/stable/commodities-list` (master list of tradable commodities)."""
        try:
            data = self._get("/stable/commodities-list", {})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/commodities-list",
                "FMP feature unavailable (stable/commodities-list); continuing without commodities list.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_batch_forex_quotes(
        self, symbols: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """FMP `/stable/batch-forex-quotes` (DXY components, EURUSD, USDJPY, ...)."""
        params: dict[str, Any] = {}
        if symbols:
            cleaned = [s.strip().upper() for s in symbols if str(s or "").strip()]
            if cleaned:
                params["symbols"] = ",".join(cleaned)
        try:
            data = self._get("/stable/batch-forex-quotes", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/batch-forex-quotes",
                "FMP feature unavailable (stable/batch-forex-quotes); continuing without forex quote data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_forex_list(self) -> list[dict[str, Any]]:
        """FMP `/stable/forex-list` (master list of tradable FX pairs)."""
        try:
            data = self._get("/stable/forex-list", {})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/forex-list",
                "FMP feature unavailable (stable/forex-list); continuing without forex list.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_cot_report(
        self,
        symbol: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """FMP `/stable/commitment-of-traders-report`."""
        params: dict[str, Any] = {}
        if symbol:
            cleaned = str(symbol).strip().upper()
            if cleaned:
                params["symbol"] = cleaned
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        try:
            data = self._get("/stable/commitment-of-traders-report", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/commitment-of-traders-report",
                "FMP feature unavailable (stable/commitment-of-traders-report); continuing without CoT report data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_cot_analysis(
        self,
        symbol: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """FMP `/stable/commitment-of-traders-analysis` (positioning summary)."""
        params: dict[str, Any] = {}
        if symbol:
            cleaned = str(symbol).strip().upper()
            if cleaned:
                params["symbol"] = cleaned
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        try:
            data = self._get("/stable/commitment-of-traders-analysis", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/commitment-of-traders-analysis",
                "FMP feature unavailable (stable/commitment-of-traders-analysis); continuing without CoT analysis data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_stock_news(
        self,
        symbols: list[str] | None = None,
        page: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """FMP `/stable/news/stock-latest` (latest stock-tagged news feed)."""
        params: dict[str, Any] = {
            "page": max(int(page), 0),
            "limit": max(int(limit), 1),
        }
        if symbols:
            cleaned = [s.strip().upper() for s in symbols if str(s or "").strip()]
            if cleaned:
                params["symbols"] = ",".join(cleaned)
        try:
            data = self._get("/stable/news/stock-latest", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/news/stock-latest",
                "FMP feature unavailable (stable/news/stock-latest); continuing without stock news data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_income_statement(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """FMP `/stable/income-statement` (single-symbol P&L)."""
        cleaned = str(symbol or "").strip().upper()
        if not cleaned:
            return []
        params = {
            "symbol": cleaned,
            "period": str(period or "annual").strip().lower() or "annual",
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/income-statement", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/income-statement",
                "FMP feature unavailable (stable/income-statement); continuing without income statement data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_balance_sheet(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """FMP `/stable/balance-sheet-statement` (single-symbol balance sheet)."""
        cleaned = str(symbol or "").strip().upper()
        if not cleaned:
            return []
        params = {
            "symbol": cleaned,
            "period": str(period or "annual").strip().lower() or "annual",
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/balance-sheet-statement", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/balance-sheet-statement",
                "FMP feature unavailable (stable/balance-sheet-statement); continuing without balance sheet data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_cash_flow_statement(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """FMP `/stable/cash-flow-statement` (single-symbol cash flows)."""
        cleaned = str(symbol or "").strip().upper()
        if not cleaned:
            return []
        params = {
            "symbol": cleaned,
            "period": str(period or "annual").strip().lower() or "annual",
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/cash-flow-statement", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/cash-flow-statement",
                "FMP feature unavailable (stable/cash-flow-statement); continuing without cash flow data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []


    def get_economic_indicators(
        self,
        name: str,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """FMP `/stable/economic-indicators?name=...` (GDP, CPI, unemployment, ...)."""
        cleaned = str(name or "").strip()
        if not cleaned:
            return []
        params: dict[str, Any] = {"name": cleaned}
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        try:
            data = self._get("/stable/economic-indicators", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/economic-indicators",
                "FMP feature unavailable (stable/economic-indicators); continuing without economic indicator data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_house_trades(self, symbol: str) -> list[dict[str, Any]]:
        """Disclosed US House trades for a given ticker (`/stable/house-trades`)."""
        cleaned = str(symbol or "").strip().upper()
        if not cleaned:
            return []
        try:
            data = self._get("/stable/house-trades", {"symbol": cleaned})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/house-trades",
                "FMP feature unavailable (stable/house-trades); continuing without per-symbol house trade data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_upgrades_downgrades(
        self,
        symbol: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = str(symbol).strip().upper()
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        if limit is not None:
            params["limit"] = max(int(limit), 1)
        try:
            data = self._get("/stable/grades", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/grades",
                "FMP feature unavailable (stable/grades); continuing without grades data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_insider_trading_latest(self, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        # Ultimate-plan path. The legacy /stable/insider-trading was renamed:
        # - /stable/insider-trading/latest   (no symbol filter)
        # - /stable/insider-trading/search   (with ?symbol=)
        params: dict[str, Any] = {"limit": max(int(limit), 1), "page": 0}
        if symbol:
            params["symbol"] = str(symbol).strip().upper()
            path = "/stable/insider-trading/search"
        else:
            path = "/stable/insider-trading/latest"
        try:
            data = self._get(path, params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                path.lstrip("/"),
                f"FMP feature unavailable ({path}); endpoint retired or upgraded plan required.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_insider_trading_statistics(self, symbol: str) -> list[dict[str, Any]]:
        # Ultimate-plan path. Quarterly aggregates per symbol — one call
        # replaces the broad /stable/insider-trading/latest scan + manual
        # aggregation. Returns rows with year/quarter/acquiredTransactions/
        # disposedTransactions/acquiredDisposedRatio/totalAcquired/etc.
        cleaned = str(symbol).strip().upper()
        if not cleaned:
            return []
        params = {"symbol": cleaned}
        try:
            data = self._get("/stable/insider-trading/statistics", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/insider-trading/statistics",
                "FMP feature unavailable (stable/insider-trading/statistics); endpoint retired or upgraded plan required.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_institutional_ownership(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        # Ultimate-plan path. The legacy /stable/institutional-ownership was
        # split into multiple endpoints; the per-symbol position summary is
        # the closest replacement of the previous payload shape.
        params = {
            "symbol": str(symbol).strip().upper(),
        }
        try:
            data = self._get("/stable/institutional-ownership/symbol-positions-summary", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/institutional-ownership/symbol-positions-summary",
                "FMP feature unavailable (stable/institutional-ownership/symbol-positions-summary); endpoint retired or upgraded plan required.",
                exc=exc,
            )
            return []
        rows = list(data) if isinstance(data, list) else []
        if limit and len(rows) > limit:
            rows = rows[: max(int(limit), 1)]
        return rows

    def get_acquisition_of_beneficial_ownership(self, symbol: str) -> list[dict[str, Any]]:
        # SC 13D / 13G filings (5%+ stakes). Event-driven and orthogonal to
        # quarterly 13F snapshots — often precedes catalyst moves by days.
        cleaned = str(symbol).strip().upper()
        if not cleaned:
            return []
        try:
            data = self._get(
                "/stable/acquisition-of-beneficial-ownership",
                {"symbol": cleaned},
            )
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/acquisition-of-beneficial-ownership",
                "FMP feature unavailable (stable/acquisition-of-beneficial-ownership); endpoint retired or upgraded plan required.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_senate_trades_latest(self, limit: int = 100) -> list[dict[str, Any]]:
        # /stable/senate-latest returns recent disclosures across all senators
        # without symbol filter — fast, single call. Use for daily ticker scan.
        params = {"page": 0, "limit": max(int(limit), 1)}
        try:
            data = self._get("/stable/senate-latest", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/senate-latest",
                "FMP feature unavailable (stable/senate-latest); endpoint retired or upgraded plan required.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_house_trades_latest(self, limit: int = 100) -> list[dict[str, Any]]:
        params = {"page": 0, "limit": max(int(limit), 1)}
        try:
            data = self._get("/stable/house-latest", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/house-latest",
                "FMP feature unavailable (stable/house-latest); endpoint retired or upgraded plan required.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_treasury_rates(self, date_from: date | None = None, date_to: date | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        try:
            data = self._get("/stable/treasury-rates", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/treasury-rates",
                "FMP feature unavailable (stable/treasury-rates); continuing without treasury rates data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_house_trading(self, limit: int = 100) -> list[dict[str, Any]]:
        params = {"limit": max(int(limit), 1)}
        try:
            data = self._get("/stable/house-latest", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/house-latest",
                "FMP feature unavailable (stable/house-latest); continuing without house latest data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_dcf(self, symbol: str) -> dict[str, Any]:
        params = {"symbol": str(symbol).strip().upper()}
        try:
            data = self._get("/stable/discounted-cash-flow", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/discounted-cash-flow",
                "FMP feature unavailable (stable/discounted-cash-flow); continuing without discounted cash flow data.",
                exc=exc,
            )
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        requested_symbol = str(symbol).strip().upper()
        try:
            data = self._get("/stable/profile", {"symbol": requested_symbol})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/profile",
                "FMP feature unavailable (stable/profile); continuing without profile data.",
                exc=exc,
            )
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                if str(row.get("symbol") or "").strip().upper() == requested_symbol:
                    return dict(row)
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}

    def get_price_target_consensus(self, symbol: str) -> dict[str, Any]:
        requested_symbol = str(symbol).strip().upper()
        try:
            data = self._get("/stable/price-target-consensus", {"symbol": requested_symbol})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/price-target-consensus",
                "FMP feature unavailable (stable/price-target-consensus); continuing without price target consensus data.",
                exc=exc,
            )
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                if str(row.get("symbol") or "").strip().upper() == requested_symbol:
                    return dict(row)
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}

    def get_price_target_summary(self, symbol: str) -> dict[str, Any]:
        requested_symbol = str(symbol).strip().upper()
        try:
            data = self._get("/stable/price-target-summary", {"symbol": requested_symbol})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/price-target-summary",
                "FMP feature unavailable (stable/price-target-summary); continuing without price target summary data.",
                exc=exc,
            )
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                if str(row.get("symbol") or "").strip().upper() == requested_symbol:
                    return dict(row)
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}

    def get_grades_consensus(self, symbol: str) -> dict[str, Any]:
        requested_symbol = str(symbol).strip().upper()
        try:
            data = self._get("/stable/grades-consensus", {"symbol": requested_symbol})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/grades-consensus",
                "FMP feature unavailable (stable/grades-consensus); continuing without grades consensus data.",
                exc=exc,
            )
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                if str(row.get("symbol") or "").strip().upper() == requested_symbol:
                    return dict(row)
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}

    def get_analyst_estimates(self, symbol: str, *, period: str = "annual", limit: int = 8) -> list[dict[str, Any]]:
        params = {
            "symbol": str(symbol).strip().upper(),
            "period": _normalise_analyst_estimates_period(period),
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/analyst-estimates", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/analyst-estimates",
                "FMP feature unavailable (stable/analyst-estimates); continuing without analyst estimates data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_earnings_report(self, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
        params = {
            "symbol": str(symbol).strip().upper(),
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/earnings", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/earnings",
                "FMP feature unavailable (stable/earnings); continuing without earnings data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_historical_price_eod_full(self, symbol: str, date_from: date, date_to: date) -> list[dict[str, Any]] | dict[str, Any]:
        params = {
            "symbol": str(symbol).strip().upper(),
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        try:
            data = self._get("/stable/historical-price-eod/full", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/historical-price-eod/full",
                "FMP feature unavailable (stable/historical-price-eod/full); continuing without full data.",
                exc=exc,
            )
            return []
        if isinstance(data, dict):
            return dict(data)
        return list(data) if isinstance(data, list) else []

    def get_intraday_chart(
        self,
        symbol: str,
        interval: str = "1min",
        day: date | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "symbol": str(symbol).strip().upper(),
            "limit": max(int(limit), 1),
        }
        if day is not None:
            params["from"] = day.isoformat()
            params["to"] = day.isoformat()
        try:
            data = self._get(f"/stable/historical-chart/{interval}", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                f"stable/historical-chart/{interval}",
                f"FMP feature unavailable (stable/historical-chart/{interval}); continuing without intraday chart data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_index_quote(self, symbol: str = "^VIX") -> dict[str, Any]:
        requested_symbol = str(symbol).strip().upper()
        try:
            data = self._get("/stable/quote", {"symbol": requested_symbol})
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/quote",
                "FMP feature unavailable (stable/quote); continuing without quote data.",
                exc=exc,
            )
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                if str(row.get("symbol") or "").strip().upper() == requested_symbol:
                    return dict(row)
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}

    def get_sector_performance_snapshot(self, as_of: date | None = None) -> list[dict[str, Any]]:
        # /stable/sector-performance-snapshot REQUIRES a `date` parameter; calling
        # without one returns an empty payload. Default to today (US/Eastern) so
        # callers that don't supply ``as_of`` still get meaningful data.
        effective_date = as_of if as_of is not None else _today_et_date()
        params: dict[str, Any] = {"date": effective_date.isoformat()}
        try:
            data = self._get("/stable/sector-performance-snapshot", params)
        except RuntimeError as exc:
            _log_feature_unavailable_once(
                "stable/sector-performance-snapshot",
                "FMP feature unavailable (stable/sector-performance-snapshot); continuing without sector performance snapshot data.",
                exc=exc,
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_sector_performance(self) -> list[dict[str, Any]]:
        # FMP retired /stable/sector-performance (always 404). The replacement is
        # /stable/sector-performance-snapshot which REQUIRES a date param and
        # returns one row per (sector, exchange) with the field ``averageChange``.
        # Aggregate per sector and translate to the legacy ``changesPercentage``
        # shape that all callers (run_open_prep, smc_provider_policy, ...) expect.
        query_date = _today_et_date()
        for _ in range(6):
            try:
                data = self._get(
                    "/stable/sector-performance-snapshot",
                    {"date": query_date.isoformat()},
                )
            except RuntimeError as exc:
                # A 4xx for a non-trading day or transient network glitch must
                # not abort the walk-back loop — older dates may still succeed.
                logger.warning(
                    "sector-performance-snapshot for %s failed; "
                    "trying previous trading day: %s",
                    query_date.isoformat(),
                    exc,
                )
                query_date = _prev_us_equity_trading_day(query_date)
                continue
            raw_rows = list(data) if isinstance(data, list) else []
            rows = _aggregate_sector_snapshot_rows(raw_rows)
            if rows:
                return rows
            query_date = _prev_us_equity_trading_day(query_date)
        return []


@dataclass
class FinnhubClient:
    """Open-prep facade over the Finnhub REST API.

    Delegates HTTP I/O to :pyfunc:`terminal_finnhub._get` so the same
    DISABLED-pattern (auto-mute on 403/404), rate-limit backoff and
    API-key handling apply to the open-prep run as to the terminal UI.
    Each method returns the *raw* Finnhub JSON shape so existing callers
    in ``open_prep.run_open_prep`` (which already destructure ``data`` /
    ``points`` / ``levels`` / ``technicalAnalysis``) keep working.

    Provider-audit decision (2026-05-12, Option A):
        Finnhub ``/stock/recommendation``, ``/news-sentiment``,
        ``/stock/social-sentiment`` and ``/stock/insider-sentiment``
        carry signals that are **not** 1:1 replicated in FMP, so the
        previous empty-stub shape was actively dropping data on the
        floor. These methods are now wired to live HTTP. Failures still
        return the documented empty shape (``[]`` / ``{}``) so callers
        do not need defensive try/except for the network path.

    The thin facade pattern (rather than importing ``terminal_finnhub``
    free functions directly) is kept because callers already pass a
    ``FinnhubClient`` instance through the open-prep dataflow; switching
    to module-level functions would touch every call site in
    ``run_open_prep`` for no benefit.
    """

    api_key: str = ""

    @classmethod
    def from_env(cls) -> FinnhubClient:
        return cls(api_key=str(os.environ.get("FINNHUB_API_KEY") or ""))

    def available(self) -> bool:
        return bool(self.api_key)

    # ── internal HTTP shim ──
    #
    # We import ``terminal_finnhub`` lazily so the open-prep package can
    # be imported in environments where the terminal stack is not
    # available (e.g. CI smoke tests, headless cron runners that don't
    # ship Streamlit). On import failure we fall back to the original
    # stub behaviour so the run keeps moving — the audit decision to
    # surface Finnhub signals must not break offline runs.
    def _http_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            return None
        try:
            from terminal_finnhub import _get as _finnhub_get
        except Exception:  # pragma: no cover - environmental fallback
            logger.debug(
                "FinnhubClient: terminal_finnhub unavailable; returning empty payload",
                exc_info=True,
            )
            return None
        # R6 (2026-05-12): pass the API key explicitly via the new ``api_key=``
        # kwarg added in ``terminal_finnhub._get``. The previous shim wrote
        # ``self.api_key`` into ``os.environ["FINNHUB_API_KEY"]`` and restored
        # it in a ``finally`` block; that pattern was racy under concurrent
        # FinnhubClient instances and violated the
        # ``tests/test_os_environ_mutation_ledger.py`` spirit. See R6 in
        # ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md``.
        try:
            return _finnhub_get(path, params or {}, api_key=self.api_key)
        except Exception:
            logger.debug("Finnhub %s call failed", path, exc_info=True)
            return None

    def get_insider_sentiment(
        self, symbol: str, from_date: str, to_date: str,
    ) -> dict[str, Any]:
        """Return the raw ``/stock/insider-sentiment`` payload.

        Finnhub returns ``{"data": [{"symbol", "year", "month", "mspr",
        "positiveChange", "negativeChange", ...}, ...], "symbol": ...}``.
        Callers in ``run_open_prep._fetch_insider_sentiment`` destructure
        ``raw["data"]`` directly, so we return the unwrapped dict.
        """
        sym = (symbol or "").strip().upper()
        if not sym or not self.api_key:
            return {}
        raw = self._http_get(
            "/stock/insider-sentiment",
            {"symbol": sym, "from": from_date, "to": to_date},
        )
        return raw if isinstance(raw, dict) else {}

    def get_peers(self, symbol: str) -> list[str]:
        """Return the company-peers list from ``/stock/peers``."""
        sym = (symbol or "").strip().upper()
        if not sym or not self.api_key:
            return []
        raw = self._http_get("/stock/peers", {"symbol": sym})
        return [str(p) for p in raw if isinstance(p, str)] if isinstance(raw, list) else []

    def get_social_sentiment(self, symbol: str) -> dict[str, Any]:
        """Return raw ``/stock/social-sentiment`` payload.

        Note: this endpoint requires a Finnhub paid tier; the
        ``terminal_finnhub._get`` shim records a permanent DISABLED flag
        on the first 403 so subsequent calls short-circuit without
        burning quota.
        """
        sym = (symbol or "").strip().upper()
        if not sym or not self.api_key:
            return {}
        raw = self._http_get("/stock/social-sentiment", {"symbol": sym})
        return raw if isinstance(raw, dict) else {}

    def get_pattern_recognition(self, symbol: str) -> dict[str, Any]:
        """Return raw ``/scan/pattern`` payload (``points`` list inside)."""
        sym = (symbol or "").strip().upper()
        if not sym or not self.api_key:
            return {}
        raw = self._http_get(
            "/scan/pattern", {"symbol": sym, "resolution": "D"},
        )
        return raw if isinstance(raw, dict) else {}

    def get_support_resistance(self, symbol: str) -> dict[str, Any]:
        """Return raw ``/scan/support-resistance`` payload."""
        sym = (symbol or "").strip().upper()
        if not sym or not self.api_key:
            return {}
        raw = self._http_get(
            "/scan/support-resistance",
            {"symbol": sym, "resolution": "D"},
        )
        return raw if isinstance(raw, dict) else {}

    def get_aggregate_indicators(self, symbol: str) -> dict[str, Any]:
        """Return raw ``/scan/technical-indicator`` payload."""
        sym = (symbol or "").strip().upper()
        if not sym or not self.api_key:
            return {}
        raw = self._http_get(
            "/scan/technical-indicator",
            {"symbol": sym, "resolution": "D"},
        )
        return raw if isinstance(raw, dict) else {}

    def get_fda_calendar(self) -> list[dict[str, Any]]:
        """Return ``/fda-advisory-committee-meeting-calendar`` rows.

        Finnhub returns a list of dicts; older plans return 403 which
        the shim auto-mutes via the DISABLED-pattern.
        """
        if not self.api_key:
            return []
        raw = self._http_get("/fda-advisory-committee-meeting-calendar")
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]
        return []
