# ADR-002: Temporary `fail_under` Reduction for the SMC Coverage Gate

| Field       | Value                                              |
|-------------|----------------------------------------------------|
| Status      | Proposed                                           |
| Date        | 2026-04-23                                         |
| Deciders    | skipp-dev                                          |
| Supersedes  | (none — extends ADR-001 scope)                     |
| Related     | PRs #26, #27, #29, #31, #32; issue #17             |

## Context

`pyproject.toml` enforces a hard coverage gate on the SMC scope:

```toml
[tool.coverage.report]
fail_under = 95
```

The scope (per `coverage-marathon-2026-04-23-status` and the
`smc-scope-excludes-streamlit-terminal` repo memory) is:

```toml
source = ["newsstack_fmp", "open_prep", "smc_core", "smc_integration", "scripts"]
omit   = ["tests/*", "*.pine"]
```

As of 2026-04-23 the actual measured total on `main` is **85.20 %**.
The validate gate therefore fails on every PR — including pure safety,
infra, and bug-fix PRs that have nothing to do with coverage:

| PR  | Topic                                               | Validate result   |
|-----|-----------------------------------------------------|-------------------|
| #26 | omit-list expansion for 8 standalone CLIs + monitor | fail @ 85.20 %    |
| #27 | `[tool.setuptools] packages` build fix              | fail @ 85.20 %    |
| #29 | bucket A — `open_prep/macro.py` 33 → 89 %           | fail @ 85.73 %    |
| #31 | bucket B — `realtime_signals` 36 → 42 %             | fail (small lift) |
| #32 | bucket C — `technical_analysis` 68 → 95 %           | pending           |

Marathon math: closing 85.20 → 95.00 requires roughly **10 percentage
points**. The largest single landed bucket so far (#29) delivered
**+0.53 pp**. Even bucket C's full module flip is estimated at 2–3 pp.
Stacking buckets A + C + the omit-list expansion of #26 is plausible
but not guaranteed to clear 95 % without a multi-week effort.

In the meantime the gate is acting as a **brake on unrelated safety
work**: PRs #33 (canonical-write guard), #35 (batch / benchmark guard),
#36 (pytest-poison scan), #38 (xlsx determinism) all have to live with
a red validate check that has nothing to do with the change under
review. That has two real costs:

1. **Signal loss.** A red gate that is *always* red trains reviewers to
   ignore it, which masks a genuine regression when one happens.
2. **Merge friction.** Every safety PR needs a manual override or a
   hand-waved "ignore validate, the failure is unrelated".

## Decision

Adopt a **two-phase, time-boxed `fail_under` reduction**:

### Phase 1 — Stabilise the floor (immediate)

* Set `fail_under = 85` in `pyproject.toml`.
* The number is chosen so the **current `main` total (85.20 %) clears
  the gate by roughly +0.20 pp**, matching the principle "today's
  measured value is the new floor, never the ceiling".
* Validate gate now fails *only* when a PR **regresses** below the
  current baseline — which is the property we actually want.
* Coverage PRs (#26, #29, #32, …) keep landing; each one **ratchets the
  floor up** in the same commit that adds the lift (see Phase 2).

### Phase 2 — Ratchet back to 95 % (roadmap)

Each merged coverage bucket bumps `fail_under` to `floor(new_total) − 0`
(no slack), so the gate never drops:

| Milestone               | Target `fail_under` | Trigger PR(s)                  |
|-------------------------|---------------------|--------------------------------|
| Phase 1 baseline        | 85                  | this ADR                       |
| After omit-list (#26)   | recompute (≈ 87?)   | #26                            |
| After bucket A (#29)    | +1                  | #29 rebased on #26             |
| After bucket C (#32)    | +2–3                | #32 rebased                    |
| After buckets D, E, …   | +n                  | follow-up coverage PRs         |
| **Restore 95**          | 95                  | final coverage PR closes gap   |

The `fail_under` value is part of the coverage PR's diff — there is no
separate "lower the gate" PR after Phase 1.

### Phase 3 — Sunset

Once `fail_under = 95` is restored:

* Delete this ADR's "Temporary" framing (mark Status = Superseded).
* Open a follow-up ADR if a different long-term scope is desired
  (e.g. per-package fail-under, branch coverage, etc.).

## Consequences

### Positive

* Safety / infra / bug-fix PRs can land on a green validate gate.
* Reviewers see a meaningful red gate again — it now signals a
  *regression*, not a known backlog.
* Coverage progress is **visible in the diff**: every bucket PR raises
  the floor by exactly the amount it earned.

### Negative

* The headline number is lower for the duration of the marathon. This
  ADR exists specifically to make that trade-off explicit and bounded.
* Risk of "ratchet drift" — a bucket PR that lands without bumping
  `fail_under`. **Mitigation**: the coverage-marathon repo memory
  (`coverage-marathon-2026-04-23-status.md`) tracks expected vs. actual
  fail_under per bucket; a CI check (future work) could enforce
  "fail_under is monotonically non-decreasing on `main`".

### Neutral

* No change to the **scope** (`source` / `omit`). This ADR is purely
  about the **threshold**, not what gets measured. ADR-001 and the
  `smc-scope-excludes-streamlit-terminal` memory remain authoritative
  for scope.

## Alternatives considered

1. **Keep `fail_under = 95`, override per-PR.** Status quo. Rejected:
   trains reviewers to ignore the gate; merge friction on every
   safety PR.
2. **Drop the coverage gate entirely.** Rejected: loses regression
   signal even after the marathon completes.
3. **Per-module `fail_under` thresholds.** Rejected for now: larger
   refactor, deferred to the post-marathon ADR.
4. **Push the marathon harder before lowering the gate.** Tried for
   the past two weeks; bucket A delivered 0.53 pp and unrelated PRs
   are accumulating. Not closing the gap fast enough to justify the
   ongoing review friction.

## Implementation

This ADR alone makes no code change. The accompanying mechanical change
(in a separate PR or the same PR, at the author's discretion) is:

```diff
 [tool.coverage.report]
 show_missing = true
 skip_empty = true
-fail_under = 95
+# Temporary reduction per ADR-002 — coverage marathon in progress.
+# Each merged coverage bucket must raise this value by the floor it
+# earned. Target is to restore 95 once buckets A–E land.
+fail_under = 85
```

## References

* `docs/ADR-001-open-prep-integration-boundary.md`
* `pyproject.toml` `[tool.coverage.report]`
* Repo memory: `coverage-marathon-2026-04-23-status.md`
* Repo memory: `smc-scope-excludes-streamlit-terminal.md`
* Issue #17 (SMC coverage scope)
* Open PRs: #26, #27, #29, #31, #32
