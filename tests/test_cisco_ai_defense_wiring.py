from __future__ import annotations

import pytest

import terminal_ai_insights as ai
import terminal_fmp_insights as fmp
from cisco_ai_defense import AIDefenseBlockedError


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": " inspected answer "}}]}


class _Client:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        return _Response()


def test_terminal_ai_inspects_request_and_response(monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "inspect_messages", lambda messages, **kwargs: calls.append((messages, kwargs)))
    monkeypatch.setattr(ai.httpx, "Client", lambda *_args, **_kwargs: _Client())
    ai._cache.clear()

    result = ai.query_llm(
        "What matters?",
        '{"total_articles": 0, "ticker_summary": {}}',
        "openai-test-key",
        model="gpt-test",
    )

    assert result.answer == "inspected answer"
    assert [kwargs["phase"] for _, kwargs in calls] == ["request", "response"]
    assert calls[0][0][-1]["role"] == "user"
    assert calls[1][0][-1] == {"role": "assistant", "content": "inspected answer"}


def test_terminal_fmp_inspects_request_and_response(monkeypatch):
    calls = []
    monkeypatch.setattr(fmp, "inspect_messages", lambda messages, **kwargs: calls.append((messages, kwargs)))
    monkeypatch.setattr(fmp.httpx, "Client", lambda *_args, **_kwargs: _Client())
    payload = {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "Use supplied data."},
            {"role": "user", "content": "Summarize."},
        ],
    }

    result = fmp._call_openai_chat(payload, "openai-test-key")

    assert result == "inspected answer"
    assert [kwargs["phase"] for _, kwargs in calls] == ["request", "response"]
    assert calls[1][0][-1] == {"role": "assistant", "content": "inspected answer"}


def test_terminal_ai_never_calls_provider_when_request_is_blocked(monkeypatch):
    provider_called = False

    def _blocked(*_args, **_kwargs):
        raise AIDefenseBlockedError("blocked test decision")

    def _client(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        return _Client()

    monkeypatch.setattr(ai, "inspect_messages", _blocked)
    monkeypatch.setattr(ai.httpx, "Client", _client)
    ai._cache.clear()

    result = ai.query_llm("blocked", "{}", "openai-test-key", model="gpt-test")

    assert provider_called is False
    assert result.answer == ""
    assert result.error is not None


def test_terminal_fmp_never_calls_provider_when_request_is_blocked(monkeypatch):
    provider_called = False

    def _blocked(*_args, **_kwargs):
        raise AIDefenseBlockedError("blocked test decision")

    def _client(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        return _Client()

    monkeypatch.setattr(fmp, "inspect_messages", _blocked)
    monkeypatch.setattr(fmp.httpx, "Client", _client)

    payload = {"model": "gpt-test", "messages": [{"role": "user", "content": "blocked"}]}
    with pytest.raises(AIDefenseBlockedError):
        fmp._call_openai_chat(payload, "openai-test-key")

    assert provider_called is False
