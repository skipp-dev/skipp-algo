# Promotion-Gate Weekly Dashboard

Closes [#2354](https://github.com/skipp-trader/skipp-algo/issues/2354) (PQ
Re-Audit finding **A8**). Aggregates the last 12 ISO weeks of archived
promotion-gate decisions into a single JSON + PNG artefact for the
risk-owner Monday review.

## What it produces

The workflow [.github/workflows/promotion-gate-weekly-dashboard.yml](../../.github/workflows/promotion-gate-weekly-dashboard.yml)
runs every Sunday at 06:00 UTC and uploads two files under the
`promotion-gate-weekly-dashboard` GitHub Actions artefact:

- `promotion_gate_dashboard_<ISO_WEEK>.json` &mdash; structured payload
  (`schema_version=1`) with per-family weekly mean of `brier`, `ece`,
  `fdr_pvalue`, `psr`, `psi` plus the current `GateThresholds`.
- `promotion_gate_dashboard_<ISO_WEEK>.png` &mdash; one subplot per
  metric, one line per family, with a horizontal gate-threshold line.

## How the dashboard is built

1. The script [scripts/build_promotion_gate_dashboard.py](../../scripts/build_promotion_gate_dashboard.py)
   scans `governance/promotion_decisions/*.json`.
2. Each file is parsed as a `REPORT_SCHEMA_VERSION=1` promotion-gate
   report (see [governance/promotion_report.py](../../governance/promotion_report.py)).
3. Reports outside the trailing window (default 12 ISO weeks) are
   dropped. Remaining `Decision.metrics` are bucketed by
   `(iso_week, family)` and averaged.
4. The aggregated points + the current `GateThresholds` are written to
   the output directory (default `artifacts/governance/`).

## Reading the artefact

For each metric the gate boundary is drawn in red:

| Metric        | Direction    | Gate default | Action when breached |
| ------------- | ------------ | -----------: | -------------------- |
| `brier`       | lower better |         0.22 | re-calibrate or pause the family |
| `ece`         | lower better |         0.05 | re-calibrate or pause the family |
| `fdr_pvalue`  | lower better |         0.05 | re-run multi-test correction |
| `psr`         | higher better |        0.95 | shrink position size, investigate edge decay |
| `psi`         | lower better |         0.25 | check feature drift, refresh training window |

A family that crosses its gate two weeks in a row is the trigger for
opening a posture-change ticket; one-off breaches are tracked but
typically resolve themselves on the next cycle.

## Seeding the archive

`governance/promotion_decisions/` is empty in the current repo. Until
the production promotion-gate runs start archiving their reports there,
the weekly cron will emit an empty-but-valid dashboard JSON and a
placeholder PNG. This is intentional fail-soft behaviour so the cron
stays green while the archive seeds itself.

## Running locally

```bash
python -m scripts.build_promotion_gate_dashboard \
    --source-dir governance/promotion_decisions \
    --output-dir artifacts/governance \
    --lookback-weeks 12
```

Add `--reference-date 2026-05-25` to anchor the window on a specific
ISO date, or `--no-png` to skip PNG rendering when matplotlib is not
installed.
