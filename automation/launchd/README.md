# C13 Phase-A — local IBKR launchd jobs

These two LaunchAgents drive the IBKR-bound jobs that **cannot** run on
the GitHub-hosted cron because they require a live TWS / IB Gateway
session. The unattended GH cron (`.github/workflows/c13-daily-cron.yml`)
consumes whatever artefacts the local jobs commit + push into
`cache/imbalance/` and `cache/wsh/`; absence is treated as a soft skip.

## Jobs

| Plist | Schedule (local time) | Script | Output |
|---|---|---|---|
| `com.skippalgo.c13.collect-imbalance.plist` | 09:28 ET (Mon-Fri) | `scripts.collect_opening_imbalances` | `cache/imbalance/<DATE>.jsonl` |
| `com.skippalgo.c13.wsh-earnings.plist` | 16:30 ET (Mon-Fri) | `scripts.wsh_earnings_calendar` | `cache/wsh/<DATE>.jsonl` |
| `com.skippalgo.c13.phase-a-export.plist` | 09:18 ET (Mon-Fri) | `scripts.export_open_prep_lists` | `reports/open_prep_trade_cards_<TS>.csv` |
| `com.skippalgo.c13.phase-a.plist` | 09:28 ET (Mon-Fri) | `scripts.build_phase_a_inputs` + `scripts.run_smc_live_incubation --phase paper` | `cache/live/setups_<DATE>.jsonl`, `cache/live/gate_status.json`, `cache/live/incubation_<DATE>.jsonl` |
| `com.skippalgo.c13.ibkr-smoke.plist` | **08:00 ET (Mon-Fri)** | `scripts.smoke_smc_to_ibkr_adapter --mode live` | `cache/live/smoke_<DATE>.jsonl`; writes `cache/live/smoke_HALT` on failure |
| `com.skippalgo.c13.audit-push.plist` | 17:30 ET (Mon-Fri) | `git push origin data/phase-a-audit` | n/a (commits today's audit artefacts to the dedicated, unprotected `data/phase-a-audit` branch, bootstrapped on first run) |

The IBKR-bound jobs (`collect-imbalance`, `phase-a`) use the rotating
clientId allocator (`scripts.ib_client_id`) so they never collide with
the long-lived `~/IB_mon` monitoring service or with each other.

## Phase-A safety contract

`com.skippalgo.c13.phase-a.plist` runs `run_smc_live_incubation.py`
with `--phase paper`. That phase wires `paper_mode=True` and
`size_scale=0.1` and never invokes a `submit_fn`, so the runner emits
`action="audit_only"` records even if TWS is connected to a live
account. **However**, before loading this plist for a 28-day Phase-A
window, verify the TWS header reads `PAPER` and Read-Only API is
disabled in API Settings — see `docs/sprints/c13_live_incubation_phase_a.md`.

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
for label in collect-imbalance wsh-earnings phase-a-export phase-a ibkr-smoke audit-push; do
    sed "s|__REPO_PATH__|${REPO}|g" \
        "automation/launchd/com.skippalgo.c13.${label}.plist" \
        > "${HOME}/Library/LaunchAgents/com.skippalgo.c13.${label}.plist"
done

# 2. Bootstrap into the user's launchd domain.
for label in collect-imbalance wsh-earnings phase-a-export phase-a ibkr-smoke audit-push; do
    launchctl bootstrap "gui/$(id -u)" \
        "${HOME}/Library/LaunchAgents/com.skippalgo.c13.${label}.plist"
done

# 3. Verify they are loaded.
for label in collect-imbalance wsh-earnings phase-a-export phase-a ibkr-smoke audit-push; do
    launchctl print "gui/$(id -u)/com.skippalgo.c13.${label}" | head -2
done

# 4. Trigger a one-shot run to validate end-to-end (writes log under /tmp).
launchctl kickstart -k "gui/$(id -u)/com.skippalgo.c13.phase-a-export"
```

## Uninstall

```bash
for label in collect-imbalance wsh-earnings phase-a-export phase-a ibkr-smoke audit-push; do
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
|---|---|
| `cache/live/smoke_HALT` exists | Abort with instructions to remove the file |
| `cache/live/smoke_<TODAY>.jsonl` missing or > 4 h old | Abort with instructions to re-run the smoke |
| `--skip-smoke-guard` passed | Both checks skipped (prints an explicit warning) |

**Sentinel lifecycle**: `smoke_HALT` is written by `run-c13-ibkr-smoke.sh` on any
non-zero exit (EXIT=2 risk violation, EXIT=3 leftover orders, or unexpected error).
Remove it manually once the root cause is resolved:

```bash
rm cache/live/smoke_HALT
```

The smoke JSONL can be pushed to the audit branch together with the other artefacts:

```bash
git add cache/live/smoke_*.jsonl \
  && git commit -m "chore(c13): smoke audit JSONL $(date +%F)" \
  && git push origin data/phase-a-audit
```

## DST handling

Plists schedule by **local clock** (`StartCalendarInterval`), so daylight
savings is handled by the OS. No EST/EDT branching needed.

## Logging

`StandardOutPath` / `StandardErrorPath` write to
`/tmp/skippalgo-c13-<job>.log` and `<job>.err`. Rotate manually if they
grow.
