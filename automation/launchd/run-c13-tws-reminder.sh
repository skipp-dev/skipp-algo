#!/usr/bin/env bash
# C13 TWS reminder — operator nudge 15 minutes before the two IBKR-bound
# cron windows. Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.tws-reminder.plist
# Mon-Fri @ 09:13 and 22:50 local time.
#
# The paper-fills chain needs the PAPER TWS running at 09:28 (phase-a
# submit) and 23:05 (fill reconcile). This job probes the API port and
# posts a macOS notification ONLY when nothing is listening — a silent
# run means TWS is already up. No venv, no repo code: pure system tools,
# so it keeps working even when the checkout is mid-rebase.
#
# macOS note: the first notification may trigger a one-time permission
# prompt for osascript/Script Editor in System Settings > Notifications.

set -euo pipefail

PORT="${C13_TWS_PORT:-7497}"

# Message names the cron window this reminder protects.
HOUR="$(date +%H)"
if [ "${HOUR#0}" -lt 12 ]; then
    NEXT="09:28 Phase-A Paper-Submit"
else
    NEXT="23:05 Fill-Reconcile"
fi

if /usr/bin/nc -z 127.0.0.1 "${PORT}" >/dev/null 2>&1; then
    echo "tws-reminder: TWS listening on ${PORT} — no reminder needed ($(date -u +%FT%TZ))"
    exit 0
fi

/usr/bin/osascript -e "display notification \"Paper-TWS läuft NICHT (Port ${PORT}). In 15 Min: ${NEXT}. Jetzt starten!\" with title \"⚠️ C13: TWS starten\" sound name \"Glass\""
echo "tws-reminder: notification sent — port ${PORT} closed ($(date -u +%FT%TZ))"
