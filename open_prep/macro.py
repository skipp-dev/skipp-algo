from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import io
import json
import logging
import os
import ssl
import time
import urllib.error
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

try:
    from newsstack_fmp._market_cal import prev_trading_day as _prev_trading_day
except Exception:  # pragma: no cover
    pass


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
        return max(float(raw_value), 0.0)
    except (TypeError, ValueError):
        pass
    try:
        parsed = parsedate_to_datetime(str(raw_value))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max((parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds(), 0.0)


def _normalize_tls_certificate_env() -> str | None:
    if certifi is None:
        return None
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
        event.clear()
        event.update(annotated_event)

    return {
        "macro_bias": max(min(total / 2.0, 1.0), -1.0),
        "events_for_bias": events_for_bias,
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


class _CircuitBreaker:
    def __init__(self, cooldown_seconds: float = 60.0) -> None:
        self.cooldown_seconds = max(cooldown_seconds, 1.0)
        self._state = "CLOSED"
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        return self._state

    def allow_request(self) -> bool:
        if self._state == "OPEN":
            if time.time() - self._opened_at >= self.cooldown_seconds:
                self._state = "HALF_OPEN"
                return True
            return False
        return True

    def on_success(self) -> None:
        self._state = "CLOSED"
        self._opened_at = 0.0

    def on_failure(self) -> None:
        self._state = "OPEN"
        self._opened_at = time.time()


def _log_feature_unavailable_once(feature_key: str, message: str) -> None:
    if feature_key in _FMP_FEATURE_UNAVAILABLE_LOGGED:
        return
    _FMP_FEATURE_UNAVAILABLE_LOGGED.add(feature_key)
    logger.info(message)


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

    @classmethod
    def from_env(cls) -> "FMPClient":
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
            raise RuntimeError(f"FMP API returned HTML on {path}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            first_line = text.splitlines()[0] if text else ""
            if "," in first_line and (first_line.startswith('"') or first_line.lower().startswith("symbol,")):
                reader = csv.DictReader(io.StringIO(text))
                return [{key: _coerce_csv_value(value) for key, value in row.items()} for row in reader]
            raise RuntimeError(f"FMP API returned invalid JSON on {path}: {text[:120]}")
        if isinstance(data, dict) and str(data.get("status") or "").lower() == "error":
            raise RuntimeError(f"FMP API error on {path}: {data.get('message') or 'unknown error'}")
        return data

    def _request_once(self, path: str, params: dict[str, Any]) -> Any:
        request = Request(self._build_url(path, params), headers={"User-Agent": "skipp-algo/1.0"})
        with urlopen(request, timeout=self.timeout_seconds, context=_build_tls_context()) as response:
            payload = response.read().decode("utf-8")
        return self._parse_payload(path, payload)

    def _execute_get(self, path: str, params: dict[str, Any], *, use_circuit_breaker: bool) -> Any:
        if use_circuit_breaker and not self._circuit_breaker.allow_request():
            raise RuntimeError(f"FMP API circuit open for {path}")
        max_attempts = max(self.retry_attempts, 1)
        for attempt in range(max_attempts):
            try:
                data = self._request_once(path, params)
                if use_circuit_breaker:
                    self._circuit_breaker.on_success()
                return data
            except urllib.error.HTTPError as exc:
                transient = exc.code in {429, 500, 502, 503, 504}
                if transient and attempt + 1 < max_attempts:
                    headers = getattr(exc, "headers", None) or {}
                    retry_after = _parse_retry_after_seconds(headers.get("Retry-After"))
                    delay = retry_after if retry_after is not None else self.retry_backoff_seconds * (attempt + 1)
                    time.sleep(max(delay, 0.0))
                    continue
                if use_circuit_breaker:
                    self._circuit_breaker.on_failure()
                body = ""
                if getattr(exc, "fp", None) is not None:
                    try:
                        body = exc.fp.read().decode("utf-8")
                    except Exception:
                        body = ""
                raise RuntimeError(f"FMP API HTTP {exc.code} on {path}: {body or exc.msg or 'HTTP error'}") from exc
            except urllib.error.URLError as exc:
                if attempt + 1 < max_attempts:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
                    continue
                if use_circuit_breaker:
                    self._circuit_breaker.on_failure()
                raise RuntimeError(f"FMP API network error on {path}: {exc}") from exc
            except RuntimeError:
                if use_circuit_breaker:
                    self._circuit_breaker.on_failure()
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
        except RuntimeError:
            _log_feature_unavailable_once(
                "stable/profile-bulk",
                "FMP feature unavailable (stable/profile-bulk); continuing without profile bulk data.",
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_profiles(self, symbols: list[str]) -> list[dict[str, Any]]:
        requested_symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
        if not requested_symbols:
            return []
        try:
            data = self._get("/stable/profile", {"symbol": ",".join(requested_symbols)})
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_company_screener(self, **kwargs: Any) -> list[dict[str, Any]]:
        try:
            data = self._get("/stable/company-screener", kwargs)
        except RuntimeError:
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
        duration_ms = int(round((time.perf_counter() - started_at) * 1000.0))
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
        except RuntimeError:
            _log_feature_unavailable_once(
                "stable/fmp-articles",
                "FMP feature unavailable (stable/fmp-articles); continuing without FMP article data.",
            )
            return []
        return list(data) if isinstance(data, list) else []

    def get_batch_aftermarket_trade(self, symbols: list[str]) -> list[dict[str, Any]]:
        data = self._get("/stable/batch-aftermarket-trade", {"symbols": ",".join(symbols)})
        return list(data) if isinstance(data, list) else []

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
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_earnings_calendar(self, from_date: date, to_date: date) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        }
        try:
            data = self._get("/stable/earnings-calendar", params)
        except RuntimeError:
            _log_feature_unavailable_once(
                "stable/earnings-calendar",
                "FMP feature unavailable (stable/earnings-calendar); continuing without earnings calendar data.",
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
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_premarket_movers(self) -> list[dict[str, Any]]:
        try:
            data = self._get("/stable/most-actives", {})
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_batch_aftermarket_quote(self, symbols: list[str]) -> list[dict[str, Any]]:
        try:
            data = self._get("/stable/batch-aftermarket-quote", {"symbols": ",".join(symbols)})
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_splits_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        params = {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        try:
            data = self._get("/stable/splits-calendar", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_dividends_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        params = {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        try:
            data = self._get("/stable/dividends-calendar", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_ipos_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        params = {
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        try:
            data = self._get("/stable/ipos-calendar", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_upgrades_downgrades(
        self,
        symbol: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = str(symbol).strip().upper()
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        try:
            data = self._get("/stable/grades", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_insider_trading_latest(self, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": max(int(limit), 1)}
        if symbol:
            params["symbol"] = str(symbol).strip().upper()
        try:
            data = self._get("/stable/insider-trading", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_institutional_ownership(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        params = {
            "symbol": str(symbol).strip().upper(),
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/institutional-ownership", params)
        except RuntimeError:
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
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_house_trading(self, limit: int = 100) -> list[dict[str, Any]]:
        params = {"limit": max(int(limit), 1)}
        try:
            data = self._get("/stable/house-latest", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_dcf(self, symbol: str) -> dict[str, Any]:
        params = {"symbol": str(symbol).strip().upper()}
        try:
            data = self._get("/stable/discounted-cash-flow", params)
        except RuntimeError:
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
        except RuntimeError:
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
        except RuntimeError:
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

    def get_earnings_report(self, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
        params = {
            "symbol": str(symbol).strip().upper(),
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/earnings", params)
        except RuntimeError:
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
        except RuntimeError:
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
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_index_quote(self, symbol: str = "^VIX") -> dict[str, Any]:
        requested_symbol = str(symbol).strip().upper()
        try:
            data = self._get("/stable/quote", {"symbol": requested_symbol})
        except RuntimeError:
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
        params: dict[str, Any] = {}
        if as_of is not None:
            params["date"] = as_of.isoformat()
        try:
            data = self._get("/stable/sector-performance-snapshot", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_sector_performance(self) -> list[dict[str, Any]]:
        today = _today_et_date()
        current = self._get("/stable/sector-performance", {"date": today.isoformat()})
        current_rows = list(current) if isinstance(current, list) else []
        if current_rows:
            return current_rows
        previous_day = _prev_us_equity_trading_day(today)
        fallback = self._get("/stable/sector-performance", {"date": previous_day.isoformat()})
        return list(fallback) if isinstance(fallback, list) else []


@dataclass
class FinnhubClient:
    api_key: str = ""

    @classmethod
    def from_env(cls) -> "FinnhubClient":
        return cls(api_key=str(os.environ.get("FINNHUB_API_KEY") or ""))

    def available(self) -> bool:
        return bool(self.api_key)

    def get_insider_sentiment(self, symbol: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
        _ = (symbol, from_date, to_date)
        return []

    def get_peers(self, symbol: str) -> list[str]:
        _ = symbol
        return []

    def get_social_sentiment(self, symbol: str) -> dict[str, Any]:
        _ = symbol
        return {}

    def get_pattern_recognition(self, symbol: str) -> list[dict[str, Any]]:
        _ = symbol
        return []

    def get_support_resistance(self, symbol: str) -> dict[str, Any]:
        _ = symbol
        return {}

    def get_aggregate_indicators(self, symbol: str) -> dict[str, Any]:
        _ = symbol
        return {}

    def get_fda_calendar(self) -> list[dict[str, Any]]:
        return []
