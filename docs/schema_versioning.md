# Schema Versioning Policy

## Canonical Source

The single source of truth for the SMC schema version is:

```
smc_core/schema_version.py → SCHEMA_VERSION
```

Every module that needs the schema version **must** import it from there.
Defining a local constant or hardcoding a string literal is forbidden — the
enforcement test `test_no_local_schema_version_constant` will catch violations.

## Semver Rules

| Bump   | When                                   | Example                                      |
| ------ | -------------------------------------- | -------------------------------------------- |
| PATCH  | Internal-only (docs, refactors)        | Fixed docstring in layering — no payload diff |
| MINOR  | Additive, backwards-compatible fields  | Added `liquidity_heat` field to snapshot      |
| MAJOR  | Breaking change requiring consumer fix | Renamed `bos` → `break_of_structure`          |

## How to Bump

1. Edit `smc_core/schema_version.py` — change `SCHEMA_VERSION`.
2. Update **all** spec examples: `spec/examples/smc_snapshot_*.json` must carry the new version.
3. Run `pytest tests/test_smc_schema_version_enforcement.py -v` to confirm.
4. If adding new fields (minor bump), update the JSON schemas in `spec/` if needed.
5. Document the change in `CHANGELOG.md`.

### What the tests enforce

| Test | Catches |
|------|---------|
| `test_schema_version_is_valid_semver` | Malformed version string |
| `test_schema_version_importable_from_smc_core` | Missing re-export |
| `test_no_local_schema_version_constant` | Duplicate definitions in producers |
| `test_spec_example_uses_current_schema_version` | Stale spec examples (all `smc_snapshot_*.json` files) |
| `test_apply_layering_emits_schema_version` | Missing version in snapshot factory |
| `test_snapshot_serialization_includes_schema_version` | Missing version in serialized output |
| `test_no_hardcoded_stale_schema_versions_in_tests` | Hardcoded old versions in test fixtures |

### Rules for test fixtures

- **Always import** `from smc_core.schema_version import SCHEMA_VERSION` — never hardcode a version string.
- **Test helpers** in `tests/helpers/smc_test_artifacts.py` already use the constant. Prefer those helpers.
- **Inline JSON** in tests: use `json.dumps({"schema_version": SCHEMA_VERSION, ...})` instead of triple-quoted JSON strings with hardcoded versions.

### Version history

| Version | Commit | Changes |
|---------|--------|---------|
| 1.0.0 | `0dff8eff` | Initial: SmcSnapshot with structure, meta (volume, technical, news), layered |
| 1.1.0 | `e49a51f5` | Schema versioning enforcement, semver utilities (no contract change) |
| 1.2.0 | `65bb2238` | Meta enrichment: event_risk, enriched_news, market_regime, new ReasonCodes |

## Compatibility Check

The `is_compatible(producer, consumer)` function determines whether a producer's
output can be read by a consumer:

- Same major version **and** producer minor ≥ consumer minor → compatible
- Different major → incompatible
- Producer minor < consumer minor → incompatible (consumer expects fields the producer doesn't emit)

```python
from smc_core.schema_version import SCHEMA_VERSION, is_compatible

# consumer code
if not is_compatible(artifact["schema_version"], SCHEMA_VERSION):
    raise ValueError(f"Incompatible schema: got {artifact['schema_version']}, need {SCHEMA_VERSION}")
```

## Files That Reference SCHEMA_VERSION

All of these import from `smc_core.schema_version`:

- `smc_core/__init__.py` (re-export)
- `smc_core/layering.py` (snapshot construction)
- `smc_integration/structure_batch.py` (artifact + manifest dicts)
- `smc_integration/batch.py` (batch manifest)
- `scripts/export_smc_structure_artifact.py` (producer payload)
- `scripts/generate_smc_micro_profiles.py` (micro profile metadata)
- `tests/helpers/smc_test_artifacts.py` (test fixture helpers)

Do **not** add `SCHEMA_VERSION = "..."` anywhere else.

## Workflow Governance Decision Flow

The CI workflow (`smc-library-refresh.yml`) uses `scripts/smc_version_governance.py`
to make an automated governance decision after every library regeneration.

### Decision matrix

| schema\_version change | library\_field\_version change | export field count change | Decision | Action |
|------------------------|-------------------------------|--------------------------|----------|--------|
| unchanged              | unchanged                     | unchanged                | auto-commit | Normal publish path |
| patch                  | unchanged                     | unchanged                | auto-commit | Normal publish path |
| minor                  | unchanged                     | unchanged                | auto-commit | Additive fields — consumers ignore extras |
| major                  | *any*                         | *any*                    | PR required | Auto-commit blocked; operator review |
| *any non-major*        | **changed**                   | *any*                    | PR required | Escalated — field layout changed without major bump |
| *any non-major*        | unchanged                     | **changed**              | PR required | Escalated — export count mismatch detected |

### Normal publish (auto-commit allowed)

This is the default 4×/day automation path:

1. Workflow generates the library with current enrichment data.
2. Evidence gates pass.
3. `smc_version_governance.py` runs → exit code 0.
4. Library is published to TradingView.
5. Version bump + commit + push happen automatically.
6. Signal alerts are evaluated and sent.

No operator action needed.

### Breaking-change publish (PR required)

When the governance check returns exit code 1:

1. Workflow generates the library.
2. Evidence gates pass.
3. `smc_version_governance.py` runs → exit code 1 (breaking).
4. **Auto-commit, publish, and alerts are all blocked.**
5. Telegram notification sent with the reason.
6. Artifacts are archived (dated snapshot) and uploaded as CI artifacts.

**Operator steps to resolve:**

1. Review the governance decision: `artifacts/ci/version_governance_YYYY-MM-DD.json`.
2. Review the library diff: `artifacts/ci/library_diff_YYYY-MM-DD.patch`.
3. Confirm the breaking change is intentional.
4. Create a PR with the schema version bump (edit `smc_core/schema_version.py`).
5. Update spec examples and `CHANGELOG.md`.
6. Run `pytest tests/test_smc_schema_version_enforcement.py -v` locally.
7. After PR review and merge, the next scheduled run will auto-commit normally.

### Manifest governance metadata

Every generated manifest now includes:

```json
{
  "schema_version": "1.2.0",
  "schema_version_previous": "1.1.0",
  "version_change_type": "minor",
  "auto_commit_allowed": true,
  "library_field_version": "v4"
}
```

| Field | Description |
|-------|-------------|
| `schema_version` | Current version from `smc_core.schema_version.SCHEMA_VERSION` |
| `schema_version_previous` | Version from the manifest that was overwritten (empty on first run) |
| `version_change_type` | Semver transition: `initial`, `unchanged`, `patch`, `minor`, `major` |
| `auto_commit_allowed` | Whether the automation path may auto-commit |
| `library_field_version` | Pine export field layout version (e.g. `"v4"`) |
