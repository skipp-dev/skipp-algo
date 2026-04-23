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

## References

- `scripts/smc_version_governance.py:124-129` — escalation logic
- `smc_core/schema_version.py` — semver policy + `SCHEMA_VERSION` constant
- `smc_core/schema_version.py:69` — `auto_commit_allowed()`
- `tests/test_smc_version_governance.py` — gate behavior pin tests
- `tests/test_smc_schema_version_enforcement.py` — enforcement of inline pins
- Issue [#16](https://github.com/skippALGO/skipp-algo/issues/16) — first
  documented production trigger of this gate (Phase-H ZONE_CAL_TRUST)
- `.github/workflows/smc-library-refresh.yml` — workflow that runs the gate
