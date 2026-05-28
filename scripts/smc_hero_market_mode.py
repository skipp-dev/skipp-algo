"""Hero Market-Mode head (ENG-WS3-03).

Realises ticket ``ENG-WS3-03`` ("Marktmodus-Hero bauen") from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``.

Composes the Hero-level **Market Mode** head as a single, deterministic
product object: regime + bias + session + trust + freshness in one
glance, lifted from the canonical enrichment + the WS2-01 trust state.

Rules:

* Exactly one source for each component (no shadow logic).
* Every Pine consumer reads the rendered ``HERO_MARKET_*`` fields.
  Dashboards must NOT recompute regime/bias/session/trust/freshness
  themselves for the Hero head — single mode display.
* Trust + freshness are integrated into the same head block (DoD).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from scripts.smc_hero_state import (
    HERO_TRUST_DEGRADED,
    HERO_TRUST_HEALTHY,
    HERO_TRUST_STALE,
    HERO_TRUST_UNAVAILABLE,
    project_trust_state_to_hero,
)
from smc_integration.trust_state import TrustState, derive_trust_state

# ── Vocabulary ────────────────────────────────────────────────────────


_BIAS_LONG_THRESHOLD: float = 0.15
_BIAS_SHORT_THRESHOLD: float = -0.15


def _classify_bias(macro_bias: float) -> str:
    """Return short / neutral / long for a macro-bias scalar."""
    if macro_bias >= _BIAS_LONG_THRESHOLD:
        return "long"
    if macro_bias <= _BIAS_SHORT_THRESHOLD:
        return "short"
    return "neutral"


# HERO_MARKET_TRUST vocabulary (#58 convergence onto HERO_TRUST).
# Derives from canonical TrustState via project_trust_state_to_hero(),
# which collapses WATCH_ONLY → "degraded" (info-loss documented in
# scripts/smc_hero_state.py). "warmup" is HERO_TRUST-only (Hero-local
# freshness signal with no TrustState counterpart) and therefore absent
# here. Pin: tests/test_hero_trust_market_trust_alignment.py enforces
# HERO_MARKET_TRUST_VOCAB == HERO_TRUST_VOCAB - {"warmup"}.
HERO_MARKET_TRUST_VOCAB: frozenset[str] = frozenset({
    HERO_TRUST_HEALTHY,
    HERO_TRUST_DEGRADED,
    HERO_TRUST_STALE,
    HERO_TRUST_UNAVAILABLE,
})


def _trust_label(state: TrustState) -> str:
    return project_trust_state_to_hero(state)


_FRESH_FROM_TRUST: Mapping[TrustState, str] = {
    TrustState.HEALTHY: "fresh",
    TrustState.DEGRADED: "fresh",
    TrustState.STALE: "stale",
    TrustState.WATCH_ONLY: "stale",
    TrustState.UNAVAILABLE: "missing",
}


def _freshness_label(state: TrustState) -> str:
    return _FRESH_FROM_TRUST.get(state, "fresh")


# ── Result dataclass ──────────────────────────────────────────────────


@dataclass(frozen=True)
class HeroMarketMode:
    """The Hero-level Market Mode head — one row, five components."""

    regime: str
    bias: str
    session: str
    trust: str
    freshness: str

    def as_dict(self) -> dict[str, str]:
        return {
            "regime": self.regime,
            "bias": self.bias,
            "session": self.session,
            "trust": self.trust,
            "freshness": self.freshness,
        }


# ── Derivation ────────────────────────────────────────────────────────


def _session_label(enrichment: Mapping[str, Any]) -> str:
    """Pick a single session label from the canonical enrichment.

    Uses ``session_context_light.SESSION_CONTEXT`` if present, falls back
    to ``session_context.SESSION_CONTEXT``, then to ``"unknown"``. The
    Hero head deliberately compresses to one label — the detailed
    session metrics stay in the Compact / Pro layers.
    """
    scl = enrichment.get("session_context_light") or {}
    if isinstance(scl, Mapping) and scl.get("SESSION_CONTEXT"):
        return str(scl["SESSION_CONTEXT"])
    sc = enrichment.get("session_context") or {}
    if isinstance(sc, Mapping) and sc.get("SESSION_CONTEXT"):
        return str(sc["SESSION_CONTEXT"])
    return "unknown"


def _regime_label(enrichment: Mapping[str, Any]) -> str:
    """Return the upper-case regime label for the Hero Market Mode block.

    Pine consumers — e.g. ``SMC_Mobile_Dashboard.pine:79`` which
    compares ``mp.HERO_MARKET_MODE`` against literals ``"BULLISH"``,
    ``"BEARISH"``, ``"RISK_OFF"`` — treat regime labels as UPPERCASE
    string identifiers. Producer A (``scripts/smc_hero_state.py``)
    emits ``HERO_MARKET_MODE`` as UPPERCASE passthrough; this helper
    feeds the reserved ``HERO_MARKET_REGIME`` export (currently not
    yet Pine-consumed) and must stay case-consistent so a future
    migration from ``HERO_MARKET_MODE`` to ``HERO_MARKET_REGIME`` does
    not silently lose every Pine colour / gate branch.

    Boundary-Contract Improvement Plan 2026-04-23, F-1 / PR-BC-03.
    """
    regime = enrichment.get("regime") or {}
    if isinstance(regime, Mapping):
        value = regime.get("regime")
        if value:
            return str(value).upper()
    return "NEUTRAL"


def _macro_bias(enrichment: Mapping[str, Any]) -> float:
    regime = enrichment.get("regime") or {}
    if isinstance(regime, Mapping):
        try:
            return float(regime.get("macro_bias") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def derive_hero_market_mode(enrichment: Mapping[str, Any]) -> HeroMarketMode:
    """Compose the Hero-level Market Mode from the canonical enrichment."""
    enr = enrichment or {}
    trust_block = enr.get("trust_state")
    if isinstance(trust_block, Mapping) and trust_block.get("state"):
        try:
            state = TrustState(str(trust_block["state"]))
        except ValueError:
            state = TrustState.HEALTHY
    else:
        state = derive_trust_state(enr).state

    return HeroMarketMode(
        regime=_regime_label(enr),
        bias=_classify_bias(_macro_bias(enr)),
        session=_session_label(enr),
        trust=_trust_label(state),
        freshness=_freshness_label(state),
    )


# ── Pine rendering ────────────────────────────────────────────────────

PINE_HERO_MARKET_FIELDS: tuple[str, ...] = (
    "HERO_MARKET_REGIME",
    "HERO_MARKET_BIAS",
    "HERO_MARKET_SESSION",
    "HERO_MARKET_TRUST",
    "HERO_MARKET_FRESHNESS",
)


def _pine_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_hero_market_mode_block_lines(
    enrichment: Mapping[str, Any],
) -> list[str]:
    """Render the Hero Market Mode head as Pine ``export const`` lines."""
    head = derive_hero_market_mode(enrichment)
    values = head.as_dict()
    lines: list[str] = ["// ── Hero Market Mode (ENG-WS3-03) ──"]
    for field, key in zip(
        PINE_HERO_MARKET_FIELDS,
        ("regime", "bias", "session", "trust", "freshness"), strict=False,
    ):
        lines.append(
            f'export const string {field} = "{_pine_string(values[key])}"'
        )
    return lines


__all__ = [
    "HERO_MARKET_TRUST_VOCAB",
    "PINE_HERO_MARKET_FIELDS",
    "HeroMarketMode",
    "derive_hero_market_mode",
    "render_hero_market_mode_block_lines",
]
