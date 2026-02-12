# Troubleshooting Log — SkippALGO v6.2.11: Missing REV-BUY Signals

**Date**: 12 Feb 2026
**Reported By**: User
**Symptom**: REV-BUY label missing on PFE 3-min chart at Feb 6th 15:27 — a clear bullish ChoCH with 1.6× volume that previously showed a valid REV-BUY.
**Version Range**: v6.2.7 → v6.2.11 (7 commits)

---

## Executive Summary

The missing REV-BUY was caused by **four independent, layered blockers** that had to be resolved in sequence. Each fix exposed the next blocker deeper in the signal chain:

| # | Blocker | Gate | Value on 15:27 bar | Fix |
|---|---------|------|--------------------|-----|
| 1 | Over-gated `revBuyGlobal` | `macOkLong_`, `smcOkL` | Macro bearish at reversal point | Removed contradictory gates (v6.2.10) |
| 2 | Same-bar COVER→BUY conflict | `if/else if` state machine | COVER consumed the bar | Two-phase state machine (v6.2.11) |
| 3 | Signal block gated by `pos == 0` | Main loop guard | `pos == -1` at computation time | Changed to `(pos==0 and ...) or allowRevBypass` (v6.2.11) |
| 4 | Probability too low for rescue path | `probOkGlobal` | `pU = 0.27` (below 0.40 threshold) | Lowered to 0.20 + added impulse requirement (v6.2.11) |
| 5 | False standard BUYs (same-dir re-entry) | Phase 2 guard | EXIT→BUY on same bar | `not didExit` / `not didCover` guards (v6.2.11) |
| 6 | False standard BUYs (`allowRevBypass` leak) | Engine gate | Engine signals fire without `allowEntry` | `standardEntryOk` gate on all engine branches (v6.2.11) |
| 7 | False standard BUYs (no probability floor) | Forecast gate bypass | pU=0.20–0.47 passed | Hard floor pU/pD ≥ 0.50 for standard entries (v6.2.11) |

---

## Detailed Root Cause Analysis

### Blocker 1: Over-gated `revBuyGlobal` (commit `4b86c58`)

**Problem**: Commit `63d4e79` had added `macOkLong_` (Macro trend filter) and `smcOkL` (SMC liquidity sweep filter) to `revBuyGlobal`. These gates contradict the purpose of a reversal entry:

- **Macro gate**: At a bullish ChoCH, the macro trend is still bearish — that's why it's a *reversal*.
- **SMC sweep**: Requires price wicking below a swing low, while the ChoCH breaks *above* a swing high.

**Fix**: Removed `macOkLong_` and `smcOkL` from `revBuyGlobal`. Only `ddOk` (drawdown hard gate) retained as a safety gate.

**Before**: `revBuyGlobal = f_fc_bool(allowNeuralReversals and macOkLong_ and ddOk and isChoCH_Long and probOkGlobal and volOk and smcOkL)`
**After**: `revBuyGlobal = f_fc_bool(allowNeuralReversals and ddOk and isChoCH_Long and probOkGlobal and volOk)`

**Result**: REV-BUYs reappeared on most ChoCH bars, but the specific Feb 6th 15:27 bar remained missing.

---

### Blocker 2: Same-bar COVER→BUY conflict (commit `7884419`)

**Problem**: When a bullish ChoCH fires while in a short position (`pos == -1`), the same `isChoCH_Long` signal triggers both:

1. **COVER** (exit the short) — via `structHit` in the exit logic
2. **REV-BUY** (enter long) — via `revBuyGlobal`

The old single `if/else if` state machine processed COVER but blocked BUY because only one branch could fire per bar. Since `isChoCH_Long` is a single-bar pulse (resets to `false` on the next bar), the REV-BUY was permanently lost.

**Fix**: Split the state machine into two phases:

- **Phase 1**: Process exits (EXIT/COVER) — `if exitSignal ... else if coverSignal ...`
- **Phase 2**: Process entries (BUY/SHORT) — separate `if buySignal ... else if shortSignal ...`

Phase 1 sets `pos := 0`, then Phase 2 immediately enters because `pos == 0`.

Also added `barsSinceEntry := 0` reset inside entry branches to prevent the new position from inheriting the old position's bar count (which would allow premature structural exits).

Also added `did*` flags (`didBuy`, `didShort`, `didExit`, `didCover`) to the Strategy file to replace `pos[1]` comparisons for event detection — `pos[1]` fails on same-bar reversals where `pos` jumps from -1 to 1.

**Result**: Same-bar COVER→BUY was now structurally possible, but still not firing.

---

### Blocker 3: Signal computation gated by `pos == 0` (commit `0198462`)

**Problem**: The entire signal computation block (where `revBuyGlobal`, `buySignal`, etc. are computed) was guarded by:

```pine
if pos == 0 and (allowEntry or allowRescue or allowRevBypass)
```

On a COVER→BUY bar, `pos == -1` at signal computation time (COVER hasn't run yet — the state machine runs later). So the block was skipped entirely, and `revBuyGlobal`/`buySignal` stayed `false`. The two-phase state machine had nothing to work with.

**Fix**: Changed the guard to:

```pine
if (pos == 0 and (allowEntry or allowRescue)) or allowRevBypass
```

`allowRevBypass` (which requires `isChoCH_Long or isChoCH_Short`) now enters the signal block even when in-position. Reversal signals compute before the state machine runs. Phase 2 can then use the pre-computed `buySignal` after Phase 1 exits.

**Safety**: Standard engine signals (`gateBuy` etc.) also compute in this block, but Phase 2 is still gated by `pos == 0`, so they can't trigger a double entry.

**Result**: The signal chain was now structurally complete, but still not firing on the specific 15:27 bar.

---

### Blocker 4: Probability too low (`pU = 0.27`) (commits `fd27179`, `5816caf`, `79612e2`)

**Discovery**: Added a diagnostic label on ChoCH bars showing all gate values. On PFE Feb 6th 15:27:

```
ChoCH DIAG
NeuRev:true    ✓
ddOk:true      ✓
pU:0.27        ✗ (below 0.40 threshold)
volOk:true     ✓
coolOk:true    ✓
RevByp:true    ✓
Entry:false    (blocked by statistical gates — expected)
Rescue:true    ✓
isRevB:false   ✗ (blocked by probOkGlobal)
buySig:false   ✗ (blocked because isRevB is false)
pos:0          ✓
hugeV:true     ✓
vRat:1.6       ✓
```

**Root Cause**: At the exact ChoCH reversal bar, the neural probability `pU` naturally lags — the model still reflects the prior bearish trend. Requiring `pU >= 0.40` at the inflection point is contradictory: the ChoCH structure + 1.6× volume IS the confirmation, not the probability.

**Fix (3 commits)**:

1. **Lowered rescue threshold**: `pU >= 0.40` → `pU >= 0.20` for the hugeVol path. When volume ≥ 1.5× SMA, `pU` just needs to be non-trivial (≥ 20%).

2. **Added directional impulse requirement**: After lowering the threshold, too many weak REV-BUYs appeared on small-body ChoCH bars. Added `impulseLong` (body > 0.7×ATR and close > open) as a required gate on the rescue path only.

3. **Restored `not na(pU)` check**: Prevents NA poisoning at history start where `pU` is `na`.

**Final formula**:

```pine
probOkGlobal = not na(pU) and ((pU >= 0.50) or (hugeVolG and pU >= 0.20 and impulseLong))
```

| Path | Probability | Volume | Impulse | Use case |
|------|------------|--------|---------|----------|
| Standard | pU ≥ 0.50 | volOk | Not required | Normal reversal, model agrees |
| Rescue | pU ≥ 0.20 | hugeVolG (≥ 1.5×) | Required (body > 0.7×ATR, bullish) | Reversal at inflection, model lagging |

---

## Commit Log

| Commit | Description |
|--------|-------------|
| `4b86c58` | v6.2.10: Remove macOkLong_, smcOkL from revBuyGlobal |
| `7884419` | v6.2.11: Two-phase state machine (COVER→BUY same-bar support) |
| `0198462` | v6.2.11: Signal computation gate fix (`pos != 0` for reversals) |
| `c6a1fde` | v6.2.11: Add diagnostic plots (14 `plot()` calls) |
| `eaeddc8` | v6.2.11: Fix plot limit — replace plots with single diagnostic label |
| `fd27179` | v6.2.11: Lower hugeVol probability threshold 0.40 → 0.20 |
| `5816caf` | v6.2.11: Add directional impulse requirement to rescue path |
| `79612e2` | v6.2.11: Restore `not na(pU)` check on probOkGlobal |
| `7a31518` | v6.2.11: Block same-direction re-entry (`didExit`/`didCover` guards) |
| `ce33d7c` | v6.2.11: Remove ChoCH diagnostic label |
| `12d320b` | v6.2.11: Gate engine signals with `standardEntryOk` |
| `0030085` | v6.2.11: Hard probability floor pU/pD ≥ 0.50 for standard entries |

---

## Files Changed

| File | Changes |
|------|---------|
| `SkippALGO.pine` | State machine restructure, signal gate fix, probOkGlobal tuning, `standardEntryOk` gate, pU/pD ≥ 0.50 floor |
| `SkippALGO_Strategy.pine` | Parity: same state machine, `did*` flags, probOkGlobal tuning, `standardEntryOk` gate, pU/pD ≥ 0.50 floor |

---

## Key Architectural Insight

The REV-BUY signal chain has **two independent dimensions** that must both be satisfied:

1. **Reachability** — Can the code physically reach `revBuyGlobal` computation?
   - Requires entering the signal block (now via `allowRevBypass` even with `pos != 0`)
   - Requires the state machine to process the entry (now via Phase 2 after Phase 1 exit)

2. **Gate qualification** — Does the bar meet the reversal criteria?
   - `isChoCH_Long` (structural reversal on this exact bar)
   - `probOkGlobal` (neural probability, with rescue path for model lag)
   - `volOk` (volume confirmation)
   - `ddOk` (drawdown safety)

Blockers 1–3 were reachability issues. Blocker 4 was a gate qualification issue. Blockers 5–7 were **side effects** of the reachability fixes — opening the signal block to reversals also opened it to false standard entries. Previous fix attempts only addressed one dimension at a time, which is why each fix exposed the next blocker.

---

### Blocker 5: False standard BUYs — same-direction re-entry (commit `7a31518`)

**Problem**: After fixing the REV-BUY chain, same-bar same-direction re-entries appeared. When Phase 1 processed an EXIT (long → flat), Phase 2 would immediately re-enter BUY if the engine signal was still true — producing EXIT→BUY on the same bar.

**Fix**: Added guards to Phase 2:

- `if buySignal and pos == 0 and not didExit` — blocks EXIT→BUY
- `else if shortSignal and pos == 0 and not didCover` — blocks COVER→SHORT

Cross-direction reversals (COVER→BUY, EXIT→SHORT) remain allowed.

**Result**: Partially fixed. Some false BUYs persisted.

---

### Blocker 6: False standard BUYs — `allowRevBypass` leaking engine signals (commit `12d320b`)

**Problem**: When `allowRevBypass` entered the signal block (because a ChoCH was present), ALL engine-specific computations ran (`gateBuy`, `baseBuy`, etc.) — they assumed the outer guard already verified `allowEntry`/`allowRescue`. This produced false BUY labels on ChoCH bars where only reversal signals should be considered.

**Fix**: Added `standardEntryOk = (pos == 0) and (allowEntry or allowRescue)` and prepended it to all four engine branches (Hybrid, Breakout, Trend+Pullback, Loose). When entered via `allowRevBypass` alone, engine signals stay false — only the unified reversal injection applies.

**Result**: Fixed some false BUYs, but others persisted with `allowEntry=true` and low pU.

---

### Blocker 7: False standard BUYs — no probability floor (commits `9bb4f22`, `0030085`)

**Discovery**: Diagnostic label on the false BUY bar showed:

```
BUY-DIAG
aE:true aR:false aRB:false
pos:0 stdOk:true
revB:false eng:Hybrid
pU:0.20 vol:2
cool:true dd:true
```

**Root cause**: The forecast gate (`fcGateLongSafe`) defaults to `true` when `forecastAllowed` is false (e.g., when `use3Way` is off, or `f_forecast_allowed()` returns false). This silently bypasses ALL probability checks in `f_entry_forecast_gate()`, including `pU >= minDirProb` (default 0.42). A standard BUY could fire with pU as low as 0.20 — the model predicted 80% bearish.

First fix set floor to 0.40, but pU=0.47 slipped through (model still predicted bearish at <50%). Raised to 0.50.

**Fix**: Added a hard probability floor AFTER engine signal computation and BEFORE reversal injection:

```pine
if buySignal and (na(pU) or pU < 0.50)
    buySignal := false
if shortSignal and (na(pD) or pD < 0.50)
    shortSignal := false
```

- Standard entries require the model to actually predict the direction (≥ 50%)
- `na(pU)` is fail-closed (blocked)
- Reversal entries are unaffected — injected AFTER this check with their own `probOkGlobal` handling

**Result**: All false BUYs eliminated. REV-BUY at Feb 6 15:27 still fires correctly.

---

## Diagnostic Label (Temporary)

A diagnostic label fires on every `isChoCH_Long` bar when "Show Debug Labels" is enabled. It shows all gate values for quick triage. To remove, delete the `// v6.2.11 Diagnostic` block in `SkippALGO.pine` (after the conflict resolution section).

---

## Related Documentation

- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Original Feb 7 rescue mode fix (15:27/15:30 signals)
- [TROUBLESHOOTING_GHOST_SIGNALS.md](TROUBLESHOOTING_GHOST_SIGNALS.md) — PFE ghost signal / repainting fix (Feb 6)
- [CHANGELOG_v6.2.7.md](CHANGELOG_v6.2.7.md) — allowRevBypass, unified injection, NA poisoning fix
- [SkippALGO_Deep_Technical_Documentation.md](SkippALGO_Deep_Technical_Documentation.md) — REV-BUY gate documentation (Section: REV-BUY Logic)
