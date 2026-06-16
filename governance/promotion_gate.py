"""Sprint X2 — PromotionGate consolidator.

Aggregates the per-check verdicts (Brier, FDR p-value, PSR/MinTRL, PSI,
live-Brier-vs-walkforward ratio) into a single ``Decision`` per event
family. Pure aggregator: every threshold here mirrors the one already
enforced inside the originating sprint's module. Changing a threshold in
this file alone must NOT shift the gate behaviour — the source of truth
remains the per-sprint module.

Schema is pinned at ``DECISION_SCHEMA_VERSION``. Bumped to 2 in Sprint
W1.a (2026-05-17) to carry the new hardening fields (psi_slope,
conformal_coverage/target, regime_degraded) plus a ``provenance``
sub-dict with non-numeric metadata (``wf_scheme``, ``bootstrap_method``,
``psr_method``, ...). Downstream consumers can keep treating the
Decision dict as opaque; ``provenance`` defaults to an empty dict.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from governance.types import (
    Blocker,
    BlockerSeverity,
    Decision,
    EventFamily,
    Posture,
    ProvenanceValue,
)

DECISION_SCHEMA_VERSION = 2

# Provenance keys whose absence is a promotion-blocking ``info`` event
# when the gate is run in strict mode (Sprint W1.a). The keys map to the
# upstream sprint that owns the value:
#   wf_scheme, wf_embargo_bars  → C2.1 walk-forward
#   bootstrap_method            → C3.1 BCa bootstrap
#   block_size                  → C4.1 block permutation
#   psr_method                  → C6.1 PSR / MinIS
#   stacked_used                → C10.1 stacking + conformal
REQUIRED_PROVENANCE_KEYS = (
    "wf_scheme",
    "wf_embargo_bars",
    "bootstrap_method",
    "block_size",
    "psr_method",
    "stacked_used",
)

# ADR-0016: the three provenance keys that describe an upstream ML-modelling
# layer (BCa bootstrap, block permutation, stacking ensemble). A pipeline that
# performs no such modelling -- an SMC-direct "no-ML" pipeline whose returns
# come straight from events and whose scores are raw event scores -- legitimately
# cannot declare them; for such a class they are NOT-APPLICABLE rather than
# not-declared. The remaining required keys (wf_scheme, wf_embargo_bars,
# psr_method) are pipeline-agnostic and stay required for every class.
ML_MODELLING_PROVENANCE_KEYS = frozenset({
    "bootstrap_method",
    "block_size",
    "stacked_used",
})

# ADR-0016: provenance key by which a family declares its pipeline class, and
# the recognised no-ML classes that waive ML_MODELLING_PROVENANCE_KEYS. The
# waiver is conditional: an absent or UNKNOWN pipeline_class grants no waiver,
# so the keys cannot be dropped by declaring an arbitrary string.
PIPELINE_CLASS_KEY = "pipeline_class"
SMC_DIRECT_NO_ML = "smc_direct_no_ml"
NO_ML_PIPELINE_CLASSES = frozenset({SMC_DIRECT_NO_ML})

# Default thresholds mirrored here for aggregation only.
# The source of truth for each threshold is the originating sprint's
# module and/or sprint-plan document that introduced the check; the
# constants below MUST stay aligned with those upstream definitions.
# Updating a value in this file alone must NOT change gate semantics.
#
# Pointers (verified 2026-04-27):
#   * Brier (0.22):       gate-level absolute cap; the live recalibrator
#                         tracks a separate brier_regret_threshold (~0.02)
#                         in the C10 ML layer (see
#                         docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md).
#                         No module-level CALIBRATED_BRIER_TARGET exists
#                         today — this gate is the sole source of truth.
#   * ECE (0.05):         gate is the source of truth
#                         (docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md).
#   * FDR-q (0.05):       scripts/run_ab_comparison.py::FDR_Q.
#   * PSR/MinTRL:         docs/SPRINT_PLAN_C6_PSR_MINTRL_2026-04-26.md and
#                         open_prep/stats_helpers.py::probabilistic_sharpe
#                         / min_trl.
#   * PSI (0.25):         consolidator's hard cap, above the per-feature
#                         drift-alarm thresholds defined for the C9 drift
#                         layer (see docs/SPRINT_PLAN_C9_DRIFT_2026-04-26.md).
#                         The ml/drift/ package does not yet expose a
#                         module-level constant.
#   * live/wf (1.5):      docs/SPRINT_PLAN_C8_LIVE_INCUBATION_2026-04-26.md.
DEFAULT_BRIER_MAX = 0.22
DEFAULT_ECE_MAX = 0.05
DEFAULT_FDR_Q = 0.05
DEFAULT_PSR_MIN = 0.95
DEFAULT_MINTRL_MAX_YEARS = 2.0
DEFAULT_PSI_MAX = 0.25
DEFAULT_LIVE_VS_WF_RATIO_MAX = 1.5
# Lower sanity-floor on live/wf Brier ratio. A live calibration that is
# more than ~20x better than walk-forward is statistically suspicious
# (data-leakage, lookahead bias, regime-fit artefact). Surfaced via the
# dedicated ``suspicious_too_good`` warning check (visible but
# non-blocking) so an operator can investigate without blocking
# otherwise-passing promotions on a single suspicious ratio.
DEFAULT_LIVE_VS_WF_RATIO_MIN = 0.05
# Sprint W1.a additions — conservative starting thresholds; tighten when
# the corresponding sprint modules publish their own constants.
#   psi_slope: per-period PSI drift slope. C9.1 alarms at >0.05/period.
#   conformal_coverage_tolerance: how far observed coverage may fall
#              below ``conformal_target`` before the gate blocks.
DEFAULT_PSI_SLOPE_MAX = 0.05
DEFAULT_CONFORMAL_COVERAGE_TOLERANCE = 0.02

# GAP-4 (small-sample Brier instability). The headline Brier is a point
# estimate whose sampling distribution is wide under serial dependence at the
# few-hundred-event scale typical here (Bailey & Lopez de Prado 2012; Wilks
# 2010). The block-bootstrap CI upper bound (95th percentile of the
# stationary-block-bootstrapped Brier; see scripts/build_family_metrics.py)
# must ALSO sit under this bar, i.e. we require 95% confidence that the true
# Brier is below threshold rather than trusting a lucky point estimate. Set
# equal to the point-estimate bar by default so the whole CI must clear it.
DEFAULT_BRIER_CI_UPPER_MAX = DEFAULT_BRIER_MAX

# Out-of-range sentinel for ``GateThresholds.brier_ci_upper_max``: a Brier
# score lives in ``[0, 1]``, so a negative default unambiguously means "track
# ``brier_max``" without overloading ``None``. ``__post_init__`` resolves it to
# a concrete float, so the stored attribute is ALWAYS a plain ``float`` and no
# call site has to re-narrow ``float | None``.
_TRACK_BRIER_MAX = -1.0


@dataclass(frozen=True)
class GateThresholds:
    brier_max: float = DEFAULT_BRIER_MAX
    # Defaults to the ``_TRACK_BRIER_MAX`` sentinel so it TRACKS ``brier_max``:
    # a caller that tightens (or loosens) the point-estimate bar automatically
    # moves the CI bar with it, rather than silently leaving the CI check at
    # 0.22. Pass an explicit float to decouple the two knobs. The sentinel is
    # resolved to a concrete float in ``__post_init__``, so the stored value is
    # always a plain ``float``.
    brier_ci_upper_max: float = _TRACK_BRIER_MAX
    ece_max: float = DEFAULT_ECE_MAX
    fdr_q: float = DEFAULT_FDR_Q
    # W9-6 (SMR wave 9): number of families being evaluated simultaneously
    # in a single promotion run.  When > 1, the per-family FDR threshold is
    # tightened by Bonferroni correction to control the experiment-wide error
    # rate: effective_fdr_q = fdr_q / n_concurrent_families.  Set to 1
    # (default) to preserve the original per-family behaviour for single-
    # family evaluations or when the caller performs its own correction.
    n_concurrent_families: int = 1
    psr_min: float = DEFAULT_PSR_MIN
    mintrl_max_years: float = DEFAULT_MINTRL_MAX_YEARS
    psi_max: float = DEFAULT_PSI_MAX
    live_vs_wf_ratio_max: float = DEFAULT_LIVE_VS_WF_RATIO_MAX
    live_vs_wf_ratio_min: float = DEFAULT_LIVE_VS_WF_RATIO_MIN
    psi_slope_max: float = DEFAULT_PSI_SLOPE_MAX
    conformal_coverage_tolerance: float = DEFAULT_CONFORMAL_COVERAGE_TOLERANCE
    # Sprint W1.a: when True, missing provenance keys and missing W1.a
    # fields emit ``info`` blockers and prevent promotion. Default False
    # so legacy callers keep their existing posture; W1.b's CLI flips
    # this to True for the production pipeline.
    strict_provenance: bool = False
    # ADR-0023 Stage 2: families whose move-size resolution check is armed
    # strict *individually*. For an armed family an unmeasured
    # ``magnitude_resolution_pass`` emits a fail-closed ``info`` blocker even
    # when the gate is otherwise lax. Deliberately decoupled from
    # ``strict_provenance`` so arming one family's magnitude floor can never
    # co-trigger the unrelated ``provenance.*`` / W1.a missing-field blockers
    # (ADR-0016 no-ML waiver interactions stay untouched). Populated from
    # ``governance/magnitude_stage_policy.json`` by the production CLI.
    magnitude_strict_families: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        # Couple the Brier CI bar to the point-estimate bar unless the caller
        # explicitly set it. The sentinel resolves to ``brier_max`` here so the
        # default-construction posture is unchanged; this only ensures a
        # ``brier_max`` override flows through to the CI check too, and leaves
        # the stored attribute a plain ``float``.
        if self.brier_ci_upper_max == _TRACK_BRIER_MAX:
            object.__setattr__(self, "brier_ci_upper_max", self.brier_max)


@dataclass
class FamilyMetrics:
    """Per-family snapshot consumed by the consolidator.

    Any field set to ``None`` is treated as "check not yet available":
    the consolidator emits an ``info``-severity blocker AND counts the
    check as failing, so promotion is blocked until the metric is
    actually measured. ``info`` distinguishes "missing" from a real
    threshold breach (which uses ``blocker``) but it does not relax the
    promotion contract — a partially measured family is never promoted.

    Sprint W1.a additions (``regime_degraded``, ``psi_slope``,
    ``conformal_coverage``/``conformal_target``, ``provenance``) are
    only enforced when ``GateThresholds.strict_provenance`` is True,
    so existing legacy snapshots stay valid.
    """

    family: EventFamily
    brier: float | None = None
    # GAP-4: 95th-percentile upper bound of the block-bootstrapped Brier.
    # Enforced like the W1.a metrics: once measured a breach always blocks;
    # when unmeasured it only blocks under strict_provenance.
    brier_ci_upper: float | None = None
    ece: float | None = None
    fdr_pvalue: float | None = None
    psr: float | None = None
    mintrl_years: float | None = None
    psi: float | None = None
    live_brier: float | None = None
    walkforward_brier: float | None = None
    # W1.a: C5.1 regime degradation flag. True → hard blocker.
    regime_degraded: bool | None = None
    # W1.a: C9.1 PSI-trend slope. Compared against psi_slope_max.
    psi_slope: float | None = None
    # W1.a: C10.1 conformal coverage. Compared against conformal_target
    # with conformal_coverage_tolerance slack.
    conformal_coverage: float | None = None
    conformal_target: float | None = None
    # ADR-0023: additive tier-2 move-size sizing qualifier. ``True`` = the v1
    # score cleared the pre-registered §2 resolution bar for this family;
    # ``False`` = it did not (hard blocker on ``magnitude_resolution_floor``);
    # ``None`` = not yet measured (non-blocking unless strict). ``magnitude_auc``
    # is the score-alone OOS AUC, surfaced for transparency only.
    magnitude_resolution_pass: bool | None = None
    magnitude_auc: float | None = None
    # W1.a: non-numeric hardening metadata (wf_scheme, bootstrap_method,
    # psr_method, ...). Keys listed in REQUIRED_PROVENANCE_KEYS are
    # required under strict mode.
    provenance: dict[str, ProvenanceValue] = field(default_factory=dict)
    extras: dict[str, float] = field(default_factory=dict)


def _check(
    *,
    name: str,
    observed: float | None,
    threshold: float,
    lower_is_better: bool,
    blockers: list[Blocker],
    metrics: dict[str, float],
    label: str | None = None,
) -> bool:
    """Run a single threshold check; mutate blockers/metrics; return ok-flag."""
    label = label or name
    if observed is None:
        # ``observed`` is ``None`` (not NaN) so the Decision payload stays
        # safe to serialize with ``json.dumps(..., allow_nan=False)``,
        # which is the policy used by every downstream consumer.
        blockers.append({
            "check": name,
            "severity": "info",
            "observed": None,
            "threshold": threshold,
            "message": f"{label} not yet measured",
        })
        return False
    metrics[label] = float(observed)
    ok = (observed <= threshold) if lower_is_better else (observed >= threshold)
    if not ok:
        direction = "<=" if lower_is_better else ">="
        blockers.append({
            "check": name,
            "severity": "blocker",
            "observed": float(observed),
            "threshold": float(threshold),
            "message": f"{label}={observed:.4f} fails {direction} {threshold:.4f}",
        })
    return ok


def _emit(
    blockers: list[Blocker],
    *,
    check: str,
    severity: BlockerSeverity,
    observed: float | None,
    threshold: float,
    message: str,
) -> None:
    """Append a Blocker with the given severity. F-009: deduplicates the
    per-severity dict construction so the warning/blocker/info call sites
    (especially the live-vs-wf branch) share one constructor."""
    blockers.append({
        "check": check,
        "severity": severity,
        "observed": observed,
        "threshold": float(threshold),
        "message": message,
    })


def _posture(blockers: Iterable[Blocker]) -> Posture:
    """Map blocker severities to a four-step traffic light.

    Any ``info`` severity (missing metric) blocks promotion in
    ``evaluate``, so posture must downgrade to at least ``yellow`` to
    avoid the contradictory ``posture='green'`` + ``promoted=False``
    output that an ``info`` blocker would otherwise produce.
    """
    sev = [b["severity"] for b in blockers]
    n_blocker = sev.count("blocker")
    n_warning = sev.count("warning")
    n_info = sev.count("info")
    if n_blocker >= 2:
        return "red"
    if n_blocker == 1:
        return "orange"
    if n_warning >= 1 or n_info >= 1:
        return "yellow"
    return "green"


class PromotionGate:
    """Consolidator over per-sprint gate checks.

    Usage::

        gate = PromotionGate()
        decision = gate.evaluate(FamilyMetrics(
            family="BOS", brier=0.18, ece=0.03, fdr_pvalue=0.01,
            psr=0.97, mintrl_years=1.4, psi=0.12,
            live_brier=0.20, walkforward_brier=0.18,
        ))
        if decision["promoted"]:
            ...
    """

    def __init__(self, thresholds: GateThresholds | None = None) -> None:
        self.thresholds = thresholds or GateThresholds()

    def evaluate(self, snapshot: FamilyMetrics) -> Decision:
        t = self.thresholds
        blockers: list[Blocker] = []
        metrics: dict[str, float] = {}

        ok_brier = _check(
            name="brier_threshold",
            observed=snapshot.brier,
            threshold=t.brier_max,
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="brier",
        )
        # GAP-4: block-bootstrap Brier CI upper bound. Once measured, a CI that
        # pokes above the bar always blocks (serial-dependence-aware evidence
        # that the true Brier may exceed threshold). When unmeasured it only
        # blocks under strict_provenance so legacy snapshots stay valid.
        # ``brier_ci_upper_max`` is resolved to a concrete float in
        # ``__post_init__`` (the ``_TRACK_BRIER_MAX`` sentinel is coupled to
        # ``brier_max`` there), so it is always a plain float here.
        if snapshot.brier_ci_upper is None:
            if t.strict_provenance:
                blockers.append({
                    "check": "brier_ci_upper",
                    "severity": "info",
                    "observed": None,
                    "threshold": float(t.brier_ci_upper_max),
                    "message": "brier_ci_upper not yet measured",
                })
                ok_brier_ci = False
            else:
                ok_brier_ci = True
        else:
            ok_brier_ci = _check(
                name="brier_ci_upper",
                observed=snapshot.brier_ci_upper,
                threshold=t.brier_ci_upper_max,
                lower_is_better=True,
                blockers=blockers,
                metrics=metrics,
                label="brier_ci_upper",
            )
        ok_ece = _check(
            name="ece_threshold",
            observed=snapshot.ece,
            threshold=t.ece_max,
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="ece",
        )
        ok_fdr = _check(
            name="fdr_significance",
            observed=snapshot.fdr_pvalue,
            # W9-6 (SMR wave 9): apply Bonferroni correction when
            # multiple families are evaluated concurrently. With k families
            # the Bonferroni-adjusted threshold is fdr_q / k, which controls the
            # family-wise error rate (FWER) at level fdr_q regardless of
            # the number of simultaneous tests. n_concurrent_families=1
            # (default) leaves the threshold unchanged.
            threshold=t.fdr_q / max(t.n_concurrent_families, 1),
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="fdr_pvalue",
        )
        ok_psr = _check(
            name="psr_minimum",
            observed=snapshot.psr,
            threshold=t.psr_min,
            lower_is_better=False,
            blockers=blockers,
            metrics=metrics,
            label="psr",
        )
        ok_mintrl = _check(
            name="mintrl_horizon",
            observed=snapshot.mintrl_years,
            threshold=t.mintrl_max_years,
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="mintrl_years",
        )
        ok_psi = _check(
            name="psi_drift",
            observed=snapshot.psi,
            threshold=t.psi_max,
            lower_is_better=True,
            blockers=blockers,
            metrics=metrics,
            label="psi",
        )

        # Live-vs-WF ratio: classifies the input shape *before* delegating
        # the arithmetic, so each pathological case maps to a distinct
        # severity instead of a single info-blocker for everything that
        # isn't the happy path. The arithmetic for the happy path is still
        # delegated to ``scripts.forward_test_tracking.expected_vs_realized_ratio``
        # so PromotionGate and the C8.1 forward-test tracker share one
        # implementation.
        #
        # Severity map (Brier is mathematically in [0, 1]):
        #   live or wf missing      → info     (not measured yet, blocks)
        #   live or wf non-finite   → blocker  (data_integrity_violation)
        #   wf <= 0                 → blocker  (invalid ratio denominator)
        #   wf > 0, ratio > MAX     → blocker  (threshold breach)
        #   wf > 0, ratio < MIN     → warning  (suspicious_too_good, non-blocking)
        #   otherwise               → ok
        #
        # ``warning`` is the only severity here that does NOT flip
        # ``ok_live``; everything else blocks promotion.
        from scripts.forward_test_tracking import expected_vs_realized_ratio

        live = snapshot.live_brier
        wf = snapshot.walkforward_brier
        if live is None or wf is None:
            blockers.append({
                "check": "live_vs_wf_ratio",
                "severity": "info",
                "observed": None,
                "threshold": float(t.live_vs_wf_ratio_max),
                "message": "live or walkforward brier not yet measured",
            })
            ok_live = False
        elif not (math.isfinite(live) and math.isfinite(wf)):
            blockers.append({
                "check": "live_vs_wf_ratio",
                "severity": "blocker",
                "observed": None,
                "threshold": float(t.live_vs_wf_ratio_max),
                "message": (
                    "live_vs_wf_ratio data_integrity_violation: "
                    "non-finite live or walkforward brier (NaN/Inf)"
                ),
            })
            ok_live = False
        elif wf <= 0.0:
            blockers.append({
                "check": "live_vs_wf_ratio",
                "severity": "blocker",
                "observed": None,
                "threshold": float(t.live_vs_wf_ratio_max),
                "message": (
                    f"live_vs_wf_ratio data_integrity_violation: "
                    f"walkforward_brier={wf:.4f} <= 0 makes live/wf ratio invalid"
                ),
            })
            ok_live = False
        else:
            # wf > 0 — happy path, ratio is well-defined
            ratio = expected_vs_realized_ratio(live, wf)
            if ratio is None:  # defensive: should be unreachable after pre-classification
                raise RuntimeError(
                    "expected_vs_realized_ratio returned None despite "
                    f"pre-classified finite live/wf inputs (live={live!r}, wf={wf!r})"
                )
            metrics["live_vs_wf_ratio"] = float(ratio)
            if ratio > t.live_vs_wf_ratio_max:
                blockers.append({
                    "check": "live_vs_wf_ratio",
                    "severity": "blocker",
                    "observed": float(ratio),
                    "threshold": float(t.live_vs_wf_ratio_max),
                    "message": (
                        f"live/wf brier ratio={ratio:.2f} exceeds "
                        f"{t.live_vs_wf_ratio_max:.2f}"
                    ),
                })
                ok_live = False
            elif ratio < t.live_vs_wf_ratio_min:
                blockers.append({
                    "check": "suspicious_too_good",
                    "severity": "warning",
                    "observed": float(ratio),
                    "threshold": float(t.live_vs_wf_ratio_min),
                    "message": (
                        f"live_vs_wf_ratio suspicious_too_good: "
                        f"ratio={ratio:.4f} below {t.live_vs_wf_ratio_min:.2f} "
                        "(live calibration suspiciously better than walkforward)"
                    ),
                })
                ok_live = True  # warning does not block
            else:
                ok_live = True

        for k, v in snapshot.extras.items():
            metrics[f"extra.{k}"] = float(v)

        # ---- W1.a additions ----------------------------------------------
        provenance_out = dict(snapshot.provenance)

        # C5.1 regime degradation: True is always a hard blocker; None is
        # only blocking when strict_provenance is on.
        if snapshot.regime_degraded is True:
            metrics["regime_degraded"] = 1.0
            blockers.append({
                "check": "regime_degraded",
                "severity": "blocker",
                "observed": 1.0,
                "threshold": 0.0,
                "message": "C5.1 regime stratifier flagged this family as degraded",
            })
            ok_regime = False
        elif snapshot.regime_degraded is None:
            if t.strict_provenance:
                blockers.append({
                    "check": "regime_degraded",
                    "severity": "info",
                    "observed": None,
                    "threshold": 0.0,
                    "message": "regime_degraded not yet measured",
                })
                ok_regime = False
            else:
                ok_regime = True
        else:
            metrics["regime_degraded"] = 0.0
            ok_regime = True

        # ADR-0023: additive move-size resolution floor. A family is move-size
        # sizeable only if the v1 score cleared the pre-registered §2 bar
        # (AUC floor + bootstrap CI + permutation-null resolution). Additive to
        # ``brier_threshold`` — direction stays guarded, this never lowers a bar.
        #
        # Stage 2 (per-family arming): a family in
        # ``magnitude_strict_families`` is fail-closed on a *missing*
        # measurement even when the gate is otherwise lax. Only this branch
        # consults the armed set — it cannot affect any other check.
        magnitude_armed = snapshot.family in t.magnitude_strict_families
        if snapshot.magnitude_resolution_pass is None:
            if t.strict_provenance or magnitude_armed:
                blockers.append({
                    "check": "magnitude_resolution_floor",
                    "severity": "info",
                    "observed": None,
                    "threshold": 1.0,
                    "message": (
                        "magnitude_resolution not yet measured"
                        + (
                            " (family armed strict — ADR-0023 Stage 2)"
                            if magnitude_armed
                            else ""
                        )
                    ),
                })
                ok_magnitude = False
            else:
                ok_magnitude = True
        elif snapshot.magnitude_resolution_pass:
            metrics["magnitude_resolution_pass"] = 1.0
            if snapshot.magnitude_auc is not None:
                metrics["magnitude_auc"] = float(snapshot.magnitude_auc)
            ok_magnitude = True
        else:
            metrics["magnitude_resolution_pass"] = 0.0
            if snapshot.magnitude_auc is not None:
                metrics["magnitude_auc"] = float(snapshot.magnitude_auc)
            blockers.append({
                "check": "magnitude_resolution_floor",
                "severity": "blocker",
                "observed": 0.0,
                "threshold": 1.0,
                "message": "family does not clear the ADR-0023 §2 move-size "
                           "resolution bar",
            })
            ok_magnitude = False

        # C9.1 PSI-trend slope.
        if snapshot.psi_slope is None:
            if t.strict_provenance:
                blockers.append({
                    "check": "psi_slope_threshold",
                    "severity": "info",
                    "observed": None,
                    "threshold": float(t.psi_slope_max),
                    "message": "psi_slope not yet measured",
                })
                ok_psi_slope = False
            else:
                ok_psi_slope = True
        else:
            ok_psi_slope = _check(
                name="psi_slope_threshold",
                observed=snapshot.psi_slope,
                threshold=t.psi_slope_max,
                lower_is_better=True,
                blockers=blockers,
                metrics=metrics,
                label="psi_slope",
            )

        # C10.1 conformal coverage vs target.
        if snapshot.conformal_coverage is None or snapshot.conformal_target is None:
            if t.strict_provenance:
                blockers.append({
                    "check": "conformal_coverage",
                    "severity": "info",
                    "observed": (
                        None
                        if snapshot.conformal_coverage is None
                        else float(snapshot.conformal_coverage)
                    ),
                    "threshold": (
                        0.0
                        if snapshot.conformal_target is None
                        else float(snapshot.conformal_target)
                    ),
                    "message": "conformal coverage or target not yet measured",
                })
                ok_conformal = False
            else:
                ok_conformal = True
        else:
            metrics["conformal_coverage"] = float(snapshot.conformal_coverage)
            metrics["conformal_target"] = float(snapshot.conformal_target)
            floor = (
                float(snapshot.conformal_target)
                - float(t.conformal_coverage_tolerance)
            )
            if snapshot.conformal_coverage < floor:
                blockers.append({
                    "check": "conformal_coverage",
                    "severity": "blocker",
                    "observed": float(snapshot.conformal_coverage),
                    "threshold": float(floor),
                    "message": (
                        f"conformal coverage={snapshot.conformal_coverage:.4f} "
                        f"fails >= target {snapshot.conformal_target:.4f} - "
                        f"tolerance {t.conformal_coverage_tolerance:.4f}"
                    ),
                })
                ok_conformal = False
            else:
                ok_conformal = True

        # Required provenance keys. Only enforced in strict mode; in lax
        # mode the keys are surfaced verbatim into Decision.provenance.
        if t.strict_provenance:
            # ADR-0016: a recognised no-ML pipeline class waives the
            # ML-modelling keys (they are not-applicable, not missing). An
            # absent or unknown class grants no waiver.
            no_ml_class = provenance_out.get(PIPELINE_CLASS_KEY) in NO_ML_PIPELINE_CLASSES

            def _required(key: str) -> bool:
                # ADR-0016: ML-modelling keys are not-applicable (not required)
                # for a declared no-ML pipeline class; all other keys stay
                # required for every class.
                return not (no_ml_class and key in ML_MODELLING_PROVENANCE_KEYS)

            for key in REQUIRED_PROVENANCE_KEYS:
                if key in provenance_out or not _required(key):
                    continue
                blockers.append({
                    "check": f"provenance.{key}",
                    "severity": "info",
                    "observed": None,
                    "threshold": 0.0,
                    "message": f"provenance.{key} not declared",
                })
            ok_provenance = all(
                key in provenance_out or not _required(key)
                for key in REQUIRED_PROVENANCE_KEYS
            )
        else:
            ok_provenance = True

        promoted = all(
            (
                ok_brier,
                ok_brier_ci,
                ok_ece,
                ok_fdr,
                ok_psr,
                ok_mintrl,
                ok_psi,
                ok_live,
                ok_regime,
                ok_magnitude,
                ok_psi_slope,
                ok_conformal,
                ok_provenance,
            )
        )
        decision: Decision = {
            "schema_version": DECISION_SCHEMA_VERSION,
            "family": snapshot.family,
            "promoted": promoted,
            "posture": _posture(blockers),
            "blockers": blockers,
            "metrics": metrics,
            "provenance": provenance_out,
        }
        return decision

    def audit(self, decision: Decision) -> str:
        """Human-readable single-string summary for dashboards / logs."""
        head = (
            f"[{decision['posture'].upper()}] {decision['family']} "
            f"{'PROMOTED' if decision['promoted'] else 'BLOCKED'}"
        )
        if not decision["blockers"]:
            return head
        lines = [head]
        for b in decision["blockers"]:
            lines.append(f"  - {b['severity']}/{b['check']}: {b['message']}")
        return "\n".join(lines)


__all__ = [
    "DECISION_SCHEMA_VERSION",
    "DEFAULT_BRIER_CI_UPPER_MAX",
    "DEFAULT_CONFORMAL_COVERAGE_TOLERANCE",
    "DEFAULT_PSI_SLOPE_MAX",
    "ML_MODELLING_PROVENANCE_KEYS",
    "NO_ML_PIPELINE_CLASSES",
    "PIPELINE_CLASS_KEY",
    "REQUIRED_PROVENANCE_KEYS",
    "SMC_DIRECT_NO_ML",
    "FamilyMetrics",
    "GateThresholds",
    "PromotionGate",
]
