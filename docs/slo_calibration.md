# SLO — Calibration Quality (Plan §3.1.2)

> **Status:** Documentation seam · UI banner ready · auto-trigger wiring pending live CI artifact stream
> **Owner:** SMC scorer + dashboard
> **Last reviewed:** 2026-04-21

This document defines the Service-Level Objective for the SMC calibration
metrics produced by `smc_core.calibration_metrics` and consumed by the
public Hero one-liner.

The objective is intentionally **observable from the surface**: a user
looking at the dashboard must be able to tell whether the calibration is
within SLO without leaving TradingView.

## Objective

The smooth Expected Calibration Error
([Błasiok & Nakkiran 2023, smECE](https://arxiv.org/abs/2309.12236))
of the published scorer, computed on the rolling-30-day measurement
window, MUST satisfy:

```
smECE_30d ≤ 0.12
```

A continuous breach (3 consecutive measurement runs above the threshold)
triggers the **CAL-BREACH** mitigation pipeline below.

> Why smECE and not classical binned ECE? smECE is a *consistent* estimator
> (Błasiok–Nakkiran §3) that does not depend on a bin grid, so it cannot
> hide a calibration drift inside a single bucket. The classical 10-bin
> ECE is still computed and published as a legacy reference field, but is
> not the SLO target.

## Secondary indicators (informational, no SLO trigger)

| Metric | Reference | Reported field | Healthy band |
|---|---|---|---|
| Distance-to-Calibration (dCE) | [Rossellini 2025](https://arxiv.org/abs/2502.19851) | `calibration_report.dce` | ≤ 0.06 |
| Brier score | Brier 1950 | `benchmark.brier_score` | ≤ 0.15 |
| Sample size | n/a | `calibration_report.n_samples` | ≥ 300 events |

dCE measures whether the predictor is *calibratable* under any monotone
re-mapping; a high dCE next to a low smECE indicates the surface is on
the calibratable manifold but coincidentally well-aligned at the
reporting moment — a reason to investigate even without a hard SLO trigger.

## Mitigation pipeline (CAL-BREACH)

When the SLO is breached for 3 consecutive measurement runs:

1. **Surface signal.** The dashboard `Calibration Breach Banner` input
   flips to `true`, and the Hero one-liner appends a `⚠CAL-BREACH` token
   if the user has wired the BLOCKER token (already the default token
   order). Operators see the breach without leaving TradingView.

2. **Trust degradation.** The hero `mp.HERO_TRUST` field downgrades to
   `degraded` until the next clean run. This is consumed by the
   existing tier colouring (`CLR_TIER_T3`) — no new code path.

3. **Notification.** A GitHub issue is opened by the measurement workflow
   with the failing report attached. The issue carries the
   `slo:cal-breach` label so it can be tracked separately from
   functional bugs.

4. **Operator playbook.** Investigate in the order:
   * symbol-level smECE drift (which symbol moved? — check the
     stratified report from `smc_core.benchmark.stratified_fvg_report`),
   * sample size collapse (did upstream data ingest break?),
   * weight-drift gate state (did the calibrated weights freeze?),
   * if none above, escalate to a recalibration run.

## Reporting cadence

* **Per-run:** every measurement workflow execution writes
  `calibration_report.json` with all three metric families. The CI
  fast-gate fails the run if `smECE > 0.20` (hard ceiling, separate
  from the rolling SLO).
* **Daily:** the rolling-30-day smECE is recomputed and published as
  `calibration_report_public.json` (Plan §3.1.1).
* **Monthly:** SLO summary report in `docs/slo_reports/YYYY-MM.md`
  (Plan §3.1.2 — generation script lands once daily artifacts have
  accumulated 30 days of history).

## Public anchoring

The calibration SHA is exposed via the `Calibration SHA` dashboard
input. When set and the `SHA` token is added to `Hero Token Order`,
the Hero one-liner emits `sha:<7chars>` so a screenshot stays
SHA-anchored — the operator can cross-reference any reported metric
against a specific report version (Plan §3.1.1 + §3.1.3).

## Open hooks (intentionally not wired yet)

* Auto-flip of `calibration_breach_banner` based on the daily SLO
  computation. Today the banner is operator-controlled; the auto-trigger
  arrives when the daily artifact stream is live (Plan W14–W15).
* `dCE` SLO gate — currently informational only. Promotion to a binding
  SLO is contingent on observing how the metric behaves over a full
  rolling-90-day window (Plan W17–W19).

## References

* Błasiok, J., & Nakkiran, P. (2023). *Smooth ECE: Principled Reliability
  Diagrams via Kernel Smoothing.* arXiv:2309.12236.
* Rossellini, R., et al. (2025). *Testable and Actionable Calibration:
  A Distance-to-Calibration Framework.* arXiv:2502.19851.
* Plan §3.1.1 (Open Calibration Report), §3.1.2 (Continuous Calibration
  SLO), §3.1.3 (Testable Calibration Adoption).
