# G2/G3 A/B Watchdog — Status

_Generated: `2026-09-10T05:34:15.616612+00:00`_
_Source commit: `37b98de`_

## Plan-mandated signals

| Signal | Value |
|---|---|
| §G2 rollback required (≥ 2 consecutive losses) | **YES** (current streak: 4) |
| §G3 promotion ready (SPRT accept_h1) | **no** |
| §G3 stop for futility (SPRT accept_h0) | **no** |

## SPRT (aggregated over window)

| Metric | Value |
|---|---|
| Window entries | 4 |
| Decision | `inconclusive` |
| Treatment n | 22 |
| Treatment k (hits) | 11 |
| Treatment hit rate | 0.5 |
| LLR | -0.1581 |
| Wald upper / lower | 2.7726 / -1.5581 |

## Most recent entry

| Field | Value |
|---|---|
| Timestamp | 2026-09-10T05:34:15.616612+00:00 |
| Experiment | g3-arm-b-candidate-weights |
| Treatment hit rate | 0.5 |
| Control hit rate | 0.5 |
| Treatment underperformed | True |
| Single-run SPRT | `—` |
