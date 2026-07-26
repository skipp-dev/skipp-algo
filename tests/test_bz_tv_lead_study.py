"""Unit test for the pure aggregation of the TV-vs-Benzinga lead study."""

from __future__ import annotations

from scripts.bz_tv_lead_study import summarize_lead
from scripts.news_event_matcher import MatchedEvent, SourceItem


def _ev(**per_source) -> MatchedEvent:
    e = MatchedEvent(tickers=["AAPL"])
    for src, (ts, hl) in per_source.items():
        e._add(SourceItem(source=src, item_id=f"{src}1", published_ts=ts,
                          headline=hl, tickers=["AAPL"]))
    return e


def test_summarize_lead_coverage_and_direction() -> None:
    events = [
        # both, TV earlier by 30s
        _ev(benzinga=(130.0, "Apple beats"), tv=(100.0, "Apple beats")),
        # both, Benzinga earlier by 10s
        _ev(benzinga=(200.0, "Nvidia deal"), tv=(210.0, "Nvidia deal")),
        # TV-only
        _ev(tv=(300.0, "Tesla recall")),
        # Benzinga-only
        _ev(benzinga=(400.0, "AMD guidance")),
    ]
    s = summarize_lead(events)
    assert s["events_total"] == 4
    assert s["both_sources"] == 2
    assert s["tv_only"] == 1
    assert s["bz_only"] == 1
    assert s["matched_with_lead"] == 2
    assert s["tv_earlier_count"] == 1          # only the first event
    assert s["median_lead_s"] == median_of([30.0, -10.0])
    assert s["max_lead_s"] == 30.0


def median_of(xs):
    from statistics import median
    return median(xs)


def test_summarize_lead_empty() -> None:
    s = summarize_lead([])
    assert s["events_total"] == 0
    assert s["median_lead_s"] is None
    assert s["tv_earlier_share"] == 0.0
