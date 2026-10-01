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

## Reading it: which family stands where

The question these files answer is "does this family earn anything after
costs, and is the sample large enough to say so". Read it in this order.

1. **Pick the plane.** `ledger/track_record_gate_1D.json` is the governed
   plane; `ledger/track_record_gate_15m.json` is the observation plane. Both
   are cumulative. A file that does not exist yet means the cumulative series
   is still empty (for 15m: no trade anchored on or after 2026-10-01).
2. **Check the sample first.** `per_variant.<FAMILY>.n_trades`. Below 100 the
   check `oos_trades` is red and every other row is a diagnostic, not a
   finding — `claim_note` says so in words.
3. **Read the four rows that carry the answer**, under
   `per_variant.<FAMILY>.checks[]` (each row is `name`, `status`, `value`,
   `threshold`):
   - `win_rate` — share of winning trades (threshold 0.55);
   - `bootstrap_sharpe_ci_low` — lower bound of the Sharpe interval. This is
     the row that separates "positive" from "indistinguishable from zero";
   - `psr_sr_star_zero` — probabilistic Sharpe against zero (threshold 0.95);
   - `min_trl_within_n` — trades needed for that Sharpe to be credible,
     against the trades there are.
4. **Then the verdict.** `per_variant.<FAMILY>.status` and `.claimable`.
5. **Check how fresh it is.** The last line of
   `ledger/returns_ledger_<plane>.jsonl` carries `first_recorded` (the run
   date that added it) and `anchor_ts` (when the setup formed).

The same table, printed (run from the repo root):

```bash
python - <<'PY'
import json
for plane in ("1D", "15m"):
    try:
        gate = json.load(open(f"docs/calibration/gates/ledger/track_record_gate_{plane}.json"))
    except FileNotFoundError:
        print(f"{plane}: no cumulative verdict yet"); continue
    for family, verdict in sorted(gate["per_variant"].items()):
        row = {c["name"]: c for c in verdict["checks"]}
        show = lambda name: f"{row[name]['value']:.3g} ({row[name]['status']})" if row[name]["value"] is not None else "n/a"
        print(f"{plane} {family:5} n={verdict['n_trades']:4d} status={verdict['status']:6} "
              f"win_rate={show('win_rate')} sharpe_ci_low={show('bootstrap_sharpe_ci_low')} psr={show('psr_sr_star_zero')}")
PY
```

The 30-day window verdicts (`track_record_gate_<date>.json` here for 1D,
`15m/track_record_gate_<date>.json` for 15m) have the same structure. Use
them for "how were the last 30 days", the ledger verdicts for "what has
accumulated".

