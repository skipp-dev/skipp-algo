# G2/G3 A/B Watchdog — Status

_Generated: `2026-10-06T05:38:26.998898+00:00`_
_Source commit: `e83a9f8`_

## Plan-mandated signals

| Signal | Value |
|---|---|
| §G2 rollback required (≥ 2 consecutive losses) | **YES** (current streak: 17) |
| §G3 promotion ready (SPRT accept_h1) | **no** |
| §G3 stop for futility (SPRT accept_h0) | **no** |

## SPRT (aggregated over window)

| Metric | Value |
|---|---|
| Window entries | 17 |
| Decision | `inconclusive` |
| Treatment n | 62 |
| Treatment k (hits) | 25 |
| Treatment hit rate | 0.4032 |
| LLR | -1.176 |
| Wald upper / lower | 2.7726 / -1.5581 |

## Most recent entry

| Field | Value |
|---|---|
| Timestamp | 2026-10-06T05:38:26.998898+00:00 |
| Experiment | g3-arm-b-candidate-weights |
| Treatment hit rate | 0.4032 |
| Control hit rate | 0.4032 |
| Treatment underperformed | True |
| Single-run SPRT | `—` |
