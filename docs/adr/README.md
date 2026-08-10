# ADR Index

This directory contains the Architecture Decision Records (ADRs) for the
SkippAlgo repository. Each ADR captures the *context*, *decision*, and
*consequences* of a single architecturally significant choice. ADRs are
**append-only** — to revise a decision, add a new ADR that supersedes the
old one and update the table below.

## Status legend

- **Accepted** — in force, enforced by tests/CI where applicable.
- **Superseded** — kept for history; replaced by a newer ADR.
- **Proposed** — draft under discussion; not yet enforced.

## Index

| #    | Title | Status | Date | Enforced by |
| ---- | ----- | ------ | ---- | ----------- |
| 0001 | [Structure contract normalization](0001-structure-contract-normalization.md) | Accepted | 2026-Q1 | `tests/test_smc_structure_contract_*.py` |
| 0002 | [Promotion eligibility policy](0002-promotion-eligibility-policy.md) | Accepted | 2026-Q1 | `tests/test_smc_promotion_*.py` |
| 0003 | [Pine legacy physical-move resolver](0003-pine-legacy-physical-move-resolver.md) | Accepted | 2026-Q1 | `tests/test_pine_*.py` |
| 0004 | [Resilient vs circuit-breaker](0004-resilient-vs-circuit-breaker.md) | Accepted | 2026-Q1 | runtime resiliency layer |
| 0005 | [Pure-stdlib measurement runtime](0005-pure-stdlib-measurement-runtime.md) | Accepted | 2026-04 | `tests/test_adr_0005_pure_stdlib_runtime.py` + `tests/test_check_adr_0005_pure_stdlib_cli.py` |
| 0006 | [HERO Vocab Discipline](0006-hero-vocab-discipline.md) | Accepted | 2026-04-24 | `tests/test_hero_observed_vocab_pin.py` |
| 0007 | [HERO Field Invariants](0007-hero-field-invariants.md) | Accepted | 2026-04-24 | `tests/test_hero_risk_vocab_and_reachability_pin.py`, `tests/test_hero_schema_fingerprint.py` |
| 0008 | [PromotionGate threshold origins and recalibration policy](0008-promotion-gate-thresholds.md) | Accepted | 2026-05-17 | `governance/promotion_gate.py` (constants); ADR is doc-only |
| 0009 | [Pin-ledger consolidation vs. per-domain ledger files](0009-pin-ledger-consolidation.md) | Accepted (B) | 2026-05-30 | `pin_registry.toml` + `tests/_pin_registry.py` |
| 0010 | [Cron-workflow invariants — per-workflow contract tests vs. generative suite](0010-cron-workflow-invariants-suite.md) | Accepted (C) | 2026-05-30 | `tests/test_cron_workflow_invariants.py` |
| 0011 | [Auto-merge + admin-bypass pattern for single-developer PRs](0011-auto-merge-admin-bypass-pattern.md) | Accepted (C) | 2026-05-30 | `scripts/verify_branch_protection.py` + `tests/test_verify_branch_protection.py` (branch-protection: required-reviews disabled, `fast-gates` required) |
| 0012 | [`fast-gates` vs `validate` job separation policy](0012-fast-gates-vs-validate-separation.md) | Accepted (B) | 2026-05-30 | `@pytest.mark.slow` (`conftest.py`) + `tests/_fast_inventory.py` |
| 0013 | [Atomic vs cross-cutting workflow PRs](0013-atomic-vs-cross-cutting-workflow-prs.md) | Accepted (C) | 2026-05-30 | `scripts/check_pr_title_concern.py` + `.github/workflows/pr-title-concern-lint.yml` (PR-title convention `concern(scope): …`) |
| 0014 | [EV#6 PSI-trend source and EV#7 regime-degradation source](0014-ev6-psi-trend-source-and-ev7-regime-deferral.md) | Accepted | 2026-06-02 | `governance/family_calibration.py`, `governance/family_event_score.py`, `governance/family_returns.py` |
| 0015 | [Edge proof and calibration are separate promotion tiers](0015-edge-vs-calibration-promotion-tiers.md) | Accepted (decision) | 2026-06-02 | (implementation staged: tiered `risk_sizeable` in `governance/family_verdict.py`; no gate code changed by the ADR) |
| 0016 | [Aggressor-signed order-flow data path for microstructure shadow features](0016-orderflow-aggressor-datapath.md) | Proposed (data-path scope; `williams_vix_fix` candidate **retired** — see ADR-0026) | 2026-06-03 | doc-only (scopes the data path for the ADR-0019 shadow-feature workstream; no code changed) |
| 0016 | [Pipeline-provenance classes (no-ML pipelines)](0016-pipeline-provenance-classes.md) | Accepted | 2026-06-02 | number collision with the order-flow data-path ADR above; both keep their slot per the no-renumber rule |
| 0017 | [Live-incubation surrogate for offline backtests (live-vs-WF)](0017-live-incubation-surrogate.md) | Accepted | 2026-06-02 | live-vs-walk-forward incubation surrogate |
| 0018 | [Split-conformal coverage from walk-forward OOS pairs](0018-split-conformal-coverage.md) | Accepted | 2026-06-02 | conformal coverage from WF OOS pairs |
| 0019 | [Multi-feature family score v2 (meta-label) — order-flow-led resolution](0019-multi-feature-family-score-v2.md) | Superseded by ADR-0026 (OHLCV candidate queue **formally closed**) | 2026-06-02 | doc-only; shadow-feature A/B onramp — see [onramp saturation verdict](../governance/feature_onramp_saturation_verdict.md) |
| 0020 | [Options-flow data path — signed UOA notional as the next orthogonal shadow-feature axis](0020-options-flow-datapath.md) | Proposed | 2026-06-04 | doc-only (ranks the three new-information axes by repo maturity; scopes the options-flow data path; no code changed) |
| 0021 | [VRVP volume-profile location + Rejection Blocks as the next orthogonal shadow features](0021-smc-vrvp-rjb-shadow.md) | Proposed (draft) | 2026-06-06 | doc-only; VRVP scalars + Rejection Blocks wired recorded-only, gated on a pre-registered A/B before promotion |
| 0022 | [Joint meta-label A/B executed — direction saturated; re-target tier-2 sizing to move-size](0022-meta-label-joint-ab-and-magnitude-retarget.md) | Accepted (A/B executed; recorded — see ADR-0026) | 2026-06-05 | doc-only; executes ADR-0019's joint A/B (rejected on direction) and records the move-size re-targeting hypothesis — see [joint findings](../governance/adr0022_meta_label_joint_findings.md); tooling `governance/family_meta_label.py` + `scripts/run_meta_label_ab.py` |
| 0023 | [Pre-register the tier-2 sizing gate move-size re-target](0023-tier-2-size-gate-magnitude-retarget.md) | Accepted / Executed — Stage 1 live, Stage 2 armed (BOS/SWEEP); see ADR-0026 + [live-rollout handover](../governance/adr0023_live_rollout_handover.md) | 2026-06-05 | `governance/magnitude_resolution_gate.py` + `governance/magnitude_stage_policy.json` (was doc-only pre-registration; proof passed on real data) |
| 0024 | [Allow `--force-with-lease` on `bot/*` snapshot branches](0024-force-with-lease-allowance-bot-snapshot-branches.md) | Accepted | 2026-06-10 | `tests/test_workflow_auth_pattern.py::test_workflow_force_push_is_allowlisted` (`_FORCE_LEASE_ALLOWLIST`) |
| 0025 | [Grafana App Platform `dashboard.grafana.app/v1` publish surface (classic schema in `spec`)](0025-grafana-dashboard-apis-v1-surface-migration.md) | Accepted | 2026-06-22 | `scripts/publish_overlay_dashboard.py` + `tests/test_publish_overlay_dashboard.py` + `tests/test_live_overlay_dashboard_contract.py`; pin re-alignment per ADR-0009 |
| 0026 | [Record executed status of the tier-2 magnitude re-target + OHLCV queue closure](0026-magnitude-retarget-executed-and-ohlcv-queue-closed.md) | Accepted (records-only) | 2026-07-12 | doc-only; reconciles the index with executed ADR-0019/0022/0023 decisions + `williams_vix_fix` retirement; no code changed |
| 0027 | [Structure artifacts are runtime outputs](0027-structure-artifacts-runtime-outputs.md) | Accepted (Design B) | 2026-07-13 | structure-provider integration tests + production/release workflow availability gates |
| 0029 | [Payload volume is a first-class signal; publish gates compare field pairs](0029-payload-volume-first-class-signal.md) | Proposed | 2026-07-22 | doc-only (design); enforcement staged — see *Enforced by (planned)* in the ADR |
| 0030 | [Hosted Terminal purpose and audience — growth expected, class change gated](0030-terminal-purpose-and-audience.md) | Accepted | 2026-07-23 | invariant 3 by `tests/test_ai_defense_egress_guard.py`; invariants 1/2/4/5/6 are review-time only |
| 0031 | [Track-record returns definition and publish channel](0031-track-record-returns-definition-and-channel.md) | Accepted | 2026-07-29 | track-record and regime report producers; disclosure contract is documentation-enforced |
| 0032 | [Canonical portfolio state and projected pre-trade risk](0032-portfolio-state-and-risk-projection.md) | Accepted | 2026-08-08 | portfolio snapshot, projection and shadow evidence tests |
| 0033 | [Commercial product goal and separate customer plane](0033-commercial-product-and-customer-plane.md) | Accepted | 2026-08-10 | Phase 0 documentation; automated customer/evidence gates are planned in Phases 1–2 |

## Reservation rule

The next free ADR number is **0034**. To avoid concurrent-PR collisions:

1. Reserve the next number by opening the PR with the file already named
   (e.g. `docs/adr/0008-foo.md`) before the rebase race window closes.
2. If two PRs collide on the same number, the second to merge renames its
   ADR to the next free slot and updates this index in the same commit.
3. Superseded ADRs keep their original number — never renumber.

## Authoring guide

- Use the existing ADRs as templates. Aim for one *Decision* per ADR.
- Include a *Consequences* section (positive and negative).
- Where the ADR is *enforced* by tests, list those tests in the index
  table so reviewers can locate the guard rails quickly.
- Cross-reference related ADRs in the *Related* metadata header.
