# G2/G3 A/B Watchdog — Status

_Generated: `2026-10-09T05:39:27.372674+00:00`_
_Source commit: `bdc1887`_

## Plan-mandated signals

| Signal | Value |
|---|---|
| §G2 rollback required (≥ 2 consecutive losses) | **YES** (current streak: 20) |
| §G3 promotion ready (SPRT accept_h1) | **no** |
| §G3 stop for futility (SPRT accept_h0) | **no** |

## SPRT (aggregated over window)

| Metric | Value |
|---|---|
| Window entries | 20 |
| Decision | `inconclusive` |
| Treatment n | 70 |
| Treatment k (hits) | 27 |
| Treatment hit rate | 0.3857 |
| LLR | -1.4769 |
| Wald upper / lower | 2.7726 / -1.5581 |

## Most recent entry

| Field | Value |
|---|---|
| Timestamp | 2026-10-09T05:39:27.372674+00:00 |
| Experiment | g3-arm-b-candidate-weights |
| Treatment hit rate | 0.3857 |
| Control hit rate | 0.3857 |
| Treatment underperformed | True |
| Single-run SPRT | `—` |
