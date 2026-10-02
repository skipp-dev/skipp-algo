# G2/G3 A/B Watchdog — Status

_Generated: `2026-10-02T05:37:14.415377+00:00`_
_Source commit: `1250b9e`_

## Plan-mandated signals

| Signal | Value |
|---|---|
| §G2 rollback required (≥ 2 consecutive losses) | **YES** (current streak: 15) |
| §G3 promotion ready (SPRT accept_h1) | **no** |
| §G3 stop for futility (SPRT accept_h0) | **no** |

## SPRT (aggregated over window)

| Metric | Value |
|---|---|
| Window entries | 15 |
| Decision | `inconclusive` |
| Treatment n | 43 |
| Treatment k (hits) | 19 |
| Treatment hit rate | 0.4419 |
| LLR | -0.6134 |
| Wald upper / lower | 2.7726 / -1.5581 |

## Most recent entry

| Field | Value |
|---|---|
| Timestamp | 2026-10-02T05:37:14.415377+00:00 |
| Experiment | g3-arm-b-candidate-weights |
| Treatment hit rate | 0.4419 |
| Control hit rate | 0.4419 |
| Treatment underperformed | True |
| Single-run SPRT | `—` |
