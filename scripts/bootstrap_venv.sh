#!/usr/bin/env bash
# bootstrap_venv.sh — set up a complete local Python environment for skipp-algo.
#
# Idempotent. Run from the repo root.  Creates (or reuses) a venv at
# the path in $SKIPP_VENV (default: /Users/steffenpreuss/.venv) and
# installs every runtime + test dependency from requirements.txt.
#
# Why this exists:
#   pyproject.toml only declares the optional `vol-regime` extra.
#   Runtime dependencies live exclusively in requirements.txt, so a venv
#   created via `pip install -e .` is silently incomplete (you discover
#   missing packages at import time, e.g. `tradingview_ta`, `databento`,
#   `pandas_market_calendars`).  This script is the single supported
#   bootstrap path for local development; CI follows the same recipe.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="${SKIPP_VENV:-${HOME}/.venv}"
REQ_FILE="${REPO_ROOT}/requirements.txt"

if [[ ! -f "${REQ_FILE}" ]]; then
    echo "❌  requirements.txt not found at ${REQ_FILE}" >&2
    exit 1
fi

# ── Step 1: create venv if missing ─────────────────────────────────
if [[ ! -d "${VENV_PATH}" ]]; then
    echo "▶  creating venv at ${VENV_PATH}"
    python3 -m venv "${VENV_PATH}"
else
    echo "▶  reusing venv at ${VENV_PATH}"
fi

# ── Step 2: upgrade pip + install requirements ─────────────────────
PY="${VENV_PATH}/bin/python"
PIP="${VENV_PATH}/bin/pip"

echo "▶  upgrading pip / setuptools / wheel"
"${PY}" -m pip install --quiet --upgrade pip setuptools wheel

echo "▶  installing requirements.txt (this is the source of truth for runtime deps)"
"${PIP}" install --quiet -r "${REQ_FILE}"

# ── Step 3: verify the providers we audit can be imported ──────────
echo "▶  verifying provider imports"
"${PY}" - <<'PY'
import importlib
import sys

REQUIRED = [
    "httpx",
    "databento",
    "tradingview_ta",
    "pandas",
    "pytest",
    "dotenv",          # python-dotenv
    "yfinance",
]
missing = []
for mod in REQUIRED:
    try:
        importlib.import_module(mod)
    except Exception as exc:
        missing.append(f"  - {mod}: {type(exc).__name__}: {exc}")

if missing:
    print("❌  missing or broken modules after install:", file=sys.stderr)
    print("\n".join(missing), file=sys.stderr)
    sys.exit(1)

print("✅  all required provider modules importable")
PY

echo
echo "✅  bootstrap complete"
echo "    venv:     ${VENV_PATH}"
echo "    activate: source ${VENV_PATH}/bin/activate"
