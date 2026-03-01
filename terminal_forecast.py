"""Analyst forecast data for the Streamlit terminal.

Provides price-target consensus, analyst ratings, EPS estimates,
and recent grades via FMP (``/stable/`` API, primary) with
``yfinance`` as fallback.  Results are cached per symbol with a
configurable TTL.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# ── Optional deps ────────────────────────────────────────────────
try:
    import httpx  # type: ignore[import-untyped]

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

try:
    import yfinance as yf  # type: ignore[import-untyped]

    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False

# ── FMP base URL & client ────────────────────────────────────────
_FMP_BASE = "https://financialmodelingprep.com"
_fmp_client: httpx.Client | None = None
_fmp_client_lock = threading.Lock()
_APIKEY_RE = __import__("re").compile(r"(apikey|api_key|token|key)=[^&\s]+", __import__("re").IGNORECASE)


def _get_fmp_client() -> httpx.Client | None:
    global _fmp_client
    if _fmp_client is None and _HTTPX_AVAILABLE:
        with _fmp_client_lock:
            if _fmp_client is None:
                _fmp_client = httpx.Client(timeout=10.0)
                atexit.register(_fmp_client.close)
    return _fmp_client


def _fmp_key() -> str:
    return os.environ.get("FMP_API_KEY", "")


def _fmp_get(path: str, **params: Any) -> list[dict] | dict | None:
    """GET from FMP /stable/ API.  Returns parsed JSON or None on error."""
    key = _fmp_key()
    if not key:
        return None
    client = _get_fmp_client()
    if client is None:
        return None
    params["apikey"] = key
    try:
        r = client.get(f"{_FMP_BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]
    except Exception as exc:
        log.debug("FMP %s failed: %s", path, _APIKEY_RE.sub(r"\1=***", str(exc)))
        return None


# ── Rating label mapping ────────────────────────────────────────
_RATING_ICON: dict[str, str] = {
    "Strong Buy": "🟢🟢",
    "Buy": "🟢",
    "Hold": "🟡",
    "Sell": "🔴",
    "Strong Sell": "🔴🔴",
}


@dataclass
class PriceTarget:
    """Analyst price-target consensus."""

    current_price: float = 0.0
    target_high: float = 0.0
    target_low: float = 0.0
    target_mean: float = 0.0
    target_median: float = 0.0
    # Extended — from FMP price-target-summary
    last_month_avg: float = 0.0
    last_month_count: int = 0
    last_quarter_avg: float = 0.0
    last_quarter_count: int = 0
    last_year_avg: float = 0.0
    last_year_count: int = 0

    @property
    def upside_pct(self) -> float:
        if self.current_price and self.target_mean:
            return ((self.target_mean - self.current_price) / self.current_price) * 100
        return 0.0

    @property
    def upside_high_pct(self) -> float:
        if self.current_price and self.target_high:
            return ((self.target_high - self.current_price) / self.current_price) * 100
        return 0.0

    @property
    def upside_low_pct(self) -> float:
        if self.current_price and self.target_low:
            return ((self.target_low - self.current_price) / self.current_price) * 100
        return 0.0


@dataclass
class AnalystRating:
    """Analyst recommendation counts."""

    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0
    consensus_label: str = ""  # from FMP "consensus" field

    @property
    def total(self) -> int:
        return self.strong_buy + self.buy + self.hold + self.sell + self.strong_sell

    @property
    def consensus(self) -> str:
        """Return consensus label."""
        if self.consensus_label:
            return self.consensus_label
        if self.total == 0:
            return ""
        counts = {
            "Strong Buy": self.strong_buy,
            "Buy": self.buy,
            "Hold": self.hold,
            "Sell": self.sell,
            "Strong Sell": self.strong_sell,
        }
        return max(counts, key=counts.get)  # type: ignore[arg-type]

    @property
    def consensus_icon(self) -> str:
        return _RATING_ICON.get(self.consensus, "")


@dataclass
class EPSEstimate:
    """One row of quarterly/annual EPS estimate."""

    period: str = ""  # e.g. "2025-09-27" (FMP) or "0q" (yfinance)
    avg: float = 0.0
    low: float = 0.0
    high: float = 0.0
    year_ago_eps: float = 0.0
    num_analysts: int = 0
    growth: float = 0.0  # decimal (0.18 = 18%)
    # Additional FMP fields
    revenue_avg: float = 0.0
    ebitda_avg: float = 0.0


@dataclass
class UpgradeDowngrade:
    """One recent analyst action."""

    date: str = ""
    firm: str = ""
    to_grade: str = ""
    from_grade: str = ""
    action: str = ""  # e.g. "maintain", "upgrade", "downgrade", "init"


@dataclass
class ForecastResult:
    """Full forecast data for one symbol."""

    symbol: str
    ts: float = 0.0
    source: str = ""  # "fmp" or "yfinance"

    price_target: PriceTarget | None = None
    rating: AnalystRating | None = None
    eps_estimates: list[EPSEstimate] = field(default_factory=list)
    upgrades_downgrades: list[UpgradeDowngrade] = field(default_factory=list)

    error: str = ""

    @property
    def has_data(self) -> bool:
        return bool(
            self.price_target
            or self.rating
            or self.eps_estimates
            or self.upgrades_downgrades
        )


# ── In-memory cache ──────────────────────────────────────────────
_cache: dict[str, ForecastResult] = {}
_CACHE_TTL_S = 300.0  # 5 minutes
_CACHE_MAX_SIZE = 200  # evict expired entries when exceeded
_cache_lock = threading.Lock()


# ── FMP fetcher (primary) ────────────────────────────────────────


def _fetch_fmp(sym: str) -> ForecastResult | None:
    """Try fetching forecast data from FMP /stable/ endpoints."""
    if not _fmp_key():
        return None

    result = ForecastResult(symbol=sym, ts=time.time(), source="fmp")
    got_anything = False

    # 1) Price Target Consensus
    pt_data = _fmp_get("/stable/price-target-consensus", symbol=sym)
    if isinstance(pt_data, list) and pt_data:
        d = pt_data[0]
        # Need current price — fetch quick profile
        current = 0.0
        q = _fmp_get("/stable/profile", symbol=sym)
        if isinstance(q, list) and q:
            current = float(q[0].get("price", 0))

        result.price_target = PriceTarget(
            current_price=current,
            target_high=float(d.get("targetHigh", 0)),
            target_low=float(d.get("targetLow", 0)),
            target_mean=float(d.get("targetConsensus", 0)),
            target_median=float(d.get("targetMedian", 0)),
        )
        got_anything = True

        # Enrich with price-target-summary
        pts_data = _fmp_get("/stable/price-target-summary", symbol=sym)
        if isinstance(pts_data, list) and pts_data:
            s = pts_data[0]
            result.price_target.last_month_avg = float(s.get("lastMonthAvgPriceTarget", 0))
            result.price_target.last_month_count = int(s.get("lastMonthCount", 0))
            result.price_target.last_quarter_avg = float(s.get("lastQuarterAvgPriceTarget", 0))
            result.price_target.last_quarter_count = int(s.get("lastQuarterCount", 0))
            result.price_target.last_year_avg = float(s.get("lastYearAvgPriceTarget", 0))
            result.price_target.last_year_count = int(s.get("lastYearCount", 0))

    # 2) Grades Consensus (analyst ratings)
    gc_data = _fmp_get("/stable/grades-consensus", symbol=sym)
    if isinstance(gc_data, list) and gc_data:
        d = gc_data[0]
        result.rating = AnalystRating(
            strong_buy=int(d.get("strongBuy", 0)),
            buy=int(d.get("buy", 0)),
            hold=int(d.get("hold", 0)),
            sell=int(d.get("sell", 0)),
            strong_sell=int(d.get("strongSell", 0)),
            consensus_label=str(d.get("consensus", "")),
        )
        got_anything = True

    # 3) Analyst Estimates (quarterly EPS)
    ae_data = _fmp_get("/stable/analyst-estimates", symbol=sym, period="quarter", limit=8)
    if isinstance(ae_data, list) and ae_data:
        for d in ae_data:
            date_str = d.get("date", "")
            result.eps_estimates.append(EPSEstimate(
                period=date_str,
                avg=float(d.get("epsAvg", 0)),
                low=float(d.get("epsLow", 0)),
                high=float(d.get("epsHigh", 0)),
                num_analysts=int(d.get("numAnalystsEps", 0) or d.get("numberOfAnalysts", 0)),
                revenue_avg=float(d.get("revenueAvg", 0)),
                ebitda_avg=float(d.get("ebitdaAvg", 0)),
            ))
        got_anything = True

    # 4) Grades (individual upgrades/downgrades)
    gr_data = _fmp_get("/stable/grades", symbol=sym, limit=15)
    if isinstance(gr_data, list) and gr_data:
        for d in gr_data:
            result.upgrades_downgrades.append(UpgradeDowngrade(
                date=str(d.get("date", ""))[:10],
                firm=str(d.get("gradingCompany", "")),
                to_grade=str(d.get("newGrade", "")),
                from_grade=str(d.get("previousGrade", "")),
                action=str(d.get("action", "")),
            ))
        got_anything = True

    return result if got_anything else None


# ── yfinance fetcher (fallback) ──────────────────────────────────


def _fetch_yf(sym: str) -> ForecastResult | None:
    """Fallback: fetch forecast data from Yahoo Finance."""
    if not _YF_AVAILABLE:
        return None

    try:
        ticker = yf.Ticker(sym)
        result = ForecastResult(symbol=sym, ts=time.time(), source="yfinance")

        # Price targets
        try:
            pt = ticker.analyst_price_targets
            if pt and isinstance(pt, dict):
                result.price_target = PriceTarget(
                    current_price=float(pt.get("current") or 0),
                    target_high=float(pt.get("high") or 0),
                    target_low=float(pt.get("low") or 0),
                    target_mean=float(pt.get("mean") or 0),
                    target_median=float(pt.get("median") or 0),
                )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            log.debug("yfinance price targets failed for %s: %s", sym, exc)

        # Analyst ratings
        try:
            rec = ticker.recommendations_summary
            if rec is not None and not rec.empty:
                row = rec.iloc[0]
                result.rating = AnalystRating(
                    strong_buy=int(row.get("strongBuy", 0)),
                    buy=int(row.get("buy", 0)),
                    hold=int(row.get("hold", 0)),
                    sell=int(row.get("sell", 0)),
                    strong_sell=int(row.get("strongSell", 0)),
                )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            log.debug("yfinance ratings failed for %s: %s", sym, exc)

        # EPS estimates
        try:
            ee = ticker.earnings_estimate
            if ee is not None and not ee.empty:
                for period_label in ee.index:
                    row = ee.loc[period_label]
                    result.eps_estimates.append(EPSEstimate(
                        period=str(period_label),
                        avg=float(row.get("avg") or 0),
                        low=float(row.get("low") or 0),
                        high=float(row.get("high") or 0),
                        year_ago_eps=float(row.get("yearAgoEps") or 0),
                        num_analysts=int(row.get("numberOfAnalysts") or 0),
                        growth=float(row.get("growth") or 0),
                    ))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            log.debug("yfinance EPS estimates failed for %s: %s", sym, exc)

        # Upgrades / Downgrades
        try:
            ud = ticker.upgrades_downgrades
            if ud is not None and not ud.empty:
                for idx, row in ud.head(15).iterrows():
                    date_str = str(idx)[:10] if idx else ""
                    result.upgrades_downgrades.append(UpgradeDowngrade(
                        date=date_str,
                        firm=str(row.get("Firm", "")),
                        to_grade=str(row.get("ToGrade", "")),
                        from_grade=str(row.get("FromGrade", "")),
                        action=str(row.get("Action", "")),
                    ))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            log.debug("yfinance upgrades/downgrades failed for %s: %s", sym, exc)

        return result if result.has_data else None

    except Exception as exc:
        log.debug("yfinance forecast failed for %s: %s", sym, exc)
        return None


# ── Public API ───────────────────────────────────────────────────


def fetch_forecast(symbol: str, *, force: bool = False) -> ForecastResult:
    """Fetch analyst forecast data for *symbol*.

    Tries FMP first (richer data, /stable/ API), falls back to yfinance.
    Returns cached result if younger than ``_CACHE_TTL_S`` unless *force*.
    """
    sym = symbol.upper().strip()
    now = time.time()

    if not force:
        with _cache_lock:
            cached = _cache.get(sym)
            if cached and (now - cached.ts) < _CACHE_TTL_S:
                return cached

    # Try FMP first (primary)
    result = _fetch_fmp(sym)

    # Fallback to yfinance
    if result is None:
        result = _fetch_yf(sym)

    # Nothing worked
    if result is None:
        result = ForecastResult(symbol=sym, ts=now, error="No forecast data available")

    result.ts = now
    with _cache_lock:
        _cache[sym] = result
        # Evict expired entries when cache grows beyond limit
        if len(_cache) > _CACHE_MAX_SIZE:
            expired = [k for k, v in _cache.items() if now - v.ts > _CACHE_TTL_S]
            for k in expired:
                del _cache[k]
    return result


def price_target_badge(symbol: str) -> str:
    """Return a compact badge like '🎯 $293 (+10.9%)' for inline display."""
    r = fetch_forecast(symbol)
    if not r.price_target or r.price_target.target_mean <= 0:
        return "—"
    pt = r.price_target
    return f"🎯 ${pt.target_mean:.0f} ({pt.upside_pct:+.1f}%)"


def rating_badge(symbol: str) -> str:
    """Return a compact badge like '🟢 Buy (5/24/16/1/1)' for inline display."""
    r = fetch_forecast(symbol)
    if not r.rating or r.rating.total == 0:
        return "—"
    rt = r.rating
    return (
        f"{rt.consensus_icon} {rt.consensus} "
        f"({rt.strong_buy}/{rt.buy}/{rt.hold}/{rt.sell}/{rt.strong_sell})"
    )
