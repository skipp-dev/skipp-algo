# SMC Trust & Provider Governance Matrix

> Created: 2026-04-16 · WP-3
> Scope: SMC_Core_Engine, SMC_Dashboard, SMC_Long_Strategy, smc_context_resolvers

## Trust Tiers

Trust is resolved from three inputs:
- `signal_quality_tier` — from measurement pipeline (`high` / `good` / `ok` / other)
- `signal_freshness` — data age (`fresh` / `aging` / `stale`)
- `provider_status` — data pipeline health (`ok` / `calendar_missing` / `news_missing` / `no_data`)

### Resolution Logic (`resolve_trust_tier`)

| provider_status | signal_freshness | signal_quality_tier        | → Trust Tier    |
|-----------------|-----------------|----------------------------|-----------------|
| ok              | fresh           | high                       | **High**        |
| ok              | fresh/aging     | high / good / ok           | **Guarded**     |
| ≠ ok            | any             | high / good / ok           | **Degraded**    |
| any             | stale           | high / good / ok           | **Degraded**    |
| ≠ ok            | any             | ≠ high/good/ok             | **Insufficient**|
| ok              | any             | ≠ high/good/ok             | **Insufficient**|

## Governance Matrix

| Trust Tier     | Confidence Display | Hero Action     | Entry Best/Strict | Strategy Entry | Alert                |
|----------------|--------------------|-----------------|-------------------|----------------|----------------------|
| **High**       | High               | normal          | ✅ allowed         | ✅ allowed      | —                    |
| **Guarded**    | Usable             | normal          | ✅ allowed         | ✅ allowed      | —                    |
| **Degraded**   | Thin               | normal + suffix | ✅ allowed         | ✅ allowed      | `Trust Degraded`     |
| **Insufficient** | Caution          | normal          | ❌ suppressed      | ❌ suppressed   | `Trust Insufficient` |

### Runtime Effects (active since WP-3C)

1. **Entry suppression at Insufficient** — `long_entry_best_state` and `long_entry_strict_state`
   are forced `false` when trust is `Insufficient`. This propagates through BUS plots to
   Strategy, so no new Strategy inputs are required.

2. **Blocker text override** — `long_strict_blocker_text` is set to `'Blocked: Trust Insufficient'`
   so the hero card and alerts show the actual reason.

3. **Confidence display fix** — `compose_trade_threshold_text()` now maps the actual trust tier
   values (`High`/`Guarded`/`Degraded`/`Insufficient`) instead of stale tier names
   (`Strong`/`Usable`/`Thin`) that never matched.

## Provider Degradation

| Provider Status      | Effect on Trust                                  |
|----------------------|--------------------------------------------------|
| `ok`                 | No impact — trust determined by quality + freshness |
| `calendar_missing`   | Degrades to at most `Degraded`                   |
| `news_missing`       | Degrades to at most `Degraded`                   |
| `no_data`            | Degrades to `Insufficient` (if quality also low) |

## Contradictions Fixed (WP-3B)

1. **`compose_trade_threshold_text` was dead code** — compared against `'Strong'`/`'Usable'`/`'Thin'`
   but received `'High'`/`'Guarded'`/`'Degraded'`/`'Insufficient'`. Confidence always showed
   `'Caution'` regardless of trust. Fixed to use actual tier names.

2. **Strategy had zero trust gating** — `SMC_Long_Strategy.pine` gates on quality score, regime,
   and risk levels but never on trust. Now automatically enforced via entry state suppression
   in Core Engine (no Strategy changes needed).

3. **Trust was display-only in Core Engine** — resolved for hero text and alerts but never gated
   entry lifecycle. Now gates entry best/strict at `Insufficient`.

4. **Dashboard/Core casing difference** — Dashboard: lowercase (`high`, `guarded`). Core: Title
   Case (`High`, `Guarded`). Semantically equivalent, separate resolvers. Not a functional bug;
   documented for awareness.

## Design Principles

- **No hard blocking at Degraded** — operator retains full discretion. Degraded means data is
  stale or provider is down, but quality was previously adequate. The operator sees the warning
  and decides.
- **Hard suppression only at Insufficient** — no measurement data means the system cannot
  assess signal quality. Entry suppression is justified because the quality score that feeds
  into the entry gates has no basis.
- **Single source of truth** — trust tier is resolved once (`core_trust_tier_early`) and reused
  in hero display, alerts, and entry gating. No redundant resolution.
