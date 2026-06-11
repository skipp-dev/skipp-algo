"""ADR-0023 staged-rollout policy: which families have Stage 2 armed.

The ADR-0023 live rollout (``docs/governance/adr0023_live_rollout_handover.md``
§3) is a 3-stage ramp. Stage 2 = "arm strict mode for the qualified families
only": for an **armed** family the promotion gate treats an *unmeasured*
move-size resolution as a fail-closed ``info`` blocker (instead of the lax
Stage-1 no-op), and a measured ``False`` keeps hard-blocking as it always did.

This module is the single source of truth for that arming state. The policy
lives in a checked-in JSON file (``governance/magnitude_stage_policy.json``)
so that:

* the promotion-gate CLI (``scripts/run_promotion_gate.py``) reads the armed
  set at run time — no code change is needed to arm or demote a family;
* the weekly Stage-1 evaluator (``scripts/eval_magnitude_shadow_weekly.py``)
  can **auto-demote** an armed family that falls below the §2 bar (handover
  §5 item 7) by rewriting the file and recording the event in ``history``;
* every arming/demotion is an auditable git commit.

Safety posture
--------------
* A **missing** policy file resolves to the unarmed Stage-1 default — the
  gate stays exactly as dormant as it is today (arming is opt-in).
* A **malformed** policy file raises ``ValueError`` — a corrupt policy must
  never silently disarm an enforcement that an operator deliberately armed.
* Arming is fail-closed: it can only ever *add* blockers, never enable
  sizing. Stage 3 (real move-size sizing) reads the same armed set, so a
  demotion automatically removes a family from magnitude sizing too.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_json

MAGNITUDE_STAGE_POLICY_SCHEMA_VERSION = 1

DEFAULT_POLICY_PATH = Path("governance") / "magnitude_stage_policy.json"

# The only stages the rollout defines (handover §3).
_VALID_STAGES = (1, 2, 3)


@dataclass(frozen=True)
class MagnitudeStagePolicy:
    """Checked-in arming state for the ADR-0023 staged rollout.

    ``stage`` is the highest stage *any* family has reached; per-family
    enforcement is driven solely by membership in ``armed_families``.
    ``k`` / ``n`` freeze the weekly confirmation window the arming was (and
    demotions are) judged against, so the evaluator and the policy can never
    silently disagree about the bar. ``history`` is an append-only audit
    trail of arm/demote events.
    """

    stage: int = 1
    armed_families: frozenset[str] = frozenset()
    k: int = 3
    n: int = 4
    history: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.stage not in _VALID_STAGES:
            raise ValueError(f"stage must be one of {_VALID_STAGES}, got {self.stage!r}")
        if not (1 <= self.k <= self.n):
            raise ValueError(f"require 1 <= k <= n, got k={self.k} n={self.n}")
        if self.stage == 1 and self.armed_families:
            raise ValueError(
                "stage 1 is measure-only; armed_families must be empty "
                f"(got {sorted(self.armed_families)})"
            )


def _unarmed_default() -> MagnitudeStagePolicy:
    return MagnitudeStagePolicy()


def load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> MagnitudeStagePolicy:
    """Load the stage policy; missing file → unarmed Stage-1 default.

    A malformed file raises ``ValueError`` rather than falling back: silently
    reverting to "unarmed" would disarm a deliberately armed enforcement.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _unarmed_default()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed magnitude stage policy {p}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"magnitude stage policy {p} must be a JSON object, "
            f"got {type(payload).__name__}"
        )
    version = payload.get("schema_version")
    if version != MAGNITUDE_STAGE_POLICY_SCHEMA_VERSION:
        raise ValueError(
            f"magnitude stage policy {p}: unsupported schema_version "
            f"{version!r} (expected {MAGNITUDE_STAGE_POLICY_SCHEMA_VERSION})"
        )
    armed = payload.get("armed_families", [])
    if not isinstance(armed, list) or not all(isinstance(f, str) for f in armed):
        raise ValueError(
            f"magnitude stage policy {p}: armed_families must be a list of strings"
        )
    history = payload.get("history", [])
    if not isinstance(history, list) or not all(isinstance(h, dict) for h in history):
        raise ValueError(
            f"magnitude stage policy {p}: history must be a list of objects"
        )
    try:
        return MagnitudeStagePolicy(
            stage=int(payload.get("stage", 1)),
            armed_families=frozenset(armed),
            k=int(payload.get("k", 3)),
            n=int(payload.get("n", 4)),
            history=tuple(history),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"magnitude stage policy {p}: {exc}") from exc


def policy_to_dict(policy: MagnitudeStagePolicy) -> dict[str, Any]:
    """Stable JSON-serialisable representation (sorted armed set)."""
    return {
        "schema_version": MAGNITUDE_STAGE_POLICY_SCHEMA_VERSION,
        "stage": policy.stage,
        "armed_families": sorted(policy.armed_families),
        "k": policy.k,
        "n": policy.n,
        "history": list(policy.history),
    }


def save_policy(
    policy: MagnitudeStagePolicy, path: str | Path = DEFAULT_POLICY_PATH
) -> None:
    """Atomically persist the policy file."""
    atomic_write_json(policy_to_dict(policy), Path(path), indent=2, sort_keys=False)


def demote_family(
    policy: MagnitudeStagePolicy,
    family: str,
    *,
    reason: str,
    date: str,
) -> MagnitudeStagePolicy:
    """Remove *family* from the armed set, recording the event in history.

    Demoting the last armed family drops the policy back to Stage 1. The
    function is a no-op-with-error for families that are not armed — callers
    must not "demote" a family that was never armed (that would fabricate an
    audit-trail event).
    """
    if family not in policy.armed_families:
        raise ValueError(f"family {family!r} is not armed; cannot demote")
    remaining = policy.armed_families - {family}
    event = {
        "action": "demote",
        "family": family,
        "reason": reason,
        "date": date,
    }
    return replace(
        policy,
        stage=policy.stage if remaining else 1,
        armed_families=remaining,
        history=policy.history + (event,),
    )


__all__ = [
    "DEFAULT_POLICY_PATH",
    "MAGNITUDE_STAGE_POLICY_SCHEMA_VERSION",
    "MagnitudeStagePolicy",
    "demote_family",
    "load_policy",
    "policy_to_dict",
    "save_policy",
]
