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

Both use the rotating clientId allocator (`scripts.ib_client_id`) so
they never collide with the long-lived `~/IB_mon` monitoring service or
with each other.

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
for label in collect-imbalance wsh-earnings; do
    sed "s|__REPO_PATH__|${REPO}|g" \
        "automation/launchd/com.skippalgo.c13.${label}.plist" \
        > "${HOME}/Library/LaunchAgents/com.skippalgo.c13.${label}.plist"
done

# 2. Bootstrap into the user's launchd domain.
launchctl bootstrap "gui/$(id -u)" \
    ~/Library/LaunchAgents/com.skippalgo.c13.collect-imbalance.plist
launchctl bootstrap "gui/$(id -u)" \
    ~/Library/LaunchAgents/com.skippalgo.c13.wsh-earnings.plist

# 3. Verify they are loaded.
launchctl print "gui/$(id -u)/com.skippalgo.c13.collect-imbalance" | head
launchctl print "gui/$(id -u)/com.skippalgo.c13.wsh-earnings"      | head

# 4. Trigger a one-shot run to validate end-to-end (writes log under /tmp).
launchctl kickstart -k "gui/$(id -u)/com.skippalgo.c13.collect-imbalance"
```

## Uninstall

```bash
launchctl bootout "gui/$(id -u)/com.skippalgo.c13.collect-imbalance"
launchctl bootout "gui/$(id -u)/com.skippalgo.c13.wsh-earnings"
rm ~/Library/LaunchAgents/com.skippalgo.c13.*.plist
```

## DST handling

Plists schedule by **local clock** (`StartCalendarInterval`), so daylight
savings is handled by the OS. No EST/EDT branching needed.

## Logging

`StandardOutPath` / `StandardErrorPath` write to
`/tmp/skippalgo-c13-<job>.log` and `<job>.err`. Rotate manually if they
grow.
