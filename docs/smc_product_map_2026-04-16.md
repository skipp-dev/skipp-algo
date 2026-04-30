# SMC Product Map — 2026-04-16

Status: **Active**
Feature Freeze: 2026-04-15 — 2026-05-15

---

## 1. What the SMC Product Is

The **SMC Long-Dip Suite v7** is a TradingView indicator system for
structured long-dip entries on US equities. It consists of:

- **One engine** (SMC_Core_Engine.pine) — the primary operator surface
- **Eight private libraries** (SMC++/) — shared types, drawing, lifecycle, BUS, profiles
- **One generated data library** (pine/generated/smc_micro_profiles_generated.pine)
- **Eleven companion indicators** — context overlays consuming the engine's BUS/library output
- **One companion strategy** (SMC_Long_Strategy.pine) — execution surface on the BUS contract

Everything else in this repository is either tooling, legacy, or historical reference.

---

## 2. Classification

### Mainline (11 files)

The core product. Changes here require compile + semantic contract tests.

| File | Type | Role |
|------|------|------|
| SMC_Core_Engine.pine | indicator | Primary engine — structure, lifecycle, hero card, alerts, BUS output |
| SMC++/smc_core_types.pine | library | Shared enums and UDTs |
| SMC++/smc_utils.pine | library | Generic helpers (range, LTF, clamping) |
| SMC++/smc_draw.pine | library | Draw wrapper types (SmcLine, SmcLabel, SmcBox) |
| SMC++/smc_bus_private.pine | library | BUS row/pack serialization |
| SMC++/smc_lifecycle_private.pine | library | Entry lifecycle status composers |
| SMC++/smc_observability_private.pine | library | Debug text composers |
| SMC++/smc_context_resolvers.pine | library | Context resolution + BUS packing |
| SMC++/smc_profile_engine.pine | library | Volume profile engine (Bucket, Profile types) |
| pine/generated/smc_micro_profiles_generated.pine | library | Generated microstructure data (~315 fields, incl. Zone Priority + Contextual Calibration) |
| pine/generated/smc_micro_profiles_core_import_snippet.pine | snippet | Import bindings for generated library |

### Companion (12 files)

Consume BUS/library output from the engine. NOT the engine itself.
Do not constitute feature gaps when they lag behind engine development.

| File | Type | Role |
|------|------|------|
| SMC_Dashboard.pine | indicator | Operator dashboard — Decision Brief, Audit View (74 rows incl. Calibration Confidence, Per-Family Performance, FVG Health) |
| SMC_Long_Strategy.pine | strategy | Execution surface — 8-channel BUS contract |
| SMC_Event_Overlay.pine | indicator | Event-risk verticals + restriction zones |
| SMC_HTF_Confluence.pine | indicator | ATR regime + reversal context scores |
| SMC_Imbalance_Context.pine | indicator | FVG zones, BPR, liquidity voids |
| SMC_Liquidity_Context.pine | indicator | S/R levels, zone bias, sweeps |
| SMC_Liquidity_Structure.pine | indicator | Sweep events, pool imbalance |
| SMC_Orderflow_Overlay.pine | indicator | Flow qualifier, delta proxy, ATS |
| SMC_Profile_Context.pine | indicator | Ticker grade, VWAP position, spread regime |
| SMC_Session_Context.pine | indicator | Session labels, killzone highlight |
| SMC_Structure_Context.pine | indicator | Structure state, CHoCH/BOS markers |
| SMC_Breakout_Overlay.pine | indicator | BOS/CHoCH breakout boxes + vol-emoji + ATR-RR W/L sim |
| SMC_VRVP_Overlay.pine | indicator | Visible-range volume profile + multi-POC (no library imports) |
| SMC_Exit_Signal.pine | indicator | Position-lifecycle SM + alertcondition() für Stop/TP1/TP2/Defensive — beginner-facing exit engine |
| Volume_Weighted_Trend_SkippAlgo.pine | indicator | Standalone branded tool (no SMC imports) |

### Operator-only (1 file)

Internal tooling. Not user-facing, not published.

| File | Type | Role |
|------|------|------|
| SMC_TV_Bridge.pine | indicator | v5, dormant backend API bridge. Core fetch code commented out |

### Legacy — QuickALGO (6 files)

Predecessor product. Superseded by SMC v7.
Active on TradingView for existing subscribers. No new development.

| File | Type | Status |
|------|------|--------|
| QuickALGO.pine | indicator | v6.3.5 — original signal engine. 336 inputs, 301 hidden (WP-2) |
| pine/skipp_math.pine | library | Math/clamping helpers |
| pine/skipp_scoring.pine | library | Trend/regime scoring |
| pine/skipp_indicators.pine | library | Zero-lag EMA variants |
| pine/skipp_calibration.pine | library | Rolling accumulators, Platt scaling |
| pine/skipp_labels.pine | library | Capped label helpers |

### Legacy — Standalone indicators (20 files)

Historical standalone scripts. Each was a development step toward the
current SMC system. Logic has been internalized or superseded.

**CHoCH family** (5) — structure detection, now in SMC Core:
- CHoCH.pine, CHOCH-Indicator.pine, CHOCH-Strategy.pine
- CHOCH-Base_Indikator.pine, CHOCH-Base_Strategy.pine

**USI family** (7) — 6-line Zero-Lag RSI stacking, partly absorbed:
- USI.pine, USI-Flip.pine, USI_Lines.pine, USI_Strategy.pine
- USI-CHOCH.pine, USI-REV-BUY.pine, REV-BUY.pine

**REV Ladder** (2) — multi-stage entry ladder:
- REV-Ladder.pine, REV-Ladder-CHoCH.pine

**BFI** (2) — breakout finder:
- Breakout_Finder_Intelligent.pine, BFI-Reversal.pine

**VWAP Reclaim** (4) — VWAP reclaim tools:
- VWAP_Reclaim_Indicator.pine, VWAP_Reclaim_Strategy.pine
- VWAP_Long_Reclaim_Indicator.pine, VWAP_Long_Reclaim_Strategy.pine

### Historical Reference (1 file)

| File | Type | Status |
|------|------|--------|
| BTC 3m EV Scalper BALANCED (Harmonized).pine | strategy | v5, BTC-specific. Asset-bound, Pine v5 |

### Test/Generated (5 files)

| File | Purpose |
|------|---------|
| test_div.pine | Trivial division test |
| tests/test_color.pine | Color plot test |
| tests/fixtures/generated_seed/pine/generated/*.pine | Test seed copies |
| tests/fixtures/generated_showcase/showcase_lean_surface.pine | Review-only showcase |

---

## 3. Hard Non-Goals

1. **Legacy scripts are not feature gaps.** CHoCH, USI, REV-Ladder, BFI,
   and VWAP Reclaim logic has been internalized into SMC or is deliberately
   standalone. Their existence does not indicate missing SMC functionality.

2. **Companion scripts are not deficits.** They consume BUS/library output.
   A companion lagging behind engine development is normal, not a gap.

3. **No feature roadmap from standalones.** Standalone scripts served their
   purpose as development steps. They must not be read as "missing features"
   that need to be added to SMC.

4. **QuickALGO is a separate product.** It has its own subscriber base and
   its own library stack. It is not part of SMC Mainline.

---

## 4. Mainline Boundary Rules

- New Pine files claiming Mainline status require:
  - import from at least one SMC++ library
  - consumption or production of BUS data
  - semantic contract test coverage
- Companion scripts must NOT duplicate engine logic — only consume it.
- Operator-only scripts must be clearly marked and not published.
- Legacy scripts receive bugfixes only, no feature development.

---

## 5. Archive Candidates

Files that may be moved to an `archive/` directory in a future cleanup pass
(post-freeze). No deletion — only relocation for clarity.

| File(s) | Reason | Blocker |
|---------|--------|---------|
| BTC 3m EV Scalper BALANCED (Harmonized).pine | Pine v5, single-asset, no imports | None — pure historical |
| USI-Flip.pine | Near-duplicate of USI.pine | Verify no unique TradingView publication |
| SMC_TV_Bridge.pine | v5, core fetch commented out | Verify no active backend dependency |
| test_div.pine | Trivial, no test runner coverage | None |

Files that **must stay** despite Legacy status:

| File(s) | Reason |
|---------|--------|
| QuickALGO.pine + pine/skipp_*.pine | Active TradingView publication, subscriber base |
| CHoCH.pine family | Referenced in onboarding docs, USI-CHOCH_Onboarding.md |
| REV-Ladder.pine family | Referenced in RFC displacement_candle_rfc.md |
| BFI family | Independent TradingView publication |
| VWAP family | Independent TradingView publication, technical docs exist |

---

## 6. Document Cross-References

| Document | Relevance |
|----------|-----------|
| docs/FEATURE_FREEZE.md | Active freeze constraints |
| docs/LEGACY_REMOVAL_PLAN.md | Engine-internal legacy field removal (BUS compat) |
| docs/smc_field_consumer_governance.md | Generated field lifecycle rules |
| docs/smc_trust_governance_matrix.md | Trust tier runtime effects |
| smc_deep_review_v7.md | Architecture review (v7 current) |
| smc_deep_review_v5.md | Historical architecture review (v5) |
