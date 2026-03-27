# SMC Parity Harness

## What It Tests

The parity harness verifies that the three stages of the SMC pipeline
produce structurally equivalent output:

```
Canonical Python         Bridge Snapshot           TV Pine Payload
(build_explicit_         (build_structure_         (snapshot_to_pine_
 structure_from_bars)     from_raw → layering)      payload)
        │                       │                       │
        └──── parity ───────────┘                       │
                                └──── parity ───────────┘
```

### Stage 1: Canonical → Bridge
Compares each structure family (BOS, OB, FVG, sweeps) from the canonical
builder output against the typed `SmcStructure` produced by the bridge
ingest layer.

### Stage 2: Bridge → Pine Payload
Verifies that `snapshot_to_pine_payload()` emits every bridge entity with
correct fields (style is enrichment and excluded from structural comparison).

### Stage 3: TV Pipe-Encoding
Verifies that `encode_levels()`, `encode_zones()`, and `encode_sweeps()`
produce strings that decode back to the canonical structure values.

## How to Run

```bash
# Run all 46 parity tests
pytest tests/test_smc_parity.py -v

# Run a specific parity layer
pytest tests/test_smc_parity.py::TestCanonicalToBridgeParity -v
pytest tests/test_smc_parity.py::TestBridgeToPineParity -v
pytest tests/test_smc_parity.py::TestTvEncodingParity -v

# Generate human-readable parity report
python -m tests.parity.report
```

## Normalization Rules

Field differences between canonical and bridge are explicit in
`tests/parity/normalization.py`. Currently allowed drops:

| Family           | Extra canonical fields dropped at bridge |
|------------------|------------------------------------------|
| BOS              | `source`                                 |
| Orderblocks      | `anchor_ts`, `source`                    |
| FVG              | `anchor_ts`, `source`                    |
| Liquidity sweeps | `source`, `source_liquidity_id`          |

If the canonical builder adds a new field that the bridge should carry,
the parity test will fail until either:
1. The normalization rule is updated (approved drop), or
2. The bridge ingest is updated to carry the field

No fuzzy matching is used. All comparisons are exact after normalization.

## Fixtures

Three synthetic bar datasets in `tests/parity/fixtures.py`:

| Fixture         | Pattern                   | Produces                     |
|-----------------|---------------------------|------------------------------|
| `trending_30d`  | Uptrend with pullbacks    | BOS events + FVG gaps        |
| `reversal_30d`  | Up then down              | CHOCH events + sweeps        |
| `flat_20d`      | Range-bound               | Empty families (zero events) |

## File Layout

```
tests/
  parity/
    __init__.py
    fixtures.py         # deterministic bar generators
    normalization.py    # approved field-drop rules + TV decoders
    report.py           # standalone parity report utility
  test_smc_parity.py    # 46 pytest tests
docs/
  parity_harness.md     # this file
```

## CI Coverage vs. Pine Runtime

### What CI covers (automated, deterministic)

- Python canonical structure generation from synthetic bars
- Bridge ingest: canonical dict → typed `SmcStructure`
- Layering: `SmcStructure` + `SmcMeta` → `SmcSnapshot`
- Pine payload adapter: `SmcSnapshot` → JSON payload
- TV pipe-encoding: roundtrip encode/decode of all structure families
- Schema version enforcement (separate test suite)
- Provider smoke checks (live artifact health via `run_smc_ci_health_checks.py`)

### What CI does NOT cover (smoke/preflight concern)

- **Full Pine Script runtime parity**: TradingView Pine cannot be executed
  deterministically in repo CI. The Pine payload is a JSON contract consumed
  by Pine Script via `request.security()` calls. Whether Pine renders it
  correctly is a visual/runtime concern.

- **TradingView endpoint liveness**: The `/smc_tv` endpoint encodes data for
  Pine consumption. CI verifies the encoding logic but not the live endpoint.

### Recommended smoke steps for operators

1. **Pre-deploy**: Run `python -m tests.parity.report` to confirm no drift.
2. **Post-deploy**: Hit `/smc_tv?symbol=AAPL&timeframe=15m` and verify the
   response contains pipe-encoded strings with expected segment counts.
3. **Visual**: Load `SMC_Core_Engine` in TradingView, apply to a chart,
   verify BOS/OB/FVG/sweep overlays appear at expected price levels.

These smoke steps are documented but not automated — they require either
a TradingView session or a live server.
