#!/usr/bin/env bash
# C13 TWS autostart — bring the paper TWS up 30 min before the 08:00 ET smoke.
#
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.tws-autostart.plist.
#
# Why this exists
# ---------------
# The whole C13 fills chain needs a logged-in paper TWS listening on 7497 at
# 08:00 ET (smoke) and 09:28 ET (submit). Until now that was a human task,
# nudged by run-c13-tws-reminder.sh. Measured 2026-08-02 over the 19 recorded
# smoke days: 9 SUCCESS, 10 DEGRADED — every DEGRADED one a
# ConnectionRefused on 7497, i.e. TWS not running. The reminder fired
# correctly on each of those days (23 notifications in its log); it is the
# human link that fails, so more reminders cannot fix it.
#
# Starting the TWS app alone is not enough: the API port only opens after a
# successful login. IBC (github.com/IbcAlpha/IBC) drives that login.
#
# Credential handling
# -------------------
# The password lives in the login Keychain (service skipp.ibkr.paper) and is
# NEVER passed on a command line — IBC's own twsstartmacos.sh hands it to
# java as --pw=..., which would expose it to `ps`. Instead this script writes
# a runtime ini (mode 600, in a 700 directory) containing the credentials,
# invokes IBC's inner entry point directly with --ibc-ini pointing at it, and
# shreds that file as soon as the port answers. IBC's own documentation
# recommends exactly this location-protected ini.
#
# The file is removed on every exit path via trap, including failure.
#
# One-time machine setup (performed and live-verified 2026-08-02, dry-run
# "TWS listening on 7497 after 20s"):
#
#   1. IBC 3.24.1 unpacked at ~/ibc (sha256 of IBCMacos-3.24.1.zip:
#      5ea02834bfc9379b98d4d217ddf87df74c070b7901306b05795dfe166f4d3898).
#   2. The OFFLINE TWS build at ~/Applications/TWS-Offline, symlinked as
#      "~/Applications/Trader Workstation 10.45" (IBC resolves the install
#      as "<tws-path>/Trader Workstation <version>"). Use the NATIVE Apple
#      Silicon build (tws-stable-macos-arm.dmg — note "macos-arm", the x64
#      one is "macosx-x64"): the x64 build works but runs under Rosetta,
#      which macOS now warns about and Apple is phasing out. Re-verified on
#      arm 2026-08-02: real credential login, port open after 10s. The
#      self-updating TWS under /Applications does NOT work with IBC — see
#      below.
#   3. Inside TWS-Offline/jars every *.dat has a *.jar symlink next to it.
#      Modern TWS ships core jars renamed to timestamped .dat (plain,
#      unencrypted jar archives — verified with file/unzip), and IBC's
#      classpath glob in scripts/ibcstart.sh collects *.jar ONLY. Without
#      the symlinks IBC dies at startup with "jclient/LoginFrame" (exit
#      1107) because that class lives in jts4launch-*.dat. The self-updating
#      build replaces its jars on every update, which is why it is not used
#      here.
#      **KORREKTUR 2026-08-29: "the offline build never self-updates, so the
#      symlinks are durable" stand hier und war FALSCH.** Gemessen: der
#      Offline-Build tauschte jts4launch-1045-macos-arm am 5.8. gegen ein neu
#      benanntes .dat, der Symlink vom 2.8. zeigte ins Leere, und IBC starb
#      24 Tage lang an genau diesem exit 1107 — waehrend die SUCCESS-Marker
#      dieser Tage alle "already-running" (Handstart) trugen. Deshalb legt
#      der Treiber die Links jetzt selbst an, statt sie vorauszusetzen.
#
# Repo policy: never --force, never --no-verify.

set -euo pipefail

PORT="${C13_TWS_PORT:-7497}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
IBC_HOME="${C13_IBC_HOME:-${HOME}/ibc}"
KEY_SERVICE="${C13_IBKR_KEYCHAIN_SERVICE:-skipp.ibkr.paper}"
KEY_ACCOUNT="${C13_IBKR_KEYCHAIN_ACCOUNT:-steffen81}"
TWS_MAJOR="${C13_TWS_MAJOR_VRSN:-10.45}"
TWS_APP_PATH="${C13_TWS_PATH:-${HOME}/Applications}"
WAIT_SECS="${C13_TWS_WAIT_SECS:-240}"
DATE="$(date -u +%Y-%m-%d)"
MARKER="${REPO}/cache/live/.tws_autostart_status_${DATE}"

_write_marker() {
    mkdir -p "${REPO}/cache/live"
    # JAR_NOTE haengt an JEDEM Ausgang, nicht nur an den gruenen: eine
    # Selbst-Aktualisierung, die zusammen mit einem anderen Defekt auftritt
    # (IBC weg, Keychain leer, Login-Timeout), waere sonst genau dort
    # unsichtbar, wo man sie am dringendsten sehen will. Zum Definitionszeit-
    # punkt ist JAR_NOTE noch ungesetzt; bash loest es beim AUFRUF auf.
    printf '%s|%s%s\n' "$1" "${2:-}" "${JAR_NOTE:-}" > "${MARKER}"
}

# ET gate: 07:30 ET, 30 min ahead of the smoke. The plist fires at the three
# candidate LOCAL hours bracketing the Berlin<->ET offset; exactly one passes.
source "$(dirname "$0")/lib_c13_et_gate.sh"
c13_require_et_window "$REPO" 07 30 10 tws-autostart || exit 0

# --- Jar-Symlinks ABLEITEN statt annehmen ----------------------------------
# Der Kopf dieses Skripts behauptete: "The offline build never self-updates, so
# the symlinks are durable". Am 2026-08-29 WIDERLEGT: der Offline-Build hatte
# jts4launch-1045-macos-arm am 5.8. gegen ein neu benanntes .dat getauscht, der
# am 2.8. von Hand gesetzte *.jar-Symlink zeigte seither ins Leere, und IBC
# starb an JEDEM Werktag mit "jclient/LoginFrame" / exit 1107 — 24 Tage lang,
# weil genau diese Klasse in jts4launch-*.dat liegt und IBCs Classpath-Glob nur
# *.jar sammelt. Eine handgepflegte Symlink-Liste kann ihre eigene Drift nicht
# fangen; also wird die Population hier vor JEDEM Start aus den .dat-Dateien
# ABGELEITET und jeder tote Link entfernt. Repariert werden musste = laut, denn
# eine stille Selbst-Aktualisierung ist genau das, was 24 Tage unsichtbar blieb.
TWS_JARS="${TWS_APP_PATH}/Trader Workstation ${TWS_MAJOR}/jars"
JAR_REPAIRS=0
if [[ -d "${TWS_JARS}" ]]; then
    for _dat in "${TWS_JARS}"/*.dat; do
        [[ -e "${_dat}" ]] || continue          # leeres Glob
        _link="${_dat%.dat}.jar"
        if [[ ! -e "${_link}" ]]; then          # fehlt ODER zeigt ins Leere
            rm -f "${_link}"
            ln -s "$(basename "${_dat}")" "${_link}"
            JAR_REPAIRS=$((JAR_REPAIRS + 1))
        fi
    done
    for _link in "${TWS_JARS}"/*.jar; do
        # Tote Links, deren .dat UMBENANNT wurde: die Schleife oben legt den
        # neuen Link an, entfernt den alten aber nicht — und ein toter Eintrag
        # im Classpath ist genau der Ausfall vom 5.8.
        [[ -L "${_link}" ]] || continue
        [[ -e "${_link}" ]] && continue
        rm -f "${_link}"
        JAR_REPAIRS=$((JAR_REPAIRS + 1))
    done
fi
JAR_NOTE=""
if [[ "${JAR_REPAIRS}" -gt 0 ]]; then
    JAR_NOTE=":jarlinks-repaired=${JAR_REPAIRS}"
    echo "tws-autostart: ${JAR_REPAIRS} Jar-Symlink(s) in ${TWS_JARS} repariert" \
         "— der TWS-Build hat sich selbst aktualisiert." >&2
fi

if /usr/bin/nc -z 127.0.0.1 "${PORT}" >/dev/null 2>&1; then
    # "already-running" beweist NICHTS ueber den Autostart: der Port kann von
    # einem Handstart offen sein. Genau so sahen 11./12./17./18./20./28.8. gruen
    # aus, waehrend seit dem 5.8. kein einziger IBC-Start gelang. Bei der Triage
    # zaehlt die NACHRICHT, nicht das Verdikt.
    echo "tws-autostart: TWS already listening on ${PORT} — nothing to do."
    _write_marker "SUCCESS" "already-running"
    exit 0
fi

if [[ ! -x "${IBC_HOME}/scripts/ibcstart.sh" ]]; then
    echo "tws-autostart: IBC not found at ${IBC_HOME} — install it or set C13_IBC_HOME" >&2
    _write_marker "DEGRADED" "ibc-missing:${IBC_HOME}"
    exit 1
fi

# Keychain read. `security` prompts interactively when the item is not in the
# search list; under launchd there is no UI, so a missing item must fail fast
# and loudly rather than hang.
PW="$(security find-generic-password -s "${KEY_SERVICE}" -a "${KEY_ACCOUNT}" -w 2>/dev/null || true)"
if [[ -z "${PW}" ]]; then
    echo "tws-autostart: no Keychain password for ${KEY_SERVICE}/${KEY_ACCOUNT}." \
         "Add it with: security add-generic-password -s ${KEY_SERVICE} -a ${KEY_ACCOUNT} -w" >&2
    _write_marker "DEGRADED" "keychain-missing:${KEY_SERVICE}/${KEY_ACCOUNT}"
    exit 1
fi

PRIVATE_DIR="${IBC_HOME}/private"
mkdir -p "${PRIVATE_DIR}"
chmod 700 "${PRIVATE_DIR}"
RUNTIME_INI="${PRIVATE_DIR}/config-runtime-${DATE}.ini"

# Shred on EVERY exit path, success or failure.
trap 'rm -f "${RUNTIME_INI}"' EXIT

umask 077
{
    # Start from the stock ini, drop any credential/mode lines it carries, and
    # append ours. Keeping the stock body means IBC upgrades keep their
    # defaults instead of silently losing settings this script never knew.
    grep -vE '^(IbLoginId|IbPassword|TradingMode)=' "${IBC_HOME}/config.ini"
    printf 'IbLoginId=%s\n' "${KEY_ACCOUNT}"
    printf 'IbPassword=%s\n' "${PW}"
    printf 'TradingMode=paper\n'
} > "${RUNTIME_INI}"
chmod 600 "${RUNTIME_INI}"
unset PW

mkdir -p "${IBC_HOME}/logs"
echo "tws-autostart: starting paper TWS ${TWS_MAJOR} via IBC ($(date -u +%FT%TZ))"

# --user/--pw deliberately omitted: the credentials travel in the ini only.
nohup "${IBC_HOME}/scripts/ibcstart.sh" "${TWS_MAJOR}" \
    "--tws-path=${TWS_APP_PATH}" \
    "--ibc-path=${IBC_HOME}" \
    "--ibc-ini=${RUNTIME_INI}" \
    "--mode=paper" \
    "--on2fatimeout=exit" \
    >> "${IBC_HOME}/logs/tws-autostart-${DATE}.log" 2>&1 &

# Wait for the API port. A login that never completes is the failure this job
# exists to surface, so time out loudly instead of exiting 0 on a dark port.
WAITED=0
while [[ "${WAITED}" -lt "${WAIT_SECS}" ]]; do
    if /usr/bin/nc -z 127.0.0.1 "${PORT}" >/dev/null 2>&1; then
        echo "tws-autostart: TWS listening on ${PORT} after ${WAITED}s."
        _write_marker "SUCCESS" "started-in:${WAITED}s"
        exit 0
    fi
    sleep 5
    WAITED=$((WAITED + 5))
done

echo "tws-autostart: TWS did not open ${PORT} within ${WAIT_SECS}s —" \
     "see ${IBC_HOME}/logs/tws-autostart-${DATE}.log" >&2
_write_marker "DEGRADED" "port-not-open-after:${WAIT_SECS}s"
exit 1
