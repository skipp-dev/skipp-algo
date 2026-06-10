"""Unified Trust-State model for the SMC product surface (ENG-WS2-01).

Realises ticket ``ENG-WS2-01`` from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``
("Einheitliches Trust-State-Modell definieren").

The repository today exposes provider/artefact health through several
per-domain views (:mod:`smc_integration.provider_health`,
:mod:`smc_tv_bridge.provider_status`, generated micro profiles, …). Each
of those vocabularies is correct in isolation but the product surface
(Pine dashboard, Hero State, action degradation) needs a single canonical
state alphabet that:

1. has *few*, *stable* product states an operator can reason about,
2. maps deterministically from any provider/artefact lage to exactly one
   product state, and
3. separates **cause** (which domain/code produced the state) from
   **effect** (how the action surface should behave).

This module defines exactly that vocabulary plus a pure derivation from
an enriched ``provider_report`` (the dict returned by
``smc_integration.provider_health.run_provider_health_check`` and
classified through
:func:`smc_integration.provider_health.classify_domain_alerts_to_failure_actions`).

The five canonical product states (per the ticket's scope) are:

- ``HEALTHY``     — full trust; the product can show every signal.
- ``DEGRADED``    — advisory-only failures; entries still allowed, but
                    the surface should communicate the limitation.
- ``STALE``       — at least one stale-data domain that is itself not
                    severe enough to suppress entries (e.g. volume/news
                    stale).
- ``WATCH_ONLY``  — at least one suppress-class failure (typically a
                    structure-domain stale > 24 h); the action surface
                    must downgrade to *no new entries*.
- ``UNAVAILABLE`` — a hard-degrade failure (missing/invalid structure or
                    similar); the product surface cannot trust the
                    snapshot at all.

The derivation is pure and read-only: it accepts the existing dict shape
and returns a structured :class:`TrustStateAssessment`.

This slice does not touch the dashboard or any export; it only pins the
shared vocabulary so subsequent WS2 tickets (ENG-WS2-02 export, ENG-WS2-03
badges, ENG-WS2-04 action degradation) can consume one stable surface.
"""
from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from smc_integration.provider_health import (
    FailureAction,
    classify_domain_alerts_to_failure_actions,
)

# ── Canonical product states ──────────────────────────────────────────


class TrustState(enum.Enum):
    """The five canonical product trust states (ENG-WS2-01 scope)."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    WATCH_ONLY = "watch_only"
    UNAVAILABLE = "unavailable"


# Stable severity order — lowest trust wins when multiple states apply.
# The ordering is fixed and intentionally encoded once so no caller can
# reinvent it.
_STATE_SEVERITY: tuple[TrustState, ...] = (
    TrustState.HEALTHY,
    TrustState.DEGRADED,
    TrustState.STALE,
    TrustState.WATCH_ONLY,
    TrustState.UNAVAILABLE,
)


def _state_rank(state: TrustState) -> int:
    return _STATE_SEVERITY.index(state)


# ── Action impact vocabulary ──────────────────────────────────────────
# Effect = how the product action surface must respond.

ACTION_IMPACT_NONE = "none"
ACTION_IMPACT_ADVISORY_ONLY = "advisory_only"
ACTION_IMPACT_NO_NEW_ENTRIES = "no_new_entries"
ACTION_IMPACT_SUPPRESS_PRODUCT = "suppress_product"

ACTION_IMPACTS: tuple[str, ...] = (
    ACTION_IMPACT_NONE,
    ACTION_IMPACT_ADVISORY_ONLY,
    ACTION_IMPACT_NO_NEW_ENTRIES,
    ACTION_IMPACT_SUPPRESS_PRODUCT,
)

_STATE_TO_ACTION_IMPACT: dict[TrustState, str] = {
    TrustState.HEALTHY: ACTION_IMPACT_NONE,
    TrustState.DEGRADED: ACTION_IMPACT_ADVISORY_ONLY,
    TrustState.STALE: ACTION_IMPACT_ADVISORY_ONLY,
    TrustState.WATCH_ONLY: ACTION_IMPACT_NO_NEW_ENTRIES,
    TrustState.UNAVAILABLE: ACTION_IMPACT_SUPPRESS_PRODUCT,
}


def state_action_impact(state: TrustState) -> str:
    """Return the canonical action-impact string for a trust state."""
    return _STATE_TO_ACTION_IMPACT[state]


# ── Cause / Effect separation ─────────────────────────────────────────


@dataclass(frozen=True)
class TrustStateCause:
    """Why the product surface is not HEALTHY.

    ``None`` fields mean "no contributing alert" (only valid for HEALTHY).
    ``attribution`` is ``"exact"`` when an alert exactly matched the target
    state, ``"worst_severity_heuristic"`` when no exact match existed and
    the worst-severity alert was used as a proxy.
    """

    domain: str | None
    failure_type: str | None
    code: str | None
    description: str | None
    attribution: str = "exact"  # "exact" | "worst_severity_heuristic"


@dataclass(frozen=True)
class TrustStateAssessment:
    """The complete trust assessment for one provider report.

    Cause and effect are surfaced separately so a UI consumer can render
    the *why* and the *what next* independently (per Definition of Done
    of ENG-WS2-01: "Health-Ausgaben benennen Ursache und Auswirkung
    getrennt").
    """

    state: TrustState
    action_impact: str
    cause: TrustStateCause
    contributing_alerts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    derived_from_overall_status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Stable JSON-friendly projection (used by exports)."""
        return {
            "state": self.state.value,
            "action_impact": self.action_impact,
            "cause": {
                "domain": self.cause.domain,
                "failure_type": self.cause.failure_type,
                "code": self.cause.code,
                "description": self.cause.description,
            },
            "contributing_alerts": [dict(a) for a in self.contributing_alerts],
            "derived_from_overall_status": self.derived_from_overall_status,
        }


# ── Derivation ────────────────────────────────────────────────────────


def _coerce_alerts(alerts: Any) -> list[dict[str, Any]]:
    """Return a defensive copy of a domain_alerts iterable."""
    if not alerts:
        return []
    out: list[dict[str, Any]] = []
    for alert in alerts:
        if isinstance(alert, Mapping):
            out.append(dict(alert))
    return out


def _ensure_classified(
    domain_alerts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run the failure-action classifier exactly once, idempotently."""
    if all("failure_action" in alert for alert in domain_alerts):
        return domain_alerts
    return classify_domain_alerts_to_failure_actions(domain_alerts)


def _state_from_action(
    action: FailureAction,
    *,
    has_stale: bool,
) -> TrustState:
    """Map (worst FailureAction, has_stale) → TrustState.

    The mapping is deliberately exhaustive; an unknown FailureAction
    value (added later) falls through to DEGRADED rather than HEALTHY
    so the addition is loud, not silent.
    """
    if action is FailureAction.HARD_DEGRADE:
        return TrustState.UNAVAILABLE
    if action is FailureAction.SUPPRESS:
        return TrustState.WATCH_ONLY
    if action is FailureAction.ADVISORY:
        # Advisory split: stale-data advisories surface as STALE so the
        # product can show "Daten älter als …" in one badge; everything
        # else is generic DEGRADED.
        return TrustState.STALE if has_stale else TrustState.DEGRADED
    if action is FailureAction.FALLBACK:
        return TrustState.HEALTHY
    # Defensive default — see docstring.
    return TrustState.DEGRADED


def _failure_type_of(alert: Mapping[str, Any]) -> str:
    """Best-effort failure_type for an enriched alert."""
    code = str(alert.get("code") or "").upper()
    if "STALE" in code:
        return "stale"
    if "MISSING" in code or "DROPPED" in code or "SILENT_DOMAIN_DROP" in code:
        return "missing"
    if "FALLBACK" in code:
        return "fallback"
    if "INVALID" in code:
        return "invalid"
    return "unknown"


def _select_primary_cause(
    enriched_alerts: list[dict[str, Any]],
    target_state: TrustState,
) -> TrustStateCause:
    """Pick the single contributing alert that best explains ``target_state``.

    Picks the first alert (in original order) whose mapped TrustState
    matches ``target_state``. HEALTHY returns an all-None cause.
    """
    if target_state is TrustState.HEALTHY or not enriched_alerts:
        return TrustStateCause(None, None, None, None)

    for alert in enriched_alerts:
        action_str = str(alert.get("failure_action") or "").strip()
        try:
            action = FailureAction(action_str)
        except ValueError:
            continue
        ftype = _failure_type_of(alert)
        candidate_state = _state_from_action(action, has_stale=(ftype == "stale"))
        if candidate_state is target_state:
            return TrustStateCause(
                domain=str(alert.get("domain") or "").strip().lower() or None,
                failure_type=ftype,
                code=str(alert.get("code") or "").strip().upper() or None,
                description=str(alert.get("message") or alert.get("description") or "") or None,
            )

    # Fall back to the worst-severity alert if no exact-state match exists
    # (this can happen when the overall_status was injected without a
    # per-alert breakdown).
    fallback = enriched_alerts[0]
    return TrustStateCause(
        domain=str(fallback.get("domain") or "").strip().lower() or None,
        failure_type=_failure_type_of(fallback),
        code=str(fallback.get("code") or "").strip().upper() or None,
        description=str(fallback.get("message") or fallback.get("description") or "") or None,
        attribution="worst_severity_heuristic",
    )


def derive_trust_state(provider_report: Mapping[str, Any]) -> TrustStateAssessment:
    """Derive the canonical trust assessment from a provider_report.

    Accepts the dict shape produced by
    :func:`smc_integration.provider_health.run_provider_health_check` —
    in particular the keys ``overall_status`` and ``domain_alerts``. The
    function is read-only: it does not mutate the input.

    Rules (in priority order):

    1. If any enriched alert maps to ``HARD_DEGRADE`` → ``UNAVAILABLE``.
    2. If any enriched alert maps to ``SUPPRESS``    → ``WATCH_ONLY``.
    3. If any stale-data advisory is present         → ``STALE``.
    4. If any other ADVISORY is present              → ``DEGRADED``.
    5. Otherwise                                     → ``HEALTHY``.

    The ``cause`` is the first alert whose mapped state equals the
    chosen state, so the visible reason matches the visible state.
    """
    overall_status = None
    if isinstance(provider_report, Mapping):
        overall = provider_report.get("overall_status")
        if isinstance(overall, str):
            overall_status = overall

    domain_alerts = _coerce_alerts(
        provider_report.get("domain_alerts") if isinstance(provider_report, Mapping) else None
    )
    enriched = _ensure_classified(domain_alerts)

    if not enriched:
        # No alerts → HEALTHY (regardless of overall_status), unless the
        # overall_status itself signals an unrecoverable failure with no
        # per-alert breakdown.
        if overall_status and overall_status.lower() not in {"ok", "warn"}:
            state = TrustState.UNAVAILABLE
            cause = TrustStateCause(
                domain=None,
                failure_type=None,
                code=overall_status.upper(),
                description=f"Provider report overall_status={overall_status!r}",
            )
            return TrustStateAssessment(
                state=state,
                action_impact=state_action_impact(state),
                cause=cause,
                contributing_alerts=(),
                derived_from_overall_status=overall_status,
            )
        state = TrustState.HEALTHY
        return TrustStateAssessment(
            state=state,
            action_impact=state_action_impact(state),
            cause=TrustStateCause(None, None, None, None),
            contributing_alerts=(),
            derived_from_overall_status=overall_status,
        )

    # Compute the worst per-alert TrustState across all enriched alerts.
    candidate_states: list[TrustState] = []
    for alert in enriched:
        action_str = str(alert.get("failure_action") or "").strip()
        try:
            action = FailureAction(action_str)
        except ValueError:
            continue
        candidate_states.append(
            _state_from_action(action, has_stale=(_failure_type_of(alert) == "stale"))
        )

    # Alerts were present but none classifiable → conservative DEGRADED.
    worst_state = (
        TrustState.DEGRADED
        if not candidate_states
        else max(candidate_states, key=_state_rank)
    )

    cause = _select_primary_cause(enriched, worst_state)
    contributing = tuple(
        alert for alert, st in zip(enriched, candidate_states, strict=False) if st is worst_state
    )

    return TrustStateAssessment(
        state=worst_state,
        action_impact=state_action_impact(worst_state),
        cause=cause,
        contributing_alerts=contributing,
        derived_from_overall_status=overall_status,
    )


def all_trust_states() -> Iterable[TrustState]:
    """Stable iteration order over every canonical trust state."""
    return _STATE_SEVERITY


__all__ = [
    "ACTION_IMPACTS",
    "ACTION_IMPACT_ADVISORY_ONLY",
    "ACTION_IMPACT_NONE",
    "ACTION_IMPACT_NO_NEW_ENTRIES",
    "ACTION_IMPACT_SUPPRESS_PRODUCT",
    "TrustState",
    "TrustStateAssessment",
    "TrustStateCause",
    "all_trust_states",
    "derive_trust_state",
    "state_action_impact",
]
