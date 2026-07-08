#!/usr/bin/env bash
# C13 TWS reminder — operator nudge 15 minutes before the day's TWS-bound
# cron windows. Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.tws-reminder.plist.
#
# Two windows, two clocks (realigned 2026-07-08 after the phase-a/ibkr-smoke
# true-ET fix of 2026-07-07 moved the morning jobs to ET):
#
#   * MORNING (ET-gated): 07:45 ET, 15 min before the 08:00 ET ibkr-smoke —
#     the first job of the day that trips smoke_HALT when TWS is down — and
#     early enough for the 09:28 ET phase-a submit. The plist fires at the
#     three candidate local times (12:45/13:45/14:45, Berlin<->ET +5/+6/+7h);
#     the ET gate below lets exactly one per ET weekday through. (The old
#     09:13 LOCAL fire hit ~03:13 ET and protected nothing.)
#   * EVENING (local, ungated): 22:50 local, 15 min before the 23:05 LOCAL
#     fill reconcile (reconcile is deliberately not ET-scheduled).
#
# This job probes the API port and posts a macOS notification ONLY when
# nothing is listening — a silent run means TWS is already up. No venv, no
# repo Python: system tools plus the sibling lib_c13_et_gate.sh shell lib.
#
# macOS note: the first notification may trigger a one-time permission
# prompt for osascript/Script Editor in System Settings > Notifications.

set -euo pipefail

PORT="${C13_TWS_PORT:-7497}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

# Which window is this fire? Morning candidates land 12:45-14:45 local, the
# evening fire at 22:50 local — split on local hour < 20.
HOUR="$(date +%H)"
if [ "$((10#$HOUR))" -lt 20 ]; then
    # Morning path: only the candidate whose TRUE ET clock is 07:45 (+-10m)
    # proceeds; the other two DST-bracket fires no-op. The once-per-ET-day
    # marker also dedupes a launchd wake-catch-up racing the regular fire.
    source "$(dirname "$0")/lib_c13_et_gate.sh"
    c13_require_et_window "$REPO" 07 45 10 tws-reminder || exit 0
    NEXT="08:00 ET IBKR-Smoke + 09:28 ET Phase-A-Submit"
else
    NEXT="23:05 Fill-Reconcile"
fi

if /usr/bin/nc -z 127.0.0.1 "${PORT}" >/dev/null 2>&1; then
    echo "tws-reminder: TWS listening on ${PORT} — no reminder needed ($(date -u +%FT%TZ))"
    exit 0
fi

/usr/bin/osascript -e "display notification \"Paper-TWS läuft NICHT (Port ${PORT}). In 15 Min: ${NEXT}. Jetzt starten!\" with title \"⚠️ C13: TWS starten\" sound name \"Glass\""
echo "tws-reminder: notification sent — port ${PORT} closed ($(date -u +%FT%TZ))"
