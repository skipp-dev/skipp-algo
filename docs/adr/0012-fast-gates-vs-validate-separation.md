# ADR-0012: `fast-gates` vs `validate` job separation policy

| Field      | Value                                                                 |
|------------|-----------------------------------------------------------------------|
| Status     | Proposed                                                              |
| Date       | 2026-05-30                                                            |
| Deciders   | skipp-dev                                                             |
| Related    | `.github/workflows/smc-fast-pr-gates.yml`, `.github/workflows/ci.yml`, branch protection on `main` |

## Context

CI on PRs runs two main pytest passes:

- **`fast-gates`** (≤ 8 min target): pin-ledger drift, structural
  invariants, smoke imports. Required by branch protection.
- **`validate`** (≥ 10 min): the full test suite (~600 tests +
  property-based + integration). Not required by branch protection
  today.

In practice both jobs run **most of the same tests** (ledger tests
appear in both via the default test collection). Observed today:
- #2452 failed `fast-gates` on `test_workflow_upload_artifact_uniform_version`
- #2451 failed `validate` on `test_noqa_budget`
- #2453 failed both on the same `test_urllib_urlopen_ledger`

This is duplicative compute (~7 min × 2 = ~14 min per PR head SHA)
and confusing signal (which job *should* have caught what?).

## Decision drivers

- **PR cycle time**: every duplicate test adds ~50 ms × 600 = ~30 s
  per run; the structural overhead (uv setup, dependency install,
  coverage) is ~3 min per job.
- **Required-check semantics**: branch protection requires `fast-gates`
  only. The pin-ledger class of regressions is what blocks PRs daily;
  this strongly suggests those *belong* in `fast-gates`.
- **`validate` value-add**: today it mostly re-runs `fast-gates` plus
  property-based and integration tests. Stripping the overlap would
  make `validate` a true "additional confidence" gate.

## Options

### Option A — Status quo (both jobs run the full suite)
Pros: belt-and-braces; impossible to forget a category. Cons: 2×
compute, ambiguous signal.

### Option B — `fast-gates` = pin-ledgers + structural; `validate` = everything else
Disjoint test selection via pytest markers (`@pytest.mark.fast_gate`)
or a `tests/fast_gates/` subfolder. Branch protection requires both
(after ADR-0011 resolution).

Pros: zero duplicate runtime; clear "*who caught what*". Cons: needs
marker hygiene; tests that are *both* a ledger pin and an integration
check (e.g. workflow-contract tests) need a clear home.

### Option C — `fast-gates` = subset of fastest tests; `validate` = full
Keep `validate` as the truth source; `fast-gates` runs a curated
quick-fail subset. Both still pass through `pytest`.

Pros: drop-in; no marker churn. Cons: subset drift; new tests default
to neither category clearly.

### Option D — Single CI job with two stages
Collapse to one job with `pytest --maxfail=N` early-fail on the ledger
class and full pass after. Required check is one.

Pros: simplest mental model. Cons: loses parallel execution; total
clock time on green runs goes up.

## Decision

*(pending operator)*

## Consequences

- B is the clean answer if marker discipline can be enforced (a small
  meta-test that asserts every test file is in exactly one bucket).
- C is the cheap incremental step.
- D simplifies the matrix but slows green PRs.
- Whichever path, this ADR must be resolved before "*activate
  `validate` as required check*" (Operator-Punkt 1) is acted on.
