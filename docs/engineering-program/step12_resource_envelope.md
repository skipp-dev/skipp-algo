# WP-R2 — Step-12 Resource Envelope

Stand: 2026-04-18

## Purpose

Defines the safe operating bounds for the Step-12 snapshot-build phase of the
`smc-library-refresh` pipeline and documents the telemetry that guards them.

## Telemetry Points (already present)

The runtime (`smc_microstructure_base_runtime.py`) emits structured telemetry
at every major allocation boundary inside `build_symbol_day_microstructure_feature_frame`
and `run_databento_base_scan_pipeline`:

| Telemetry Point | What It Emits |
|----------------|---------------|
| `minute_frame_input` | rows, cols, approx_frame_mib after initial column selection |
| `minute_frame_normalized_pre_sort` | rows after coercion and NaN drop |
| `minute_frame_batching` | total rows, trade_days count, threshold when batching triggers |
| `minute_frame_batch_N` | per-batch rows/cols/mib |
| `minute_metrics_batched_output` | final merged minute metrics rows/cols/mib |
| `minute_frame_pre_sort` / `minute_frame_sorted` | rows/cols/mib around the sort step |
| Step 12/12a complete | elapsed seconds, final symbol-day feature rows, frame MiB |
| Step 12/12 complete | elapsed seconds, base snapshot rows |

### Resource Envelope Summary (added by WP-R2)

At the end of `run_databento_base_scan_pipeline`, a structured JSON artifact
`resource_envelope.json` is written to the export directory and attached to
the result dict. Fields:

```json
{
  "pipeline_elapsed_s": 142.3,
  "step_12_elapsed_s": 48.7,
  "symbol_day_features_rows": 18400,
  "symbol_day_features_mib": 12.4,
  "base_snapshot_rows": 920,
  "session_minute_rows": 1680000,
  "trade_days_covered": 20,
  "universe_symbols": 46,
  "batch_row_threshold": 2000000,
  "runner_label": "ubuntu-latest"
}
```

## Safe Operating Bounds

The bounds below are derived from observed successful runs on the
`ubuntu-latest` runner (standard GitHub-hosted, 2-core).

| Dimension | Current Typical | Warning Threshold | Hard Limit |
|-----------|----------------|-------------------|------------|
| `session_minute_rows` | 1.2–1.8 M | 3.0 M | 5.0 M |
| `symbol_day_features_mib` | 8–15 MiB | 50 MiB | 200 MiB |
| `step_12_elapsed_s` | 30–60 s | 180 s | 600 s |
| `pipeline_elapsed_s` | 600–1600 s | 3600 s | 6000 s (100 min, below 120-min timeout) |
| `universe_symbols` | 40–50 | 100 | 200 |
| `trade_days_covered` | 20 | 30 | 60 |

### Batching Safety

The `SYMBOL_DAY_FEATURE_BATCH_ROW_THRESHOLD` (2,000,000 rows) splits
minute-frame processing by trade day when exceeded. This prevents
single-allocation memory spikes. The threshold is load-adaptive: as the
universe grows, batching activates automatically.

## Monitoring Guidance

1. **CI logs**: All telemetry emits to stdout via the progress callback.
   Search for `"Step 12/12 telemetry:"` or `"Resource envelope:"` in the
   GitHub Actions log to find the summary.
2. **Artifact**: The `resource_envelope.json` file is written alongside other
   export artifacts. It can be consumed by downstream alerting or dashboards.
3. **Alert trigger**: If `step_12_elapsed_s` exceeds 180 s or
   `symbol_day_features_mib` exceeds 50 MiB in a future run, consider
   investigating data volume growth before the hard limit is reached.

## Drift Guard (WP-R-drift)

A drift advisory triggers when any metric reaches ≥60% of its warning
threshold. This gives early visibility into growing trends before they
become actual warnings.

| Level | Trigger | Action |
|-------|---------|--------|
| Drift advisory (📈) | ≥60% of warning threshold | Monitor — no action required |
| Warning (⚠️) | ≥ warning threshold | Investigate data volume growth |
| Hard limit (🛑) | ≥ hard limit | Immediate investigation; consider runner upgrade |

### Hosted-only Re-evaluation Trigger

A hosted-only re-evaluation (upgrading to 8-core or investigating
alternative approaches) should be triggered when:

1. **Two or more** consecutive runs show warning-level threshold breaches, OR
2. Any single run hits a hard limit violation, OR
3. Pipeline duration consistently exceeds 60 minutes (50% of the 120-min timeout)

The re-evaluation path is documented in
`docs/engineering-program/runner_hosted_vs_selfhosted_decision.md`.
