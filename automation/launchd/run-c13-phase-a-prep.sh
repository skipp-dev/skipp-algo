#!/usr/bin/env bash
# C13 / Phase-A — pre-open producer driver.
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.phase-a-prep.plist
# on Mon-Fri @ 09:15 local time (ET). Writes setups_<DATE>.jsonl +
# gate_status_<DATE>.json into cache/phase_a/.
#
# Idempotent: re-running on the same trade-date overwrites prior outputs
# atomically. Safe to kickstart on demand for a dry-run.

set -euo pipefail

# Derive REPO from this script's location so the driver is portable across
# workstations without editing the tracked file. VENV / SETUPS_SOURCE /
# RETURNS / KNOWN_VARIANTS can be overridden via environment variables
# (set in the LaunchAgent plist's ``EnvironmentVariables`` block) for
# non-default paths.
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${C13_VENV:-${HOME}/.venv}"

# Optional upstream inputs. Empty values are the documented Phase-A
# seed contract: empty setups file + every variant marked "skipped".
SETUPS_SOURCE="${C13_SETUPS_SOURCE:-}"
RETURNS="${C13_RETURNS:-}"
KNOWN_VARIANTS="${C13_KNOWN_VARIANTS:-}"

DATE="$(date -u +%Y-%m-%d)"
OUTPUT_DIR="${REPO}/cache/phase_a"

cd "${REPO}"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

mkdir -p "${OUTPUT_DIR}"

ARGS=(
    "--trade-date" "${DATE}"
    "--output-dir" "${OUTPUT_DIR}"
)
if [[ -n "${SETUPS_SOURCE}" ]]; then
    ARGS+=("--setups-source" "${SETUPS_SOURCE}")
fi
if [[ -n "${RETURNS}" ]]; then
    ARGS+=("--returns" "${RETURNS}")
fi
if [[ -n "${KNOWN_VARIANTS}" ]]; then
    ARGS+=("--known-variants" "${KNOWN_VARIANTS}")
fi

python -m scripts.build_phase_a_inputs "${ARGS[@]}"
