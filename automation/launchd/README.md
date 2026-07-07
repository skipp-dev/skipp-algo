# C13 Phase-A — local IBKR launchd jobs

These two LaunchAgents drive the IBKR-bound jobs that **cannot** run on
the GitHub-hosted cron because they require a live TWS / IB Gateway
session. The unattended GH cron (`.github/workflows/c13-daily-cron.yml`)
consumes whatever artefacts the local jobs commit + push into
`cache/imbalance/` and `cache/wsh/`; absence is treated as a soft skip.

## Jobs

| Plist | Schedule (local time) | Script | Output |
| --- | --- | --- | --- |
| `com.skippalgo.c13.collect-imbalance.plist` | 09:28 ET (Mon-Fri) | `scripts.collect_opening_imbalances` | `cache/imbalance/<DATE>.jsonl` |
| `com.skippalgo.c13.wsh-earnings.plist` | 16:30 ET (Mon-Fri) | `scripts.wsh_earnings_calendar` | `cache/wsh/<DATE>.jsonl` |
| `com.skippalgo.c13.phase-a-export.plist` | 09:18 ET (Mon-Fri) | `scripts.export_open_prep_lists` | `reports/open_prep_trade_cards_<TS>.csv` |
| `com.skippalgo.c13.phase-a.plist` | 09:28 ET (Mon-Fri) | `scripts.build_phase_a_inputs` + `scripts.run_smc_live_incubation --phase paper --place-paper-orders` | `cache/live/setups_<DATE>.jsonl`, `cache/live/gate_status.json`, `cache/live/incubation_<DATE>.jsonl` (bracket sets submitted to the PAPER TWS) |
| `com.skippalgo.c13.ibkr-smoke.plist` | **08:00 ET (Mon-Fri)** | `scripts.smoke_smc_to_ibkr_adapter --mode live` | `cache/live/smoke_<DATE>.jsonl`; writes `cache/live/smoke_HALT` on failure |
| `com.skippalgo.c13.reconcile.plist` | 23:05 local (Mon-Fri) | `scripts.reconcile_incubation_fills` | stamps `fill_price`/`close_price`/`close_action`/`size_usd` + PnL/R onto `cache/live/incubation_<DATE>.jsonl` and publishes it (Phase-B execution-promotion fills — NOT the ADR-0023 §5 gate) |
| `com.skippalgo.c13.tws-reminder.plist` | 09:13 + 22:50 local (Mon-Fri) | `run-c13-tws-reminder.sh` (system tools only, no venv) | macOS notification 15 min before each IBKR-bound window — posts ONLY when nothing listens on the paper port |
| `com.skippalgo.c13.audit-push.plist` | 17:30 ET (Mon-Fri) | `git push origin data/phase-a-audit` | n/a (commits today's audit artefacts to the dedicated, unprotected `data/phase-a-audit` branch, bootstrapped on first run) |

The IBKR-bound jobs (`collect-imbalance`, `phase-a`) use the rotating
clientId allocator (`scripts.ib_client_id`) so they never collide with
the long-lived `~/IB_mon` monitoring service or with each other.

## Phase-A safety contract

`com.skippalgo.c13.phase-a.plist` runs `run_smc_live_incubation.py`
with `--phase paper --place-paper-orders` (C13b T1.2, enabled
2026-07-06 to produce measurable paper fills for the **C8 Phase-A→B
execution-promotion ladder** — `scripts/evaluate_phase_criteria.py`).
**Correction (2026-07-06, post-review):** these fills do NOT feed the
ADR-0023 §5 E[PnL] gate — §5 reads FamilyEvent `(score, return)`
samples from the magnitude-benchmark pool, and these open-prep
`smc_orb_vwap_hold` fills carry no SMC family. Running this cron
advances Phase-B, not ADR-0023 Stage 3. The submitter carries a built-in
paper-port guard (7497/4002 only) and the CLI refuses
`--place-paper-orders` on any live phase, so a mis-configured TWS can
never receive real orders from this cron. **However**, before loading
this plist, verify the TWS header reads `PAPER` and Read-Only API is
disabled in API Settings — see `docs/sprints/c13_live_incubation_phase_a.md`.

The fills chain requires the paper TWS to be RUNNING at 09:28 local
(submit) and 23:05 local (reconcile); a down TWS surfaces as
`action="submit_failed"` records resp. a red reconcile job — never
silently.

Known limitation: the WSH earnings filter is structurally empty until
the watchlist rows carry IBKR conIds (`wsh_earnings_calendar` skips
`con_id=-1` rows; every snapshot so far is `degraded:no-events`).
Resolving conIds via `qualifyContracts` is a planned follow-up; until
then phase-a runs with the earnings filter skipped.

Promotion to `--phase live_small` (10% size, real submits) requires a
Phase-B sign-off and is a separate plist that does not yet exist in
this directory.

## Install

The driver scripts (`run-c13-imbalance.sh`, `run-c13-wsh.sh`) derive the
repo path from their own location, so no editing is needed there. The
plists carry a `__REPO_PATH__` placeholder in `ProgramArguments` that
must be substituted with your absolute checkout path before installing
into `~/Library/LaunchAgents/` (the placeholder keeps the tracked plist
files portable across workstations).

Override `C13_VENV` (default: `$HOME/.venv`) and `C13_WATCHLIST`
(default: `<REPO>/reports/databento_watchlist_top5_pre1530.csv`) via
the plist's `EnvironmentVariables` block if your local layout differs.

```bash
REPO="$(pwd)"   # run from the repo root

# 1. Substitute the placeholder and copy plists into the per-user
#    LaunchAgents directory.
for label in collect-imbalance wsh-earnings phase-a-export phase-a ibkr-smoke reconcile tws-reminder audit-push; do
    sed -e "s|__REPO_PATH__|${REPO}|g" \
        -e "s|__HOME__|${HOME}|g" \
        "automation/launchd/com.skippalgo.c13.${label}.plist" \
        > "${HOME}/Library/LaunchAgents/com.skippalgo.c13.${label}.plist"
done

# 2. Bootstrap into the user's launchd domain.
for label in collect-imbalance wsh-earnings phase-a-export phase-a ibkr-smoke reconcile tws-reminder audit-push; do
    launchctl bootstrap "gui/$(id -u)" \
        "${HOME}/Library/LaunchAgents/com.skippalgo.c13.${label}.plist"
done

# 3. Verify they are loaded.
for label in collect-imbalance wsh-earnings phase-a-export phase-a ibkr-smoke reconcile tws-reminder audit-push; do
    launchctl print "gui/$(id -u)/com.skippalgo.c13.${label}" | head -2
done

# 4. Trigger a one-shot run to validate end-to-end (writes log under
#    ${HOME}/Library/Logs/skippalgo/ — see Logging section below).
launchctl kickstart -k "gui/$(id -u)/com.skippalgo.c13.phase-a-export"
```

## Uninstall

```bash
for label in collect-imbalance wsh-earnings phase-a-export phase-a ibkr-smoke reconcile tws-reminder audit-push; do
    launchctl bootout "gui/$(id -u)/com.skippalgo.c13.${label}" 2>/dev/null || true
done
rm ~/Library/LaunchAgents/com.skippalgo.c13.*.plist
```

## IBKR Smoke Guard

`com.skippalgo.c13.ibkr-smoke.plist` fires at **08:00 ET** (90 min before open).
It runs `python -m scripts.smoke_smc_to_ibkr_adapter --mode live` (module
invocation from the repo root): connects to the Paper Gateway
on `127.0.0.1:7497`, places each intent as a limit order, waits for an ack, then
cancels. Pure round-trip — no real fills.

`run_ibkr_open_execution.py` performs a startup guard before connecting to TWS:

| Condition | Effect |
| --- | --- |
| `cache/live/smoke_HALT` exists | Abort with instructions to remove the file |
| `cache/live/smoke_<TODAY>.jsonl` missing or > 4 h old | Abort with instructions to re-run the smoke |
| `--skip-smoke-guard` passed | Both checks skipped (prints an explicit warning) |

**Sentinel lifecycle**: `smoke_HALT` is written by `run-c13-ibkr-smoke.sh` on any
non-zero exit (EXIT=2 risk violation, EXIT=3 leftover orders, or unexpected error).
Remove it manually once the root cause is resolved:

```bash
rm cache/live/smoke_HALT
```

The smoke JSONL can be pushed to the audit branch together with the other artefacts via the hardened isolated-worktree helper:

```bash
bash automation/launchd/run-c13-audit-push.sh
```

## Timezone (ET) scheduling

`StartCalendarInterval` fires by the Mac's **local clock** — which equals US
market time only if the Mac itself runs on `America/New_York`. On a non-ET Mac
(e.g. `Europe/Berlin`) a plist that says `09:28` fires at 09:28 **local** =
03:28 ET, ~6 h before the US open. That is not academic: on 2026-07-07 it was
root-caused as the reason the ORB paper orders never filled (placed pre-market)
and the pre-market TWS smoke always tripped `smoke_HALT` (ran 02:00 ET,
overnight, TWS off).

**The two market-critical jobs are made timezone-correct** without assuming the
Mac's zone, via [`lib_c13_et_gate.sh`](lib_c13_et_gate.sh):

- The plist fires at the **three candidate local times** that bracket the
  Berlin↔ET offset (+5 / +6 / +7 h across the mismatched US/EU DST windows) —
  e.g. `phase-a` 09:28 ET → 14:28 / 15:28 / 16:28; `ibkr-smoke` 08:00 ET →
  13:00 / 14:00 / 15:00.
- The wrapper's `c13_require_et_window` reads the **true** ET wall clock
  (`TZ=America/New_York`, which tracks US DST) and lets exactly **one** fire per
  ET weekday proceed; the others no-op. A once-per-ET-day marker prevents
  duplicate paper orders.

Correct year-round with no hardcoded offset. **On an ET Mac** it still works
(the 09:28-ET candidate is one of the three and the gate passes it), but you may
simplify the plist back to the single ET time and drop the two extras.

**After changing a gated plist you must re-install it** (re-run the `sed`
substitution + `launchctl bootout`/`bootstrap` for that label; see *Install*).

> Still raw-local (fire ~6 h early on a Berlin Mac, follow-up): `phase-a-export`,
> `collect-imbalance`, `wsh-earnings`, `audit-push`. These are data-collection /
> push jobs (not order placement), so early firing degrades rather than breaks
> them; `collect-imbalance` also has catch-up, which needs a catch-up-aware gate.

## Missed-run catch-up / backfill

`StartCalendarInterval` only fires **once** on the next wake and *coalesces*
every occurrence missed while the workstation was asleep. So if the Mac slept
through Monday, Tuesday and Wednesday, launchd runs the job a single time on
Thursday and the Monday/Tuesday data is silently lost.

The data-producing drivers therefore replay every missed **business day**
inside a single wake via [`lib_c13_catchup.sh`](lib_c13_catchup.sh):

- A run-date counts as **done** only when its per-date status marker exists and
  begins with the success prefix (`ok:` for the data-push drivers, `SUCCESS|`
  for phase-a). Absent or `degraded:`/`DEGRADED|` markers are replayed.
- `c13_run_with_catchup` walks the business days in a bounded look-back window
  (default **7 calendar days**, override with `C13_CATCHUP_LOOKBACK_DAYS`),
  oldest first, and invokes the driver's `process_one_date "<YYYY-MM-DD>"` for
  each one that is not yet done; today is run as a safety net only when no
  dates are missing. A failing date is
  logged and tallied but does **not** abort the remaining dates.

Wired into the **historical, per-run-date** jobs, where backfilling a past date
reconstructs real state:

| Driver | Marker dir / prefix | Success prefix |
| --- | --- | --- |
| `run-c13-imbalance.sh` | `cache/imbalance/.push_status_` | `ok:` |
| `run-c13-phase-a.sh` | `cache/live/.phase_a_status_` | `SUCCESS\|` |

Note: `run-c13-phase-a.sh` writes a per-date status marker but does **not**
invoke `c13_run_with_catchup`; it runs once on wake and produces an incubation
audit log for the given day.  Multi-day backfill is not wired for Phase A
(past incubation results are not actionable for live-trading decisions).

The remaining jobs are **forward-looking / stateless**, so a single on-wake
fire is already sufficient and multi-day backfill is intentionally *not* wired:

- `run-c13-wsh.sh` pulls a forward earnings *calendar* (`--window-days`); a
  replay would just re-stamp past dates with today's calendar.
- `run-c13-ibkr-smoke.sh` verifies *current* TWS connectivity; a past morning
  cannot be smoke-tested after the fact.
- `run-c13-phase-a-export.sh` writes timestamped (not per-date) artefacts, and
  `run-c13-audit-push.sh` is an idempotent publish of whatever already exists.

The look-back window bounds retries, so a permanently-failing date (e.g. a
market holiday with no data) is retried for at most a week rather than forever.

## Logging

`StandardOutPath` / `StandardErrorPath` write to
`~/Library/Logs/skippalgo/skippalgo-c13-<job>.log` and `<job>.err`.
The `__HOME__` placeholder is substituted by the install `sed` command.
Create the directory once before bootstrapping:

```bash
mkdir -p "${HOME}/Library/Logs/skippalgo"
```

Rotate manually if files grow.
