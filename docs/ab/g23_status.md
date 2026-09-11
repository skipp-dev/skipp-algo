# G2/G3 A/B Watchdog — Status

_Generated: `2026-09-11T09:53:07.726502+00:00`_
_Source commit: `b90ddcc`_

## Plan-mandated signals

| Signal | Value |
|---|---|
| §G2 rollback required (≥ 2 consecutive losses) | **YES** (current streak: 5) |
| §G3 promotion ready (SPRT accept_h1) | **no** |
| §G3 stop for futility (SPRT accept_h0) | **no** |

## SPRT (aggregated over window)

| Metric | Value |
|---|---|
| Window entries | 5 |
| Decision | `inconclusive` |
| Treatment n | 31 |
| Treatment k (hits) | 13 |
| Treatment hit rate | 0.4194 |
| LLR | -0.5271 |
| Wald upper / lower | 2.7726 / -1.5581 |

## Most recent entry

| Field | Value |
|---|---|
| Timestamp | 2026-09-11T09:53:07.726502+00:00 |
| Experiment | g3-arm-b-candidate-weights |
| Treatment hit rate | 0.4194 |
| Control hit rate | 0.4194 |
| Treatment underperformed | True |
| Single-run SPRT | `—` |
