from __future__ import annotations

from types import SimpleNamespace

import pytest
from aidefense.runtime.models import Action

import cisco_ai_defense as defense
import terminal_fmp_insights as fmp
from cisco_ai_defense import (
    AIDefenseBlockedError,
    AIDefenseConfigurationError,
    AIDefenseUnavailableError,
)


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


@pytest.mark.parametrize(
    "failure",
    [
        AIDefenseBlockedError("blocked test decision"),
        AIDefenseUnavailableError("inspection unavailable"),
        AIDefenseConfigurationError("region is not supported"),
    ],
    ids=["policy-block", "cisco-unavailable", "invalid-configuration"],
)
def test_terminal_fmp_never_calls_provider_when_request_inspection_fails(monkeypatch, failure):
    """Every request-phase failure class must stop egress, not just a block.

    2026-08-29: only the block case was pinned, so the demo claim "a Cisco
    timeout / a broken configuration also means zero provider calls" rested on
    reading the code rather than on a test. A future refactor that caught
    ``AIDefenseUnavailableError`` around the inspection call and fell through to
    ``httpx`` would have kept this file green.
    """
    provider_called = False

    def _fail(*_args, **_kwargs):
        raise failure

    def _client(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        return _Client()

    monkeypatch.setattr(fmp, "inspect_messages", _fail)
    monkeypatch.setattr(fmp.httpx, "Client", _client)

    payload = {"model": "gpt-test", "messages": [{"role": "user", "content": "blocked"}]}
    with pytest.raises(type(failure)):
        fmp._call_openai_chat(payload, "openai-test-key")

    assert provider_called is False


def test_one_exchange_produces_one_transaction_id_across_both_phases(monkeypatch):
    """Request and response inspection of the same query must be joinable."""
    seen = []
    monkeypatch.setattr(
        fmp, "inspect_messages",
        lambda _messages, **kwargs: seen.append((kwargs["phase"], kwargs.get("transaction_id"))),
    )
    monkeypatch.setattr(fmp.httpx, "Client", lambda *_args, **_kwargs: _Client())

    payload = {"model": "gpt-test", "messages": [{"role": "user", "content": "q"}]}
    fmp._call_openai_chat(payload, "openai-test-key")

    assert [phase for phase, _ in seen] == ["request", "response"]
    ids = {tid for _, tid in seen}
    assert len(ids) == 1 and next(iter(ids)), f"phases must share one non-empty id, got {seen}"


def test_a_cache_delivery_is_also_one_correlated_exchange(monkeypatch):
    seen = []
    monkeypatch.setattr(
        fmp, "inspect_messages",
        lambda _messages, **kwargs: seen.append((kwargs["phase"], kwargs.get("transaction_id"))),
    )
    monkeypatch.setattr(fmp.httpx, "Client", lambda *_args, **_kwargs: _Client())
    fmp._cache.clear()

    fmp.query_fmp_llm("repeat", "{}", "openai-test-key", model="gpt-test")
    seen.clear()
    fmp.query_fmp_llm("repeat", "{}", "openai-test-key", model="gpt-test")

    assert [phase for phase, _ in seen] == ["request", "response"]
    ids = {tid for _, tid in seen}
    assert len(ids) == 1 and next(iter(ids)), f"cache delivery must share one id, got {seen}"


def test_terminal_fmp_never_calls_provider_on_a_real_incomplete_cisco_decision(monkeypatch):
    """Drive the REAL wrapper, not a stub, with a decision Cisco never completed.

    The SDK parses a missing ``is_safe`` as ``True``; the wrapper rejects that
    because ``action`` alone is not an authorization. This test wires the real
    ``cisco_ai_defense.inspect_messages`` into the real consumer so the whole
    fail-closed chain — SDK response, contract validation, exception, missing
    provider call — is covered end to end.
    """
    provider_called = False

    class _Cisco:
        def inspect_conversation(self, _messages, **_kwargs):
            return SimpleNamespace(is_safe=None, action=Action.ALLOW, severity=None, rules=[], event_id=None)

    def _client(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        return _Client()

    monkeypatch.setenv("CISCO_AI_DEFENSE_API_KEY", "a" * 64)
    monkeypatch.setenv("CISCO_AI_DEFENSE_REGION", "eu-central-1")
    monkeypatch.setenv("CISCO_AI_DEFENSE_MODE", "enforce")
    monkeypatch.delenv("CISCO_AI_DEFENSE_RESPONSE_MODE", raising=False)
    monkeypatch.setattr(defense, "_get_client", lambda *_args: _Cisco())
    monkeypatch.setattr(fmp, "inspect_messages", defense.inspect_messages)
    monkeypatch.setattr(fmp.httpx, "Client", _client)

    payload = {"model": "gpt-test", "messages": [{"role": "user", "content": "question"}]}
    with pytest.raises(AIDefenseUnavailableError, match="incomplete decision"):
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
