from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from open_prep import realtime_signals as rs


def _request(endpoint: str, *, token: str | None, question: str) -> urllib.request.Request:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(
        endpoint,
        data=json.dumps(
            {
                "schema_version": 1,
                "question": question,
                "context_json": '{"total_articles":1,"ticker_summary":{"AAPL":{}}}',
            }
        ).encode("utf-8"),
        headers=headers,
        method="POST",
    )


def test_ai_endpoint_fails_closed_and_routes_to_producer_llm(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    question = "confidential-question-marker"
    calls: list[tuple[str, str, str]] = []

    def fake_query(*, question: str, context_json: str, api_key: str) -> SimpleNamespace:
        calls.append((question, context_json, api_key))
        return SimpleNamespace(
            answer="inspected response",
            model="gpt-4o",
            cached=False,
            context_articles=1,
            context_tickers=1,
            fmp_tickers=0,
            error="",
        )

    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "shared-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "producer-openai-key")
    monkeypatch.setitem(
        sys.modules,
        "terminal_fmp_insights",
        SimpleNamespace(query_fmp_llm=fake_query),
    )
    caplog.set_level(logging.DEBUG)
    server = rs._start_telemetry_server(rs.ScoreTelemetry(), port=0, host="127.0.0.1")
    assert server is not None
    endpoint = f"http://127.0.0.1:{server.server_port}/ai-insights"

    try:
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(_request(endpoint, token=None, question=question), timeout=2)
        assert missing.value.code == 401

        with pytest.raises(urllib.error.HTTPError) as wrong:
            urllib.request.urlopen(_request(endpoint, token="wrong", question=question), timeout=2)
        assert wrong.value.code == 401

        with urllib.request.urlopen(
            _request(endpoint, token="shared-secret", question=question), timeout=2
        ) as response:
            payload = json.load(response)
        assert payload["answer"] == "inspected response"
        assert calls == [
            (
                question,
                '{"total_articles":1,"ticker_summary":{"AAPL":{}}}',
                "producer-openai-key",
            )
        ]
        assert question not in caplog.text

        monkeypatch.delenv("SIGNALS_INTERNAL_TOKEN")
        with pytest.raises(urllib.error.HTTPError) as unconfigured:
            urllib.request.urlopen(
                _request(endpoint, token="shared-secret", question=question), timeout=2
            )
        assert unconfigured.value.code == 503
    finally:
        server.shutdown()
        server.server_close()


def test_ai_endpoint_rejects_invalid_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "shared-secret")
    server = rs._start_telemetry_server(rs.ScoreTelemetry(), port=0, host="127.0.0.1")
    assert server is not None
    endpoint = f"http://127.0.0.1:{server.server_port}/ai-insights"
    request = urllib.request.Request(
        endpoint,
        data=b'{"schema_version":2}',
        headers={
            "Authorization": "Bearer shared-secret",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as invalid:
            urllib.request.urlopen(request, timeout=2)
        assert invalid.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
