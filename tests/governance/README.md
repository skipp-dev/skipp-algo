# `tests/governance/` — Cross-surface contract gates

Tests in this folder are **governance gates**: they pin the shape of
contracts that cross module boundaries (Python ↔ Pine ↔ Streamlit ↔
generated JSON). A failure here is almost always a design signal —
"did you update every consumer?" — not a code bug.

## `test_boundary_vocab_fingerprint.py`

Closes HIGH-Finding **H-4** from `SMC_SYSTEM_REVIEW_2026-04-24`.

Pins the valid string values for every `HERO_*` and `SMC_BUS` vocabulary
in one snapshot (`vocab_fingerprint.json`). A rename or addition fails
the test and prints the list of consumer surfaces that must be updated
in the same PR.

### Run

```bash
pytest tests/governance/ -v
```

### Add a new vocabulary field

1. Add a `VocabEntry(...)` row to `VOCAB_REGISTRY` — list every
   downstream consumer surface (Pine files, Streamlit widgets, docs).
2. Regenerate the snapshot:
   ```bash
   python tests/governance/test_boundary_vocab_fingerprint.py --regenerate-snapshot
   ```
3. Update each consumer surface listed in step 1, **in the same PR**.
4. Commit `vocab_fingerprint.json` alongside your code change.

### Rename an existing vocabulary value

Same as above. The test will fail until the snapshot is regenerated,
which forces a reviewer to see the diff.

### Why two layers (values + SHA-256)

- **Values** tell you *what* changed — the diff is inline in the
  assertion message, and reviewers can eyeball the delta.
- **Fingerprint** is a single hash you can grep for in Pine or Streamlit
  code to confirm the consumer was bumped in lock-step.

### Consumer surfaces tracked

| Vocabulary | Surfaces |
|---|---|
| `HERO_FIELD_NAMES` | `scripts/generate_smc_micro_profiles.py:1046-1052`, `SMC_Dashboard.pine`, `SMC_Mobile_Dashboard.pine`, `streamlit_terminal.py`, `docs/BOUNDARY_CONTRACT.md` |
| `HERO_TRUST_VOCAB` | `SMC_Dashboard.pine:1753,1768,1774`, `SMC_Mobile_Dashboard.pine:50,55`, `smc_integration.trust_state` |
| `HERO_SETUP_QUALITY_VOCAB` | `SMC_Dashboard.pine` (SetupQuality tinting), `scripts/smc_hero_setup_quality.py` |
| `HERO_ACTION_VOCAB` | `SMC_Dashboard.pine` (~line 1728), `scripts/smc_hero_state._derive_hero_action`, `scripts/smc_hero_action._ACTION_TABLE` |
| `HERO_QUALITY_A_TO_B` | Producer-A ↔ Producer-B bridge |
| `ENGINE_BUS_CHANNELS` (ordered) | `SMC_Core_Engine.pine` plot block — plot order is load-bearing |
| `EXECUTABLE_BUS_CHANNELS` | `SMC_Long_Strategy.pine`, `smc_strategy_router` |
| `LITE_BUS_CHANNELS`, `LITE_SURFACE_BUS_CHANNELS`, `PRO_ONLY_BUS_CHANNELS` | Tier dashboards |
| `C9_*_BUS_CHANNELS` | ADR-0001 Structure Contract Normalization partitioning |
| `DASHBOARD_GROUP_TITLES*`, `STRATEGY_GROUP_TITLES*` | Pine group() rendering |

### Relationship to existing boundary tests

- `tests/test_smc_bus_manifest_contract.py` — pins the manifest ↔ Pine
  plot binding shape (different axis: binding order + group mapping).
- `tests/test_pine_boundary_literals.py` — pins that specific Pine
  string literals exist in specific files.
- `tests/test_smc_core_engine_semantic_contract.py` — pins Pine-side
  semantic dependencies.

Vocab-Fingerprint adds the missing axis: the **closed set of valid
values** each vocabulary may take. The three tests together cover
"which names exist", "where they are used", and "what values they can
contain".
