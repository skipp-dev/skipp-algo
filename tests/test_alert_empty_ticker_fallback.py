"""Pin the dollar-prefix ticker regex fallback (Lane 15)."""
from streamlit_terminal_alerts import _TICKER_DOLLAR_RE


def test_regex_extracts_dollar_ticker():
    m = _TICKER_DOLLAR_RE.search("$AAPL beats earnings")
    assert m is not None
    assert m.group(1) == "AAPL"


def test_regex_extracts_multi_letter_ticker():
    m = _TICKER_DOLLAR_RE.search("$TSLA up 5%")
    assert m is not None
    assert m.group(1) == "TSLA"


def test_regex_no_match_in_plain_headline():
    assert _TICKER_DOLLAR_RE.search("market opens flat") is None


def test_regex_does_not_match_overlong_token():
    m = _TICKER_DOLLAR_RE.search("$VERYLONG news")
    assert m is None or len(m.group(1)) <= 5
