"""Trust-State export glue (ENG-WS2-02).

Realises ticket ``ENG-WS2-02`` from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``
("Trust/Freshness in den Export-Pfad ziehen").

This module is the thin bridge between the canonical product-state
vocabulary defined in :mod:`smc_integration.trust_state` (ENG-WS2-01) and
the Pine library that ``scripts.generate_smc_micro_profiles`` writes:

- :func:`attach_trust_state_to_enrichment` lifts a provider_report onto
  the enrichment dict as a ``trust_state`` block (the JSON projection of
  :class:`smc_integration.trust_state.TrustStateAssessment`).
- :func:`render_trust_block_lines` produces the deterministic Pine
  ``export const`` lines for that block, with a HEALTHY fallback when
  the upstream pipeline has not (yet) populated the block.

Definition of Done covered by this slice:

- Pine-seitig stehen explizite Zustandsfelder zur Verfuegung
  (``TRUST_STATE``, ``TRUST_ACTION_IMPACT``, ``TRUST_CAUSE_*``,
  ``TRUST_DEGRADATION_REASON``).
- Degradierungsgruende sind fuer die Surface lesbar
  (``TRUST_DEGRADATION_REASON``).
- Keine doppelte Berechnung derselben Zustandslage im Dashboard:
  the Pine consumer reads the pre-classified trust block instead of
  re-computing it from ``STALE_PROVIDERS`` + ``PROVIDER_COUNT``.

The block is intentionally additive — existing ``PROVIDER_COUNT`` and
``STALE_PROVIDERS`` exports stay unchanged so no current consumer
breaks.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from smc_integration.action_degradation import (
    ActionDegradation,
    derive_action_degradation,
)
from smc_integration.trust_state import (
    ACTION_IMPACT_NONE,
    TrustState,
    TrustStateAssessment,
    TrustStateCause,
    derive_trust_state,
)

# Stable Pine field-name surface (caller never spells these manually).
PINE_TRUST_FIELDS: tuple[str, ...] = (
    "TRUST_STATE",
    "TRUST_ACTION_IMPACT",
    "TRUST_CAUSE_DOMAIN",
    "TRUST_CAUSE_FAILURE_TYPE",
    "TRUST_CAUSE_CODE",
    "TRUST_DEGRADATION_REASON",
)

# Stable Pine field-name surface for the action-degradation block
# (ENG-WS2-04). Kept on a separate tuple so the existing trust block
# stays byte-for-byte unchanged.
PINE_ACTION_DEGRADATION_FIELDS: tuple[str, ...] = (
    "ACTION_DEGRADATION_TIER",
    "ACTION_DEGRADATION_REASON",
    "ACTION_DEGRADATION_DERIVED_FROM",
)


def _pine_string(value: Any) -> str:
    """Pine-safe quoted string (escape backslashes and double quotes)."""
    if value is None:
        return '""'
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def attach_trust_state_to_enrichment(
    enrichment: dict[str, Any] | None,
    provider_report: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Set ``enrichment['trust_state']`` from a provider report.

    Mutates and returns ``enrichment`` so the caller can chain. When
    either argument is falsy the enrichment is returned unchanged so the
    helper is safe to call unconditionally in upstream pipelines.
    """
    if enrichment is None or provider_report is None:
        return enrichment
    assessment = derive_trust_state(provider_report)
    enrichment["trust_state"] = assessment.as_dict()
    return enrichment


def _fallback_trust_block(
    enrichment: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Synthesise a minimal HEALTHY block when no trust_state is set.

    Used when ``enrichment['trust_state']`` is absent so the export
    contract stays stable: every Pine library always carries the
    ``TRUST_*`` fields, regardless of whether the upstream pipeline
    has been upgraded to populate them yet.

    If the legacy ``providers.stale_providers`` field is non-empty we
    surface a STALE bucket with that as the cause description, so a
    pipeline that produces the legacy provider block (but no
    trust_state) does not silently report HEALTHY.
    """
    providers = (enrichment or {}).get("providers") or {}
    stale = str(providers.get("stale_providers") or "").strip()
    if stale:
        return {
            "state": TrustState.STALE.value,
            "action_impact": "advisory_only",
            "cause": {
                "domain": "providers",
                "failure_type": "stale",
                "code": "STALE_PROVIDERS",
                "description": f"Stale providers reported by upstream: {stale}",
            },
            "contributing_alerts": [],
            "derived_from_overall_status": None,
        }
    return {
        "state": TrustState.HEALTHY.value,
        "action_impact": ACTION_IMPACT_NONE,
        "cause": {
            "domain": None,
            "failure_type": None,
            "code": None,
            "description": None,
        },
        "contributing_alerts": [],
        "derived_from_overall_status": None,
    }


def trust_block_for_export(
    enrichment: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the trust block the export should serialise.

    Reads ``enrichment['trust_state']`` when present; otherwise falls
    back to :func:`_fallback_trust_block` so the export contract is
    stable.
    """
    payload = (enrichment or {}).get("trust_state")
    if isinstance(payload, Mapping):
        # Defensive shallow-copy so the caller cannot mutate the
        # original via the returned dict.
        block: dict[str, Any] = dict(payload)
        cause = block.get("cause")
        if isinstance(cause, Mapping):
            block["cause"] = dict(cause)
        return block
    return _fallback_trust_block(enrichment)


def render_trust_block_lines(
    enrichment: Mapping[str, Any] | None,
) -> list[str]:
    """Render the deterministic Pine ``export const`` lines for the block.

    Output order matches :data:`PINE_TRUST_FIELDS` (state, action_impact,
    cause domain, cause failure_type, cause code, degradation_reason).
    Always emits all six fields so a Pine consumer can read them
    unconditionally.
    """
    block = trust_block_for_export(enrichment)
    cause = block.get("cause") or {}
    state = block.get("state") or TrustState.HEALTHY.value
    action_impact = block.get("action_impact") or ACTION_IMPACT_NONE
    domain = cause.get("domain") or ""
    failure_type = cause.get("failure_type") or ""
    code = cause.get("code") or ""
    description = cause.get("description") or ""

    return [
        "// ── Trust State (ENG-WS2-02) ──",
        f"export const string TRUST_STATE = {_pine_string(state)}",
        f"export const string TRUST_ACTION_IMPACT = {_pine_string(action_impact)}",
        f"export const string TRUST_CAUSE_DOMAIN = {_pine_string(domain)}",
        f"export const string TRUST_CAUSE_FAILURE_TYPE = {_pine_string(failure_type)}",
        f"export const string TRUST_CAUSE_CODE = {_pine_string(code)}",
        f"export const string TRUST_DEGRADATION_REASON = {_pine_string(description)}",
    ]


def _assessment_from_block(block: Mapping[str, Any]) -> TrustStateAssessment:
    """Reconstruct a TrustStateAssessment from a previously-serialised block.

    Used by :func:`render_action_degradation_block_lines` so the render
    path can reuse the deterministic ENG-WS2-04 derivation without
    forcing every caller to also keep the live assessment object
    around. Falls back to HEALTHY when the block is malformed.
    """
    state_raw = str(block.get("state") or TrustState.HEALTHY.value).strip().lower()
    try:
        state = TrustState(state_raw)
    except ValueError:
        state = TrustState.HEALTHY
    cause_raw = block.get("cause") or {}
    cause = TrustStateCause(
        domain=(cause_raw.get("domain") or None),
        failure_type=(cause_raw.get("failure_type") or None),
        code=(cause_raw.get("code") or None),
        description=(cause_raw.get("description") or None),
    )
    return TrustStateAssessment(
        state=state,
        action_impact=str(block.get("action_impact") or ACTION_IMPACT_NONE),
        cause=cause,
        contributing_alerts=tuple(block.get("contributing_alerts") or ()),
        derived_from_overall_status=block.get("derived_from_overall_status"),
    )


def action_degradation_for_export(
    enrichment: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Return the action-degradation block the export should serialise.

    Reads ``enrichment['action_degradation']`` when present (already
    derived upstream); otherwise rebuilds it deterministically from the
    trust block via the canonical ENG-WS2-04 mapping. The resulting
    dict always carries the three keys ``tier``, ``reason`` and
    ``derived_from_state`` so consumers can iterate the contract
    unconditionally.
    """
    payload = (enrichment or {}).get("action_degradation")
    if isinstance(payload, Mapping):
        return {
            "tier": str(payload.get("tier") or ActionDegradation.NONE.value),
            "reason": str(payload.get("reason") or ""),
            "derived_from_state": str(
                payload.get("derived_from_state") or TrustState.HEALTHY.value
            ),
        }
    block = trust_block_for_export(enrichment)
    assessment = _assessment_from_block(block)
    return derive_action_degradation(assessment).as_dict()


def render_action_degradation_block_lines(
    enrichment: Mapping[str, Any] | None,
) -> list[str]:
    """Render the deterministic Pine ``export const`` lines for the
    action-degradation block (ENG-WS2-04).

    Output order matches :data:`PINE_ACTION_DEGRADATION_FIELDS`.
    Always emits all three fields so a Pine consumer can read them
    unconditionally.
    """
    block = action_degradation_for_export(enrichment)
    return [
        "// ── Action Degradation (ENG-WS2-04) ──",
        f"export const string ACTION_DEGRADATION_TIER = {_pine_string(block['tier'])}",
        f"export const string ACTION_DEGRADATION_REASON = {_pine_string(block['reason'])}",
        f"export const string ACTION_DEGRADATION_DERIVED_FROM = {_pine_string(block['derived_from_state'])}",
    ]


__all__ = [
    "PINE_ACTION_DEGRADATION_FIELDS",
    "PINE_TRUST_FIELDS",
    "action_degradation_for_export",
    "attach_trust_state_to_enrichment",
    "render_action_degradation_block_lines",
    "render_trust_block_lines",
    "trust_block_for_export",
]
