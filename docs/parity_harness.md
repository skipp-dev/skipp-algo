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
# Run all 217 parity tests
pytest tests/test_smc_parity.py -v

# Run a specific parity layer
pytest tests/test_smc_parity.py::TestCanonicalToBridgeParity -v
pytest tests/test_smc_parity.py::TestBridgeToPineParity -v
pytest tests/test_smc_parity.py::TestTvEncodingParity -v
pytest tests/test_smc_parity.py::TestFixtureFamilyPresence -v
pytest tests/test_smc_parity.py::TestPineRequiredFields -v
pytest tests/test_smc_parity.py::TestSnapshotContract -v

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

Nine synthetic bar datasets in `tests/parity/fixtures.py`:

| Fixture         | Pattern                              | Primary Target          | Families Produced           |
|-----------------|--------------------------------------|-------------------------|-----------------------------|
| `bullish_bos`   | Steady uptrend with pullbacks        | BOS UP                  | 4 BOS, 3 FVG               |
| `bearish_bos`   | Steady downtrend with bounces        | BOS DOWN                | 4 BOS, 3 FVG               |
| `orderblock`    | Two-candle displacement patterns     | Orderblocks (BULL+BEAR) | 3 OB, 1 BOS, 2 FVG         |
| `fvg`           | Gapped candle sequences              | FVG (BULL+BEAR)         | 2 FVG                       |
| `sweep`         | Pivot3 levels + spike-and-reverse    | Sweeps (BUY+SELL)       | 2 sweeps, 1 OB, 1 FVG      |
| `mixed`         | Multi-phase with all families        | All families populated  | BOS, OB, FVG, sweeps        |
| `trending_30d`  | Uptrend with pullbacks (30 bars)     | BOS + FVG               | 6 BOS, 5 FVG               |
| `reversal_30d`  | Up then down (30 bars)               | CHOCH + sweeps          | 5 BOS, 3 FVG, 8 sweeps     |
| `flat_20d`      | Range-bound (20 bars)                | Empty (zero events)     | —                           |

Each targeted fixture has an entry in `EXPECTED_FAMILIES` that declares which
families it *must* produce. `TestFixtureFamilyPresence` enforces these guards.

## File Layout

```
tests/
  parity/
    __init__.py
    fixtures.py         # deterministic bar generators + EXPECTED_FAMILIES
    normalization.py    # approved field-drop rules + TV decoders + required fields
    report.py           # standalone parity report utility
  test_smc_parity.py    # 217 pytest tests (7 classes × 9 fixtures)
docs/
  parity_harness.md     # this file
```

## Test Classes

| Class                        | Tests | What it verifies                                              |
|------------------------------|-------|---------------------------------------------------------------|
| `TestCanonicalToBridgeParity`| 45    | Canonical dict → bridge `SmcStructure` exact field match      |
| `TestBridgeToPineParity`     | 54    | Bridge snapshot → pine payload (sans style) + coverage flags  |
| `TestTvEncodingParity`       | 36    | Pipe-encoded strings decode back to canonical values          |
| `TestFixtureFamilyPresence`  | 9     | Each fixture produces its declared minimum families           |
| `TestPineRequiredFields`     | 36    | Every pine entity has all required fields                     |
| `TestSnapshotContract`       | 36    | schema_version, symbol/timeframe roundtrip, dir normalization |
| `test_parity_report_all_pass`| 1     | Full parity report produces zero drift                        |

## Required Pine Payload Fields

Defined in `tests/parity/normalization.py`:

| Entity           | Required fields                              |
|------------------|----------------------------------------------|
| BOS              | `id`, `time`, `price`, `kind`, `dir`, `style`|
| Orderblock       | `id`, `low`, `high`, `dir`, `valid`, `style` |
| FVG              | `id`, `low`, `high`, `dir`, `valid`, `style` |
| Liquidity sweep  | `id`, `time`, `price`, `side`, `style`       |

If the pine adapter adds a new field, it must be added to the required-field
set or the parity test will flag it as coverage gap.

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

## Boundary Summary

```
┌─────────────────────────────────────────────────────────────────┐
│  REPO CI (automated, deterministic)                             │
│                                                                 │
│  bars → canonical → bridge → layering → pine payload → TV enc  │
│         ├─ parity ─┤         ├─ parity ─┤  ├─ roundtrip ─┤    │
│         ├─ fields ─┤         ├─ fields ─┤                      │
│         ├─ schema_version ──────────────┤                      │
│         └─ dir/kind/side normalization ─┘                      │
│                                                                 │
│  9 fixtures × 7 test classes = 217 tests                        │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  SMOKE / PREFLIGHT (manual or semi-automated)                   │
│                                                                 │
│  • TradingView Pine runtime rendering                           │
│  • Live /smc_tv endpoint liveness                               │
│  • Visual overlay spot-checks                                   │
└─────────────────────────────────────────────────────────────────┘
```
