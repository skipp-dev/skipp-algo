# Zone Priority Calibration Report

**Source:** `artifacts/reports/benchmark_corpus`  
**Total events:** 6112  
**Pairs contributing:** 192

## Family Weights

| Family | Prior | Observed Hit Rate | Calibrated | Δ |
|--------|------:|------------------:|-----------:|--:|
| OB | 0.82 | 0.3317 | 0.4782 | -0.3418 |
| FVG | 0.61 | 0.5699 | 0.5820 | -0.0280 |
| BOS | 0.81 | 0.8654 | 0.8488 | +0.0388 |
| SWEEP | 0.73 | 0.6584 | 0.6799 | -0.0501 |

## Per-Family Detail

| Family | Events | Hits | Pairs | Simple HR | Weighted HR |
|--------|-------:|-----:|------:|----------:|------------:|
| OB | 603 | 200 | 48 | 0.3317 | 0.3317 |
| FVG | 3388 | 1931 | 48 | 0.5700 | 0.5699 |
| BOS | 988 | 855 | 48 | 0.8654 | 0.8654 |
| SWEEP | 1133 | 746 | 48 | 0.6584 | 0.6584 |

## Rank Thresholds (unchanged)

| Rank | Min Score |
|------|----------:|
| A | 75 |
| B | 50 |
| C | 25 |
| D | 0 |
