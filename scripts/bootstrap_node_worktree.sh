#!/usr/bin/env bash
# Prepare Node dependencies for TypeScript/Playwright checks in a git worktree.
#
# Usage:
#   scripts/bootstrap_node_worktree.sh [worktree-root]
#
# Audit worktrees often do not have their own node_modules directory, so
# `tsx --test ...` can fail before it reaches the code under review. Prefer a
# symlink to the primary checkout's node_modules when package-lock.json matches;
# otherwise run npm ci inside the target worktree.
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  awk 'NR > 1 && /^#($| )/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
  exit 0
fi

if [[ -n "${1:-}" ]]; then
  TARGET_ROOT="$(cd -- "$1" && pwd)"
else
  TARGET_ROOT="$(git rev-parse --show-toplevel)"
fi

PACKAGE_JSON="${TARGET_ROOT}/package.json"
PACKAGE_LOCK="${TARGET_ROOT}/package-lock.json"
TARGET_NODE_MODULES="${TARGET_ROOT}/node_modules"

if [[ ! -f "${PACKAGE_JSON}" || ! -f "${PACKAGE_LOCK}" ]]; then
  echo "ERROR: ${TARGET_ROOT} is not a Node-enabled skipp-algo checkout" >&2
  exit 1
fi

if [[ -e "${TARGET_NODE_MODULES}" ]]; then
  echo "node_modules already present: ${TARGET_NODE_MODULES}"
  exit 0
fi

SOURCE_ROOT="${SKIPP_NODE_MODULES_SOURCE:-}"
if [[ -z "${SOURCE_ROOT}" ]]; then
  if git -C "${TARGET_ROOT}" rev-parse --git-common-dir >/dev/null 2>&1; then
    COMMON_DIR="$(git -C "${TARGET_ROOT}" rev-parse --path-format=absolute --git-common-dir)"
    SOURCE_ROOT="$(cd -- "${COMMON_DIR}/.." && pwd)"
  fi
fi

SOURCE_NODE_MODULES=""
if [[ -n "${SOURCE_ROOT}" ]]; then
  SOURCE_ROOT="$(cd -- "${SOURCE_ROOT}" && pwd)"
  if [[ "${SOURCE_ROOT}" != "${TARGET_ROOT}" \
    && -d "${SOURCE_ROOT}/node_modules" \
    && -f "${SOURCE_ROOT}/package-lock.json" \
    && -f "${SOURCE_ROOT}/node_modules/playwright/package.json" \
    && -x "${SOURCE_ROOT}/node_modules/.bin/tsx" \
    && -x "${SOURCE_ROOT}/node_modules/.bin/tsc" \
    && -x "${SOURCE_ROOT}/node_modules/.bin/playwright" ]] \
    && cmp -s "${PACKAGE_LOCK}" "${SOURCE_ROOT}/package-lock.json"; then
    SOURCE_NODE_MODULES="${SOURCE_ROOT}/node_modules"
  fi
fi

if [[ -n "${SOURCE_NODE_MODULES}" ]]; then
  ln -s "${SOURCE_NODE_MODULES}" "${TARGET_NODE_MODULES}"
  echo "Linked node_modules -> ${SOURCE_NODE_MODULES}"
  exit 0
fi

if [[ "${SKIPP_NODE_BOOTSTRAP_NO_INSTALL:-}" == "1" ]]; then
  echo "ERROR: no compatible source node_modules found and SKIPP_NODE_BOOTSTRAP_NO_INSTALL=1" >&2
  exit 1
fi

echo "Installing Node dependencies in ${TARGET_ROOT} via npm ci"
cd "${TARGET_ROOT}"
npm ci
