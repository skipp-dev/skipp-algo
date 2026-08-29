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
    monkeypatch.delenv("CISCO_AI_DEFENSE_RESPONSE_MODE", raising=False)
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


def test_caller_supplied_transaction_id_is_used_for_both_metadata_and_log(monkeypatch, caplog):
    """One exchange, one id — otherwise "transaction" names a single inspection.

    2026-08-29: request and response inspection of the same user query each
    minted their own uuid, so the two Cisco events and the two log lines could
    not be joined. Measured live in the Producer log: one terminal query
    produced transaction_id=7fb089e7... for the request and 81b8f43e... for the
    response.
    """
    client = _Client(_result(safe=True, action=Action.ALLOW))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)
    shared = defense.new_transaction_id()

    with caplog.at_level("INFO"):
        request_decision = defense.inspect_messages(
            _messages(), phase="request", source="s", model="m", transaction_id=shared,
        )
        response_decision = defense.inspect_messages(
            _messages(), phase="response", source="s", model="m", transaction_id=shared,
        )

    assert request_decision.transaction_id == shared
    assert response_decision.transaction_id == shared
    assert len(client.calls) == 2, "both phases must have reached the SDK"
    for _messages_sent, kwargs in client.calls:
        assert kwargs["metadata"].client_transaction_id == shared
        assert kwargs["request_id"] == shared
    assert caplog.text.count(f"transaction_id={shared}") == 2


def test_omitted_transaction_id_still_mints_a_unique_one(monkeypatch):
    client = _Client(_result(safe=True, action=Action.ALLOW))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    first = defense.inspect_messages(_messages(), phase="request", source="s", model="m")
    second = defense.inspect_messages(_messages(), phase="request", source="s", model="m")

    assert first.transaction_id != second.transaction_id


def test_allowed_decision_logs_the_event_id_for_correlation(monkeypatch, caplog):
    """An ALLOWED transaction must be correlatable to the Cisco event log too.

    2026-08-29: ``event_id`` was logged only on a violation, so a clean
    transaction could be tied to the dashboard by timestamp alone. Cisco mints
    an event id only on a violation today, hence the ``none`` fallback -- the
    point is that the field is present and carries the id whenever there is one.
    """
    client = _Client(_result(safe=True, action=Action.ALLOW, event_id="allowed-event"))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    with caplog.at_level("INFO"):
        decision = defense.inspect_messages(
            _messages(), phase="request", source="terminal-fmp-insights", model="gpt-test",
        )

    assert decision.allowed is True
    assert "event_id=allowed-event" in caplog.text
    assert f"transaction_id={decision.transaction_id}" in caplog.text


def test_allowed_decision_without_a_cisco_event_logs_an_explicit_placeholder(monkeypatch, caplog):
    client = _Client(_result(safe=True, action=Action.ALLOW, event_id=""))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    with caplog.at_level("INFO"):
        defense.inspect_messages(
            _messages(), phase="response", source="terminal-fmp-insights", model="gpt-test",
        )

    assert "event_id=none" in caplog.text


def test_sdk_client_uses_the_region_endpoint_and_suppresses_body_debug_logs():
    client = defense._get_client("a" * 64, "eu-central-1", 7)

    assert client.endpoint == "https://eu.api.inspect.aidefense.security.cisco.com/api/v1/inspect/chat"
    assert client.config.logger.level == defense.logging.WARNING
    assert client.config.logger.propagate is False
    assert len(client.config.logger.handlers) == 1
    assert isinstance(client.config.logger.handlers[0], defense.logging.NullHandler)


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


def test_response_mode_override_monitors_response_but_enforces_request(monkeypatch):
    monkeypatch.setenv("CISCO_AI_DEFENSE_RESPONSE_MODE", "monitor")
    client = _Client(_result(safe=False, action=Action.BLOCK, event_id="blocked-event"))
    monkeypatch.setattr(defense, "_get_client", lambda *_args: client)

    decision = defense.inspect_messages(
        _messages(), phase="response", source="terminal-fmp-insights", model="gpt-test",
    )
    assert decision.allowed is False

    with pytest.raises(defense.AIDefenseBlockedError, match="blocked-event"):
        defense.inspect_messages(
            _messages(), phase="request", source="terminal-fmp-insights", model="gpt-test",
        )


@pytest.mark.parametrize("mode", ["off", "disabled", "allow"])
def test_response_mode_override_cannot_disable_inspection(monkeypatch, mode):
    monkeypatch.setenv("CISCO_AI_DEFENSE_RESPONSE_MODE", mode)

    with pytest.raises(defense.AIDefenseConfigurationError, match="must be 'enforce' or 'monitor'"):
        defense.inspect_messages(
            _messages(), phase="response", source="terminal-ai-insights", model="gpt-test",
        )


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


# ---------------------------------------------------------------------------
# Region contract.
#
# _SUPPORTED_REGIONS is an allow-list in a fail-closed path, so it has to match
# what the SDK can actually resolve — not what a document says. Measured
# 2026-08-29, the two disagree, and the SDK is the one that runs:
#
#   region            Cisco docs        SDK (measured)
#   us-west-2         us.               us.
#   eu-central-1      eu.               eu.
#   ap-northeast-1    -- (docs say      apj.
#                     region `ap-ne-1`,
#                     host `ap.`)
#   me-central-1      not documented    uae.
#
# Two traps this pins:
#   * `ap-ne-1`, the region name in Cisco's published table, is REJECTED by the
#     SDK (`ValueError: Invalid region`). An operator following the docs would
#     configure a value that cannot work.
#   * `me-central-1` IS supported (uae host) though absent from the docs. A
#     research pass over Cisco's documentation on 2026-08-29 concluded no
#     Middle-East host exists; acting on that would have removed a working
#     region. The endpoint below is the counter-evidence.
#
# `Config` is a process-wide singleton that IGNORES later parameters (it logs
# "Config singleton already initialized" and keeps the first region), so each
# case must reset it — and a probe that does not reset gets a uniform, plausible
# and wrong answer. That is how this table was nearly recorded incorrectly.
# ---------------------------------------------------------------------------

_REGION_ENDPOINTS = {
    "us-west-2": "https://us.api.inspect.aidefense.security.cisco.com/api/v1/inspect/chat",
    "eu-central-1": "https://eu.api.inspect.aidefense.security.cisco.com/api/v1/inspect/chat",
    "ap-northeast-1": "https://apj.api.inspect.aidefense.security.cisco.com/api/v1/inspect/chat",
    "me-central-1": "https://uae.api.inspect.aidefense.security.cisco.com/api/v1/inspect/chat",
}


def _fresh_client(region: str):
    """Build a client for *region*, defeating the Config singleton."""
    from aidefense import ChatInspectionClient, Config

    Config._instances.clear()
    return ChatInspectionClient(api_key="a" * 64, config=Config(region=region))


def test_every_allowed_region_resolves_to_its_own_cisco_endpoint():
    """The allow-list and the SDK must agree, region by region.

    Not one representative region: an allow-list is a claim about ALL of its
    members, and a single spot check would keep a region that the SDK no longer
    resolves.
    """
    assert set(defense._SUPPORTED_REGIONS) == set(_REGION_ENDPOINTS), (
        "the allow-list and the measured endpoint table drifted apart; "
        "re-measure with a fresh process per region before editing either"
    )
    for region, expected in sorted(_REGION_ENDPOINTS.items()):
        assert _fresh_client(region).endpoint == expected, region
    assert len({*_REGION_ENDPOINTS.values()}) == len(_REGION_ENDPOINTS), (
        "two regions resolved to the same host — the singleton was not reset"
    )


def test_an_unknown_region_is_refused_by_the_sdk_not_silently_defaulted():
    """Positive control: the assertion above only means something if a bad
    region actually fails. A silent default would make every case pass."""
    import pytest as _pytest

    for bogus in ("ap-ne-1", "xx-fantasy-9", ""):
        with _pytest.raises(ValueError, match=r"[Ii]nvalid region"):
            _fresh_client(bogus)


def test_the_wrapper_rejects_a_region_the_sdk_would_reject():
    """`ap-ne-1` is Cisco's documented region name and the SDK refuses it.

    The wrapper must refuse it first, with its own configuration error, so the
    failure names the configuration rather than surfacing an SDK ValueError.
    """
    assert "ap-ne-1" not in defense._SUPPORTED_REGIONS
