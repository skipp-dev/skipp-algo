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
2. Update `spec/examples/smc_snapshot_aapl_15m_normal.json` to match.
3. Run `pytest tests/test_smc_schema_version_enforcement.py -v` to confirm.
4. If adding new fields (minor bump), update the JSON schemas in `spec/` if needed.
5. Document the change in `CHANGELOG.md`.

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
