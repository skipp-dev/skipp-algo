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
| 0016 | [Aggressor-signed order-flow data path for microstructure shadow features](0016-orderflow-aggressor-datapath.md) | Proposed | 2026-06-03 | doc-only (scopes the data path for the ADR-0019 shadow-feature workstream; no code changed) |

## Reservation rule

The next free ADR number is **0017**. To avoid concurrent-PR collisions:

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
