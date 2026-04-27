#!/usr/bin/env bash
# C13 / Phase-A — one-shot installer for the three LaunchAgents.
#
# Substitutes ``__REPO_PATH__`` in each tracked plist template with the
# absolute path to the local checkout, copies the result into
# ~/Library/LaunchAgents/, then bootstraps each agent into the user's
# launchd domain. Idempotent: re-running replaces the installed plists
# and re-bootstraps the agents.
#
# Run from the repo root:
#
#     bash automation/launchd/install-c13-phase-a.sh
#
# Optional environment variables:
#   AGENTS_DIR   override target dir (default ~/Library/LaunchAgents)
#   DRY_RUN=1    print what would happen, don't write anything
#
# IMPORTANT — TWS BLOCKER:
# The session agent refuses to start unless the operator has manually
# created the killswitch sentinel:
#     echo PAPER-CONFIRMED > <REPO>/cache/phase_a/.go-live
# The sentinel must be re-confirmed every time the operator restarts
# TWS, to make accidental "live cash on port 7497" impossible.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
AGENTS_DIR="${AGENTS_DIR:-${HOME}/Library/LaunchAgents}"
DRY_RUN="${DRY_RUN:-0}"

LABELS=(
    "com.skippalgo.c13.phase-a-prep"
    "com.skippalgo.c13.phase-a-session"
    "com.skippalgo.c13.phase-a-audit-push"
)

run() {
    if [[ "${DRY_RUN}" == "1" ]]; then
        echo "+ $*"
    else
        "$@"
    fi
}

mkdir -p "${AGENTS_DIR}"

for label in "${LABELS[@]}"; do
    src="${REPO}/automation/launchd/${label}.plist"
    dst="${AGENTS_DIR}/${label}.plist"
    if [[ ! -f "${src}" ]]; then
        echo "Template missing: ${src}" >&2
        exit 1
    fi
    if [[ "${DRY_RUN}" == "1" ]]; then
        echo "+ sed s|__REPO_PATH__|${REPO}|g < ${src} > ${dst}"
    else
        sed "s|__REPO_PATH__|${REPO}|g" "${src}" > "${dst}"
    fi
done

# Make the shim drivers executable in the working tree (the bootstrap
# step doesn't care about the +x bit on macOS — launchd runs them via
# /bin/bash — but local kickstart-from-CLI does).
for shim in run-c13-phase-a-prep.sh run-c13-phase-a-session.sh run-c13-phase-a-audit-push.sh; do
    run chmod +x "${REPO}/automation/launchd/${shim}"
done

# Bootstrap (or re-bootstrap) each agent into the user's launchd domain.
DOMAIN="gui/$(id -u)"
for label in "${LABELS[@]}"; do
    plist="${AGENTS_DIR}/${label}.plist"
    # bootout is best-effort: the agent may not be loaded yet on first
    # install, in which case bootout fails — but bootstrap succeeds
    # only if the agent isn't already loaded, so we try both.
    run launchctl bootout "${DOMAIN}/${label}" 2>/dev/null || true
    run launchctl bootstrap "${DOMAIN}" "${plist}"
done

echo
echo "Installed and bootstrapped:"
for label in "${LABELS[@]}"; do
    echo "  - ${label}"
done
echo
echo "Verify each is loaded with:"
for label in "${LABELS[@]}"; do
    echo "  launchctl print ${DOMAIN}/${label} | head"
done
echo
echo "REMINDER: the session agent will soft-skip until you create the killswitch sentinel:"
echo "  mkdir -p ${REPO}/cache/phase_a"
echo "  echo PAPER-CONFIRMED > ${REPO}/cache/phase_a/.go-live"
echo "Only do this AFTER confirming TWS is on a PAPER account on port 7497."
