# R4 Context readback — decision

**Status:** decided 2026-08-01 (option C). Implementation and TradingView
execution are separate, later steps.

**Decides:** how the Context BUS channel values are made readable so the
`R4-OVERLAY` parity gate ("Compare structure and zone output with Suite and
Breakout evidence") can be closed.

---

## 1. What was blocking, and why it should not have been

The R4 shadow evidence recorded the parity comparison as
`blocked_on_observability` and named this next step:

> A fixture-only on-chart readback mechanism, following the R2.4 precedent
> (`table.new` marked TEST ONLY, never published). **Deliberately NOT built
> here: a second competing observability mechanism is explicitly ruled out by
> the R2.4 outcome**, so the method is an owner decision.

The emphasised clause does not hold up. Three checks:

**The claim has no source.** No R2.4 artifact and no document states such a
rule. `smc_hold_manager_tradingview_replay_2026-07-28.json` and the fixture
compile artifact contain no statement about observability mechanisms at all.
What the R2.4 record does document is a *procedure*: exact-hash approval, a
private `TEST ONLY` saved script, an isolated validation layout, no
publication, canonical chart state restored afterwards. A procedure is not a
prohibition.

**It was not a long-standing decision.** The sentence was written on
2026-07-31T05:23Z by #4231 — the same day, in the same workstream that then
cites it as the reason the gate cannot close.

**The precedent it cites is an instance of building a readback, not of
refusing one.** Measured: `SMC_Hold_Manager.pine` contains zero `table.new`;
`tests/fixtures/pine/smc_hold_manager_r2_4_fixture.pine` contains eight. The
readback was built — in a generated throwaway fixture rather than in the
product surface. What the precedent actually rules out is a readback **in the
production surface**. That constraint is real and is kept below.

The dated measurement in the same artifact (`finding`: all channels are
`display.none`, so their values render nowhere) is correct and unchanged. Only
the forward-looking `requiredNext` sentence was amended.

## 2. The option that was never considered

The blocker was framed as "either build a table or stay blocked". There is a
third possibility the artifact does not mention: `display.data_window`.

`display.none` hides a plot everywhere. `display.data_window` keeps it off the
chart but shows its value in the Data Window — which is exactly what a numeric
parity comparison needs.

This is not an exotic idea in this repository: `display.data_window` is used
**59 times**, including in `SMC_Session_Context.pine`, a Context-family surface.
It is also not a second mechanism — it is the same plot channel with a
different visibility flag, so the "competing mechanism" objection does not
apply to it even on the original reading.

## 3. Options

| | Mechanism | Cost | Readout |
|---|---|---|---|
| **A** | Fixture copy of the producer with `display.data_window` on all 62 channels | one flag per plot | Data Window, all channels, one bar at a time |
| **B** | Fixture copy with a `table.new` panel (literal R2.4 precedent) | a rendered panel to lay out and pin | on-chart, many channels at once, stable across bars |
| **C** | Both: `data_window` for the full 62-channel dump, `table.new` for the parity-relevant subset | A plus a 17-row table | both of the above |

The parity-relevant subset is the `structure` (7) and `zone` (10) channels named
by the gate — 17 rows.

## 4. Decision: C

Rationale, in the order that decided it:

**A alone risks a second blocked round.** The Data Window shows values for the
hovered bar. Whether 62 rows read that way are workable for a parity comparison
is not knowable from the repository — it is a live-UI property. Choosing A and
discovering it is impractical costs another shadow session.

**B alone throws away the cheap part.** The `data_window` flag costs almost
nothing and covers all 62 channels; restricting visibility to a hand-picked
table subset means anything outside the subset stays unreadable, which is how
this gate got stuck in the first place.

**C is not meaningfully more expensive than B.** The table is the work; adding
the visibility flag alongside it is per-plot mechanical.

Constraints that stay in force, from the R2.4 precedent:

- the readback exists **only** in a generated fixture derived from the
  canonical source, never in `SMC_Context_Bus.pine` or any product surface;
- the fixture is marked `TEST ONLY`, is never published, and is not added to
  the managed rollout;
- the canonical source hash is embedded so source drift fails closed;
- the canonical chart state is restored and saved after the run.

## 5. What this decision does not settle

- **`R4-BUS` remains open** on owner sign-off of the shadow observation. That
  gate is a signature, not a mechanism, and is untouched here.
- **The existing shadow evidence is partly stale.** It was captured against
  commit `393dafedd`; #4263 has since changed both `SMC_Context_Bus.pine` and
  `SMC_Context_Overlay.pine`, and the channel count moved 60 → 62. The binding
  readback has to be re-run against the current contract regardless of which
  readback mechanism is used.
- **Execution needs a TradingView session.** Building the generator and the
  fixture is repository work; compiling, running and reading them back is not.

## 6. Sources

- `artifacts/governance/smc_context_bus_r4_shadow_tradingview_2026-07-31.json`
  — the shadow evidence, its `finding`, and the amended `requiredNext`
- `artifacts/governance/pine_extended_migration_traceability.json` — R4-BUS and
  R4-OVERLAY open gates
- `artifacts/governance/smc_hold_manager_tradingview_replay_2026-07-28.json`
  — the R2.4 outcome actually on record
- `scripts/generate_smc_hold_manager_tv_fixture.py` — the R2.4 generator, the
  pattern an R4 readback generator follows
- `scripts/smc_context_bus_manifest.py` — the 62-channel contract and its groups
