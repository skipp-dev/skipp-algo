# G2/G3 A/B Watchdog — Status

_Generated: `2026-09-07T05:35:03.640769+00:00`_
_Source commit: `35f220c`_

## Plan-mandated signals

| Signal | Value |
|---|---|
| §G2 rollback required (≥ 2 consecutive losses) | **no** (current streak: 1) |
| §G3 promotion ready (SPRT accept_h1) | **no** |
| §G3 stop for futility (SPRT accept_h0) | **no** |

## SPRT (aggregated over window)

| Metric | Value |
|---|---|
| Window entries | 1 |
| Decision | `inconclusive` |
| Treatment n | 5 |
| Treatment k (hits) | 4 |
| Treatment hit rate | 0.8 |
| LLR | 0.1467 |
| Wald upper / lower | 2.7726 / -1.5581 |

## Most recent entry

| Field | Value |
|---|---|
| Timestamp | 2026-09-07T05:35:03.640769+00:00 |
| Experiment | g3-arm-b-candidate-weights |
| Treatment hit rate | 0.8 |
| Control hit rate | 0.8 |
| Treatment underperformed | True |
| Single-run SPRT | `—` |
