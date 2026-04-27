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

```bash
# 1. Edit run-c13-imbalance.sh / run-c13-wsh.sh and set REPO + VENV paths.
# 2. Copy plists into the per-user LaunchAgents directory.
cp automation/launchd/com.skippalgo.c13.*.plist ~/Library/LaunchAgents/

# 3. Bootstrap into the user's launchd domain.
launchctl bootstrap "gui/$(id -u)" \
    ~/Library/LaunchAgents/com.skippalgo.c13.collect-imbalance.plist
launchctl bootstrap "gui/$(id -u)" \
    ~/Library/LaunchAgents/com.skippalgo.c13.wsh-earnings.plist

# 4. Verify they are loaded.
launchctl print "gui/$(id -u)/com.skippalgo.c13.collect-imbalance" | head
launchctl print "gui/$(id -u)/com.skippalgo.c13.wsh-earnings"      | head

# 5. Trigger a one-shot run to validate end-to-end (writes log under /tmp).
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
