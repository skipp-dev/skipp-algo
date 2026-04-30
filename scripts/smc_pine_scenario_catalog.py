"""Pine Scenario Catalog — canonical decision-cases for WS1 Pine Evidence Lane.

This module is the read-only contract slice for ticket ``WS1-FT-01`` from
``docs/smc_deep_review_2026-04-20_pine_evidence_first_ticketset.md``.

It defines the smallest canonical list of Pine product decision-cases so that
release-gates and post-release validation can reference scenarios by stable id,
in the same Hero-Surface vocabulary that the dashboards consume
(``scripts/smc_hero_state.py``).

This slice intentionally does not introduce any new gate logic. It only fixes
the catalog so that downstream evidence fixtures (``WS1-FT-02``) and gate
hooks (``WS1-FT-03``) can be wired against a stable, named contract.

Scenarios intentionally cover the six product cases listed in the
first-ticketset document:

1. BOS bullish continuation
2. CHoCH reclaim into long bias
3. OB reclaim with valid trigger
4. FVG fill with actionable follow-through
5. Stale or degraded context — watch / avoid
6. Blocked / no-trade state
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

# Hero vocabulary constants mirror ``scripts/smc_hero_state.py``. They are
# duplicated here as plain literals (rather than imported) so that this catalog
# is self-contained and can be referenced from gate scripts that already pin
# the Hero vocabulary independently.
_MARKET_MODES: frozenset[str] = frozenset(
    {"BULLISH", "BEARISH", "NEUTRAL", "RISK_OFF"}
)
_BIASES: frozenset[str] = frozenset({"LONG", "SHORT", "FLAT"})
_TRUST_STATES: frozenset[str] = frozenset(
    {"healthy", "warmup", "degraded", "stale", "unavailable"}
)
_SETUP_QUALITIES: frozenset[str] = frozenset({"high", "good", "ok", "low"})
_ACTIONS: frozenset[str] = frozenset({"ACTIVE", "WATCH", "AVOID", "BLOCKED"})


@dataclass(frozen=True)
class PineScenario:
    """A single canonical Pine decision-case.

    Attributes
    ----------
    scenario_id:
        Stable, machine-friendly identifier (``ws1_*``). Used by gate reports
        to point at a specific scenario without re-deriving the case.
    name:
        Short product-language label.
    inputs_summary:
        Human-readable summary of the input assumptions a fixture would set up
        when it later realises this scenario as a deterministic artefact
        (``WS1-FT-02``).
    expected_market_mode / expected_bias / expected_trust / expected_setup_quality:
        Expected values of the corresponding ``HERO_*`` fields once the Hero
        State Contract has consumed the realised enrichment for this case.
    expected_action:
        Expected ``HERO_ACTION`` for this case. The single primary product
        handling that the surface should communicate.
    degradation_reason:
        Either an empty string when no degradation applies, or the visible
        ``HERO_RISK`` / blocker that explains why the action is not
        ``ACTIVE``. Mirrors the visible degradation text the dashboards show.
    """

    scenario_id: str
    name: str
    inputs_summary: str
    expected_market_mode: str
    expected_bias: str
    expected_trust: str
    expected_setup_quality: str
    expected_action: str
    degradation_reason: str

    def __post_init__(self) -> None:  # pragma: no cover - trivial guard
        if self.expected_market_mode not in _MARKET_MODES:
            raise ValueError(
                f"{self.scenario_id}: invalid market_mode "
                f"{self.expected_market_mode!r}"
            )
        if self.expected_bias not in _BIASES:
            raise ValueError(
                f"{self.scenario_id}: invalid bias {self.expected_bias!r}"
            )
        if self.expected_trust not in _TRUST_STATES:
            raise ValueError(
                f"{self.scenario_id}: invalid trust {self.expected_trust!r}"
            )
        if self.expected_setup_quality not in _SETUP_QUALITIES:
            raise ValueError(
                f"{self.scenario_id}: invalid setup_quality "
                f"{self.expected_setup_quality!r}"
            )
        if self.expected_action not in _ACTIONS:
            raise ValueError(
                f"{self.scenario_id}: invalid action {self.expected_action!r}"
            )
        if self.expected_action == "ACTIVE" and self.degradation_reason:
            raise ValueError(
                f"{self.scenario_id}: ACTIVE action must not carry a "
                "degradation_reason"
            )
        if self.expected_action != "ACTIVE" and not self.degradation_reason:
            raise ValueError(
                f"{self.scenario_id}: non-ACTIVE action requires a visible "
                "degradation_reason"
            )


_PINE_SCENARIOS: tuple[PineScenario, ...] = (
    PineScenario(
        scenario_id="ws1_bos_bullish_continuation",
        name="BOS bullish continuation",
        inputs_summary=(
            "Healthy regime is BULLISH, layering allows trades, signal "
            "freshness is fresh, ensemble quality is good, and a confirmed "
            "BOS prints inside an aligned higher-timeframe structure."
        ),
        expected_market_mode="BULLISH",
        expected_bias="LONG",
        expected_trust="healthy",
        expected_setup_quality="high",
        expected_action="ACTIVE",
        degradation_reason="",
    ),
    PineScenario(
        scenario_id="ws1_choch_reclaim_long",
        name="CHoCH reclaim into long bias",
        inputs_summary=(
            "Regime flips from neutral or bearish toward bullish via a CHoCH "
            "reclaim, layering allows trades, freshness is fresh, ensemble "
            "quality is good, and the reclaim is confirmed on close."
        ),
        expected_market_mode="BULLISH",
        expected_bias="LONG",
        expected_trust="healthy",
        expected_setup_quality="good",
        expected_action="ACTIVE",
        degradation_reason="",
    ),
    PineScenario(
        scenario_id="ws1_ob_reclaim_valid_trigger",
        name="OB reclaim with valid trigger",
        inputs_summary=(
            "Bullish order block is reclaimed with a valid trigger candle, "
            "regime is BULLISH, layering allows trades, freshness is fresh, "
            "ensemble quality is good, and zone priority points at the OB."
        ),
        expected_market_mode="BULLISH",
        expected_bias="LONG",
        expected_trust="healthy",
        expected_setup_quality="good",
        expected_action="ACTIVE",
        degradation_reason="",
    ),
    PineScenario(
        scenario_id="ws1_fvg_fill_actionable",
        name="FVG fill with actionable follow-through",
        inputs_summary=(
            "Bullish FVG is filled inside a healthy bullish regime, layering "
            "allows trades, freshness is fresh, ensemble quality is at least "
            "ok, and the follow-through candle confirms the fill."
        ),
        expected_market_mode="BULLISH",
        expected_bias="LONG",
        expected_trust="healthy",
        expected_setup_quality="ok",
        expected_action="ACTIVE",
        degradation_reason="",
    ),
    PineScenario(
        scenario_id="ws1_stale_context_watch",
        name="Stale or degraded context — watch only",
        inputs_summary=(
            "Otherwise valid bullish setup runs against stale signal "
            "freshness or multiple stale providers, so trust degrades to "
            "stale and the surface must hold the action at watch."
        ),
        expected_market_mode="BULLISH",
        expected_bias="LONG",
        expected_trust="stale",
        expected_setup_quality="ok",
        expected_action="WATCH",
        degradation_reason="DATA_STALE",
    ),
    PineScenario(
        scenario_id="ws1_blocked_no_trade",
        name="Blocked / no-trade state",
        inputs_summary=(
            "Layering escalates to BLOCKED — for example via an active high "
            "impact macro window — so even with healthy trust and a "
            "structurally clean setup the surface must report no trade."
        ),
        expected_market_mode="NEUTRAL",
        expected_bias="FLAT",
        expected_trust="healthy",
        expected_setup_quality="ok",
        expected_action="BLOCKED",
        degradation_reason="EVENT_RISK",
    ),
)


PINE_SCENARIO_CATALOG: tuple[PineScenario, ...] = _PINE_SCENARIOS
"""Public read-only handle to the canonical scenario tuple."""


_BY_ID: Mapping[str, PineScenario] = MappingProxyType(
    {scenario.scenario_id: scenario for scenario in _PINE_SCENARIOS}
)


def list_pine_scenarios() -> tuple[PineScenario, ...]:
    """Return the canonical scenarios in delivery order."""
    return PINE_SCENARIO_CATALOG


def get_pine_scenario(scenario_id: str) -> PineScenario:
    """Look up a canonical scenario by its ``scenario_id``.

    Raises
    ------
    KeyError
        When ``scenario_id`` is not part of the canonical catalog.
    """
    try:
        return _BY_ID[scenario_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown pine scenario_id={scenario_id!r}; "
            f"known ids: {sorted(_BY_ID)}"
        ) from exc


__all__ = [
    "PINE_SCENARIO_CATALOG",
    "PineScenario",
    "get_pine_scenario",
    "list_pine_scenarios",
]
