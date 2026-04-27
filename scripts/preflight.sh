#!/usr/bin/env bash
# Preflight gate for any skipp-algo workflow runner.
#
# Usage:
#   ./scripts/preflight.sh                # block on any critical provider
#   PREFLIGHT_NOTIFY=0 ./scripts/preflight.sh   # disable push alerts
#
# Exit codes:
#   0  all critical providers OK         → safe to launch the workflow
#   1  at least one critical provider down → workflow MUST NOT launch
#
# Designed to be the first line of any cron / launchd / make target that
# starts a long-running process:
#
#   ./scripts/preflight.sh && python my_workflow.py
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-${SKIPP_VENV:-${HOME}/.venv}/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

NOTIFY_FLAG=""
if [[ "${PREFLIGHT_NOTIFY:-1}" == "1" ]]; then
  NOTIFY_FLAG="--notify"
fi

PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}" exec "${PYTHON_BIN}" \
  "${REPO_ROOT}/scripts/probe_providers.py" --preflight ${NOTIFY_FLAG}
