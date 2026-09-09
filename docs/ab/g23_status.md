# G2/G3 A/B Watchdog — Status

_Generated: `2026-09-09T05:34:29.200209+00:00`_
_Source commit: `acb82da`_

## Plan-mandated signals

| Signal | Value |
|---|---|
| §G2 rollback required (≥ 2 consecutive losses) | **YES** (current streak: 3) |
| §G3 promotion ready (SPRT accept_h1) | **no** |
| §G3 stop for futility (SPRT accept_h0) | **no** |

## SPRT (aggregated over window)

| Metric | Value |
|---|---|
| Window entries | 3 |
| Decision | `inconclusive` |
| Treatment n | 15 |
| Treatment k (hits) | 6 |
| Treatment hit rate | 0.4 |
| LLR | -0.2904 |
| Wald upper / lower | 2.7726 / -1.5581 |

## Most recent entry

| Field | Value |
|---|---|
| Timestamp | 2026-09-09T05:34:29.200209+00:00 |
| Experiment | g3-arm-b-candidate-weights |
| Treatment hit rate | 0.4 |
| Control hit rate | 0.4 |
| Treatment underperformed | True |
| Single-run SPRT | `—` |
