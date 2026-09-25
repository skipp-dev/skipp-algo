# G2/G3 A/B Watchdog — Status

_Generated: `2026-09-25T05:36:06.374215+00:00`_
_Source commit: `4d0062a`_

## Plan-mandated signals

| Signal | Value |
|---|---|
| §G2 rollback required (≥ 2 consecutive losses) | **YES** (current streak: 10) |
| §G3 promotion ready (SPRT accept_h1) | **no** |
| §G3 stop for futility (SPRT accept_h0) | **no** |

## SPRT (aggregated over window)

| Metric | Value |
|---|---|
| Window entries | 10 |
| Decision | `inconclusive` |
| Treatment n | 39 |
| Treatment k (hits) | 18 |
| Treatment hit rate | 0.4615 |
| LLR | -0.4629 |
| Wald upper / lower | 2.7726 / -1.5581 |

## Most recent entry

| Field | Value |
|---|---|
| Timestamp | 2026-09-25T05:36:06.374215+00:00 |
| Experiment | g3-arm-b-candidate-weights |
| Treatment hit rate | 0.4615 |
| Control hit rate | 0.4615 |
| Treatment underperformed | True |
| Single-run SPRT | `—` |
