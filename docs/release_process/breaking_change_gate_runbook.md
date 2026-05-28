# Breaking-Change Gate Runbook

## Purpose

The `smc-library-refresh.yml` workflow includes a **breaking-change governance
gate** (`scripts/smc_version_governance.py`) that fail-closes any auto-commit
when the regenerated Pine library would constitute a breaking change without
an explicit `SCHEMA_VERSION` bump.

This runbook documents how to read the gate's decision and resolve it.

## Symptom

Workflow run finishes with `success` (the gate is *not* a job failure) but
the publish/commit steps were **skipped**. In the workflow log:

```
Detect library changes -> Library content changed -> proceeding to publish
Evaluate version governance -> Breaking change detected -- auto-commit blocked.
  reasons: [
    "export field count changed: N -> N+M",
    "escalated to MAJOR: field layout changed without schema_version major bump"
  ]
Publish library to TradingView -> SKIPPED
Bump library version -> SKIPPED
Commit and push changes -> SKIPPED
```

## How the gate decides

`scripts/smc_version_governance.py:124-129` escalates a `MINOR` semver delta
to `MAJOR` when **either** of the following is true *without* an explicit
`SCHEMA_VERSION` MAJOR bump:

- `field_count_changed` — the regenerated library exports more (or fewer)
  fields than the committed one
- `field_version_changed` — the per-field version stamp drifted

`scripts/smc_core/schema_version.py:auto_commit_allowed()` then returns
`False` for `MAJOR`, which is what blocks the publish/commit steps.

## Decision tree

```
Did the field count change between committed and regenerated library?
├─ YES → Bump SCHEMA_VERSION MAJOR (X+1.0.0) — see "Resolution: MAJOR" below.
│       The governance gate (smc_version_governance.py:123) escalates ANY
│       field-count delta — including purely additive ones — to MAJOR
│       unless SCHEMA_VERSION carries a MAJOR bump. A MINOR bump is NOT
│       sufficient and will be rejected with
│       "escalated to MAJOR: field layout changed without schema_version
│       major bump" (see audit-correction on issue #16, issue #22).
└─ NO  → Did `field_version` (per-family stamp) change?
        ├─ YES → MINOR bump is sufficient — see "Resolution: MINOR" below.
        └─ NO  → Likely a manifest-only change; PATCH or no bump.
```

## Resolution: MINOR (additive metadata only)

Reserved for `field_version` per-family stamp changes that do NOT alter the
export field count. A new top-level export field always requires MAJOR
(see Decision tree).

1. Edit `smc_core/schema_version.py`:
   ```python
   SCHEMA_VERSION = "X.Y+1.0"  # bump MINOR, reset PATCH
   ```
   Add a comment block above the constant explaining the addition.

2. Update inline test fixtures with the new version (the enforcement test
   `tests/test_smc_schema_version_enforcement.py::test_no_hardcoded_stale_schema_versions_in_tests`
   will tell you exactly which lines):
   ```bash
   for f in tests/test_smc_*.py tests/fixtures/generated_showcase/showcase_manifest.json; do
     sed -i '' 's/"schema_version": "X\.Y\.Z"/"schema_version": "X.Y+1.0"/g' "$f"
   done
   ```

3. Update spec examples:
   ```bash
   sed -i '' 's/"schema_version": "X\.Y\.Z"/"schema_version": "X.Y+1.0"/' spec/examples/smc_snapshot_*.json
   ```

4. Regenerate the seed fixture so it matches what the workflow will emit:
   ```bash
   python3 -m scripts.refresh_generated_artifacts
   ```

5. Local verification:
   ```bash
   python -m pytest tests/test_smc_version_governance.py \
                    tests/test_smc_schema_version_enforcement.py \
                    tests/test_zone_priority_calibration.py -q
   ```

6. Commit + push + open PR. Once merged on `main`, the next scheduled
   `smc-library-refresh.yml` run will see the bump, classify the change as
   `MINOR`, and proceed with publish/commit.

## Resolution: MAJOR (breaking OR field-count change)

Used when fields are added, renamed, removed, or change semantics — i.e.
any time the export field count changes, **including purely additive new
fields** (the gate does not distinguish additive vs. destructive).

1. Bump `SCHEMA_VERSION` MAJOR: `X+1.0.0`
2. Update all Pine consumers that reference the changed fields (see
   `scripts/smc_zone_priority_consumer.py` for the canonical list)
3. Repeat MINOR steps 2-5
4. Special: open a `breaking-change` labelled PR; do **not** rely on the
   automatic refresh-workflow to propagate the change

### Worked example (issue #22, ZONE_CAL_TRUST add)

Field count grew 200 → 201 (new `ZONE_CAL_TRUST` string export). PR #18
tried MINOR (2.0.0 → 2.1.0); refresh-run #24807633995 rejected with:

```
export field count changed: 200 → 201; escalated to MAJOR: field layout
changed without schema_version major bump
```

Resolution: bump to `3.0.0` and re-run refresh.

## Verification: did the gate pass?

After the bump-PR merges, watch the next `smc-library-refresh.yml` run.
Look for:

```
Evaluate version governance -> Change classified as MINOR (allowed)
Publish library to TradingView -> success
Bump library version -> success
Commit and push changes -> success
```

If the gate still blocks, re-read the `reasons` array — there may be
additional drift you missed.

## Operator workflow with auto-PR (since PR #2415, F-V8-N1)

Before #2415 the workflow silently skipped publish/commit steps when the
gate fired — runs stayed green and no human got notified. Three bumps
(`v5.5b → v5.5c → v6.0a → v7.0a`) stacked up over five weeks before the
loophole was spotted. The current workflow now:

1. Annotates the run with `::error file=…,title=Breaking change blocks publish`
   plus a Before/After table in `$GITHUB_STEP_SUMMARY`.
2. Drops `artifacts/ci/release_pending.flag` as a sticky artifact.
3. Opens a `bot/library-release-pending-<RUN_ID>` PR labelled
   `release-pending` + `breaking-change` + `automated`, carrying the
   regenerated `pine/generated/` artifacts.
4. Gates all downstream publish steps on a single `publish_allowed` output
   from the `Compute publish gate` step.
5. Honors the `allow_breaking_publish=true` `workflow_dispatch` input —
   only on `refs/heads/main` — as the explicit operator override.

### Operator checklist (after seeing a blocked refresh run)

1. Review the auto-opened `bot/library-release-pending-*` PR. Verify the
   bump is intentional (compare `library_field_version` old → new in
   `artifacts/ci/version_governance_<DATE>.json`).
2. Merge the release-pending PR. This documents the bump for downstream
   reviewers; it does NOT publish to TradingView on its own.
3. Re-run `smc-library-refresh.yml` via `workflow_dispatch` with
   `allow_breaking_publish=true`. The override is only honored on
   `refs/heads/main` (defence-in-depth: schedule + workflow_run runs can
   never publish a breaking change silently).
4. Confirm the publish step succeeded (`Publish library to TradingView`
   shows `success`, `artifacts/tradingview/library_release_manifest.json`
   reflects the new `publishedVersion`).
5. Open the consumer-import bump PR — see next section.

## Consumer-import bump (after a successful republish)

When TradingView's `publishedVersion` ticks up (e.g. `1 → 2`), all Pine
consumers of the `preuss_steffen/smc_micro_profiles_generated` library
must update their import line. Use the existing helper:

```bash
# From repo root, AFTER the TV publish succeeded:
./scripts/bump_pine_library_import.sh 1 2
```

**Namespace note:** `SMC_Hold_Manager.pine` imports
`skippALGO/smc_micro_profiles_generated/1` from a **separate, manually
managed TradingView namespace** (documented in
`scripts/smc_bus_manifest.py:333`). It is intentionally excluded from
the auto-bump workflow + this helper. If the `skippALGO` library is
ever republished, bump it explicitly:

```bash
./scripts/bump_pine_library_import.sh 1 2 skippALGO/smc_micro_profiles_generated
```

The helper is idempotent — running it twice is safe.

Verify only `import` lines changed before committing:

```bash
git diff -U0 -- '*.pine' | grep -E '^[-+]' | grep -v '^[-+]import' | head
# (should be empty)
git add -u && git commit -m "chore(pine): bump smc_micro_profiles_generated import /1 -> /2"
```

Open as a separate PR (label `pine-consumer-bump`). This is the
follow-up to issue [#59](https://github.com/skippALGO/skipp-algo/issues/59).

## References

- `scripts/smc_version_governance.py:124-129` — escalation logic
- `smc_core/schema_version.py` — semver policy + `SCHEMA_VERSION` constant
- `smc_core/schema_version.py:69` — `auto_commit_allowed()`
- `tests/test_smc_version_governance.py` — gate behavior pin tests
- `tests/test_smc_schema_version_enforcement.py` — enforcement of inline pins
- `scripts/bump_pine_library_import.sh` — consumer-import bump helper
- Issue [#16](https://github.com/skippALGO/skipp-algo/issues/16) — first
  documented production trigger of this gate (Phase-H ZONE_CAL_TRUST)
- Issue [#59](https://github.com/skippALGO/skipp-algo/issues/59) — consumer-import
  bump follow-up
- PR [#2415](https://github.com/skippALGO/skipp-algo/pull/2415) — F-V8-N1
  auto-PR + override + error-annotation surface
- `.github/workflows/smc-library-refresh.yml` — workflow that runs the gate
