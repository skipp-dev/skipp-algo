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


def test_terminal_fmp_validation_returns_safe_answer_when_runtime_blocks(monkeypatch):
    provider_called = False

    def _blocked(*_args, **_kwargs):
        raise AIDefenseBlockedError("blocked test decision")

    def _client(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        return _Client()

    monkeypatch.setattr(fmp, "inspect_messages", _blocked)
    monkeypatch.setattr(fmp.httpx, "Client", _client)
    fmp._cache.clear()

    result = fmp.query_fmp_llm(
        "blocked",
        "{}",
        "openai-test-key",
        model="gpt-test",
        blocked_answer="Blocked by application policy.",
    )

    assert provider_called is False
    assert result.answer == "Blocked by application policy."
    assert result.error == ""


@pytest.mark.parametrize(
    ("module", "query"),
    [
        (ai, ai.query_llm),
        (fmp, fmp.query_fmp_llm),
    ],
)
def test_positive_cache_hit_is_reinspected_without_recalling_provider(monkeypatch, module, query):
    phases = []
    provider_calls = 0

    def _inspect(_messages, **kwargs):
        phases.append(kwargs["phase"])

    class _CountingClient(_Client):
        def post(self, *_args, **_kwargs):
            nonlocal provider_calls
            provider_calls += 1
            return _Response()

    monkeypatch.setattr(module, "inspect_messages", _inspect)
    monkeypatch.setattr(module.httpx, "Client", lambda *_args, **_kwargs: _CountingClient())
    module._cache.clear()

    first = query("repeat", "{}", "openai-test-key", model="gpt-test")
    phases.clear()
    second = query("repeat", "{}", "openai-test-key", model="gpt-test")

    assert first.cached is False
    assert second.answer == "inspected answer"
    assert second.cached is True
    assert phases == ["request", "response"]
    assert provider_calls == 1


@pytest.mark.parametrize(
    ("module", "query"),
    [
        (ai, ai.query_llm),
        (fmp, fmp.query_fmp_llm),
    ],
)
def test_current_response_policy_can_block_a_positive_cache_hit(monkeypatch, module, query):
    phases = []
    provider_calls = 0
    block_response = False

    def _inspect(_messages, **kwargs):
        phases.append(kwargs["phase"])
        if block_response and kwargs["phase"] == "response":
            raise AIDefenseBlockedError("blocked current cached response")

    class _CountingClient(_Client):
        def post(self, *_args, **_kwargs):
            nonlocal provider_calls
            provider_calls += 1
            return _Response()

    monkeypatch.setattr(module, "inspect_messages", _inspect)
    monkeypatch.setattr(module.httpx, "Client", lambda *_args, **_kwargs: _CountingClient())
    module._cache.clear()

    first = query("policy transition", "{}", "openai-test-key", model="gpt-test")
    phases.clear()
    block_response = True
    second = query("policy transition", "{}", "openai-test-key", model="gpt-test")

    assert first.answer == "inspected answer"
    assert second.answer == ""
    assert second.error is not None
    assert phases == ["request", "response"]
    assert provider_calls == 1
