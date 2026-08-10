# SMC commercial product identity

Status: canonical Phase-0 identity, 2026-08-10. Commercial target accepted;
broad customer launch not yet approved.

## One-Liner

"Decision-first long-dip context for active US-equity traders—on the chart,
with visible freshness, provenance and uncertainty."

## What it is

The SMC Long-Dip Suite is the primary TradingView surface for structured
long-dip decisions. It combines Pine-native structure, zones, invalidation and
a decision-first summary. The optional SMC Decision Board adds deeper context.
The planned Skipp Live Decision Mesh is the separate first-party companion for
time-sensitive proprietary context that Pine cannot receive through arbitrary
HTTP calls.

Backend-provider availability is not itself a customer feature and does not
prove that data is live on a Pine surface. The external commercial-clearance
process is handled separately and outside this repository.

## What it is NOT

- Not a generic SMC indicator (not "another BOS/CHOCH script")
- Not a short-selling system (long-only, short planned separately)
- Not a guaranteed signal or trade-recommendation service
- Not a backtesting framework (the strategy is a companion, not the core)
- Not a replacement for trading education
- Not an automated live-execution product
- Not a TradingView data-provider integration

## Target users

- Active US equity traders who understand SMC concepts
- Traders who want more than chart drawings—transparent context, freshness and
  invalidation
- Intermediate to advanced users willing to learn a system

## Product family

| Product | Role | Commercial status |
|---|---|---|
| SMC Long-Dip Suite | Main chart indicator: zones, Focus/Hero decision, invalidation and alerts | Existing mainline; initial customer surface |
| SMC Decision Board | Optional explanation and evidence companion | Existing mainline; Pro candidate |
| Skipp Live Decision Mesh | Timely first-party context with freshness and provenance | Private prototype; not released |
| SMC Long-Dip Strategy | Research and evaluation companion | Existing; outside initial performance promise |
| Skipp Operator Terminal | Research, monitoring, operations and support | Internal only under ADR-0030 |

## Key differentiators

1. **Decision-first chart surface** — attention, support, invalidation and risk
   before implementation detail.
2. **Visible trust and uncertainty** — deterministic state with explicit unknown
   and insufficient-evidence conditions.
3. **Regime and event context** — only where the released surface has current,
   provenance-backed data.
4. **Granular alerts** — setup lifecycle rather than a single binary action.
5. **Evidence-class discipline** — modeled OOS, paper and live remain separate.
6. **First-party live companion direction** — the Live Decision Mesh is the
   planned home for timely context outside Pine's supported data boundary.

## What we do NOT compete on

- Visual beauty (LuxAlgo wins on aesthetics)
- Simplicity (ICT community scripts are simpler)
- Feature count (we have fewer visible features, more data depth)

## Naming

- Commercial family: **Skipp SMC** (working umbrella; final brand clearance is
  separate)
- Chart product: **SMC Long-Dip Suite**
- Pro chart companion: **SMC Decision Board**
- Live companion: **Skipp Live Decision Mesh**
- Internal surface: **Skipp Operator Terminal**
- Source and Pine publication names change only through a separate compatible
  release plan
- Library: `smc_micro_profiles_generated`
- Avoid as new customer-facing names: "SMC Core" alone (too generic),
  "SkippALGO" (historical repository name)

## Claims boundary

`docs/commercial/CLAIMS_REGISTRY.md` is authoritative for customer-facing
claims. No metric, provider count, test count, track record or availability
statement is standing copy merely because it appears in an older document.
