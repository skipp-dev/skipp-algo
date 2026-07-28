# §15 Exact Shadow and EWMA Recalibration Contract

Status: observation-only. This change does not activate §15 or EWMA.

## Exact §15 evidence

The production scorer continues to use its current inputs. A second complete
`rank_candidates_v2` execution receives measured Wilder ADX and Bollinger-band
width from the same chronological EOD candles already used for ATR. The replay
uses the identical universe, news, sector, market-regime weights and adaptive
gates. It therefore includes component caps, risk penalties, rumor and
counter-trend haircuts, tiering, sorting and rank movement.

Only rows with `exact_second_scorer_pass=true` count as decision evidence.
ATR-proxy display values and late enrichment values are excluded. The served
ranking is always sliced from the baseline pass; shadow cannot gate, promote or
reorder a live candidate.

A later §15 activation requires a separately approved, versioned decision based
on multiple completed production sessions. This change contains no activation
flag or live weight change.

## Shared ATR-candle cache

Each ATR cache payload now persists `technical_features_by_symbol` with:

- measured ADX,
- measured Bollinger-band width,
- raw 50-session energy-weighted moving-average data,
- source and `bars_through` provenance.

A legacy cache without that block is incomplete for shadow purposes and causes
a full historical refresh rather than fabricated neutral technical values.

## EWMA stays separate

Skipp's `ewma` is an energy-weighted price measure, not a conventional
exponentially weighted moving average. It remains neutral in both live and §15
shadow scoring. `ewma_score_shadow` is persisted as an observe-only outcome and
feature-importance column so a consistently labelled cohort can be built.

Recalibration requires at least 200 labelled rows with an actually measured
`ewma_score_shadow` (not merely 200 total FI labels), a formula-era-homogeneous
cohort, FDR-aware feature evidence and a new versioned feature/weight contract.
The recurring feature-importance artifact exposes a dedicated
`ewma_recalibration` decision with its own measured-sample shortfall. Until then
EWMA has no `FEATURE_TO_WEIGHT_KEY` mapping and cannot be auto-tuned or activated.

## Deferred components

A3 `institutional_quality` and A4 `estimate_revision` remain in the current
schema despite being production-dormant. They may only be wired or removed in
the next versioned feature/weight contract with an explicit migration. B1, E1
and G1 are outside this change and remain untouched.
