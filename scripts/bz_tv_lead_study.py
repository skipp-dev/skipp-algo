"""Historical content-lead pre-study: TradingView (Reuters/DJ) vs Benzinga.

Answers the CONTENT question **offline, with no waiting** for live data:
does TradingView's web-engine headline feed (which relays Reuters / Dow Jones,
tier-1) surface market-movers with an *earlier published time* than Benzinga —
or carry ones Benzinga misses entirely?

What this does and does NOT settle
----------------------------------
* SETTLES (historically): content coverage + *published-time* lead. If TV shows
  no coverage advantage and no published-time lead here, it is disqualified as a
  cheap add-on before any live work. If it does lead/broaden, that motivates the
  live test.
* Does NOT settle: **delivery latency** (WS-push vs REST-poll receipt). That has
  no historical trace — it only exists when you listen live — so ``t_ws`` /
  ``t_rest`` still require the shadow recorder on a trading day.
* Caveat: some aggregators backdate a wire story to its ORIGINAL publish time, so
  a published-time comparison can *understate* the real delivery lead. Treat a
  positive TV lead here as a lower bound / motivation, not the final number.

TradingView is read as a standalone measurement here — it is NOT re-enabled as a
runtime provider (that retirement, PR #3777, stands). TV headlines are a recent
window only (~200 items/symbol), so the historical horizon is ~1 day.

Usage
-----
    PYTHONPATH=. python scripts/bz_tv_lead_study.py \\
        --symbols AAPL,NVDA,TSLA,MSFT,AMD --days 1 --min-headline-sim 0.6
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from statistics import median
from typing import Any

import httpx

from scripts.news_event_matcher import MatchedEvent, SourceItem, match_events

logger = logging.getLogger("bz_tv_lead_study")

_TV_URL = "https://news-headlines.tradingview.com/v2/view/headlines/symbol"


def _benzinga_items(
    key: str, day_from: date, day_to: date, page_size: int
) -> list[SourceItem]:
    """Fetch Benzinga archive items over a date range as SourceItems."""
    r = httpx.get(
        "https://api.benzinga.com/api/v2/news",
        params={"token": key, "pageSize": page_size, "displayOutput": "abstract",
                "dateFrom": day_from.isoformat(), "dateTo": day_to.isoformat()},
        headers={"Accept": "application/json"}, timeout=30,
    )
    r.raise_for_status()
    out: list[SourceItem] = []
    for it in r.json() or []:
        # Explicit fallback (not an `or`-chain) so the field-preference ledger
        # guard stays satisfied: `created` is the publish time; `updated` only
        # backfills the rare item that omits it.
        created = it.get("created")
        if not created:
            created = it.get("updated")
        try:
            ts = parsedate_to_datetime(created).timestamp() if created else 0.0
        except (TypeError, ValueError):
            ts = 0.0
        tickers = [s.get("name") for s in (it.get("stocks") or []) if s.get("name")]
        out.append(SourceItem(
            source="benzinga", item_id=str(it.get("id") or ""), published_ts=ts,
            headline=it.get("title") or "", tickers=tickers,
        ))
    return out


def _tv_items(symbols: list[str]) -> list[SourceItem]:
    """Fetch the recent TradingView headline window per symbol as SourceItems.

    Standalone read of the (unofficial) web-engine endpoint for MEASUREMENT
    only — this does not re-enable the retired runtime provider (PR #3777).
    """
    out: list[SourceItem] = []
    seen: set[str] = set()
    for sym in symbols:
        try:
            r = httpx.get(
                _TV_URL,
                params={"client": "web", "lang": "en", "symbol": f"NASDAQ:{sym}"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=20,
            )
            if r.status_code != 200:
                logger.warning("TV %s HTTP %s (Cloudflare?) — skipping", sym, r.status_code)
                continue
            data = r.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("TV fetch failed for %s", sym, exc_info=True)
            continue
        items = data.get("items") if isinstance(data, dict) else data
        for it in items or []:
            iid = str(it.get("id") or "")
            if iid in seen:
                continue
            seen.add(iid)
            rel = it.get("relatedSymbols") or []
            tickers = [s.get("symbol", "").split(":")[-1] for s in rel if isinstance(s, dict)]
            tickers = [t for t in tickers if t] or [sym]
            out.append(SourceItem(
                source="tv", item_id=iid,
                published_ts=float(it.get("published") or 0.0),
                headline=it.get("title") or "",
                tickers=tickers,
            ))
    return out


def summarize_lead(events: list[MatchedEvent]) -> dict[str, Any]:
    """Pure aggregation: coverage + published-time lead of TV vs Benzinga.

    ``lead_s`` for a both-sources event = ``t_benzinga - t_tv`` (positive means
    TradingView's published time was EARLIER than Benzinga's).
    """
    both, tv_only, bz_only = 0, 0, 0
    leads: list[float] = []
    for e in events:
        has_bz = "benzinga" in e.per_source
        has_tv = "tv" in e.per_source
        if has_bz and has_tv:
            both += 1
            t_bz = e.timestamp("benzinga", prefer_arrival=False)
            t_tv = e.timestamp("tv", prefer_arrival=False)
            if t_bz and t_tv:
                leads.append(t_bz - t_tv)
        elif has_tv:
            tv_only += 1
        elif has_bz:
            bz_only += 1
    tv_earlier = sum(1 for x in leads if x > 0)
    return {
        "events_total": len(events),
        "both_sources": both,
        "tv_only": tv_only,
        "bz_only": bz_only,
        "matched_with_lead": len(leads),
        "tv_earlier_count": tv_earlier,
        "tv_earlier_share": (tv_earlier / len(leads)) if leads else 0.0,
        "median_lead_s": median(leads) if leads else None,
        "max_lead_s": max(leads) if leads else None,
    }


def run_study(
    *, symbols: list[str], days: int, page_size: int,
    time_window_s: float, min_headline_sim: float,
) -> dict[str, Any]:
    key = os.getenv("BENZINGA_DIRECT_API_KEY") or os.getenv("BENZINGA_API_KEY") or ""
    if not key:
        raise RuntimeError("BENZINGA_DIRECT_API_KEY / BENZINGA_API_KEY missing")
    day_to = date.today()
    day_from = day_to - timedelta(days=max(1, days))
    bz = _benzinga_items(key, day_from, day_to, page_size)
    tv = _tv_items(symbols)
    # Restrict Benzinga to the symbol universe so both sides are comparable.
    universe = {s.upper() for s in symbols}
    bz = [i for i in bz if i.ticker_set() & universe]
    events = match_events(bz + tv, time_window_s=time_window_s,
                          min_headline_sim=min_headline_sim)
    report = {
        "generated_utc": datetime.now(tz=UTC).isoformat(),
        "symbols": symbols,
        "benzinga_items": len(bz),
        "tv_items": len(tv),
        "summary": summarize_lead(events),
        "note": "published-time lead (lower bound); delivery latency needs the live recorder",
    }
    return report


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Historical TV-vs-Benzinga content-lead pre-study.")
    p.add_argument("--symbols", type=str, default="AAPL,NVDA,TSLA,MSFT,AMD")
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--time-window-s", type=float, default=180.0)
    p.add_argument("--min-headline-sim", type=float, default=0.6)
    args = p.parse_args(argv)
    report = run_study(
        symbols=[s.strip().upper() for s in args.symbols.split(",") if s.strip()],
        days=args.days, page_size=args.page_size,
        time_window_s=args.time_window_s, min_headline_sim=args.min_headline_sim,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
