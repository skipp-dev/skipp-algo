# SMC Field Consumer Governance

> Created: 2026-04-17 · WP-2E
> Scope: `pine/generated/smc_micro_profiles_generated.pine` (auto-generated library)

## Purpose

Every exported field in the generated micro-profiles library adds compile cost,
cognitive load, and maintenance surface. This document establishes lifecycle
rules so the library stays lean and every field earns its place.

---

## Field Inventory (as of WP-2C audit)

| Category                        | Fields | Notes                          |
|---------------------------------|-------:|--------------------------------|
| **Total exported**              |    289 |                                |
| Active (≥1 Pine consumer)       |    175 | 60.6 %                        |
| Orphaned (0 Pine consumers)     |    108 | 37.0 % — reduction candidates  |
| Deprecated + orphaned           |     63 | safe to sunset                 |
| Deprecated + still consumed     |     95 | migrate consumers first        |
| Non-deprecated orphaned         |     51 | classify or adopt              |

### Fully Dead Deprecated Sections (0 consumers)

| Section                  | Fields | Generator Tag               |
|--------------------------|-------:|-----------------------------|
| Order Blocks v5.2        |     13 | `order_blocks_v52`          |
| Zone Projection v5.2     |     10 | `zone_projection_v52`       |
| Session Structure v5.3   |     14 | `session_structure_v53`     |
| Range Regime v5.3        |     11 | `range_regime_v53`          |
| Range Profile Regime v5.3|     22 | `range_profile_regime_v53`  |
| **Total**                | **70** |                             |

These are listed in `DEPRECATED_COMPATIBILITY_GROUPS` in
`scripts/generate_smc_micro_profiles.py` and marked with
`// ORPHANED — no Pine consumer, sunset candidate` in the generated output.

---

## Lifecycle Rules

1. **New field → must have a named consumer.**
   Every field added to the generator must reference the Pine file(s) that will
   `import` and read it. If no consumer exists at merge time, the field is not
   exported.

2. **Consumer removed → field gets `ORPHANED` marker.**
   When a Pine consumer drops a field reference, the generator section header is
   updated to include `ORPHANED`. The field stays exported for one schema version
   bump to allow rollback.

3. **Orphaned + one version → move to `DEPRECATED_COMPATIBILITY_GROUPS`.**
   After the grace period the section is added to the sunset list. The generator
   still emits the field (with a comment) but it is a deletion candidate.

4. **Deprecated past sunset date → remove from generator.**
   When `smc_bus_manifest.DEPRECATED_FIELD_POLICY.sunset_date` is reached, the
   section is deleted from `write_pine_library()` and the corresponding
   `smc_*.py` module can be archived.

5. **Phantom consumers are bugs.**
   References that only exist in test fixtures (not production Pine) do not
   count as consumers. The WP-2C audit found 6 such phantom references in
   `SMC_Core_Engine.pine` (`UNIVERSE_TICKERS`, `NEWS_CATEGORY_MAP`, etc.).
   These must be fixed or removed.

---

## Tooling

| Tool                                | Purpose                        |
|-------------------------------------|--------------------------------|
| `pine_input_surface.py audit`       | Count inputs, groups, hidden % |
| `pine_apply_surface_reduction.py`   | Bulk-apply display.none + group|
| `test_generate_smc_micro_profiles`  | Seed-reference drift detection |

---

## QuickALGO Input Surface (WP-2A/2B summary)

| Metric                | Before | After  |
|-----------------------|-------:|-------:|
| Total inputs          |    336 |    336 |
| Grouped               |    120 |    336 |
| Hidden (display.none) |      0 |    301 |
| Visible core inputs   |    336 |   **35** |
| Groups                |     13 |     35 |

89.6 % of inputs are now expert-only (hidden). The 35 visible inputs cover
config, engine, entry gates, risk management, structure, session, and display.
