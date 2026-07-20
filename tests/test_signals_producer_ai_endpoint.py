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


def _validation_request(
    endpoint: str,
    *,
    token: str | None,
    prompt: object,
) -> urllib.request.Request:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(
        endpoint,
        data=json.dumps({"prompt": prompt}).encode("utf-8"),
        headers=headers,
        method="POST",
    )


def test_ai_endpoint_fails_closed_and_routes_to_producer_llm(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    question = "confidential-question-marker"
    calls: list[tuple[str, str, str]] = []

    def fake_query(
        *,
        question: str,
        context_json: str,
        api_key: str,
        blocked_answer: str,
    ) -> SimpleNamespace:
        assert blocked_answer == ""
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


def test_validation_endpoint_uses_dedicated_auth_and_application_boundary(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    validation_token = "validation-only-token-0123456789abcdef"
    prompt = "cisco-validation-prompt-marker" + ("x" * 12_000)
    calls: list[tuple[str, dict[str, object], str, str]] = []

    def fake_query(
        *,
        question: str,
        context_json: str,
        api_key: str,
        blocked_answer: str,
    ) -> SimpleNamespace:
        calls.append((question, json.loads(context_json), api_key, blocked_answer))
        return SimpleNamespace(
            answer="inspected application response",
            model="configured-at-runtime",
            cached=False,
            context_articles=0,
            context_tickers=0,
            fmp_tickers=0,
            error="",
        )

    monkeypatch.setenv("AI_VALIDATION_TOKEN", validation_token)
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "different-internal-token")
    monkeypatch.setenv("OPENAI_API_KEY", "producer-openai-key")
    monkeypatch.setitem(
        sys.modules,
        "terminal_fmp_insights",
        SimpleNamespace(query_fmp_llm=fake_query),
    )
    caplog.set_level(logging.DEBUG)
    server = rs._start_telemetry_server(rs.ScoreTelemetry(), port=0, host="127.0.0.1")
    assert server is not None
    endpoint = f"http://127.0.0.1:{server.server_port}/ai-validation"

    try:
        for rejected_token in (None, "different-internal-token", "wrong-token"):
            with pytest.raises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(
                    _validation_request(endpoint, token=rejected_token, prompt=prompt),
                    timeout=2,
                )
            assert rejected.value.code == 401

        with urllib.request.urlopen(
            _validation_request(endpoint, token=validation_token, prompt=prompt),
            timeout=2,
        ) as response:
            payload = json.load(response)
            assert response.headers["Cache-Control"] == "no-store"

        assert payload == {
            "schema_version": 1,
            "answer": "inspected application response",
            "model": "configured-at-runtime",
            "cached": False,
            "context_articles": 0,
            "context_tickers": 0,
            "fmp_tickers": 0,
            "error": "",
        }
        assert calls == [
            (
                prompt,
                {
                    "validation_target": "skipp-ai-insights",
                    "total_articles": 0,
                    "top_articles": [],
                    "ticker_summary": {},
                },
                "producer-openai-key",
                "This request was blocked by the Skipp AI security policy.",
            )
        ]
        assert prompt not in caplog.text
    finally:
        server.shutdown()
        server.server_close()


def test_validation_endpoint_fails_closed_for_bad_config_input_and_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_token = "validation-only-token-0123456789abcdef"
    monkeypatch.setenv("OPENAI_API_KEY", "producer-openai-key")
    monkeypatch.setitem(
        sys.modules,
        "terminal_fmp_insights",
        SimpleNamespace(
            query_fmp_llm=lambda **_kwargs: SimpleNamespace(
                answer="",
                model="configured-at-runtime",
                cached=False,
                context_articles=0,
                context_tickers=0,
                fmp_tickers=0,
                error="provider failed",
            )
        ),
    )
    server = rs._start_telemetry_server(rs.ScoreTelemetry(), port=0, host="127.0.0.1")
    assert server is not None
    endpoint = f"http://127.0.0.1:{server.server_port}/ai-validation"

    try:
        monkeypatch.setenv("AI_VALIDATION_TOKEN", "too-short")
        with pytest.raises(urllib.error.HTTPError) as unconfigured:
            urllib.request.urlopen(
                _validation_request(endpoint, token="too-short", prompt="safe"),
                timeout=2,
            )
        assert unconfigured.value.code == 503

        monkeypatch.setenv("AI_VALIDATION_TOKEN", validation_token)
        for bad_prompt in ("", 42):
            with pytest.raises(urllib.error.HTTPError) as invalid:
                urllib.request.urlopen(
                    _validation_request(endpoint, token=validation_token, prompt=bad_prompt),
                    timeout=2,
                )
            assert invalid.value.code == 400

        with pytest.raises(urllib.error.HTTPError) as unavailable:
            urllib.request.urlopen(
                _validation_request(endpoint, token=validation_token, prompt="safe"),
                timeout=2,
            )
        assert unavailable.value.code == 502
        assert json.load(unavailable.value) == {
            "schema_version": 1,
            "error": "validation backend unavailable",
        }
    finally:
        server.shutdown()
        server.server_close()
