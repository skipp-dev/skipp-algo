# Promotion-gate decision archive

This directory is the per-run archive consumed by the weekly
promotion-gate dashboard (PQ Re-Audit A8 / #2354).

Every invocation of [scripts/run_promotion_gate.py](../../scripts/run_promotion_gate.py)
writes a timestamped copy of its report here in addition to the live
`artifacts/promotion_decisions.json` snapshot:

```
governance/promotion_decisions/promotion_decisions_<UTC_STAMP>.json
```

The weekly cron in
[.github/workflows/promotion-gate-weekly-dashboard.yml](../../.github/workflows/promotion-gate-weekly-dashboard.yml)
aggregates the trailing 12 ISO weeks of files in this directory via
[scripts/build_promotion_gate_dashboard.py](../../scripts/build_promotion_gate_dashboard.py).

Disable archiving for a single run with
`python -m scripts.run_promotion_gate --archive-dir ''`.

See [docs/governance/weekly_dashboard_readme.md](../../docs/governance/weekly_dashboard_readme.md)
for the risk-owner reading guide.
