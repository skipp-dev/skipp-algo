"""Fail-closed Cisco AI Defense guard for every in-repo LLM exchange.

The repository currently talks to OpenAI with raw ``httpx`` calls, so Cisco's
``agentsec`` auto-patcher cannot see those calls.  This module provides the
small explicit boundary used immediately before provider egress and before a
model response is returned to the caller.

No prompt, response, API key, or Cisco explanation is written to application
logs.  Only decision metadata that is safe for operations is logged.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from aidefense import ChatInspectionClient, Config
from aidefense.runtime.chat_models import Message, Role
from aidefense.runtime.models import Action, Metadata

logger = logging.getLogger(__name__)

_API_KEY_ENV = "CISCO_AI_DEFENSE_API_KEY"
_REGION_ENV = "CISCO_AI_DEFENSE_REGION"
_MODE_ENV = "CISCO_AI_DEFENSE_MODE"
_TIMEOUT_ENV = "CISCO_AI_DEFENSE_TIMEOUT_SECONDS"

_SUPPORTED_REGIONS = frozenset({"us-west-2", "eu-central-1", "ap-northeast-1", "me-central-1"})
_SUPPORTED_ROLES = {
    "system": Role.SYSTEM,
    "user": Role.USER,
    "assistant": Role.ASSISTANT,
}


class AIDefenseError(RuntimeError):
    """Base class for intentionally content-free AI Defense failures."""


class AIDefenseConfigurationError(AIDefenseError):
    """AI Defense is not configured strongly enough to inspect traffic."""


class AIDefenseUnavailableError(AIDefenseError):
    """AI Defense did not return a trustworthy decision."""


class AIDefenseBlockedError(AIDefenseError):
    """AI Defense rejected a prompt or model response."""


@dataclass(frozen=True)
class AIDefenseDecision:
    """Sanitized decision metadata; never contains inspected content."""

    allowed: bool
    phase: str
    severity: str
    rules: tuple[str, ...]
    event_id: str
    transaction_id: str


def _mode() -> str:
    mode = os.getenv(_MODE_ENV, "enforce").strip().lower()
    if mode not in {"enforce", "monitor"}:
        raise AIDefenseConfigurationError(f"{_MODE_ENV} must be 'enforce' or 'monitor'")
    return mode


def _timeout_seconds() -> int:
    raw = os.getenv(_TIMEOUT_ENV, "10").strip()
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise AIDefenseConfigurationError(f"{_TIMEOUT_ENV} must be an integer") from exc
    if not 1 <= timeout <= 60:
        raise AIDefenseConfigurationError(f"{_TIMEOUT_ENV} must be between 1 and 60")
    return timeout


def _runtime_config() -> tuple[str, str, int]:
    api_key = os.getenv(_API_KEY_ENV, "").strip()
    if not api_key:
        raise AIDefenseConfigurationError(f"{_API_KEY_ENV} is required for LLM traffic")
    if len(api_key) != 64:
        raise AIDefenseConfigurationError(f"{_API_KEY_ENV} must be a 64-character Inspection API key")

    region = os.getenv(_REGION_ENV, "").strip()
    if region not in _SUPPORTED_REGIONS:
        allowed = ", ".join(sorted(_SUPPORTED_REGIONS))
        raise AIDefenseConfigurationError(f"{_REGION_ENV} must be one of: {allowed}")
    return api_key, region, _timeout_seconds()


@lru_cache(maxsize=4)
def _get_client(api_key: str, region: str, timeout: int) -> ChatInspectionClient:
    # The upstream SDK logs complete request bodies at DEBUG.  Pin its logger
    # to WARNING so a global application DEBUG setting cannot expose prompts.
    sdk_logger = logging.getLogger("skipp_algo.cisco_ai_defense.sdk")
    sdk_logger.setLevel(logging.WARNING)
    config = Config(
        region=region,
        timeout=timeout,
        logger=sdk_logger,
        retry_config={
            "total": 1,
            "backoff_factor": 0.2,
            "status_forcelist": [429, 500, 502, 503, 504],
            "allowed_methods": ["POST"],
            "raise_on_status": False,
            "respect_retry_after_header": True,
        },
    )
    return ChatInspectionClient(api_key=api_key, config=config)


def _normalize_messages(messages: Sequence[Mapping[str, Any]]) -> list[Message]:
    if not messages:
        raise AIDefenseConfigurationError("AI Defense requires at least one message")

    normalized: list[Message] = []
    for item in messages:
        role_raw = item.get("role")
        content = item.get("content")
        role = _SUPPORTED_ROLES.get(str(role_raw))
        if role is None or not isinstance(content, str) or not content.strip():
            raise AIDefenseConfigurationError("AI Defense messages require a supported role and non-empty text")
        normalized.append(Message(role=role, content=content))
    return normalized


def _safe_enum_value(value: Any, default: str) -> str:
    raw = getattr(value, "value", value)
    if raw is None:
        return default
    cleaned = "".join(character for character in str(raw) if character.isalnum() or character in " ._:/-")
    return cleaned[:128] or default


def _rule_names(result: Any) -> tuple[str, ...]:
    names: set[str] = set()
    for rule in getattr(result, "rules", None) or []:
        name = getattr(rule, "rule_name", None)
        if name is not None:
            names.add(_safe_enum_value(name, "unknown"))
    return tuple(sorted(names))


def inspect_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    phase: str,
    source: str,
    model: str,
) -> AIDefenseDecision:
    """Inspect a provider request or response and enforce the Cisco decision.

    ``monitor`` permits policy violations after recording them in Cisco, but
    configuration errors, transport failures, and malformed decisions remain
    fail-closed.  There is deliberately no runtime ``off`` mode.
    """
    if phase not in {"request", "response"}:
        raise AIDefenseConfigurationError("AI Defense phase must be 'request' or 'response'")

    mode = _mode()
    api_key, region, timeout = _runtime_config()
    normalized = _normalize_messages(messages)
    transaction_id = str(uuid.uuid4())
    metadata = Metadata(
        created_at=datetime.now(UTC),
        src_app=f"skipp-algo:{source}"[:128],
        dst_app=f"openai:{model}"[:128],
        client_transaction_id=transaction_id,
    )

    try:
        result = _get_client(api_key, region, timeout).inspect_conversation(
            normalized,
            metadata=metadata,
            request_id=transaction_id,
            timeout=timeout,
        )
    except Exception as exc:
        # Never include the SDK exception text: upstream errors can contain a
        # response body and must not become a second prompt-leak channel.
        logger.error(
            "Cisco AI Defense inspection unavailable phase=%s source=%s error_type=%s",
            phase,
            source,
            type(exc).__name__,
        )
        raise AIDefenseUnavailableError("Cisco AI Defense inspection unavailable; provider call blocked") from None

    action = getattr(result, "action", None)
    is_safe = getattr(result, "is_safe", None)
    # SDK 2.1.2 defaults a missing is_safe field to True while parsing.  An
    # explicit action is therefore required as a second fail-closed contract.
    decision_valid = isinstance(is_safe, bool) and action in {Action.ALLOW, Action.BLOCK}
    if not decision_valid:
        raise AIDefenseUnavailableError("Cisco AI Defense returned an incomplete decision; provider call blocked")

    severity = _safe_enum_value(getattr(result, "severity", None), "UNKNOWN")
    rules = _rule_names(result)
    event_id = _safe_enum_value(getattr(result, "event_id", None), "")
    allowed = is_safe is True and action == Action.ALLOW
    decision = AIDefenseDecision(
        allowed=allowed,
        phase=phase,
        severity=severity,
        rules=rules,
        event_id=event_id,
        transaction_id=transaction_id,
    )

    if allowed:
        logger.info("Cisco AI Defense allowed phase=%s source=%s transaction_id=%s", phase, source, transaction_id)
        return decision

    logger.warning(
        "Cisco AI Defense violation phase=%s source=%s mode=%s severity=%s rules=%s event_id=%s transaction_id=%s",
        phase,
        source,
        mode,
        severity,
        ",".join(rules) or "unknown",
        event_id or "none",
        transaction_id,
    )
    if mode == "monitor":
        return decision
    raise AIDefenseBlockedError(
        f"Cisco AI Defense blocked {phase}; severity={severity}; rules={','.join(rules) or 'unknown'}; "
        f"event_id={event_id or 'none'}"
    )


def append_assistant_message(messages: Sequence[Mapping[str, Any]], content: str) -> list[dict[str, Any]]:
    """Return a copy of *messages* with the provider response appended."""
    return [dict(message) for message in messages] + [{"role": "assistant", "content": content}]
