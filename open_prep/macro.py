from __future__ import annotations

import functools
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

        # FMP returns {"Error Message": "..."} or {"message": "..."} on auth/plan errors.
        if isinstance(data, dict) and ("Error Message" in data or "message" in data):
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


@functools.lru_cache(maxsize=512)
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
        if impact_level in HIGH_IMPACT_LEVELS:
            out.append(event)
            continue
        if not impact_level and _is_high_impact_event_name(name, watchlist=DEFAULT_HIGH_IMPACT_EVENTS):
            out.append(event)
    return out


def _event_impact_level(event: dict[str, Any]) -> str:
    impact = event.get("impact", event.get("importance", event.get("priority")))
    return str(impact or "").strip().lower()


def filter_us_mid_impact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """US-only subset for medium-impact releases based on provider impact tags."""
    out: list[dict[str, Any]] = []
    for event in filter_us_events(events):
        if _event_impact_level(event) not in MID_IMPACT_LEVELS:
            continue

        name = str(event.get("event") or event.get("name") or "")
        normalized_name = _normalize_event_name(name)

        if any(_contains_keywords(normalized_name, p) for p in MID_IMPACT_EXCLUDE_PATTERNS):
            continue

        if any(_contains_keywords(normalized_name, p) for p in MID_IMPACT_MACRO_NAME_PATTERNS):
            out.append(event)
    return out


def macro_bias_score(events: list[dict[str, Any]], include_mid_if_no_high: bool = True) -> float:
    """Return bias in range [-1, 1], where +1 means risk-on and -1 risk-off.

    Scoring weights:
      CPI / PPI / PCE surprise  : ±1.0  (inflation = primary Fed driver)
      Average Hourly Earnings   : ±0.5  (wage inflation → hawkish = risk-off on beat)
      Unemployment Rate         : ±0.5  (higher = risk-off)
      Jobless Claims            : ±0.5
      JOLTS / Job Openings      : ±0.5  (tight labor = risk-on)
      NFP / ISM / PhillyFed     : ±0.5
      GDP / Retail Sales        : ±0.5
      Mid-impact fallback       : ±0.25 (only used when no high-impact events exist)

    Dividing by 2.0 normalises the range so a CPI + PPI double-beat saturates
    the output at +1.0 / -1.0 without overflow for typical trading days.
    """
    score = 0.0

    high_impact_events = filter_us_high_impact_events(events)
    events_for_bias = high_impact_events
    if include_mid_if_no_high and not high_impact_events:
        events_for_bias = filter_us_mid_impact_events(events)

    for event in events_for_bias:
        raw_name = str(event.get("event") or event.get("name") or "")
        # Normalise to lowercase so matching is case-insensitive regardless of
        # which FMP field variant (e.g. "CPI" vs "cpi") the response contains.
        name = _normalize_event_name(raw_name)
        actual = event.get("actual")
        consensus = event.get("consensus", event.get("forecast", event.get("estimate")))

        if actual is None or consensus is None:
            continue

        try:
            surprise = float(actual) - float(consensus)
        except (TypeError, ValueError):
            continue

        if "ppi" in name or "cpi" in name or "pce" in name:
            if surprise > 0:
                score += -1.0
            elif surprise < 0:
                score += +1.0
            # surprise == 0.0: on-consensus print — no directional contribution
        elif "average hourly earnings" in name:
            # Wage inflation above consensus is hawkish (risk-off), not risk-on.
            if surprise > 0:
                score += -0.5
            elif surprise < 0:
                score += +0.5
        elif "unemployment rate" in name:
            # Rising unemployment = economic weakness = risk-off.
            if surprise > 0:
                score += -0.5
            elif surprise < 0:
                score += +0.5
        elif "jobless claims" in name or "initial claims" in name:
            if surprise > 0:
                score += -0.5
            elif surprise < 0:
                score += +0.5
        elif "jolts" in name or "job openings" in name:
            # More openings = tight labor market = risk-on.
            if surprise > 0:
                score += +0.5
            elif surprise < 0:
                score += -0.5
        elif "philadelphia fed" in name or "philly fed" in name or "ism" in name:
            if surprise > 0:
                score += +0.5
            elif surprise < 0:
                score += -0.5
        elif "nonfarm payroll" in name:
            if surprise > 0:
                score += +0.5
            elif surprise < 0:
                score += -0.5
        elif "retail sales" in name or ("gdp" in name and "gdpnow" not in name):
            # Exclude GDPNow model updates — they are estimates, not official releases.
            if surprise > 0:
                score += +0.5
            elif surprise < 0:
                score += -0.5
        elif any(_contains_keywords(name, p) for p in MID_IMPACT_MACRO_NAME_PATTERNS):
            # Secondary mid-impact releases (housing, consumer sentiment, etc.).
            if surprise > 0:
                score += +0.25
            elif surprise < 0:
                score += -0.25

    # See docstring for why 2.0 is the correct divisor.
    normalized = score / 2.0
    return max(-1.0, min(1.0, normalized))
