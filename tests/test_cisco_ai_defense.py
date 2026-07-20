from __future__ import annotations

from types import SimpleNamespace

import pytest
from aidefense.runtime.models import Action, Rule, RuleName, Severity

import cisco_ai_defense as defense


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setenv("CISCO_AI_DEFENSE_API_KEY", "a" * 64)
    monkeypatch.setenv("CISCO_AI_DEFENSE_REGION", "eu-central-1")
    monkeypatch.setenv("CISCO_AI_DEFENSE_MODE", "enforce")
    monkeypatch.setenv("CISCO_AI_DEFENSE_TIMEOUT_SECONDS", "7")
    defense._get_client.cache_clear()


def _result(*, safe: bool, action: Action, event_id: str = "event-1"):
    return SimpleNamespace(
        is_safe=safe,
        action=action,
        severity=Severity.HIGH if not safe else Severity.NONE_SEVERITY,
        rules=[Rule(rule_name=RuleName.PROMPT_INJECTION)] if not safe else [],
        event_id=event_id,
    )


class _Client:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls = []

    def inspect_conversation(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


def _messages():
    return [
        {"role": "system", "content": "Use only supplied facts."},
        {"role": "user", "content": "Summarize the market."},
    ]


def test_safe_decision_allows_and_attaches_sanitized_metadata(monkeypatch):
    client = _Client(_result(safe=True, action=Action.ALLOW))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    decision = defense.inspect_messages(
        _messages(), phase="request", source="terminal-ai-insights", model="gpt-test",
    )

    assert decision.allowed is True
    assert decision.phase == "request"
    sent_messages, kwargs = client.calls[0]
    assert [message.role.value for message in sent_messages] == ["system", "user"]
    # Cisco SDK 2.1.2 accepts ``datetime`` here but fails to JSON-serialize it
    # on a real inspection request.  Omit the optional field and let Cisco
    # timestamp the event server-side.
    assert kwargs["metadata"].created_at is None
    assert kwargs["metadata"].src_app == "skipp-algo:terminal-ai-insights"
    assert kwargs["metadata"].dst_app == "openai:gpt-test"
    assert kwargs["metadata"].client_transaction_id == decision.transaction_id
    assert kwargs["request_id"] == decision.transaction_id
    assert kwargs["timeout"] == 7


def test_sdk_client_uses_the_region_endpoint_and_suppresses_body_debug_logs():
    client = defense._get_client("a" * 64, "eu-central-1", 7)

    assert client.endpoint == "https://eu.api.inspect.aidefense.security.cisco.com/api/v1/inspect/chat"
    assert client.config.logger.level == defense.logging.WARNING


def test_unsafe_decision_blocks_in_enforce_mode(monkeypatch):
    client = _Client(_result(safe=False, action=Action.BLOCK, event_id="blocked-event"))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    with pytest.raises(defense.AIDefenseBlockedError, match="blocked-event"):
        defense.inspect_messages(
            _messages(), phase="request", source="terminal-ai-insights", model="gpt-test",
        )


def test_unsafe_decision_is_recorded_but_allowed_in_monitor_mode(monkeypatch):
    monkeypatch.setenv("CISCO_AI_DEFENSE_MODE", "monitor")
    client = _Client(_result(safe=False, action=Action.ALLOW))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    decision = defense.inspect_messages(
        _messages(), phase="response", source="terminal-ai-insights", model="gpt-test",
    )

    assert decision.allowed is False
    assert decision.rules == ("Prompt Injection",)


def test_missing_key_is_fail_closed(monkeypatch):
    monkeypatch.delenv("CISCO_AI_DEFENSE_API_KEY")

    with pytest.raises(defense.AIDefenseConfigurationError, match="required for LLM traffic"):
        defense.inspect_messages(
            _messages(), phase="request", source="terminal-ai-insights", model="gpt-test",
        )


def test_invalid_key_format_is_fail_closed_before_sdk_initialization(monkeypatch):
    monkeypatch.setenv("CISCO_AI_DEFENSE_API_KEY", "not-an-inspection-key")

    with pytest.raises(defense.AIDefenseConfigurationError, match="64-character Inspection API key"):
        defense.inspect_messages(
            _messages(), phase="request", source="terminal-ai-insights", model="gpt-test",
        )


@pytest.mark.parametrize("mode", ["", "off", "disabled", "allow"])
def test_mode_cannot_disable_inspection(monkeypatch, mode):
    monkeypatch.setenv("CISCO_AI_DEFENSE_MODE", mode)

    with pytest.raises(defense.AIDefenseConfigurationError, match="must be 'enforce' or 'monitor'"):
        defense.inspect_messages(
            _messages(), phase="request", source="terminal-ai-insights", model="gpt-test",
        )


@pytest.mark.parametrize("timeout", ["0", "61", "not-an-integer"])
def test_timeout_is_bounded(monkeypatch, timeout):
    monkeypatch.setenv("CISCO_AI_DEFENSE_TIMEOUT_SECONDS", timeout)

    with pytest.raises(defense.AIDefenseConfigurationError, match="must be"):
        defense.inspect_messages(
            _messages(), phase="request", source="terminal-ai-insights", model="gpt-test",
        )


@pytest.mark.parametrize("region", ["", "eu", "https://attacker.invalid"])
def test_region_must_be_an_explicit_supported_cisco_region(monkeypatch, region):
    monkeypatch.setenv("CISCO_AI_DEFENSE_REGION", region)

    with pytest.raises(defense.AIDefenseConfigurationError, match="must be one of"):
        defense.inspect_messages(
            _messages(), phase="request", source="terminal-ai-insights", model="gpt-test",
        )


def test_transport_error_is_fail_closed_without_logging_content(monkeypatch, caplog):
    secret = "do-not-log-this-prompt-or-error"
    client = _Client(error=RuntimeError(secret))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    with caplog.at_level("ERROR"), pytest.raises(defense.AIDefenseUnavailableError):
        defense.inspect_messages(
            [{"role": "user", "content": secret}],
            phase="request",
            source="terminal-ai-insights",
            model="gpt-test",
        )

    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text


def test_remote_decision_metadata_cannot_inject_log_lines(monkeypatch, caplog):
    client = _Client(
        SimpleNamespace(
            is_safe=False,
            action=Action.BLOCK,
            severity="HIGH\nforged severity",
            rules=[SimpleNamespace(rule_name="Prompt Injection\nforged rule")],
            event_id="event-1\nforged event",
        )
    )
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    with caplog.at_level("WARNING"), pytest.raises(defense.AIDefenseBlockedError):
        defense.inspect_messages(
            _messages(), phase="request", source="terminal-ai-insights", model="gpt-test",
        )

    assert "\nforged" not in caplog.text
    assert "forged severity" in caplog.text
    assert "forged rule" in caplog.text
    assert "forged event" in caplog.text


@pytest.mark.parametrize(
    ("safe", "action"),
    [(True, None), (None, Action.ALLOW), ("true", Action.ALLOW)],
)
def test_incomplete_sdk_decision_is_fail_closed(monkeypatch, safe, action):
    client = _Client(SimpleNamespace(is_safe=safe, action=action, severity=None, rules=[], event_id=None))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    with pytest.raises(defense.AIDefenseUnavailableError, match="incomplete decision"):
        defense.inspect_messages(
            _messages(), phase="response", source="terminal-ai-insights", model="gpt-test",
        )


def test_append_assistant_message_does_not_mutate_input():
    messages = [{"role": "user", "content": "question"}]

    result = defense.append_assistant_message(messages, "answer")

    assert messages == [{"role": "user", "content": "question"}]
    assert result[-1] == {"role": "assistant", "content": "answer"}
