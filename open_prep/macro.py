from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

DEFAULT_HIGH_IMPACT_EVENTS: set[str] = {
    "CPI",
    "Core CPI",
    "PPI",
    "Core PPI",
    "Nonfarm Payrolls",
    "Unemployment Rate",
    "Average Hourly Earnings",
    "Retail Sales",
    "PCE",
    "Core PCE",
    "Personal Consumption Expenditures",
    "Initial Jobless Claims",
    "ISM Manufacturing PMI",
    "ISM Services PMI",
    "Philadelphia Fed Manufacturing Index",
    "JOLTS Job Openings",
    "GDP",
}

US_COUNTRY_CODES: set[str] = {"US", "USA", "UNITED STATES"}
US_CURRENCIES: set[str] = {"USD"}
HIGH_IMPACT_LEVELS: set[str] = {"high"}
MID_IMPACT_LEVELS: set[str] = {"medium", "mid", "moderate"}

HIGH_IMPACT_NAME_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("cpi",),
    ("consumer", "price", "index"),
    ("ppi",),
    ("producer", "price", "index"),
    ("nonfarm", "payroll"),
    ("unemployment", "rate"),
    ("average", "hourly", "earnings"),
    ("retail", "sales"),
    ("jobless", "claims"),
    ("initial", "claims"),
    ("ism", "manufacturing"),
    ("ism", "services"),
    ("philly", "fed"),
    ("philadelphia", "fed"),
    ("jolts",),
    ("job", "openings"),
    ("gross", "domestic", "product"),
    ("gdp",),
    ("pce",),
    ("personal", "consumption", "expenditures"),
)

MID_IMPACT_MACRO_NAME_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("ism", "manufacturing"),
    ("ism", "services"),
    ("philly", "fed"),
    ("philadelphia", "fed"),
    ("consumer", "sentiment"),
    ("consumer", "confidence"),
    ("inflation", "expectations"),
    ("new", "home", "sales"),
    ("existing", "home", "sales"),
    ("housing", "starts"),
    ("building", "permits"),
    ("durable", "goods"),
    ("factory", "orders"),
    ("leading", "indicators"),
    ("gdpnow",),
    ("atlanta", "fed", "gdpnow"),
)

MID_IMPACT_EXCLUDE_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("cftc",),
    ("speculative", "net", "positions"),
)

FORCED_HIGH_IMPACT_CANONICAL_KEYS: set[str] = {
    "core_pce_mom",
    "core_cpi_mom",
    "core_ppi_mom",
    "cpi_mom",
    "ppi_mom",
    "cpi",
    "core_cpi",
    "ppi",
    "core_ppi",
    "cpi_yoy",
    "core_cpi_yoy",
    "ppi_yoy",
    "core_ppi_yoy",
    "nfp",
    "unemployment",
    "hourly_earnings",
    "jobless_claims",
    "jolts",
    "ism",
    "philly_fed",
    "gdp_qoq",
    "retail_sales",
}

FORCED_MID_IMPACT_CANONICAL_KEYS: set[str] = {
    "pce_mom",
    "pmi_sp_global",
}

CONSENSUS_FIELD_CANDIDATES: tuple[str, ...] = (
    "consensus",
    "estimate",
    "forecast",
    "expected",
)


@dataclass(slots=True)
class FMPClient:
    """Minimal FMP client for economics calendar and quote snapshots."""

    # repr=False keeps the API key out of logs and tracebacks.
    api_key: str = field(repr=False)
    base_url: str = "https://financialmodelingprep.com"
    timeout_seconds: int = 20
    # Cached once at construction; avoids re-parsing the CA bundle on every request.
    _ssl_ctx: ssl.SSLContext = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    @classmethod
    def from_env(cls, key_name: str = "FMP_API_KEY") -> "FMPClient":
        value = os.environ.get(key_name)
        if not value:
            raise ValueError(
                f"Missing {key_name}. Add it to your shell or .env before running open prep."
            )
        return cls(api_key=value)

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        query = dict(params)
        query["apikey"] = self.api_key
        url = f"{self.base_url}{path}?{urlencode(query)}"
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self._ssl_ctx,
            ) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")
                error_data = json.loads(error_body)
                error_msg = error_data.get("Error Message", error_data.get("message", exc.reason))
            except Exception:
                error_msg = exc.reason
            raise RuntimeError(
                f"FMP API HTTP {exc.code} on {path}: {error_msg}"
            ) from exc
        except urllib.error.URLError as exc:
            # Catches timeout, DNS failure, connection reset, etc.
            # Never let the raw exception propagate — it contains the full URL
            # including the API key as a query parameter.
            raise RuntimeError(
                f"FMP API network error on {path}: {exc.reason}"
            ) from exc
        
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"FMP API returned invalid JSON on {path}: {payload[:100]}"
            ) from exc

        # FMP errors may be returned as dict payloads. Keep detection precise to
        # avoid false positives for successful payloads that include a generic
        # informational "message" field.
        if isinstance(data, dict):
            if "Error Message" in data:
                raise RuntimeError(f"FMP API error on {path}: {data}")
            status = str(data.get("status") or "").strip().lower()
            if status == "error":
                raise RuntimeError(f"FMP API error on {path}: {data}")
            if "message" in data and not any(
                key in data
                for key in (
                    "symbol",
                    "date",
                    "event",
                    "data",
                    "results",
                    "historical",
                    "financials",
                    "quotes",
                )
            ):
                raise RuntimeError(f"FMP API error on {path}: {data}")
        return data

    def get_macro_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        data = self._get(
            "/stable/economic-calendar",
            {"from": date_from.isoformat(), "to": date_to.isoformat()},
        )
        return data if isinstance(data, list) else []

    def get_batch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Fetch quotes for all symbols in a single batch request."""
        if not symbols:
            return []
        data = self._get("/stable/batch-quote", {"symbols": ",".join(symbols)})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_fmp_articles(self, limit: int = 200) -> list[dict[str, Any]]:
        """Fetch latest cross-market articles from FMP stable endpoint.

        Note: this endpoint is not symbol-filtered; filtering is done locally
        using the article `tickers` metadata and title/content matching.
        """
        safe_limit = max(1, min(int(limit), 1000))
        data = self._get("/stable/fmp-articles", {"limit": safe_limit})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_historical_price_eod_full(
        self,
        symbol: str,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        """Fetch full EOD history (OHLCV) from stable endpoint for one symbol."""
        data = self._get(
            "/stable/historical-price-eod/full",
            {
                "symbol": symbol,
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
            },
        )
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]


CANONICAL_EVENT_PATTERNS = [
    ("core_pce_mom", [r"\bcore\b", r"\bpce\b", r"\bmom\b"]),
    ("pce_mom",      [r"(?<!core )\bpce\b", r"\bmom\b"]),
    # YoY PCE entries must come AFTER the MoM entries so the longer/more-specific
    # MoM patterns have priority when both "mom" and "yoy" appear in the same name.
    ("core_pce_yoy", [r"\bcore\b", r"\bpce\b", r"\byoy\b"]),
    ("pce_yoy",      [r"(?<!core )\bpce\b", r"\byoy\b"]),
    ("gdp_qoq",      [r"\bgdp\b|\bgross domestic product\b", r"\bqoq\b"]),
    ("jobless_claims", [r"\bjobless\b|\binitial claims\b|\bcontinuing claims\b"]),
    ("philly_fed",   [r"\bphiladelphia\b|\bphilly\b", r"\bfed\b"]),
    ("pmi_sp_global", [r"\bs&p\b|\bs and p\b", r"\bglobal\b", r"\bpmi\b"]),
    ("ism",          [r"\bism\b"]),
    ("retail_sales", [r"\bretail\b", r"\bsales\b"]),
    ("cpi_mom",      [r"(?<!core )\bcpi\b", r"\bmom\b"]),
    ("core_cpi_mom", [r"\bcore\b", r"\bcpi\b", r"\bmom\b"]),
    ("ppi_mom",      [r"(?<!core )\bppi\b", r"\bmom\b"]),
    ("core_ppi_mom", [r"\bcore\b", r"\bppi\b", r"\bmom\b"]),
    # YoY CPI/PPI patterns must come AFTER MoM but BEFORE the bare cpi/ppi
    # patterns, otherwise "CPI YoY" would fall through to the bare "cpi" key
    # and receive weight 1.0 instead of the intended 0.25 for derived prints.
    ("cpi_yoy",      [r"(?<!core )\bcpi\b", r"\byoy\b"]),
    ("core_cpi_yoy", [r"\bcore\b", r"\bcpi\b", r"\byoy\b"]),
    ("ppi_yoy",      [r"(?<!core )\bppi\b", r"\byoy\b"]),
    ("core_ppi_yoy", [r"\bcore\b", r"\bppi\b", r"\byoy\b"]),
    ("cpi",          [r"(?<!core )\bcpi\b"]),
    ("core_cpi",     [r"\bcore\b", r"\bcpi\b"]),
    ("ppi",          [r"(?<!core )\bppi\b"]),
    ("core_ppi",     [r"\bcore\b", r"\bppi\b"]),
    ("nfp",          [r"\bnonfarm\b", r"\bpayroll\b"]),
    ("unemployment", [r"\bunemployment\b", r"\brate\b"]),
    ("hourly_earnings", [r"\baverage\b", r"\bhourly\b", r"\bearnings\b"]),
    ("jolts",        [r"\bjolts\b|\bjob openings\b"]),
]

def canonicalize_event_name(raw: str) -> str | None:
    name = _normalize_event_name(raw)
    for key, pats in CANONICAL_EVENT_PATTERNS:
        if all(re.search(p, name) for p in pats):
            return key
    return None

def _impact_rank(v: str | None) -> int:
    v = (v or "").lower()
    return {"high": 3, "medium": 2, "mid": 2, "moderate": 2, "low": 1}.get(v, 0)


def get_consensus(event: dict[str, Any]) -> tuple[Any, str | None]:
    for field in CONSENSUS_FIELD_CANDIDATES:
        value = event.get(field)
        if value is not None:
            return value, field
    return None, None


def _annotate_event_quality(event: dict[str, Any], actual: Any, consensus: Any, consensus_field: str | None) -> dict[str, Any]:
    """Return quality annotations without mutating the original event dict."""
    flags: list[str] = []
    if actual is None:
        flags.append("missing_actual")
    if consensus is None:
        flags.append("missing_consensus")
    if not event.get("unit"):
        flags.append("missing_unit")

    return {"consensus_field": consensus_field, "data_quality_flags": flags}

def _dedupe_quality(e: dict) -> tuple:
    """Sort key for duplicate-event selection: prefer higher impact, then
    more-complete data fields, then a stable alphabetic name tiebreaker."""
    actual = e.get("actual")
    cons, _ = get_consensus(e)
    return (
        _impact_rank(e.get("impact")),
        1 if actual is not None else 0,
        1 if cons is not None else 0,
        # Fall back to "name" field so events without an "event" key
        # are still disambiguated deterministically.
        e.get("event") or e.get("name") or "",
    )


def dedupe_events(events: list[dict]) -> list[dict]:
    buckets: dict[tuple[str, str, str], list[dict]] = {}
    passthrough: list[dict] = []
    for e in events:
        country_raw = str(e.get("country") or "").strip().upper()
        currency_raw = str(e.get("currency") or "").strip().upper()
        # Some providers omit `country` for US releases but still set `currency=USD`.
        # Preserve these events by assigning a stable US key so they can be deduped
        # and scored instead of being silently dropped.
        country = country_raw or ("US" if currency_raw in US_CURRENCIES else "")
        # Guard against date=None: the .get() default only fires when the key
        # is absent; if date IS present but None we must still substitute so
        # unrelated null-dated events are not incorrectly grouped together.
        event_date = e.get("date") or "1970-01-01"  # Fallback for tests
        raw_name = e.get("event") or e.get("name") or ""
        key = canonicalize_event_name(raw_name)
        if not country:
            continue
        if not key:
            # Non-canonical events (e.g. Consumer Sentiment, Housing Starts)
            # are passed through unchanged so downstream mid-impact filters
            # and scoring can still see them.
            passthrough.append(e)
            continue
        buckets.setdefault((country, event_date, key), []).append(e)

    out = []
    for k, items in buckets.items():
        if len(items) == 1:
            single = dict(items[0])  # copy to avoid mutating caller's dict
            if not single.get("country"):
                single["country"] = k[0]
            single["canonical_event"] = k[2]
            out.append(single)
            continue

        sorted_items = sorted(items, key=_dedupe_quality, reverse=True)
        chosen = sorted_items[0]
        chosen = dict(chosen)  # copy
        if not chosen.get("country"):
            chosen["country"] = k[0]
        chosen["canonical_event"] = k[2]
        chosen["dedup"] = {
            "was_deduped": True,
            "duplicates_count": len(items),
            "duplicates": [i.get("event") for i in items],
            "chosen_event": chosen.get("event") or chosen.get("name"),
            "policy": "impact_then_fields_then_name",
        }
        out.append(chosen)

    return out + passthrough

def _normalize_event_name(name: str) -> str:
    lowered = name.lower()
    lowered = lowered.replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


# Pre-computed once at import time to avoid rebuilding the normalized set
# on every call to _is_high_impact_event_name (DEFAULT_HIGH_IMPACT_EVENTS is constant).
_DEFAULT_HIGH_IMPACT_EVENTS_NORMALIZED: frozenset[str] = frozenset(
    _normalize_event_name(e) for e in DEFAULT_HIGH_IMPACT_EVENTS
)


def _is_high_impact_event_name(name: str, watchlist: set[str]) -> bool:
    normalized = _normalize_event_name(name)
    # GDPNow is a real-time model estimate, not an official data release;
    # exclude it explicitly before any pattern matching.
    if "gdpnow" in normalized:
        return False
    # Use the pre-computed frozenset for the default watchlist; only fall
    # back to per-call set building for custom watchlists.
    if watchlist is DEFAULT_HIGH_IMPACT_EVENTS:
        if normalized in _DEFAULT_HIGH_IMPACT_EVENTS_NORMALIZED:
            return True
    else:
        if normalized in {_normalize_event_name(item) for item in watchlist}:
            return True

    for keywords in HIGH_IMPACT_NAME_PATTERNS:
        if all(keyword in normalized for keyword in keywords):
            return True

    return False


def _contains_keywords(normalized_name: str, pattern: tuple[str, ...]) -> bool:
    return all(keyword in normalized_name for keyword in pattern)


def filter_us_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep events that are likely US macro releases."""
    out: list[dict[str, Any]] = []
    for event in events:
        country = str(event.get("country") or "").strip().upper()
        currency = str(event.get("currency") or "").strip().upper()
        if country in US_COUNTRY_CODES or currency in US_CURRENCIES:
            out.append(event)
    return out


def filter_us_high_impact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """US-only and high-impact subset used for open-bias scoring.

    Priority:
    1) Provider-tagged high impact.
    2) Name-based fallback when impact tag is missing.
    """
    out: list[dict[str, Any]] = []
    for event in filter_us_events(events):
        impact_level = _event_impact_level(event)
        name = str(event.get("event") or event.get("name") or "")
        canonical_key = canonicalize_event_name(name)
        if impact_level in HIGH_IMPACT_LEVELS:
            out.append(event)
            continue
        if canonical_key in FORCED_HIGH_IMPACT_CANONICAL_KEYS and impact_level != "low":
            out.append(event)
            continue
        if not impact_level and _is_high_impact_event_name(name, watchlist=DEFAULT_HIGH_IMPACT_EVENTS):
            out.append(event)
    return out


def _event_impact_level(event: dict[str, Any]) -> str:
    impact = event.get("impact", event.get("importance", event.get("priority")))
    return str(impact or "").strip().lower()


def filter_us_mid_impact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mid-impact US event subset based on provider impact tags and name patterns.

    Expects pre-filtered US events (e.g. output of filter_us_events / dedupe_events).
    No additional US country check is applied here; callers are responsible for
    passing US-scoped events.
    """
    out: list[dict[str, Any]] = []
    for event in events:
        name = str(event.get("event") or event.get("name") or "")
        canonical_key = canonicalize_event_name(name)
        if canonical_key in FORCED_MID_IMPACT_CANONICAL_KEYS:
            out.append(event)
            continue

        if _event_impact_level(event) not in MID_IMPACT_LEVELS:
            continue

        normalized_name = _normalize_event_name(name)

        if any(_contains_keywords(normalized_name, p) for p in MID_IMPACT_EXCLUDE_PATTERNS):
            continue

        if any(_contains_keywords(normalized_name, p) for p in MID_IMPACT_MACRO_NAME_PATTERNS):
            out.append(event)
    return out


def _events_for_bias(
    events: list[dict[str, Any]],
    include_mid_if_no_high: bool,
    include_headline_pce_confirm: bool = True,
) -> list[dict[str, Any]]:
    # Canonicalize+dedupe first across the full US event set so duplicates that
    # straddle provider impact buckets cannot slip through.
    us_events = dedupe_events(filter_us_events(events))

    high_impact_events = filter_us_high_impact_events(us_events)
    events_for_bias = list(high_impact_events)
    if include_mid_if_no_high and not high_impact_events:
        events_for_bias = filter_us_mid_impact_events(us_events)

    # Always include headline PCE as a lightweight confirm/check signal,
    # even when high-impact events are present.
    if include_headline_pce_confirm:
        existing_keys = {
            (
                str(e.get("country") or ""),
                str(e.get("date") or ""),
                str(e.get("canonical_event") or ""),
            )
            for e in events_for_bias
        }
        for event in us_events:
            if event.get("canonical_event") != "pce_mom":
                continue
            key = (
                str(event.get("country") or ""),
                str(event.get("date") or ""),
                str(event.get("canonical_event") or ""),
            )
            if key in existing_keys:
                continue
            events_for_bias.append(event)
            existing_keys.add(key)

    return events_for_bias


def macro_bias_with_components(
    events: list[dict[str, Any]],
    include_mid_if_no_high: bool = True,
    include_headline_pce_confirm: bool = True,
) -> dict[str, Any]:
    score = 0.0
    components: list[dict[str, Any]] = []
    # Make independent copies of every event so that:
    #  (a) passthrough events (non-canonical, appended by-reference in dedupe_events)
    #      do not get mutated from the caller's perspective, and
    #  (b) downstream consumers of macro_analysis["events_for_bias"] (e.g. the BEA
    #      audit) receive events that already carry computed data_quality_flags.
    events_for_bias = [dict(e) for e in _events_for_bias(
        events,
        include_mid_if_no_high=include_mid_if_no_high,
        include_headline_pce_confirm=include_headline_pce_confirm,
    )]

    for event in events_for_bias:
        raw_name = str(event.get("event") or event.get("name") or "")
        name = _normalize_event_name(raw_name)
        canonical_key = event.get("canonical_event")
        actual = event.get("actual")
        consensus, consensus_field = get_consensus(event)
        quality = _annotate_event_quality(event, actual=actual, consensus=consensus, consensus_field=consensus_field)
        # Annotate the (already-copied) event so that downstream consumers
        # such as build_bea_audit_payload can read data_quality_flags directly.
        event["data_quality_flags"] = quality["data_quality_flags"]
        event["consensus_field"] = quality["consensus_field"]

        component: dict[str, Any] = {
            "date": event.get("date"),
            "country": event.get("country"),
            "event": raw_name,
            "canonical_event": canonical_key,
            "impact": event.get("impact", event.get("importance", event.get("priority"))),
            "actual": actual,
            "consensus_value": consensus,
            "consensus_field": consensus_field,
            "surprise": None,
            "weight": 0.0,
            "contribution": 0.0,
            "skip_reason": None,
            "data_quality_flags": quality["data_quality_flags"],
            "dedup": event.get("dedup"),
        }

        if actual is None or consensus is None:
            component["skip_reason"] = "missing_actual_or_consensus"
            components.append(component)
            continue

        try:
            surprise = float(actual) - float(consensus)
        except (TypeError, ValueError):
            component["skip_reason"] = "non_numeric_actual_or_consensus"
            components.append(component)
            continue

        component["surprise"] = round(surprise, 6)

        if surprise == 0.0:
            component["skip_reason"] = "on_consensus"
            components.append(component)
            continue

        weight = 0.0
        sign = 0.0

        if canonical_key in (
            "core_pce_mom",
            "cpi_mom",
            "core_cpi_mom",
            "ppi_mom",
            "core_ppi_mom",
            "cpi",
            "core_cpi",
            "ppi",
            "core_ppi",
        ):
            weight = 1.0
            sign = -1.0 if surprise > 0 else +1.0
        elif canonical_key in (
            "pce_mom", "pce_yoy", "core_pce_yoy",
            "cpi_yoy", "core_cpi_yoy",
            "ppi_yoy", "core_ppi_yoy",
        ):
            # YoY variants carry reduced weight — the MoM prints already carry
            # full 1.0 weight and YoY is derived from the same underlying data.
            # Headline PCE MoM (pce_mom) is also 0.25 since Core PCE is the
            # primary Fed-watch print at weight 1.0.
            weight = 0.25
            sign = -1.0 if surprise > 0 else +1.0
        elif canonical_key == "hourly_earnings" or "average hourly earnings" in name:
            weight = 0.5
            sign = -1.0 if surprise > 0 else +1.0
        elif canonical_key == "unemployment" or "unemployment rate" in name:
            weight = 0.5
            sign = -1.0 if surprise > 0 else +1.0
        elif canonical_key == "jobless_claims" or "jobless claims" in name or "initial claims" in name:
            weight = 0.5
            sign = -1.0 if surprise > 0 else +1.0
        elif canonical_key == "jolts" or "jolts" in name or "job openings" in name:
            weight = 0.5
            sign = +1.0 if surprise > 0 else -1.0
        elif canonical_key == "pmi_sp_global" or (
            "pmi" in name and ("s p global" in name or "s and p global" in name)
        ):
            weight = 0.25
            sign = +1.0 if surprise > 0 else -1.0
        elif canonical_key in ("ism", "philly_fed") or "philadelphia fed" in name or "philly fed" in name or "ism" in name:
            weight = 0.5
            sign = +1.0 if surprise > 0 else -1.0
        elif canonical_key == "nfp" or "nonfarm payroll" in name:
            weight = 0.5
            sign = +1.0 if surprise > 0 else -1.0
        elif canonical_key in ("retail_sales", "gdp_qoq") or "retail sales" in name or (
            "gdp" in name and "gdpnow" not in name
        ):
            weight = 0.5
            sign = +1.0 if surprise > 0 else -1.0
        elif any(_contains_keywords(name, p) for p in MID_IMPACT_MACRO_NAME_PATTERNS):
            weight = 0.25
            sign = +1.0 if surprise > 0 else -1.0
        elif canonical_key is None and ("ppi" in name or "cpi" in name or "pce" in name):
            # Non-canonical inflation variants (e.g. CPI YoY, PCE YoY) get
            # reduced weight — the MoM prints already carry full 1.0 weight
            # and YoY is derived from the same underlying data.
            weight = 0.25
            sign = -1.0 if surprise > 0 else +1.0
        else:
            component["skip_reason"] = "unmapped_event"
            components.append(component)
            continue

        contribution = sign * weight
        score += contribution

        component["weight"] = weight
        component["contribution"] = round(contribution, 6)
        components.append(component)

    normalized = max(-1.0, min(1.0, score / 2.0))
    return {
        "macro_bias": normalized,
        "raw_score": score,
        "events_for_bias": events_for_bias,
        "score_components": components,
    }


def macro_bias_score(
    events: list[dict[str, Any]],
    include_mid_if_no_high: bool = True,
    include_headline_pce_confirm: bool = True,
) -> float:
    """Return bias in range [-1, 1], where +1 means risk-on and -1 risk-off.

    Scoring weights:
      Core PCE / Core CPI / CPI MoM / PPI MoM : ±1.0  (primary inflation drivers)
      Headline PCE MoM / YoY variants          : ±0.25 (derived / secondary prints)
      Average Hourly Earnings                  : ±0.5  (wage inflation; hawkish on beat)
      Unemployment Rate                        : ±0.5  (higher = risk-off)
      Jobless Claims                           : ±0.5
      JOLTS / Job Openings                     : ±0.5  (tight labor = risk-on)
      NFP / ISM / PhillyFed                    : ±0.5
      GDP / Retail Sales                       : ±0.5
      Mid-impact fallback                      : ±0.25 (only when no high-impact events)

    Dividing by 2.0 normalises the range so a CPI + PPI double-beat saturates
    the output at +1.0 / -1.0 without overflow for typical trading days.
    """
    return float(
        macro_bias_with_components(
            events,
            include_mid_if_no_high=include_mid_if_no_high,
            include_headline_pce_confirm=include_headline_pce_confirm,
        )["macro_bias"]
    )
