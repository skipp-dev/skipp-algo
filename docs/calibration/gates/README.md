# docs/calibration/gates/ — ADR-0031 drop-zone

Daily artifacts committed by `promotion-gate-daily` (14:00 UTC, bot auto-merge
PR) and consumed fail-soft by `public-calibration-dashboard` (04:30 UTC):

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
