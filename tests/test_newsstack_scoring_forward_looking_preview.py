"""Regression: the forward-looking-preview filter must not swallow realized catalysts.

The `ahead of ... earnings/results/report` preview pattern used a wide ``.{0,80}``
window, so the common realized-move idiom "<stock> surges ahead of <the market /
rivals / peers> after earnings" was misclassified as a *preview* — which forces
polarity to 0.0 and demotes earnings impact to 0.35 (scoring.py). That in turn
drops the composite ``news_score`` below the 0.80 gate and zeroes polarity, so the
live intraday A1/A2 -> A0 news-catalyst upgrade (realtime_signals.py:3315, which
requires ``news_score >= 0.80`` AND directional polarity) is silently suppressed
for a legitimately realized catalyst.
"""

from __future__ import annotations

from newsstack_fmp.scoring import classify_and_score, is_forward_looking_preview

# Realized-move idioms: "ahead of <comparison target>" with earnings elsewhere.
# These describe an OBSERVED move and must NOT be treated as previews.
_REALIZED_IDIOMS = [
    "NVDA jumps 12% ahead of rivals after earnings beat",
    "Apple soars ahead of the market following blowout earnings",
    "Tesla pulls ahead of peers as results top estimates",
    "Stock races ahead of the pack after earnings",
    "Ford powers ahead of the sector after results",
    "Shares climb ahead of the group post earnings",
]

# Genuine previews: the event noun is the near-object of "ahead of".
_GENUINE_PREVIEWS = [
    "Stock to watch ahead of earnings",
    "Positioning ahead of Q3 earnings",
    "What to expect ahead of Thursday's earnings report",
    "NVDA in focus ahead of its quarterly results",
    "3 stocks to buy ahead of upcoming earnings",
    "Ahead of the long-awaited earnings report",
]


def test_realized_ahead_of_idiom_not_flagged_as_preview() -> None:
    for headline in _REALIZED_IDIOMS:
        assert not is_forward_looking_preview(headline), headline


def test_genuine_ahead_of_preview_still_flagged() -> None:
    for headline in _GENUINE_PREVIEWS:
        assert is_forward_looking_preview(headline), headline


def test_realized_earnings_catalyst_keeps_full_impact_and_polarity() -> None:
    # The idiom headline must score identically to the plain realized headline:
    # full earnings impact (0.80), positive polarity, and a composite score that
    # clears the 0.80 A0-upgrade gate — otherwise the A0 escalation is lost.
    idiom = classify_and_score(
        {"headline": "NVDA jumps 12% ahead of rivals after earnings beat", "tickers": ["NVDA"]},
        cluster_count=1,
    )
    assert idiom.category == "earnings"
    assert idiom.impact == 0.80
    assert idiom.polarity > 0
    assert idiom.score >= 0.80


def test_genuine_preview_is_still_neutralized() -> None:
    preview = classify_and_score(
        {"headline": "3 stocks to buy ahead of upcoming earnings", "tickers": ["X"]},
        cluster_count=1,
    )
    # Forward-looking previews keep polarity neutral and demoted earnings impact.
    assert preview.polarity == 0.0
    assert preview.impact <= 0.35
