# SMC Review & Remediation Plan

## Goal

Establish a safety net of golden fixtures, regression tests, and contract
assertions **before** any refactoring or redesign of the SMC bridge layer.
This lets future changes prove — via CI — whether they intentionally alter
behaviour or accidentally break consumers.

## Scope

| Area | What's covered |
|---|---|
| `/smc_snapshot` endpoint | Required top-level keys, per-family field shapes |
| `/smc_tv` endpoint | Required keys, pipe-encoding format (`time\|price\|dir`, etc.) |
| `build_explicit_structure_from_bars()` | Canonical structure families (`bos`, `orderblocks`, `fvg`, `liquidity_sweeps`), id-prefix conventions, `producer_debug` keys |
| Mock snapshot | Contract parity with the real builder |

## Phase Order

1. **Phase 0 (this PR)** — golden fixtures + regression tests. No production
   code changes. Purely additive.
2. **Phase 1** — address any contract mismatches found during Phase 0
   (rename stale keys, unify enum values, etc.). Each change must be
   accompanied by a fixture update + green tests.
3. **Phase 2** — consolidate duplicate logic (e.g. mock vs. real snapshot
   builders sharing the same shape helper). Guard with the regression suite.

## How to Run the Regression Checks

```bash
# just the bridge regression suite
pytest tests/test_smc_bridge_regression.py -v

# all SMC-related tests (broader sanity)
pytest tests/ -k "smc" -v

# full suite (before pushing)
pytest tests/ -v
```

## Assumptions

- Golden fixtures use **fixed timestamps** (not `time.time()`), so they are
  deterministic and diffable.
- The mock snapshot builder (`_mock_snapshot`) is treated as a first-class
  contract holder — if it diverges from the real builder's shape, that's a
  regression.
- Pipe-encoding format for `/smc_tv` is locked at: `time|price|dir` (BOS),
  `low|high|dir|valid` (OB/FVG), `time|price|side` (sweeps).

## Files Added

| File | Purpose |
|---|---|
| `tests/fixtures/golden_smc_snapshot.json` | Golden /smc_snapshot response |
| `tests/fixtures/golden_smc_tv.json` | Golden /smc_tv response |
| `tests/fixtures/golden_canonical_structure.json` | Golden canonical structure output |
| `tests/fixture_helpers.py` | `load_fixture()` + `assert_keys_subset()` |
| `tests/test_smc_bridge_regression.py` | 17 regression tests |
| `docs/smc_review_remediation_plan.md` | This document |
