#!/usr/bin/env bash
# C7/T8 — Local launcher for the SkippALGO Track-Record Dashboard.
#
# Modes:
#   ./scripts/run_dashboard.sh                  # native streamlit run
#   ./scripts/run_dashboard.sh --container      # docker build + run
#
# The script is intentionally short — production deploy is fronted
# by an SSO-aware reverse proxy (see docs/SPRINT_PLAN_C7_DASHBOARD §T8).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE_DIR="${SKIPP_DASHBOARD_CACHE_DIR:-$REPO_ROOT/cache}"
PORT="${SKIPP_DASHBOARD_PORT:-8501}"

if [[ "${1:-}" == "--container" ]]; then
    cd "$REPO_ROOT"
    docker build -f Dockerfile.dashboard -t skipp-dashboard:latest .
    exec docker run --rm \
        -p "${PORT}:8501" \
        -v "${CACHE_DIR}:/app/cache:ro" \
        --name skipp-dashboard \
        skipp-dashboard:latest
fi

cd "$REPO_ROOT"
export SKIPP_DASHBOARD_CACHE_DIR="$CACHE_DIR"
exec streamlit run streamlit_terminal.py \
    --server.port="$PORT" \
    --server.headless=true
