# docs/calibration/gates/ — ADR-0031 drop-zone

Daily artifacts committed by `promotion-gate-daily` (14:00 UTC, bot auto-merge
PR) and consumed fail-soft by `c13-daily-cron` (22:00 UTC, Step 5b — moved
2026-07-31 from the removed `public-calibration-dashboard`, see issue #298):

| File | Producer | Consumer |
|---|---|---|
| `returns_series_<date>.json` | `scripts/build_returns_series.py` | gate + regime producers below (provenance) |
| `track_record_gate_<date>.json` | `scripts/build_track_record_gate.py` | `emit_public_calibration_report` → public report key `track_record_gate` |
| `regime_stratified_<date>.json` | `scripts/build_regime_stratified_report.py` | `emit_public_calibration_report` → public report key `regime_stratified` |

Measurement basis (disclosed in every file's `measurement` block): Variant-A
net returns *given a triggered setup* — `touch_then_horizon_close`, fixed
5 bps round-turn cost, governed 1D plane. NOT portfolio P&L. See ADR-0031.

Retention: the workflow prunes each family to the newest 90 files. An empty
directory (or a missing gate file on empty-pool days) is a normal state — the
public report simply omits the keys.

## Subdirectories (ADR-0031, Nachtrag 2026-10-01)

Both are written by the `ledger` step of `promotion-gate-daily`. No 1D
consumer sees them: every reader of this directory globs it non-recursively.

| Path | Producer | What it is |
|---|---|---|
| `15m/track_record_gate_<date>.json` | `scripts/build_track_record_gate.py` | 30-day WINDOW verdict on the 15m observation plane (retention 90) |
| `15m/regime_stratified_<date>.json` | `scripts/build_regime_stratified_report.py` | regime report of the same window (retention 90) |
| `ledger/returns_ledger_<plane>.jsonl` | `scripts/accumulate_returns_ledger.py` | append-only record of every closed trade, one line each (`1D`, `15m`) |
| `ledger/track_record_gate_<plane>.json` | `scripts/build_track_record_gate.py` | CUMULATIVE verdict over the ledger (overwritten daily) |

The 15m plane is an observation, not a gate: no §5 verdict, no effect on
arming or claim tier, not embedded in the public report. The 15m cumulative
verdict counts only trades anchored on or after 2026-10-01 (the day the plane
was fixed); earlier 15m trades stay in the ledger.

