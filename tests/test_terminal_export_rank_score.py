"""Truth-audit C (2026-07-11): rank_score rescale so |chg_pct| leads real movers.

The ranking was documented as '70% price / 30% news, dominated by |chg_pct|'
but scaled news_score by *100, which made news_score dominate (a big price
mover ranked BELOW a high-news small mover). Rescaled to *10 so the two terms
are on comparable magnitudes and |chg_pct| is the dominant term for real
movers, matching the documented intent.
"""
from __future__ import annotations

import time

from terminal_export import build_vd_snapshot


def test_big_price_mover_outranks_high_news_small_mover() -> None:
    now = time.time()
    feed = [
        {"ticker": "AAA", "news_score": 0.9, "published_ts": now},  # +1% move, high news
        {"ticker": "BBB", "news_score": 0.2, "published_ts": now},  # +8% move, low news
    ]
    rt_quotes = {
        "AAA": {"chg_pct": 1.0},
        "BBB": {"chg_pct": 8.0},
    }
    rows = build_vd_snapshot(feed, rt_quotes=rt_quotes)
    by_sym = {r["symbol"]: r for r in rows}

    # rank_score = 0.7*|chg_pct| + 0.3*(news_score*10)
    # AAA: 0.7*1 + 0.3*9 = 3.4 ; BBB: 0.7*8 + 0.3*2 = 6.2
    assert by_sym["AAA"]["rank_score"] == 3.4
    assert by_sym["BBB"]["rank_score"] == 6.2
    # The big price mover leads — the OPPOSITE of the old *100 behavior
    # (which would give AAA 27.7 vs BBB 11.6, news-dominant).
    assert rows[0]["symbol"] == "BBB"
