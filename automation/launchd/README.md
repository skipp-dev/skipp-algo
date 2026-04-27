# C13 Phase-A — local IBKR launchd jobs

These LaunchAgents drive the IBKR-bound jobs that **cannot** run on
the GitHub-hosted cron because they require a live TWS / IB Gateway
session. The unattended GH cron (`.github/workflows/c13-daily-cron.yml`)
consumes whatever artefacts the local jobs commit + push; absence is
treated as a soft skip.

## Jobs

| Plist | Schedule (local time) | Script | Output |
|---|---|---|---|
| `com.skippalgo.c13.collect-imbalance.plist` | 09:28 ET (Mon-Fri) | `scripts.collect_opening_imbalances` | `cache/imbalance/<DATE>.jsonl` |
| `com.skippalgo.c13.wsh-earnings.plist` | 16:30 ET (Mon-Fri) | `scripts.wsh_earnings_calendar` | `cache/wsh/<DATE>.jsonl` |
| `com.skippalgo.c13.phase-a-prep.plist` | 09:15 ET (Mon-Fri) | `scripts.build_phase_a_inputs` | `cache/phase_a/setups_<DATE>.jsonl` + `cache/phase_a/gate_status_<DATE>.json` |
| `com.skippalgo.c13.phase-a-session.plist` | 09:25 ET (Mon-Fri) | `scripts.run_smc_live_incubation` | `cache/incubation/incubation_<DATE>.jsonl` |
| `com.skippalgo.c13.phase-a-audit-push.plist` | 17:30 ET (Mon-Fri) | `automation/launchd/run-c13-phase-a-audit-push.sh` | commits to `data/phase-a-audit` |

The imbalance + WSH agents use the rotating clientId allocator
(`scripts.ib_client_id`) so they never collide with the long-lived
`~/IB_mon` monitoring service or with each other.

## Phase-A daily timeline

```
09:15 ET  phase-a-prep    → writes setups_<DATE>.jsonl + gate_status_<DATE>.json
09:25 ET  phase-a-session → reads those files, runs --phase paper, writes incubation log
09:28 ET  collect-imbalance (existing)
16:30 ET  wsh-earnings (existing)
17:30 ET  phase-a-audit-push → commits everything to data/phase-a-audit
```

## Install

The driver scripts (`run-c13-*.sh`) derive the repo path from their
own location, so no editing is needed there. The plists carry a
`__REPO_PATH__` placeholder in `ProgramArguments` that must be
substituted with your absolute checkout path before installing into
`~/Library/LaunchAgents/` (the placeholder keeps the tracked plist
files portable across workstations).

Override `C13_VENV` (default: `$HOME/.venv`) via the plist's
`EnvironmentVariables` block if your local layout differs. The
imbalance agent additionally accepts `C13_WATCHLIST` (default
`<REPO>/reports/databento_watchlist_top5_pre1530.csv`); the Phase-A
prep agent additionally accepts `C13_SETUPS_SOURCE`, `C13_RETURNS`
and `C13_KNOWN_VARIANTS` (all empty by default — see the seed contract
below).

### One-shot installer (Phase-A bundle)

For the three Phase-A agents (`phase-a-prep`, `phase-a-session`,
`phase-a-audit-push`) there is a wrapper that does the sed-substitute
+ copy + bootstrap in one go:

```bash
bash automation/launchd/install-c13-phase-a.sh
```

It is idempotent — re-running re-deploys and re-bootstraps the agents.
Set `DRY_RUN=1` to print what it would do without writing anything.

### Manual install (per-agent)

```bash
REPO="$(pwd)"   # run from the repo root

# 1. Substitute the placeholder and copy plists into the per-user
#    LaunchAgents directory.
for label in collect-imbalance wsh-earnings phase-a-prep phase-a-session phase-a-audit-push; do
    sed "s|__REPO_PATH__|${REPO}|g" \
        "automation/launchd/com.skippalgo.c13.${label}.plist" \
        > "${HOME}/Library/LaunchAgents/com.skippalgo.c13.${label}.plist"
done

# 2. Bootstrap into the user's launchd domain.
for label in collect-imbalance wsh-earnings phase-a-prep phase-a-session phase-a-audit-push; do
    launchctl bootstrap "gui/$(id -u)" \
        ~/Library/LaunchAgents/com.skippalgo.c13.${label}.plist
done

# 3. Verify they are loaded.
for label in collect-imbalance wsh-earnings phase-a-prep phase-a-session phase-a-audit-push; do
    launchctl print "gui/$(id -u)/com.skippalgo.c13.${label}" | head -3
done

# 4. Trigger a one-shot run to validate end-to-end (writes log under /tmp).
launchctl kickstart -k "gui/$(id -u)/com.skippalgo.c13.phase-a-prep"
```

## Phase-A killswitch (TWS-blocker)

The `phase-a-session` agent **refuses to start** unless an operator
sentinel exists at `<REPO>/cache/phase_a/.go-live` containing the
literal string `PAPER-CONFIRMED`:

```bash
mkdir -p cache/phase_a
echo PAPER-CONFIRMED > cache/phase_a/.go-live
```

Create the sentinel **only after** verifying TWS is logged into a
**paper** account on port 7497 (header top-left shows `PAPER`). Re-create
it every time you restart TWS, so an accidental `live cash on 7497` cannot
ever reach the runner. To pause Phase-A from local execution without
uninstalling the agents, simply delete the sentinel:

```bash
rm cache/phase_a/.go-live
```

With no sentinel, the session driver logs a soft-skip line to
`/tmp/skippalgo-c13-phase-a-session.log` and exits cleanly.

## Phase-A seed contract

Until the SMC quote-feed ingestion (C14 backlog) and the per-variant
returns history (C2/C3) are wired in, the prep agent runs in **seed
mode** by default:

* `setups_<DATE>.jsonl` is written as an empty file (zero bytes).
* `setups_<DATE>.meta.json` records `phase_a_seed: true` and
  `n_setups: 0`.
* `gate_status_<DATE>.json` maps every known variant to `"skipped"`.

The live-incubation runner consumes these files, finds nothing
tradable, and emits an empty audit log — which is the correct
behaviour while we have no real returns history to gate against. Once
upstream data lands, point the prep agent at it via the env-vars in
the plist:

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>C13_SETUPS_SOURCE</key>
    <string>/abs/path/to/todays_smc_setups.json</string>
    <key>C13_RETURNS</key>
    <string>/abs/path/to/per_variant_returns.json</string>
    <key>C13_KNOWN_VARIANTS</key>
    <string>smc_breaker_btc,smc_fvg_eth</string>
</dict>
```

## Uninstall

```bash
for label in collect-imbalance wsh-earnings phase-a-prep phase-a-session phase-a-audit-push; do
    launchctl bootout "gui/$(id -u)/com.skippalgo.c13.${label}" 2>/dev/null || true
done
rm ~/Library/LaunchAgents/com.skippalgo.c13.*.plist
```

## DST handling

Plists schedule by **local clock** (`StartCalendarInterval`), so daylight
savings is handled by the OS. No EST/EDT branching needed.

## Logging

`StandardOutPath` / `StandardErrorPath` write to
`/tmp/skippalgo-c13-<job>.log` and `<job>.err`. Rotate manually if they
grow.
