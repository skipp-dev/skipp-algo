# Artifact Strategy — v5.5a

**Status**: Active  
**Date**: 2026-03-30

## Two Artifact Classes

The repo maintains two distinct artifact classes:

### 1. Seed / Default Reference (committed, generator-first)

**Files**:
- `pine/generated/smc_micro_profiles_generated.pine` — generated Pine library
- `pine/generated/smc_micro_profiles_generated.json` — generation manifest

**Purpose**: Deterministic structural drift checks. These artifacts are
regenerated from the seed CSV (`tests/fixtures/seed_base_snapshot.csv`) and
contain safe defaults for all fields (`enrichment_blocks: []`, `asof_time: ""`,
`refresh_count: 0`).

**Properties**:
- All lean fields carry zero/empty/false defaults
- No enrichment data — purely structural skeleton
- Generator is sole source of truth
- Used by `test_generated_artifact_drift.py` and `test_pine_artifact_drift.py`
- Deterministic: same seed always produces identical output

### 2. Enriched Showcase Reference (fixture, hand-maintained)

**Files**:
- `tests/fixtures/reference_enrichment.json` — semantic reference fixture

**Purpose**: Product/UX/architecture review and semantic contract validation.
This fixture shows what a **realistic enriched runtime state** looks like with
plausible values across all lean blocks.

**Properties**:
- All lean field values are v5.5a contract-compliant (validated by test)
- Logically coherent scenario (bullish setup with consistent signals)
- Used by `test_pine_consumer_contract.py` (field names, allowed values, semantic coherence)
- Hand-maintained — updated when contract evolves
- NOT generated — serves as human-readable reference for what the system produces

## Why Two Classes?

| Concern | Seed Reference | Showcase Reference |
|---------|---------------|-------------------|
| Drift detection | Yes — exact byte comparison | No |
| Contract validation | Structural only | Structural + semantic |
| Generator consistency | Source of truth | Independent check |
| Realistic values | No (all defaults) | Yes (plausible scenario) |
| UX/architecture review | Limited | Full |

## Rules

1. **Generator-first**: The seed reference is always regenerated, never hand-edited
2. **showcase must pass contract**: `reference_enrichment.json` values must conform to `docs/v5_5_lean_contract.md`
3. **No third class**: Two artifact classes are sufficient. Don't add more without strong justification
4. **Test coverage**: Both classes have dedicated tests — drift tests for seed, contract tests for showcase
