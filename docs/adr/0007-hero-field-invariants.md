# ADR-0007 — HERO Field Invariants

- **Status:** Accepted
- **Date:** 2026-04-24
- **Supersedes:** —
- **Related:** [ADR-0003 — Pine legacy resolver](0003-pine-legacy-physical-move-resolver.md), [ADR-0006 — HERO Vocab Discipline](0006-hero-vocab-discipline.md)

## Context

The seven canonical HERO fields produced by [scripts/smc_hero_state.py](../../scripts/smc_hero_state.py) form the **boundary contract** between the Python enrichment pipeline and Pine consumers (`SMC_Dashboard.pine`, `SMC_Mobile_Dashboard.pine`, the generated `pine/generated/smc_micro_profiles_generated.pine`). ADR-0006 codified the *vocabulary* discipline; this ADR locks the **field-level invariants** so that future contributors do not silently break Pine consumers when adding/renaming/repurposing a HERO field.

## Decision

The Python builder [`build_hero_state`](../../scripts/smc_hero_state.py) MUST emit a flat `dict[str, str]` with **exactly seven keys**, in the order given in the table below. Each key has a fixed vocabulary (where applicable), a fixed default, and a documented Pine consumer.

### Invariants table

| # | HERO field | Vocab constant | Default | Sentinel? | Pine consumers |
| - | ---------- | -------------- | ------- | --------- | -------------- |
| 1 | `HERO_MARKET_MODE` | `HERO_MARKET_MODE_VOCAB` | `"UNKNOWN"` | **`"UNKNOWN"` ≡ waiting-state** (rendered as `⚪ awaiting data`) | `SMC_Mobile_Dashboard.pine` Mobile context block, `SMC_Dashboard.pine` Hero block |
| 2 | `HERO_BIAS` | `HERO_BIAS_VOCAB` | `"UNKNOWN"` | **`"UNKNOWN"` ≡ waiting-state** (excluded from bias chip; rendered as `⚪ awaiting data`) | `SMC_Dashboard.pine`, `SMC_Mobile_Dashboard.pine` |
| 3 | `HERO_TRUST` | `HERO_TRUST_VOCAB` | `"unavailable"` | derived | `SMC_Dashboard.pine:1769` (gates blocker on `degraded`/`stale`) |
| 4 | `HERO_SETUP_QUALITY` | `HERO_SETUP_QUALITY_VOCAB` | `"unavailable"` | **`"unavailable"` ≡ waiting-state** (rendered as `⚪ awaiting data`; maps to `avoid` on the Producer-B action table) | dashboard tier color |
| 5 | `HERO_WHY_NOW` | *(free-form string)* | `""` | none | dashboard caption |
| 6 | `HERO_RISK` | `HERO_RISK_VOCAB` (incl. `""`) | `""` | **`""` ≡ `HERO_RISK_NONE`** | `SMC_Dashboard.pine:1769` (gates blocker on `!= ""`) |
| 7 | `HERO_ACTION` | `HERO_ACTION_VOCAB` | `"WATCH"` | derived | `SMC_Dashboard.pine` |

### Rules

1. **Field count *and* vocabulary membership are part of the contract.** Adding or removing a HERO field — *or* adding/removing a vocab value (including sentinel additions) — requires a *major* `library_field_version` bump (e.g. `v5.5c` → `v6.0a` for the WS3-UI #55 sentinel rollout) and a parallel Pine-consumer update in the same PR.
2. **The empty-string sentinel for `HERO_RISK` is normative.** `SMC_Dashboard.pine:1769` reads `mp.HERO_RISK != "" ? mp.HERO_RISK : ...` to decide whether to render the blocker badge. Renaming `""` → `"NONE"` requires a Pine-side migration; it is *not* a refactor that can be done Python-side alone.
3. **Vocab membership is enforced by tests.** Every controlled-vocabulary HERO field is pinned by [tests/test_hero_observed_vocab_pin.py](../../tests/test_hero_observed_vocab_pin.py) and [tests/test_hero_risk_vocab_and_reachability_pin.py](../../tests/test_hero_risk_vocab_and_reachability_pin.py). All values returned by the `_derive_*` helpers must be vocab members.
4. **Reachability is enforced.** Every vocab member must be reachable from at least one branch of its derive helper (dead-vocab check). Adding a vocab member that no branch returns is a contract violation.
5. **Schema fingerprint pin.** [tests/test_hero_schema_fingerprint.py](../../tests/test_hero_schema_fingerprint.py) hashes the union of all six HERO vocabs + the field order and pins the digest. Any vocabulary or field-order change forces a deliberate fingerprint update — and surfaces in CHANGELOG review.

## Consequences

- **Forced co-evolution.** Source-side vocabulary changes are blocked at PR review by the fingerprint pin until the Pine consumer side is verified.
- **Empty-string discipline.** The `""` sentinel is now a *named* constant (`HERO_RISK_NONE`); future readers do not have to grep Pine to discover that empty string is meaningful.
- **Documented blast radius.** ADR-0007 is the single source-of-truth for *which Pine file consumes which HERO field*. PRs that touch `SMC_Dashboard.pine` should update this table when consumer mapping shifts.

## Out of scope

- The non-HERO library fields (microstructure, regime, calendar, etc.) keep their existing `library_field_version`-bump discipline (ADR-0003) but are not enumerated here.
- The `HERO_MARKET_MODE` and `HERO_SETUP_QUALITY` *passthrough* nature is documented but not enforced beyond vocabulary membership; upstream sources are expected to police their own emit sets.

## 2026-05-26 amendment — waiting-state sentinels (WS3-UI #55)

Defaults for `HERO_MARKET_MODE`, `HERO_BIAS`, and `HERO_SETUP_QUALITY` were switched from the substantive values (`NEUTRAL`, `FLAT`, `low`) to dedicated waiting-state sentinels (`UNKNOWN`, `UNKNOWN`, `unavailable`) so consumers can tell *“no enrichment data yet”* apart from a real neutral / flat / low reading. The sentinels are first-class vocab members (frozenset size 4→5, 3→4, 4→5 for market / bias / quality respectively) and round-trip through the Producer-B action table via `HERO_QUALITY_A_TO_B["unavailable"] = "avoid"`. Pine dashboards render `⚪ awaiting data` (grey-80) for the sentinel; the bias chip is suppressed entirely for both `FLAT` and `UNKNOWN`. This was a breaking change to Pine literal gates and shipped with the `v5.5c → v6.0a` MAJOR version bump.

## 2026-05-28 amendment — `HERO_MARKET_TRUST` vocab convergence (WS3 #58)

`HERO_MARKET_TRUST` (Producer B, `scripts/smc_hero_market_mode.py`) historically emitted a parallel vocabulary (`trusted` / `advisory` / `stale` / `watch_only` / `unavailable`) that overlapped semantically with `HERO_TRUST` (Producer A, `scripts/smc_hero_state.py`) without sharing literal labels. The April 2026 system review flagged this as the only remaining HERO vocab overlap with an unresolved naming divergence (see `docs/reviews/2026-04-24-system-review.md`).

Both producers project the canonical `smc_integration.trust_state.TrustState` enum — there is no semantic divergence, only label divergence. Producer B now derives `HERO_MARKET_TRUST` directly from `scripts.smc_hero_state.project_trust_state_to_hero` (the single existing source-of-truth for the `TrustState` → Hero-local mapping), eliminating the parallel `_TRUST_LABEL` table.

The convergence contract:

    HERO_MARKET_TRUST_VOCAB == HERO_TRUST_VOCAB - {"warmup"}

`"warmup"` is Hero-local (aging freshness signal with no `TrustState` counterpart) and therefore absent from `HERO_MARKET_TRUST`. The `WATCH_ONLY` → `"degraded"` collapse on the Producer-B side matches the already-canonical info-loss point documented for `HERO_TRUST` and is the only mapping where information is lost.

Pinned by `tests/test_hero_trust_market_trust_alignment.py` (5 parametrized `TrustState` mappings + 3 vocab-set invariants). No non-generated Pine consumer currently gates on `HERO_MARKET_TRUST` literal values (only the Pine `export const string HERO_MARKET_TRUST = "..."` constant exists, no `mp.HERO_MARKET_TRUST == "..."` comparison), so this is a producer-only contract change. Pine literal still changes → `library_field_version` bumped **v6.0a → v7.0a** (MAJOR) per the *vocab_value_removed_or_renamed* policy in `ml/schemas/v1_hero_features.json`. `deprecated_field_policy.preferred_field_version` follows.
