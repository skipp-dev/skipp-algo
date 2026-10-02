# docs/calibration/gates/ — ADR-0031 drop-zone

Daily artifacts committed by `promotion-gate-daily` (14:00 UTC, bot auto-merge
PR) and consumed fail-soft by `c13-daily-cron` (22:00 UTC, Step 5b — moved
2026-07-31 from the removed `public-calibration-dashboard`, see issue #298):

| File | Producer | Consumer |
|---|---|---|
| `returns_series_<date>.json` | `scripts/build_returns_series.py` | gate + regime producers below (provenance); `c13-daily-cron` Step 5a (trade counts per family) |
| `track_record_gate_<date>.json` | `scripts/build_track_record_gate.py` | `emit_public_calibration_report` → public report key `track_record_gate` |
| `regime_stratified_<date>.json` | `scripts/build_regime_stratified_report.py` | `emit_public_calibration_report` → public report key `regime_stratified` |
| `epnl_after_cost_<date>.json` | `scripts/run_epnl_after_cost_gate.py` | the day's ADR-0023 §5 verdict, kept as a record |

Measurement basis (disclosed in every file's `measurement` block, the §5 file
in `return_rule`): net returns *given a triggered setup* under the rule
`next_open_then_horizon_close` — entry at the open of the bar after the
decision bar, exit at the family-horizon close, fixed 5 bps round-turn cost,
governed 1D plane. NOT portfolio P&L. See ADR-0031, Nachtrag 2026-10-02 II.

Retention: the workflow prunes each family to the newest 90 files. A missing
gate file on a day without trades is a normal state — the public report simply
omits the key. `returns_series_<date>.json` is written every day the pool
exists, also with zero trades.

## Two track records, never pooled

The return rule changed on 2026-10-02. Until then every number here was a
Variant-A return (`touch_then_horizon_close`): entry at the zone midpoint or
at the event level — a price that was not reachable once the decision
existed. Measured on 15m, that entry carried the whole reported return
(+12.0 bps per trade reported, -6.5 bps when bought at the decision bar's
close); see `docs/governance/variant_a_entry_price_measurement_2026-10-02.md`.

Returns under the two rules are different quantities. They are kept apart:

| Where | Rule | What it is |
|---|---|---|
| `variant_a_frozen/` | `touch_then_horizon_close` | everything written up to 2026-10-02: the dated 1D files, `15m/`, `ledger/`. Frozen; nothing appends to it. Not a track record. |
| this directory, `15m/`, `ledger/` | `next_open_then_horizon_close` | the record that began on 2026-10-02 |

Three things keep them apart, none of them a convention:

- every ledger row and every series names its `return_rule`, and
  `accumulate_returns_ledger.py` refuses (rc 2) to append to a ledger that
  holds rows of another rule;
- an event without `forward_opens` — every pool event recorded before the
  change — yields no return under the new rule, so no old trade is re-priced
  into the new record by accident;
- the cumulative verdicts count only trades anchored on or after
  **2026-10-05**, the first trading day after the rule was fixed
  (`governance.family_returns.RETURN_RULE_EVIDENCE_START`). The rule was
  chosen with September's data on the table; trades anchored earlier stay in
  the ledger and out of the verdict. The workflow's `--evidence-start
  2026-10-01` for 15m is older and no longer the binding date.

## Subdirectories (ADR-0031, Nachtrag 2026-10-01)

`15m/` and `ledger/` are written by the `ledger` step of
`promotion-gate-daily`. No 1D consumer sees them, nor `variant_a_frozen/`:
every reader of this directory globs it non-recursively.

| Path | Producer | What it is |
|---|---|---|
| `15m/track_record_gate_<date>.json` | `scripts/build_track_record_gate.py` | 30-day WINDOW verdict on the 15m observation plane (retention 90) |
| `15m/regime_stratified_<date>.json` | `scripts/build_regime_stratified_report.py` | regime report of the same window (retention 90) |
| `ledger/returns_ledger_<plane>.jsonl` | `scripts/accumulate_returns_ledger.py` | append-only record of every closed trade, one line each (`1D`, `15m`) |
| `ledger/track_record_gate_<plane>.json` | `scripts/build_track_record_gate.py` | CUMULATIVE verdict over the ledger (overwritten daily) |

The 15m plane is an observation, not a gate: no §5 verdict, no effect on
arming or claim tier, not embedded in the public report.

## Reading it: which family stands where

The question these files answer is "does this family earn anything after
costs, and is the sample large enough to say so". Read it in this order.

1. **Pick the plane.** `ledger/track_record_gate_1D.json` is the governed
   plane; `ledger/track_record_gate_15m.json` is the observation plane. Both
   are cumulative. A file that does not exist yet means the cumulative series
   is still empty: no trade anchored on or after 2026-10-05 has closed.
2. **Check the sample first.** `per_variant.<FAMILY>.n_trades`. Below 100 the
   check `oos_trades` is red and every other row is a diagnostic, not a
   finding — `claim_note` says so in words.
3. **Read the rows that carry the answer**, under
   `per_variant.<FAMILY>.checks[]` (each row is `name`, `status`, `value`,
   `threshold`):
   - `win_rate` — share of winning trades (threshold 0.55);
   - `bootstrap_sharpe_ci_low` — lower bound of the Sharpe interval;
   - `psr_sr_star_zero` — probabilistic Sharpe against zero (threshold 0.95);
   - `min_trl_within_n` — trades needed for that Sharpe to be credible,
     against the trades there are;
   - `trading_days` and `day_clustered_mean_ci_low` — see "The day checks"
     below. These two decide whether a positive mean is distinguishable from
     zero; the rows above overstate on planes with many trades per day.
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
              f"days={show('trading_days')} day_ci_low={show('day_clustered_mean_ci_low')} psr={show('psr_sr_star_zero')}")
PY
```

The 30-day window verdicts (`track_record_gate_<date>.json` here for 1D,
`15m/track_record_gate_<date>.json` for 15m) have the same structure. Use
them for "how were the last 30 days", the ledger verdicts for "what has
accumulated". A window verdict has no evidence start: it also contains trades
anchored before 2026-10-05, priced under the new rule.

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
per day they read stronger than the evidence is.

Why they exist, measured on the Variant-A ledgers of 2026-10-02 (now under
`variant_a_frozen/ledger/`): the 2 490 trades of the 15m ledger came from 19
trading days, up to 56 on one bar, and the 30-day window verdict read `green`
for all four families; the 170 trades of the 1D ledger came from 13 days.

The day-resampled reading of a ledger, printed (run from the repo root; it
covers the whole ledger, including trades anchored before the evidence
start). Set `LEDGER_DIR` to `docs/calibration/gates/variant_a_frozen/ledger`
to read the frozen Variant-A ledgers instead:

```bash
python - <<'PY'
import collections, json, os, random
from datetime import datetime, timezone
random.seed(0)
ledger_dir = os.environ.get("LEDGER_DIR", "docs/calibration/gates/ledger")
for plane in ("1D", "15m"):
    try:
        rows = [json.loads(line) for line in open(f"{ledger_dir}/returns_ledger_{plane}.jsonl") if line.strip()]
    except FileNotFoundError:
        print(f"{plane}: no ledger yet"); continue
    if not rows:
        print(f"{plane}: ledger is empty"); continue
    print(f"{plane}: rule {rows[0]['return_rule']}")
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
