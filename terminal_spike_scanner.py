"""Price & Volume Spike Scanner.

Uses FMP API endpoints to detect real-time price and volume spikes:
- ``/stable/biggest-gainers``  — top price gainers
- ``/stable/biggest-losers``   — top price losers
- ``/stable/most-actives``     — highest volume symbols

During pre-market and after-hours, FMP gainers/losers data is stale
(last regular-session close).  When a Benzinga API key is available,
Benzinga delayed quotes are overlaid to show current extended-hours
prices, replacing the stale FMP change data.

All functions are pure (no Streamlit dependency) and can be tested
independently.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ── Regex to strip API keys from error messages ──────────────────
_APIKEY_RE = re.compile(r"(apikey|token)=[^&\s]+", re.IGNORECASE)

# US Eastern timezone for market session detection
_ET = ZoneInfo("America/New_York")

# Session boundaries (ET)
_T_0400 = datetime(2000, 1, 1, 4, 0).time()
_T_0930 = datetime(2000, 1, 1, 9, 30).time()
_T_1600 = datetime(2000, 1, 1, 16, 0).time()
_T_2000 = datetime(2000, 1, 1, 20, 0).time()

# Session icon labels — shared by streamlit_terminal and open_prep
SESSION_ICONS: dict[str, str] = {
    "pre-market": "🌅 Pre-Market",
    "regular": "🟢 Regular Session",
    "after-hours": "🌙 After-Hours",
    "closed": "⚫ Market Closed",
}


def market_session() -> str:
    """Return current US market session label.

    Returns one of: ``"pre-market"``, ``"regular"``, ``"after-hours"``,
    ``"closed"``.
    """
    now = datetime.now(_ET)
    weekday = now.weekday()  # 0=Mon … 6=Sun
    if weekday >= 5:
        return "closed"
    t = now.time()
    if t < _T_0400:
        return "closed"
    if t < _T_0930:
        return "pre-market"
    if t < _T_1600:
        return "regular"
    if t < _T_2000:
        return "after-hours"
    return "closed"


# ── FMP data fetchers ─────────────────────────────────────────────


def _fetch_fmp_list(api_key: str, endpoint: str) -> list[dict[str, Any]]:
    """Generic FMP list endpoint fetcher with retry and safe error logging."""
    import httpx

    url = f"https://financialmodelingprep.com/stable/{endpoint}"
    params = {"apikey": api_key}

    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
            return []
    except Exception as exc:
        _msg = _APIKEY_RE.sub(r"\1=***", str(exc))
        logger.warning("FMP %s fetch failed: %s", endpoint, _msg)
        return []


def fetch_gainers(api_key: str) -> list[dict[str, Any]]:
    """Fetch top price gainers from FMP."""
    return _fetch_fmp_list(api_key, "biggest-gainers")


def fetch_losers(api_key: str) -> list[dict[str, Any]]:
    """Fetch top price losers from FMP."""
    return _fetch_fmp_list(api_key, "biggest-losers")


def fetch_most_active(api_key: str) -> list[dict[str, Any]]:
    """Fetch most actively traded symbols from FMP."""
    return _fetch_fmp_list(api_key, "most-actives")


# ── Pure spike classification ─────────────────────────────────────


def classify_spike(
    change_pct: float,
    *,
    price_spike_threshold: float = 1.0,
) -> str:
    """Classify a percentage change into a spike direction.

    Returns ``"UP"``, ``"DOWN"``, or ``""`` (no spike).

    Parameters
    ----------
    change_pct : float
        Percentage price change (e.g. 2.5 means +2.5%).
    price_spike_threshold : float
        Minimum absolute percentage move to qualify as a spike.
    """
    if abs(change_pct) < price_spike_threshold:
        return ""
    return "UP" if change_pct > 0 else "DOWN"


def classify_volume_spike(
    volume: float,
    avg_volume: float,
    *,
    volume_spike_ratio: float = 2.0,
) -> bool:
    """Return True if current volume is a spike relative to average.

    Parameters
    ----------
    volume : float
        Current bar/session volume.
    avg_volume : float
        Average volume (e.g. 20-day SMA).
    volume_spike_ratio : float
        Minimum ratio ``volume / avg_volume`` to qualify.
    """
    if avg_volume <= 0:
        return False
    return (volume / avg_volume) >= volume_spike_ratio


def spike_icon(direction: str) -> str:
    """Return emoji icon for spike direction."""
    if direction == "UP":
        return "🟢"
    if direction == "DOWN":
        return "🔴"
    return "⚪"


def volume_icon(is_spike: bool) -> str:
    """Return emoji for volume spike status."""
    return "📊" if is_spike else ""


def format_change_pct(change_pct: float) -> str:
    """Format percentage change with sign and colour marker.

    Returns a Streamlit markdown-safe string like ``:green[+2.50%]``.
    """
    if change_pct > 0:
        return f":green[+{change_pct:.2f}%]"
    if change_pct < 0:
        return f":red[{change_pct:.2f}%]"
    return "0.00%"


def format_market_cap(market_cap: float | None) -> str:
    """Human-readable market cap: ``1.2B``, ``450M``, etc."""
    if market_cap is None or market_cap <= 0:
        return "—"
    if market_cap >= 1e12:
        return f"{market_cap / 1e12:.1f}T"
    if market_cap >= 1e9:
        return f"{market_cap / 1e9:.1f}B"
    if market_cap >= 1e6:
        return f"{market_cap / 1e6:.0f}M"
    return f"{market_cap:,.0f}"


def asset_type_label(symbol: str, name: str = "") -> str:
    """Heuristic asset type: ETF vs STOCK.

    Simple heuristic: known ETF suffixes or name containing 'ETF'.
    """
    _name_upper = (name or "").upper()
    _sym_upper = (symbol or "").upper()
    # Common ETF patterns
    if any(kw in _name_upper for kw in ("ETF", "FUND", "TRUST", "INDEX")):
        return "ETF"
    # Leveraged/inverse ETFs often end with known suffixes
    if _sym_upper.endswith(("L", "S", "X")) and len(_sym_upper) <= 5:
        # Could be ETF but not reliable — skip
        pass
    return "STOCK"


# ── Build unified spike table ──────────────────────────────────


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce a value to float safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def build_spike_rows(
    gainers: list[dict[str, Any]],
    losers: list[dict[str, Any]],
    actives: list[dict[str, Any]],
    *,
    price_spike_threshold: float = 1.0,
    volume_spike_ratio: float = 2.0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Merge gainers, losers, and most-active into a unified spike list.

    Each row contains:
    ``symbol``, ``name``, ``price``, ``change_pct``, ``change``,
    ``volume``, ``avg_volume``, ``volume_ratio``, ``market_cap``,
    ``spike_dir``, ``spike_icon``, ``vol_spike``, ``vol_icon``,
    ``change_display``, ``mktcap_display``, ``asset_type``, ``source``,
    ``ts``.

    Returns rows sorted by absolute change descending, capped to *limit*.
    """
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    now = time.time()

    def _process(items: list[dict[str, Any]], source: str) -> None:
        for raw in items:
            symbol = (raw.get("symbol") or "").upper().strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)

            change_pct = _safe_float(raw.get("changesPercentage"))
            change = _safe_float(raw.get("change"))
            price = _safe_float(raw.get("price"))
            volume = _safe_float(raw.get("volume"))
            avg_vol = _safe_float(raw.get("avgVolume"))
            mktcap = _safe_float(raw.get("marketCap"))
            name = raw.get("name") or raw.get("companyName") or ""

            direction = classify_spike(change_pct, price_spike_threshold=price_spike_threshold)
            vol_spike = classify_volume_spike(
                volume, avg_vol, volume_spike_ratio=volume_spike_ratio,
            )
            vol_ratio = (volume / avg_vol) if avg_vol > 0 else 0.0

            rows.append({
                "symbol": symbol,
                "name": name[:60],
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "change": round(change, 2),
                "volume": int(volume),
                "avg_volume": int(avg_vol),
                "volume_ratio": round(vol_ratio, 2),
                "market_cap": mktcap,
                "spike_dir": direction,
                "spike_icon": spike_icon(direction),
                "vol_spike": vol_spike,
                "vol_icon": volume_icon(vol_spike),
                "change_display": format_change_pct(change_pct),
                "mktcap_display": format_market_cap(mktcap),
                "asset_type": asset_type_label(symbol, name),
                "source": source,
                "ts": now,
            })

    _process(gainers, "gainer")
    _process(losers, "loser")
    _process(actives, "active")

    # Sort by absolute change descending
    rows.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    return rows[:limit]


def filter_spike_rows(
    rows: list[dict[str, Any]],
    *,
    direction: str = "all",
    min_change_pct: float = 0.0,
    asset_type: str = "all",
    vol_spike_only: bool = False,
) -> list[dict[str, Any]]:
    """Apply user filters to spike rows.

    Parameters
    ----------
    direction : str
        ``"all"``, ``"UP"``, or ``"DOWN"``.
    min_change_pct : float
        Minimum absolute change % to display.
    asset_type : str
        ``"all"``, ``"STOCK"``, or ``"ETF"``.
    vol_spike_only : bool
        If True, only show rows with volume spikes.
    """
    result = list(rows)

    if direction != "all":
        result = [r for r in result if r["spike_dir"] == direction]

    if min_change_pct > 0:
        result = [r for r in result if abs(r["change_pct"]) >= min_change_pct]

    if asset_type != "all":
        result = [r for r in result if r["asset_type"] == asset_type]

    if vol_spike_only:
        result = [r for r in result if r["vol_spike"]]

    return result


# ── Pre/post-market overlay ──────────────────────────────────────


def overlay_extended_hours_quotes(
    rows: list[dict[str, Any]],
    quotes: list[dict[str, Any]],
    *,
    price_spike_threshold: float = 1.0,
) -> list[dict[str, Any]]:
    """Overlay Benzinga delayed quotes onto spike rows.

    During extended hours (pre-market / after-hours) FMP biggest-gainers
    and biggest-losers return stale regular-session data.  This function
    replaces the stale price / change fields with fresh extended-hours
    data from Benzinga delayed quotes, so the UI shows the *current*
    move instead of yesterday's close.

    Parameters
    ----------
    rows : list[dict]
        Spike rows produced by :func:`build_spike_rows`.
    quotes : list[dict]
        Flattened Benzinga delayed-quote dicts (as returned by
        ``fetch_benzinga_quotes``).  Expected keys: ``symbol``,
        ``last``, ``change``, ``changePercent``, ``previousClose``,
        ``volume``.
    price_spike_threshold : float
        Passed to :func:`classify_spike` for re-classification.

    Returns
    -------
    list[dict]
        The same rows list, mutated in place, with updated price /
        change / direction fields where a Benzinga quote was available.
    """
    if not quotes:
        return rows

    bz_by_sym: dict[str, dict[str, Any]] = {}
    for quote in quotes:
        sym = (quote.get("symbol") or "").upper().strip()
        if sym:
            bz_by_sym[sym] = quote

    for row in rows:
        sym = row["symbol"]
        q = bz_by_sym.get(sym)
        if q is None:
            continue

        new_price = _safe_float(q.get("last"))
        new_change = _safe_float(q.get("change"))
        new_change_pct = _safe_float(q.get("changePercent"))
        new_vol = _safe_float(q.get("volume"))

        if new_price <= 0:
            continue

        row["price"] = round(new_price, 2)
        row["change"] = round(new_change, 2)
        row["change_pct"] = round(new_change_pct, 2)
        row["change_display"] = format_change_pct(new_change_pct)

        direction = classify_spike(new_change_pct, price_spike_threshold=price_spike_threshold)
        row["spike_dir"] = direction
        row["spike_icon"] = spike_icon(direction)

        if new_vol > 0:
            row["volume"] = int(new_vol)
            avg_vol = row.get("avg_volume", 0)
            if avg_vol > 0:
                row["volume_ratio"] = round(new_vol / avg_vol, 2)
                row["vol_spike"] = classify_volume_spike(new_vol, avg_vol)
                row["vol_icon"] = volume_icon(row["vol_spike"])

        if "+bz" not in row["source"]:
            row["source"] = row["source"] + "+bz"

    # Re-sort after overlay
    rows.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    return rows
