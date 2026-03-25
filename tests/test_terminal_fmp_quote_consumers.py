from __future__ import annotations

from unittest.mock import MagicMock, patch

from terminal_fmp_insights import fetch_fmp_quotes
from terminal_fmp_technicals import _fetch_price
from terminal_poller import fetch_defense_watchlist
from terminal_spike_scanner import enrich_with_batch_quote


def test_spike_scanner_enrich_with_batch_quote_uses_shared_client() -> None:
    fake_profile_response = MagicMock()
    fake_profile_response.raise_for_status.return_value = None
    fake_profile_response.json.return_value = [{"symbol": "NVDA", "averageVolume": 1200, "sector": "Semis"}]
    fake_http_client = MagicMock()
    fake_http_client.get.return_value = fake_profile_response

    with patch("terminal_spike_scanner._get_fmp_client", return_value=fake_http_client), patch(
        "terminal_spike_scanner.FMPClient.get_batch_quotes",
        autospec=True,
        return_value=[{"symbol": "NVDA", "volume": 999, "marketCap": 123456}],
    ) as mock_quotes:
        rows = enrich_with_batch_quote("key", [{"symbol": "NVDA"}])

    assert rows[0]["volume"] == 999
    assert rows[0]["marketCap"] == 123456
    assert rows[0]["avgVolume"] == 1200
    assert rows[0]["sector"] == "Semis"
    assert mock_quotes.call_args.args[1] == ["NVDA"]


def test_fetch_defense_watchlist_uses_shared_client_symbols() -> None:
    with patch(
        "terminal_poller.FMPClient.get_batch_quotes",
        autospec=True,
        return_value=[{"symbol": "LMT"}, {"symbol": "NOC"}],
    ) as mock_quotes:
        rows = fetch_defense_watchlist("key", tickers="LMT, NOC")

    assert [row["symbol"] for row in rows] == ["LMT", "NOC"]
    assert mock_quotes.call_args.args[1] == ["LMT", "NOC"]


def test_fetch_fmp_quotes_uses_shared_client() -> None:
    with patch(
        "terminal_fmp_insights.FMPClient.get_batch_quotes",
        autospec=True,
        return_value=[{"symbol": "AAPL", "price": 200.0}],
    ) as mock_quotes:
        rows = fetch_fmp_quotes("key", ["aapl", "msft"])

    assert rows == [{"symbol": "AAPL", "price": 200.0}]
    assert mock_quotes.call_args.args[1] == ["AAPL", "MSFT"]


def test_fetch_price_uses_shared_quote_path() -> None:
    with patch(
        "terminal_fmp_technicals.FMPClient.get_index_quote",
        autospec=True,
        return_value={"symbol": "AAPL", "price": "123.45"},
    ) as mock_quote:
        price = _fetch_price("aapl", "key")

    assert price == 123.45
    assert mock_quote.call_args.args[1] == "AAPL"