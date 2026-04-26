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
# C-sprint deep-review C7 fix: native mode was previously launching
# ``streamlit_terminal.py`` (the live news / trading terminal) instead
# of ``streamlit_dashboard.py`` (the read-only Track-Record Dashboard).
# The Dockerfile.dashboard ENTRYPOINT already points at
# streamlit_dashboard.py — this brings the native launcher back in
# line with the container surface so reviewers and operators see the
# same UI in both modes.
exec streamlit run streamlit_dashboard.py \
    --server.port="$PORT" \
    --server.headless=true
