"""Feature-flag SSOT (audit-L-1 R4, 2026-05-12).

Background
==========
Before this module, the ``ENABLE_OPRA_UOA`` flag was read at four
different call sites (`newsstack_fmp/config.py`, `open_prep/streamlit_monitor.py`
twice, `scripts/probe_providers.py`) using slightly different idioms:

  * ``os.getenv("ENABLE_OPRA_UOA", "1") == "1"``
  * ``os.environ.get("ENABLE_OPRA_UOA", "1").strip() == "1"``
  * ``os.getenv("ENABLE_OPRA_UOA", "1") != "1"`` (negated form)

The drift was real: the ``.strip()`` variants tolerated trailing whitespace
that the bare ``getenv`` variants rejected. An operator who exported
``ENABLE_OPRA_UOA="1 "`` (with a trailing space) would see the streamlit
panel render the OPRA path while the probe + config refused.

This module is the **single source of truth** for ``ENABLE_*`` env-var
feature flags. All call sites must import the helper rather than reading
``os.environ`` directly.

Scope caveat: the SSOT covers only importers of ``open_prep``. Two lower
layers keep **dependency-neutral mirrors** by design — ``smc_core.v2_features``
(so ``smc_core`` never imports ``open_prep``) and
``smc_integration.measurement_evidence`` (its own ``_bool_env`` /
``signal_quality_model``). Their bool + ``SIGNAL_QUALITY_MODEL`` semantics are
kept identical to the helpers here (``.strip().lower()`` + ``{v1,v2,v2.1}``
validation) but are NOT enforced to stay in lock-step — a change here must be
mirrored there. ``tests/test_feature_flag_centralization.py`` only guards
against *raw* ``ENABLE_*`` literal reads outside this module, not against these
sanctioned mirrors.

Convention:
    * Each flag is a single function ``is_<flag>_enabled() -> bool``.
    * The helper reads the env var on every call (cheap, no caching) so
      that runtime overrides via ``os.environ[...] = "0"`` take effect
      immediately. This matches the historical behaviour of the inline
      ``os.getenv(...) == "1"`` checks.
    * ``.strip()`` is applied uniformly so that ``"1 "``, ``" 1"`` and
      ``"\t1\n"`` all parse as enabled (matches the streamlit monitor's
      historical lenient behaviour, which is the safer default).

See ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md`` \xa7R4.
"""

from __future__ import annotations

import os


def _bool_env(name: str, default: str = "1") -> bool:
    """Lenient bool read: trims whitespace, treats only ``"1"`` as enabled."""

    return os.environ.get(name, default).strip() == "1"


def is_opra_uoa_enabled() -> bool:
    """Return True iff ``ENABLE_OPRA_UOA`` is set to ``"1"`` (default ON).

    The flag gates the Databento OPRA.PILLAR options-flow ingestion path.
    When False, the options-flow feed is disabled entirely — the sole
    consumer returns an empty list; NO fallback path exists (the UW /
    Benzinga options_activity paths were removed 2026-05-12). Default is
    ``"1"`` so the only working path stays on.
    """

    return _bool_env("ENABLE_OPRA_UOA", "1")


# ---------------------------------------------------------------------------
# newsstack_fmp feature flags (audit F-002 centralization, 2026-06-14)
# Previously read inline via ``os.getenv(...) == "1"`` in
# ``newsstack_fmp/config.py``.  Moved here so the SSOT contract is
# complete and the centralization guard test can enforce zero raw reads.
# ---------------------------------------------------------------------------


def is_fmp_enabled() -> bool:
    """Return True iff ``ENABLE_FMP`` is set to ``"1"`` (default ON)."""
    return _bool_env("ENABLE_FMP", "1")


def is_fmp_articles_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_ARTICLES`` is set to ``"1"`` (default ON)."""
    return _bool_env("ENABLE_FMP_ARTICLES", "1")


def is_benzinga_rest_enabled() -> bool:
    """Return True iff ``ENABLE_BENZINGA_REST`` is set to ``"1"`` (default OFF)."""
    return _bool_env("ENABLE_BENZINGA_REST", "0")


def is_benzinga_ws_enabled() -> bool:
    """Return True iff ``ENABLE_BENZINGA_WS`` is set to ``"1"`` (default OFF)."""
    return _bool_env("ENABLE_BENZINGA_WS", "0")


def is_benzinga_rss_enabled() -> bool:
    """Return True iff ``ENABLE_BENZINGA_RSS`` is set to ``"1"`` (default ON).

    Uses free RSS feed — no API key required.
    """
    return _bool_env("ENABLE_BENZINGA_RSS", "1")


def is_tradingview_news_enabled() -> bool:
    """Return True iff ``ENABLE_TRADINGVIEW_NEWS`` is set to ``"1"`` (default ON).

    TradingView uses an unofficial keyless endpoint — no API credentials
    required.  Default-ON so the Railway worker gets free symbol-scoped
    headlines out of the box.  Set to ``"0"`` to disable explicitly.
    """
    return _bool_env("ENABLE_TRADINGVIEW_NEWS", "1")


def is_open_prep_tradingview_news_enabled() -> bool:
    """Return True iff ``OPEN_PREP_ENABLE_TRADINGVIEW_NEWS == "1"`` (default ON).

    Legacy ``run_open_prep`` gate for TradingView news supplement.
    SSOT parser semantics apply: only the literal ``"1"`` enables.
    """
    return _bool_env("OPEN_PREP_ENABLE_TRADINGVIEW_NEWS", "1")


def is_open_prep_benzinga_core_news_enabled() -> bool:
    """Return True iff ``OPEN_PREP_ENABLE_BENZINGA_CORE_NEWS == "1"`` (default OFF).

    Legacy ``run_open_prep`` gate for the Benzinga Core News API supplement.
    SSOT parser semantics apply: only the literal ``"1"`` enables.
    """
    return _bool_env("OPEN_PREP_ENABLE_BENZINGA_CORE_NEWS", "0")


def is_newsapi_ai_enabled() -> bool:
    """Return True iff ``ENABLE_NEWSAPI_AI`` is set to ``"1"`` (default OFF)."""
    return _bool_env("ENABLE_NEWSAPI_AI", "0")


def is_uw_news_enabled() -> bool:
    """Return True iff ``ENABLE_UW_NEWS`` is set to ``"1"`` (default OFF).

    Unusual Whales /news/headlines endpoint.  Default-OFF because availability
    depends on UW plan tier; the DISABLED-pattern auto-suppresses on
    401/403/404 responses.
    """
    return _bool_env("ENABLE_UW_NEWS", "0")


def is_fmp_general_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_GENERAL`` is set to ``"1"`` (default ON)."""
    return _bool_env("ENABLE_FMP_GENERAL", "1")


def is_fmp_senate_trades_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_SENATE_TRADES`` is set to ``"1"`` (default OFF).

    Requires a dedicated FMP plan tier; DISABLED-pattern auto-suppresses.
    """
    return _bool_env("ENABLE_FMP_SENATE_TRADES", "0")


def is_fmp_house_trades_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_HOUSE_TRADES`` is set to ``"1"`` (default OFF).

    Requires a dedicated FMP plan tier; DISABLED-pattern auto-suppresses.
    """
    return _bool_env("ENABLE_FMP_HOUSE_TRADES", "0")


def is_fmp_8k_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_8K`` is set to ``"1"`` (default OFF).

    Requires a dedicated FMP plan tier; DISABLED-pattern auto-suppresses.
    """
    return _bool_env("ENABLE_FMP_8K", "0")


def is_fmp_13f_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_13F`` is set to ``"1"`` (default OFF).

    FMP /sec-filings/13F-HR-latest.  Requires dedicated plan tier.
    """
    return _bool_env("ENABLE_FMP_13F", "0")


# SMC Signal Quality v2 feature flags
# (TradingFinder SMC implementation plan, 2026-06-24)
# All default OFF so existing v1 scoring is unchanged until each phase is
# validated and explicitly enabled in the deployment environment.
# ---------------------------------------------------------------------------


def is_freshness_v2_enabled() -> bool:
    """Return True iff the Freshness-v2 score model is enabled (default OFF).

    Flag: ``ENABLE_FRESHNESS_V2_SCORE``. (The pre-2026-07-13 ``ENABLE_FRESHNESS
    _V2`` alias was dropped once its deprecation window closed — it was never set
    in any deployment.)

    Phase A: enables uniform freshness/invalidation enrichment across all
    SMC event families (BOS, OB, FVG, SWEEP).  When disabled, the legacy
    per-family freshness fields are used unchanged.

    SIDE EFFECT (the reason for the ``_SCORE`` rename) — this is a v2
    *score-model* flag, NOT a scoped freshness toggle. It is a member of
    :func:`any_v2_score_feature_enabled`, so enabling it routes
    ``build_signal_quality`` from the v1 to the v2 budget **even while
    ``SIGNAL_QUALITY_MODEL`` stays ``"v1"``**. That re-weights every bucket
    (structure 20→18, session 20→18, liquidity 15→12, OB 15→12, FVG 15→12,
    compression 15→12) and adds confluence 12 + SMT 4, so ``raw_score_0_100``
    and the derived tier / Pine gates / Hero-trust can move even when the
    freshness inputs are neutral. This coupling is deliberate (the v2 freshness
    label only exists inside the v2 budget); do not treat the flag as
    freshness-only.
    """
    return _bool_env("ENABLE_FRESHNESS_V2_SCORE", "0")


def is_sweep_trap_enabled() -> bool:
    """Return True iff ``ENABLE_SWEEP_TRAP`` is ``"1"`` (default OFF).

    Phase B: enables Sweep Trap Classifier enrichment.  The observe-only
    shadow features (``sweep_trap_type``, ``sweep_trap_reclaim_bars``,
    ``sweep_trap_reclaim_strength``, ``sweep_trap_fib_retrace``,
    ``sweep_trap_quality_score``, ``sweep_trap_outcome_late``) are emitted by
    the measurement/benchmark pipeline (``smc_integration.measurement_evidence``)
    into the event-ledger ``features`` — model-INDEPENDENT (this is the WS4a
    study path; it does NOT require ``SIGNAL_QUALITY_MODEL=v2``).  Separately,
    ``build_signal_quality`` surfaces ``SWEEP_TRAP_DETECTED``/``_CONFIDENCE``
    only on the v2 path, but those live-dict fields have no consumer and grant
    no weight until promoted (see :func:`is_sweep_trap_promoted`).  Requires an
    active SWEEP event to have any effect.
    """
    return _bool_env("ENABLE_SWEEP_TRAP", "0")


def is_reaction_zone_study_enabled() -> bool:
    """Return True iff the Reaction-Zone *study* is enabled (default OFF).

    Flag: ``ENABLE_REACTION_ZONE_STUDY``. (The pre-split ``ENABLE_REACTION_ZONE``
    alias was dropped once its deprecation window closed.)

    Phase C: gates the geometric reclaim/band measurer
    (:func:`smc_core.reaction_zone.compute_reaction_zone`) whose raw shadow
    fields (``level_reclaimed``, ``bars_to_reclaim``, ``close_in_rejection_band``,
    ``rejection_band_low/high``, ``bars_to_rejection_band``,
    ``close_distance_pct``, ``body_ratio``, ``rejection_wick_ratio``,
    ``directional_body``) are emitted by the measurement pipeline
    model-INDEPENDENTLY (no ``SIGNAL_QUALITY_MODEL=v2`` needed). Observe-only:
    does not route the model or gate the live score. Depends on Phase B
    (sweep trap) on the enrichment path.
    """
    return _bool_env("ENABLE_REACTION_ZONE_STUDY", "0")


def is_reaction_context_enabled() -> bool:
    """Return True iff the Reaction-*context* detector is enabled (default OFF).

    Flag: ``ENABLE_REACTION_CONTEXT``. (The pre-split ``ENABLE_REACTION_ZONE``
    alias was dropped once its deprecation window closed.)

    Gates :func:`smc_core.reaction_zone.detect_reaction_zone`, a semantically
    DIFFERENT feature from the study above: it merely flags a fresh
    structure/sweep sitting near an OB/FVG in a bias-aligned direction and emits
    ``REACTION_CONTEXT_DETECTED`` / ``_CONFIDENCE`` / ``_DIRECTION``. It inspects
    no swept level, extreme, post-sweep close, reclaim, or rejection band. The
    live-dict fields only appear on the v2 score path and have no consumer.
    """
    return _bool_env("ENABLE_REACTION_CONTEXT", "0")


def is_reaction_zone_enabled() -> bool:
    """Convenience: True iff EITHER reaction feature (study or context) is on.

    Prefer the specific :func:`is_reaction_zone_study_enabled` /
    :func:`is_reaction_context_enabled` in new code.
    """
    return is_reaction_zone_study_enabled() or is_reaction_context_enabled()


def is_confluence_score_enabled() -> bool:
    """Return True iff ``ENABLE_CONFLUENCE_SCORE`` is ``"1"`` (default OFF).

    Phase D: enables the OB ∩ FVG ∩ Sweep orthogonal confluence sub-score.
    This is the trigger for the Signal Quality v2 budget re-weight; do not
    enable before the v2 calibration gate is passed.
    """
    return _bool_env("ENABLE_CONFLUENCE_SCORE", "0")


def is_smt_divergence_enabled() -> bool:
    """Return True iff ``ENABLE_SMT_DIVERGENCE`` is ``"1"`` (default OFF).

    Phase E: enables SMT/correlation divergence layer.  Requires a
    correlated-pair data feed to be configured in the live engine.

    NOTE — unlike sweep-trap/reaction-zone, SMT has NO measurement/shadow-study
    emission: ``detect_smt_divergence`` is only called inside
    ``build_signal_quality_v2``.  So with the default ``SIGNAL_QUALITY_MODEL=v1``
    (and no v2 score flag) the ``SMT_*`` fields are emitted nowhere; they surface
    only on the v2 score path and are promotion-gated
    (see :func:`is_smt_divergence_promoted`).  It is a v2 score layer, not an
    observe-only-with-study detector.

    PRODUCTIVELY INERT — even on the v2 path the detector returns neutral for
    every production event, because no production producer builds the required
    ``correlated_context`` block (only tests supply it; see
    ``smc_core/smt_divergence.py``). Until a PIT-safe correlated-pair feed
    exists, enabling this flag (and ``SMC_SMT_DIVERGENCE_CONFIDENCE``) has no
    observable effect in production.
    """
    return _bool_env("ENABLE_SMT_DIVERGENCE", "0")


def is_sweep_trap_promoted() -> bool:
    """Return True iff ``PROMOTE_SWEEP_TRAP`` is ``"1"`` (default OFF).

    WS4b promotion gate.  While OFF the sweep-trap detector is observe-only:
    ``ENABLE_SWEEP_TRAP`` still emits the ``sweep_trap_*`` shadow features
    (and ``SWEEP_TRAP_DETECTED``/``_CONFIDENCE``), but they grant NO live
    weight.  Flipping this to ``"1"`` is the WS4b decision that lets a
    high-confidence trap downgrade ``SIGNAL_FRESHNESS`` (see OPS.md WS4a and
    :func:`scripts.smc_signal_quality.build_signal_quality_v2`).
    """
    return _bool_env("PROMOTE_SWEEP_TRAP", "0")


def is_smt_divergence_promoted() -> bool:
    """Return True iff ``PROMOTE_SMT_DIVERGENCE`` is ``"1"`` (default OFF).

    Promotion gate for the Phase E SMT layer.  While OFF the SMT detector is
    observe-only: ``ENABLE_SMT_DIVERGENCE`` still emits the ``SMT_*`` fields,
    but they add NO score-budget weight and do NOT downgrade
    ``SIGNAL_FRESHNESS``.
    """
    return _bool_env("PROMOTE_SMT_DIVERGENCE", "0")


def any_v2_feature_enabled() -> bool:
    """Return True iff any SMC v2 feature flag is enabled (observability only).

    NOTE: this predicate does NOT drive model routing — that is
    :func:`any_v2_score_feature_enabled`.  Kept as an honest "is any v2 knob
    on" check for logging/telemetry.
    """
    return any(
        (
            is_sweep_trap_enabled(),
            is_reaction_zone_enabled(),
            is_confluence_score_enabled(),
            is_freshness_v2_enabled(),
            is_smt_divergence_enabled(),
        )
    )


def any_v2_score_feature_enabled() -> bool:
    """Return True iff a SMC v2 *score-model* flag is enabled.

    Only the flags that change the numeric score/model by design route the
    signal-quality router from v1 to v2: Phase A freshness (``ENABLE_FRESHNESS
    _V2``) and Phase D confluence (``ENABLE_CONFLUENCE_SCORE``).  The
    observe-only detector flags (sweep-trap, reaction-zone, SMT) are
    deliberately EXCLUDED so that arming a shadow detector cannot silently
    flip the whole model and move ``raw_score_0_100`` (audit 2026-07-12).
    """
    return any(
        (
            is_confluence_score_enabled(),
            is_freshness_v2_enabled(),
        )
    )


def signal_quality_model() -> str:
    """Return the active Signal Quality score model version.

    Values: ``"v1"`` (default), ``"v2"`` (after Phase D cutover),
    ``"v2.1"`` (after Phase E cutover).  Controls which bucket weights
    ``build_signal_quality`` applies.

    Operators should NOT flip this to ``"v2"`` until the confluence
    calibration gate has been passed (incremental Brier non-inferiority).
    """
    model = os.environ.get("SIGNAL_QUALITY_MODEL", "v1").strip().lower() or "v1"
    if model in ("v1", "v2", "v2.1"):
        return model
    return "v1"
