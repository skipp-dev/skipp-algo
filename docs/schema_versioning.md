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
