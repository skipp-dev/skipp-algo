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

## The entry price behind every number (measured 2026-10-02)

Every return here assumes the Variant-A entry: the zone midpoint for OB and
FVG, the broken or swept level for BOS and SWEEP. On 15m that price did not
trade on the entry bar for about two thirds of the zone trades and about half
of the level trades. With an entry at the close of the same bar, no family is
positive after costs (pooled -6.4 bps per trade against +12.5 bps reported),
and BOS and OB earn less than random entries in the same symbol on the same
day. A positive mean in these files is therefore not evidence of a tradable
edge. Method, tables and limits:
`docs/governance/variant_a_entry_price_measurement_2026-10-02.md`.

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
3. **Read the rows that carry the answer**, under
   `per_variant.<FAMILY>.checks[]` (each row is `name`, `status`, `value`,
   `threshold`):
   - `win_rate` — share of winning trades (threshold 0.55);
   - `bootstrap_sharpe_ci_low` — lower bound of the Sharpe interval. This is
     the row that separates "positive" from "indistinguishable from zero";
   - `psr_sr_star_zero` — probabilistic Sharpe against zero (threshold 0.95);
   - `min_trl_within_n` — trades needed for that Sharpe to be credible,
     against the trades there are;
   - `trading_days` and `day_clustered_mean_ci_low` — see "The day checks"
     below. On 15m these two decide; the rows above overstate there.
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

## The day checks: count the days, not the trades

`n_trades` counts every symbol separately. Setups that form on the same day
in several symbols move together, so they are closer to one observation of
the market than to many. Two checks in every verdict carry that (ADR-0031,
Nachtrag 2026-10-02):

- `trading_days` — distinct UTC days the trades are anchored on (threshold
  30). Its `detail` names the largest number of trades on one day.
- `day_clustered_mean_ci_low` — lower 95 % bound of the mean return per
  trade when whole days are resampled (must be above 0). The interval, the
  number of positive days and the mean sit in `summary.day_clustered`.

Both must be green for `status` to be green. A 30-day window verdict holds
at most 22 trading days, so only the cumulative verdicts under `ledger/` can
turn green at all. `sharpe`, `bootstrap_sharpe_ci_low`, `psr_sr_star_zero`
and `min_trl_within_n` still resample trades; on a plane with many trades
per day they read stronger than the evidence is. A verdict with
`schema_version` 1.0.0 was written before the day checks and carries neither.

Measured on the ledgers of 2026-10-02:

- 15m: 2 490 trades come from 19 trading days; one bar carries up to 56
  trades (median 2). The 30-day window verdict of that day reads `green`
  for all four families (n = 2 469). Resampling whole days instead of
  trades gives a mean per trade of BOS 12.4 bps [4.2, 19.0], FVG 11.4
  [-0.4, 22.7], OB 9.3 [1.2, 14.7], SWEEP 12.2 [5.9, 16.9], with 10 to 12
  positive days out of 18 — modest, and for FVG not separable from zero.
  The cumulative 15m verdict reads `green` for SWEEP on 210 trades that
  all come from one day (2026-10-01).
- 1D: 170 trades come from 13 trading days (up to 27 per day). No family's
  day-resampled interval excludes zero.

The day-resampled reading, printed (run from the repo root; covers the whole
ledger, including 15m trades anchored before 2026-10-01):

```bash
python - <<'PY'
import collections, json, random
from datetime import datetime, timezone
random.seed(0)
for plane in ("1D", "15m"):
    try:
        rows = [json.loads(line) for line in open(f"docs/calibration/gates/ledger/returns_ledger_{plane}.jsonl") if line.strip()]
    except FileNotFoundError:
        print(f"{plane}: no ledger yet"); continue
    for family in sorted({row["family"] for row in rows}):
        by_day = collections.defaultdict(list)
        for row in rows:
            if row["family"] == family:
                by_day[datetime.fromtimestamp(row["anchor_ts"], timezone.utc).date()].append(row["pnl"] * 1e4)
        days = list(by_day.values())
        n = sum(map(len, days))
        means = []
        for _ in range(5000):
            draw = [trade for day in random.choices(days, k=len(days)) for trade in day]
            means.append(sum(draw) / len(draw))
        means.sort()
        print(f"{plane} {family:5} n={n:4d} days={len(days):3d} mean={sum(map(sum, days)) / n:6.1f} bps "
              f"ci95=[{means[124]:.1f}, {means[4874]:.1f}] positive_days={sum(sum(day) > 0 for day in days)}")
PY
```

The gate computes the same interval with its own random draws; the bounds
differ in the first decimal.

