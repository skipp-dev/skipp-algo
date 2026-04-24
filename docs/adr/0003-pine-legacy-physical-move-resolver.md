# ADR-0003: Pine Legacy Physical Move — Resolver vs. Sweep

| Field       | Value                                              |
|-------------|----------------------------------------------------|
| Status      | Proposed                                           |
| Date        | 2026-04-24                                         |
| Deciders    | skipp-dev                                          |
| Supersedes  | (none — first formal D-1 v2 design doc)            |
| Related     | [`PINE_LEGACY.md`](../../PINE_LEGACY.md), [`docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md`](../TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md) (D-1 / D-1 v2), `/memories/repo/pine-legacy-bare-name-lookup-blocker.md` |

## Context

Closes the **D-1 v2** backlog design gap. The audit
(`/Users/steffenpreuss/Downloads/TEMPORAL_NUMERICAL_AUDIT_2026-04-24.md`)
recommended `git mv`-ing the 23 legacy Pine files at the repo root into
`pine/legacy/`. Phase 1 (D-1) shipped the
[`PINE_LEGACY.md`](../../PINE_LEGACY.md) index plus a CI drift-lint
([`scripts/check_pine_legacy_drift.py`](../../scripts/check_pine_legacy_drift.py)
in [`smc-fast-pr-gates`](../../.github/workflows/smc-fast-pr-gates.yml#L71)),
which removes the *silent-drift* risk but leaves the physical move open.

When PR #110 surveyed the consumers a real architectural blocker
surfaced: three modules resolve Pine files by **bare basename**, not by
relative path:

- [`scripts/smc_bus_manifest.py`](../../scripts/smc_bus_manifest.py) —
  `SURFACE_DEFINITIONS[*].file` and `NON_SMC_PINE_FILES` frozenset
  store bare names like `'QuickALGO.pine'`.
- [`scripts/smc_file_lifecycle.py`](../../scripts/smc_file_lifecycle.py) —
  `EXPLICIT_OVERRIDES` dict and `SURFACE_MATRIX[*].name`;
  `classify_file(filename)` does dict-lookup by basename.
- [`pine_apply_surface_reduction.py`](../../pine_apply_surface_reduction.py#L569) —
  hard-codes `["QuickALGO.pine", "SkippALGO.pine", "SkippALGO_Strategy.pine"]`
  and the file-open call uses the bare name as a path.

The other consumers (`test_usi_lint.py`, README, CHANGELOG,
`docs/*.md`) are **Tier-2 mechanical sed scope** and not blockers.

## Decision drivers

1. **Atomicity** — moves must not break consumers between commits;
   either everything moves together or nothing moves.
2. **TradingView saved-script URLs** — operators have URLs pointing at
   root-level files; breakage there is silent and remote.
3. **Surface stability for consumers** — `classify_file("QuickALGO.pine")`
   is used in tests and tooling; changing the contract has wide
   blast radius.
4. **Reversibility** — if the move turns out to be wrong (e.g. one of
   the "legacy" files revives), undoing it must be cheap.

## Options

### Option A — Sweep refactor to relative paths

Change every `SURFACE_DEFINITIONS[*].file`, `EXPLICIT_OVERRIDES` key,
`SURFACE_MATRIX[*].name`, and the `pine_apply_surface_reduction.py`
list from `"QuickALGO.pine"` to `"pine/legacy/QuickALGO.pine"`.
Update `classify_file(filename)` to accept either form (or only the
relative form and force callers to migrate).

**Pros**

- Single source of truth — the path *is* the identity.
- Future moves are local to one consumer at a time.
- No magic; `open(path)` works directly.

**Cons**

- Big-bang PR: 4 modules + ~50 dict/tuple entries + every test that
  passes a basename to `classify_file` needs updating.
- Breaks the contract of `classify_file(filename)` — every caller has
  to know about the path prefix.
- Doesn't preserve the "files are identified by name across the
  product" mental model that the existing code expresses.
- TradingView saved-script URLs that bookmark `QuickALGO.pine` at the
  root *still* break (this is unavoidable for any move).

### Option B — `pine_path_resolver` shim

Add a small module `scripts/pine_path_resolver.py`:

```python
# Sketch — not committed.
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = (REPO_ROOT, REPO_ROOT / "pine" / "legacy")

def resolve_pine_file(basename: str) -> Path:
    for d in SEARCH_DIRS:
        candidate = d / basename
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Pine file not found: {basename}")
```

Every place that does `open(filename)` for a Pine file gets routed
through `resolve_pine_file()`. Bare-name lookup keys
(`SURFACE_DEFINITIONS[*].file`, `EXPLICIT_OVERRIDES`,
`SURFACE_MATRIX[*].name`) **stay unchanged**. The drift-lint
[`scripts/check_pine_legacy_drift.py`](../../scripts/check_pine_legacy_drift.py)
gets extended to scan `pine/legacy/` in addition to root.

**Pros**

- Bare-name identity preserved — `classify_file("QuickALGO.pine")`
  keeps the same contract.
- Smaller, reviewable PR: one new module, one update each in the
  three Tier-1 consumers, drift-lint extension.
- Reversible: if a file gets moved back to root, the resolver finds
  it without any consumer change.
- TradingView users with saved-script URLs at the root keep working
  *until* the file actually moves; resolver hides the detail from
  Python consumers but TV URLs still need an HTTP-301-equivalent
  (out of scope here — TV doesn't redirect).

**Cons**

- Adds an indirection layer; first-time readers have to learn about
  the resolver.
- Two valid locations for a `.pine` file (root or `pine/legacy/`) is
  a soft invariant the resolver enforces at runtime, not at type-check
  time. Mitigated by the drift-lint listing every file's expected
  location.
- Risk of name collision (a file with the same basename exists in
  both directories). Resolver should fail loudly — covered by a
  validation test.

## Decision

**Adopt Option B (resolver shim).**

Rationale:

- The bare-name identity is a deliberate design choice in
  `classify_file` and the surface matrix; preserving it is more
  faithful to the existing architecture than sweeping it away.
- Smaller blast radius makes the PR reviewable and revertible.
- The drift-lint that already exists generalizes naturally to scan
  multiple directories.
- Option A's "single source of truth" benefit is undercut by the fact
  that *the basename is already the identity in tests, generated
  manifest fixtures, and JSON artifacts*; rewriting all of those is
  out of scope for D-1 v2.

## Consequences

### What this enables (D-1 v2 PR scope)

1. New module `scripts/pine_path_resolver.py` (≈40 LOC + tests).
2. `pine_apply_surface_reduction.py` switches its `open(name)` calls
   to `open(resolve_pine_file(name))`.
3. Any other file-read call sites that take a bare basename — audit
   in the implementation PR.
4. `scripts/check_pine_legacy_drift.py` extended:
   - Index entries with `LEGACY` status MUST exist in `pine/legacy/`.
   - Index entries with active SMC-suite status MUST exist at root.
   - No basename collisions across `SEARCH_DIRS`.
5. `git mv` the 23 legacy files into `pine/legacy/`.
6. Tier-2 sed sweep: `test_usi_lint.py` default arg → use
   resolver, README/CHANGELOG/`docs/*.md` reference updates.
7. `PINE_LEGACY.md` table updated with new paths;
   `docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md` D-1 v2
   marked done.

### What stays out of scope

- No change to `SURFACE_DEFINITIONS[*].file`,
  `NON_SMC_PINE_FILES`, `EXPLICIT_OVERRIDES`, or
  `SURFACE_MATRIX[*].name` — they remain bare basenames.
- No TradingView-URL redirect — operators must update saved-script
  URLs manually after the move lands.
- No move of `test_div.pine` (test fixture) or
  `SkippALGO_Confluence.pine` (active per
  [`PINE_LEGACY.md`](../../PINE_LEGACY.md)).

### Effort estimate

≈ half-day implementation, half-day test/review.

## Verification on adoption

The implementation PR for D-1 v2 must show:

- All existing tests green without modification of consumer
  contracts (only call sites where `open()` happens get rerouted).
- New unit test: `resolve_pine_file("QuickALGO.pine")` returns the
  `pine/legacy/QuickALGO.pine` path after the move; raises
  `FileNotFoundError` for unknown files; raises (or warns) on
  duplicate-basename collision.
- Drift-lint passes against the post-move repo state.
- `PINE_LEGACY.md` `Why an index instead of git mv` section retired
  (replaced by `Why a resolver instead of relative paths`).
