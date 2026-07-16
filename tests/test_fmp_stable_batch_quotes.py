"""Contract tests for the realtime producer's true FMP batch quote path."""

from __future__ import annotations

from unittest.mock import patch

from open_prep.macro import FMPClient


def test_stable_batch_quotes_dedupes_and_uses_one_request() -> None:
    client = FMPClient(api_key="test")
    payload = [
        {"symbol": "AAPL", "price": 200.0},
        {"symbol": "MSFT", "price": 500.0},
    ]

    with patch.object(client, "_get", return_value=payload) as request:
        rows = client.get_stable_batch_quotes(["aapl", "MSFT", "AAPL", ""])

    request.assert_called_once_with(
        "/stable/batch-quote",
        {"symbols": "AAPL,MSFT"},
    )
    assert [row["symbol"] for row in rows] == ["AAPL", "MSFT"]
    diagnostics = client.get_last_quote_fetch_diagnostics()
    assert diagnostics["endpoint_used"] == "/stable/batch-quote"
    assert diagnostics["quote_fetch_chunks"] == 1
    assert diagnostics["failed_quote_symbols"] == []


def test_stable_batch_quotes_reports_missing_response_symbols() -> None:
    client = FMPClient(api_key="test")

    with patch.object(
        client,
        "_get",
        return_value=[{"symbol": "AAPL", "price": 200.0}],
    ):
        rows = client.get_stable_batch_quotes(["AAPL", "MISSING"])

    assert [row["symbol"] for row in rows] == ["AAPL"]
    diagnostics = client.get_last_quote_fetch_diagnostics()
    assert diagnostics["failed_quote_symbols"] == ["MISSING"]
    assert diagnostics["partial_quote_fetch"] is True


def test_stable_batch_quotes_chunks_at_250_symbols() -> None:
    client = FMPClient(api_key="test")
    symbols = [f"S{i:03d}" for i in range(251)]

    def response(_path: str, params: dict[str, str]) -> list[dict[str, str]]:
        return [{"symbol": symbol} for symbol in params["symbols"].split(",")]

    with patch.object(client, "_get", side_effect=response) as request:
        rows = client.get_stable_batch_quotes(symbols)

    assert request.call_count == 2
    assert len(rows) == 251
    assert client.get_last_quote_fetch_diagnostics()["quote_fetch_chunks"] == 2


def test_dedicated_aftermarket_batch_endpoints_preserve_requested_order() -> None:
    client = FMPClient(api_key="test")

    def response(path: str, _params: dict[str, str]) -> list[dict[str, object]]:
        key = "bidPrice" if path.endswith("quote") else "price"
        return [
            {"symbol": "MSFT", key: 500.0},
            {"symbol": "AAPL", key: 200.0},
        ]

    with patch.object(client, "_get", side_effect=response) as request:
        quotes = client.get_stable_batch_aftermarket_quotes(["aapl", "MSFT", "AAPL"])
        trades = client.get_stable_batch_aftermarket_trades(["aapl", "MSFT", "AAPL"])

    assert [row["symbol"] for row in quotes] == ["AAPL", "MSFT"]
    assert [row["symbol"] for row in trades] == ["AAPL", "MSFT"]
    assert request.call_args_list[0].args == (
        "/stable/batch-aftermarket-quote",
        {"symbols": "AAPL,MSFT"},
    )
    assert request.call_args_list[1].args == (
        "/stable/batch-aftermarket-trade",
        {"symbols": "AAPL,MSFT"},
    )
