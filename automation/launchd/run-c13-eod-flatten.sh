#!/usr/bin/env bash
# C13 end-of-day flatten — daily local cron driver that closes every
# remaining paper position ~15 minutes before the US cash close.
#
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.eod-flatten.plist at
# the SIX candidate local times bracketing 15:45 ET (regular days) and
# 12:45 ET (scheduled 13:00-ET early closes) across the US/EU DST mismatch
# weeks; the ET gate below targets the day's close from
# scripts/us_equity_early_closes.py and lets exactly one fire per ET weekday
# proceed (same pattern as run-c13-phase-a.sh).
#
# Why (measured 2026-08-18): the campaign submits bracket sets and
# disconnects — the executor's client-side time stop never runs, DAY exit
# legs die at the bell, and positions whose tp/sl did not trigger intraday
# accumulated as unprotected zombies (nine one-lot leftovers since June).
# scripts/c13_eod_flatten.py is the missing exit half: it drains ALL
# working orders (reqGlobalCancel, cross-client) and market-closes every
# open position, writing the fills as PortfolioFill rows so the nightly
# reconcile (run-c13-reconcile.sh) can explain the position deltas.
#
# Repo policy: never --force, never --no-verify.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"

VENV="${C13_VENV:-${REPO}/.venv}"
DATE="$(date -u +%Y-%m-%d)"
FILLS="${REPO}/cache/live/portfolio_fills_eod_${DATE}.json"
REPORT="${REPO}/cache/live/eod_flatten_report_${DATE}.json"
STATUS_MARKER="${REPO}/cache/live/.eod_flatten_status_${DATE}"
TS="$(date -u +%FT%TZ)"

_write_marker() {
    local kind="$1"
    local msg="${2:-}"
    mkdir -p "$(dirname "${STATUS_MARKER}")" 2>/dev/null || true
    printf '%s:%s:%s\n' "${kind}" "${msg}" "${TS}" > "${STATUS_MARKER}" 2>/dev/null || true
}

cd "${REPO}"

# venv-Preflight VOR dem Gate: das Gate-Ziel haengt vom Fruehschluss-Kalender
# ab, und der lebt als Single Source in Python (scripts/us_equity_early_closes
# — Review 2026-08-18 Important #2). Die Shell repliziert keine Datumsliste.
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "eod-flatten cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "preflight-error"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "eod-flatten cron: python interpreter not executable at ${PY} (check C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "python-not-executable:${PY}"
    exit 1
fi

# An Halbtagen (13:00-ET-Close) zielt das Gate auf 12:45 ET statt 15:45 ET —
# sonst invertiert der Flatten seinen Zweck: reqGlobalCancel NACH dem Close
# toetet nur noch den GTC-Schutz und schliessen kann er nichts mehr. Die
# Plist feuert dafuer zusaetzlich die 12:45-ET-Kandidaten; das Gate laesst
# genau den passenden durch. Test-Hook: C13_GATE_NOW_ET_DATE.
ET_DATE="${C13_GATE_NOW_ET_DATE:-$(TZ=America/New_York date +%Y-%m-%d)}"
read -r TARGET_HH TARGET_MM < <("${PY}" -m scripts.us_equity_early_closes --date "${ET_DATE}")

# shellcheck disable=SC1091
source "$(dirname "$0")/lib_c13_et_gate.sh"
c13_require_et_window "$REPO" "${TARGET_HH}" "${TARGET_MM}" 10 eod-flatten || exit 0

# Laufzeit-Waechter (Grenzgaenger-Sweep 2026-08-22). Am 21.8. kehrte
# ib.connect() zurueck, danach liefen alle vier ib_async-Startup-Requests in
# Timeouts und der Prozess stand 8 h 41 min. Das kostet nicht nur den Tag:
# launchd startet KEINE zweite Instanz eines noch laufenden Jobs, also blieb
# auch das 22:45-Folgefeuer aus und jeder weitere Tag waere ausgefallen —
# beweisbar am fehlenden "ET now 16:45 ... skip" im Log des 21.8.
#
# Die Frist ist abgeleitet, nicht geraten: die begrenzten Wartezeiten des
# Skripts summieren sich auf 97 s (connect 20 + reqGlobalCancel-Warteschleife
# 15 + ack-timeout 60 + Positions-Nachlese 2). 600 s lassen ~6x Luft und
# liegen weit unter dem Stundenabstand der Kandidatenfeuer.
#
# macOS hat kein timeout(1) und hier auch kein gtimeout — daher von Hand.
# TERM zuerst: scripts.c13_eod_flatten wandelt es in SystemExit, damit
# ib.disconnect() noch laeuft. Ein hartes KILL liesse clientId in TWS haengen
# und der naechste Lauf scheiterte am Connect — der Waechter haette den
# Ausfall dann nur verschoben.
FLATTEN_TIMEOUT_SECS="${C13_EOD_FLATTEN_TIMEOUT_SECS:-600}"
# Gnadenfrist zwischen TERM und KILL. Beide Werte sind Test-Hooks: der
# Waechter-Test faehrt sie auf Sekunden herunter, sonst waere er ein
# Minuten-Test und wuerde aus der Suite fliegen (= wieder ungesichert).
FLATTEN_KILL_GRACE_SECS="${C13_EOD_FLATTEN_KILL_GRACE_SECS:-30}"
# Volle Vorlage statt `-t`: dessen Semantik geht auseinander. BSD (macOS, wo
# der Cron laeuft) nimmt das Argument als PRAEFIX und haengt eigene X'e an;
# GNU (Linux, wo die Suite laeuft) verlangt X'e in der Vorlage und bricht sonst
# mit "too few X's in template" ab — genau daran starb dieser PR im ersten
# Anlauf. Mit ausgeschriebenem Pfad + X'en verhalten sich beide gleich.
TIMEOUT_FLAG="$(mktemp "${TMPDIR:-/tmp}/c13eodflatten.XXXXXX")"
trap 'rm -f "${TIMEOUT_FLAG}"' EXIT

"${PY}" -m scripts.c13_eod_flatten \
    --date "${DATE}" \
    --fills-output "${FILLS}" \
    --report-output "${REPORT}" \
    ${C13_IBKR_ACCOUNT:+--account "${C13_IBKR_ACCOUNT}"} &
_flatten_pid=$!

(
    _slept=0
    while [[ "${_slept}" -lt "${FLATTEN_TIMEOUT_SECS}" ]] && kill -0 "${_flatten_pid}" 2>/dev/null; do
        sleep 1
        _slept=$((_slept + 1))
    done
    if kill -0 "${_flatten_pid}" 2>/dev/null; then
        printf 'timeout\n' > "${TIMEOUT_FLAG}"
        echo "eod-flatten cron: runtime limit ${FLATTEN_TIMEOUT_SECS}s exceeded — terminating ${_flatten_pid}" >&2
        kill -TERM "${_flatten_pid}" 2>/dev/null || true
        _grace=0
        while [[ "${_grace}" -lt "${FLATTEN_KILL_GRACE_SECS}" ]] && kill -0 "${_flatten_pid}" 2>/dev/null; do
            sleep 1
            _grace=$((_grace + 1))
        done
        if kill -0 "${_flatten_pid}" 2>/dev/null; then
            echo "eod-flatten cron: still alive after SIGTERM — SIGKILL ${_flatten_pid}" >&2
            kill -KILL "${_flatten_pid}" 2>/dev/null || true
        fi
    fi
) &
_watchdog_pid=$!

rc=0
wait "${_flatten_pid}" || rc=$?
kill "${_watchdog_pid}" 2>/dev/null || true
wait "${_watchdog_pid}" 2>/dev/null || true

# Der Sentinel entscheidet, nicht der Exit-Code: 143/137 koennen auch von
# aussen kommen (Operator, Neustart), und "abgeschossen weil haengend" ist
# eine andere Diagnose als "abgebrochen".
if [[ -s "${TIMEOUT_FLAG}" ]]; then
    echo "eod-flatten cron: c13_eod_flatten hung and was killed after ${FLATTEN_TIMEOUT_SECS}s (rc=${rc}) — see ${REPORT}" >&2
    _write_marker "DEGRADED" "flatten-timeout:${FLATTEN_TIMEOUT_SECS}s:rc=${rc}"
    exit 1
fi

if [[ "${rc}" -ne 0 ]]; then
    echo "eod-flatten cron: c13_eod_flatten exited ${rc} — see ${REPORT}" >&2
    _write_marker "DEGRADED" "flatten-rc:${rc}"
    exit 1
fi

_write_marker "SUCCESS" "fills:${FILLS}"
